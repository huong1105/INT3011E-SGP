from __future__ import annotations

import argparse
import json
import math
import numbers
import sys
import time
from itertools import combinations

from .io_utils import VALID_SB_MODES, check_partner_bound, configure_safe_stdio
from .verifier import verify_schedule

try:
    import gurobipy as gp
    from gurobipy import GRB
except (ImportError, OSError) as exc:
    gp = None
    GRB = None
    _GUROBI_IMPORT_ERROR = str(exc)
else:
    _GUROBI_IMPORT_ERROR = None

_ENV = None

def _env():
    """Tạo Gurobi Env dùng chung, tắt OutputFlag ngay từ đầu."""
    global _ENV
    if _ENV is None:
        env = gp.Env(empty=True)
        env.setParam("OutputFlag", 0)
        env.start()
        _ENV = env
    return _ENV

def _positive_init(name, value):
    """Kiểm tra tham số nguyên dương."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")

def _timeout_seconds(timeout_seconds):
    """Kiểm tra và chuẩn hóa giới hạn thời gian."""
    if timeout_seconds is None:
        return None
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, numbers.Real):
        raise ValueError(f"timeout_seconds must be a finite positive number or None")
    value = float(timeout_seconds)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"timeout_seconds must be a finite positive number or None")
    return value

def build_ilp_model(w, g, s, sb="none"):
    """Dựng model ILP, trả (model, x, stats)."""
    n = g * s
    model = gp.Model("sgp", env=_env())
    model.Params.DualReductions = 0
    x = model.addVars(n, g, w, vtype=GRB.BINARY, name = "x")

    for i in range(n):
        for k in range(w):
            model.addConstr(
                gp.quicksum(x[i, j, k] for j in range(g)) == 1, f"one_group_{i}_{k}")

    for j in range(g):
        for k in range(w):
            model.addConstr(gp.quicksum(x[i, j, k] for i in range(n)) == s, f"group_size_{j}_{k}")

    pairs = list(combinations(range(n), 2))

    y = {}
    for a,b in pairs:
        for j in range(g):
            for k in range(w):
                var = model.addVar(vtype=GRB.CONTINUOUS, lb = 0.0, ub=1.0, name = f"y_{a}_{b}_{j}_{k}")
                y[a, b, j, k] = var
                model.addConstr(var >= x[a, j, k] + x[b, j, k] - 1)
                model.addConstr(var <= x[a, j, k])
                model.addConstr(var <= x[b, j, k])

        model.addConstr(
            gp.quicksum(y[a, b, j, k] for j in range(g) for k in range(w)) <= 1, f"meet_once_{a}_{b}"
        )

    if sb in ("sb1", "full"):
        for j in range(g):
            for c in range(s):
                model.addConstr(x[j * s + c, j, 0] == 1, f"sb1_{j}_{c}")

    if sb == "full" and w > 1:
        for k in range(1, w):
            for i in range(min(g,s)):
                model.addConstr(x[i, i, k] == 1, f"sb2_{k}_{i}")

    model.update()
    stats = {"n": n, "num_binary": n * g * w, "num_continuous": len(pairs) * g * w}
    return model, x, stats

def _extract_schedule(x, w, g, s):
    """Giải mã nghiệm ILP thành schedule[week][group] 0-based."""
    schedule = {k: {j: [] for j in range(g)} for k in range(w)}
    for i in range(g * s):
        for k in range(w):
            for j in range(g):
                if x[i, j, k].X > 0.5:
                    schedule[k][j].append(i)
                    break
    for k in range(w):
        for j in range(g):
            schedule[k][j].sort()

    return schedule

def solve_sgp_ilp(w, g, s, timeout_seconds=None, sb="none"):
    """Giải SGP bằng ILP và kiểm chứng nghiệm."""
    _positive_init("w", w)
    _positive_init("g", g)
    _positive_init("s", s)
    timeout_seconds = _timeout_seconds(timeout_seconds)
    if sb not in VALID_SB_MODES:
        raise ValueError(f"sb must be one of {VALID_SB_MODES}, got {sb!r}")

    started = time.perf_counter()
    n = g * s
    result = {"status": "ERROR", "method": "ilp", "solver": "gurobi", "backend": "gurobi",
        "solver_version": None, "w": w, "g": g, "s": s, "n": n, "sb": sb,
        "model_build_time_seconds": 0.0, "solver_wall_time_seconds": None,
        "wall_time_seconds": 0.0, "cpu_time_seconds": None, "total_time_seconds": 0.0,
        "num_vars": None, "num_constraints": None, "num_binary_vars": None,
        "stats": None, "schedule": None, "verified": False,
        "verification_errors": [], "error": None, "solver_status": None,
              }
    feasible_bound, w_max, unsat_reason = check_partner_bound(w, g, s)

    if not feasible_bound:
        result.update(
            status = "UNSAT", backend_type="precheck", solver_wall_time_seconds = 0.0,
            stats = {"n": n, "g": g, "s": s, "w": w, "w_max": w_max, "precheck_unsat": True, "unsat_reason": unsat_reason},
        )
        result["total_time_seconds"] = time.perf_counter() - started
        return result

    if gp is None:
        result.update(status="UNAVAILABLE", error=f"Gurobi unavailable: {_GUROBI_IMPORT_ERROR}")
        result["total_time_seconds"] = time.perf_counter() - started
        return result

    try:
        build_start = time.perf_counter()
        model, x, stats = build_ilp_model(w, g, s, sb=sb)
        result["model_build_time_seconds"] = time.perf_counter() - build_start
        result["solver_version"] = ".".join(str(part) for part in gp.gurobi.version())

    except gp.GurobiError as exc:
        result.update(status="UNAVAILABLE", error=f"Gurobi unavailable: {exc}")
        result["total_time_seconds"] = time.perf_counter() - started
        return result

    result["stats"] = stats
    if timeout_seconds is not None:
        model.Params.TimeLimit = timeout_seconds

    cpu_start = time.process_time()
    wall_start = time.perf_counter()
    try:
        model.optimize()
    except gp.GurobiError as exc:
        message = str(exc)
        limited = "size-limited" in message.lower() or "license" in message.lower()
        result.update(
            status="UNAVAILABLE" if limited else "ERROR",
            error=f"Gurobi error: {message}",
        )
        result["wall_time_seconds"] = time.perf_counter() - wall_start
        result["cpu_time_seconds"] = time.process_time() - cpu_start
        result["total_time_seconds"] = time.perf_counter() - started
        return result
    result["cpu_time_seconds"] = time.process_time() - cpu_start
    result["wall_time_seconds"] = time.perf_counter() - wall_start
    result["solver_wall_time_seconds"] = float(model.Runtime)
    result["num_vars"] = model.NumVars
    result["num_constraints"] = model.NumConstrs
    result["num_binary_vars"] = model.NumBinVars

    status = model.Status
    result["solver_status"] = {
        GRB.OPTIMAL: "OPTIMAL",
        GRB.INFEASIBLE: "INFEASIBLE",
        GRB.TIME_LIMIT: "TIME_LIMIT",
        GRB.INF_OR_UNBD: "INF_OR_UNBD",
        GRB.UNBOUNDED: "UNBOUNDED",
        GRB.INTERRUPTED: "INTERRUPTED",
    }.get(status, f"STATUS_{status}")
    if status == GRB.OPTIMAL:
        schedule = _extract_schedule(x, w, g, s)
        valid, errors = verify_schedule(schedule, w, g, s)
        result["verification_errors"] = errors
        if valid:
            result.update(status="SAT", schedule = schedule, verified = True)
        else:
            result.update(status="ERROR", error = "ILP solution decoded to an invalid schedule")
    elif status == GRB.INFEASIBLE:
        result["status"] = "UNSAT"
    elif status == GRB.TIME_LIMIT:
        # Giữ và kiểm chứng lịch đã tìm được trong thời gian cho phép.
        if model.SolCount > 0:
            schedule = _extract_schedule(x, w, g, s)
            valid, errors = verify_schedule(schedule, w, g, s)
            result["verification_errors"] = errors
            if valid:
                result.update(status="SAT", schedule=schedule, verified=True,
                              error=f"Gurobi TIME_LIMIT at {timeout_seconds:g}s; "
                                    "verified incumbent kept")
            else:
                result.update(status="ERROR",
                              error="Time-limit incumbent is not a valid schedule")
        else:
            result.update(status="TIMEOUT",
                          error=f"Gurobi exceeded {timeout_seconds:g} seconds")
    else:
        result.update(status="ERROR", error=f"Gurobi status {status}")

    result["total_time_seconds"] = time.perf_counter() - started
    return result

def main(argv=None):
    """CLI độc lập để debug module ILP."""
    from .display import print_result

    configure_safe_stdio()
    parser = argparse.ArgumentParser(description="Standalone Gurobi ILP solver for SGP")
    parser.add_argument("-w", type=int, required=True)
    parser.add_argument("-g", type=int, required=True)
    parser.add_argument("-s", type=int, required=True)
    parser.add_argument("--sb", default="none", choices=VALID_SB_MODES)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--zero-based", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = solve_sgp_ilp(args.w, args.g, args.s, timeout_seconds=args.timeout, sb=args.sb)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_result(result, one_based=not args.zero_based)
    return 0 if result["status"] in ("SAT", "UNSAT", "TIMEOUT") else 1

if __name__ == "__main__":
    sys.exit(main())