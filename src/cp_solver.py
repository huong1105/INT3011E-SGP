"""Giải SGP bằng OR-Tools CP-SAT."""

from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version
from itertools import combinations
import json
import math
import numbers
import sys
import time
from typing import Any

from .io_utils import VALID_SB_MODES, check_partner_bound, configure_safe_stdio, safe_print, write_csv_v1_row
from .verifier import verify_schedule

try:
    from ortools.sat.python import cp_model
except (ImportError, OSError) as exc:
    cp_model = None
    _ORTOOLS_IMPORT_ERROR = str(exc)
else:
    _ORTOOLS_IMPORT_ERROR = None


def _validate_positive_int(name: str, value: Any) -> None:
    """Kiểm tra tham số nguyên dương."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")


def _validate_timeout(timeout_seconds: Any) -> float | None:
    """Kiểm tra timeout hợp lệ."""
    if timeout_seconds is None:
        return None
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, numbers.Real):
        raise ValueError("timeout_seconds must be a finite positive number or None")
    value = float(timeout_seconds)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("timeout_seconds must be a finite positive number or None")
    return value


def _get_ortools_version() -> str | None:
    """Lấy phiên bản ortools."""
    try:
        return version("ortools")
    except PackageNotFoundError:
        return None


def build_cp_model(
    w: int,
    g: int,
    s: int,
    sb: str = "none",
) -> tuple[Any, dict[tuple[int, int, int], Any], dict[str, int]]:
    """Xây dựng mô hình CP-SAT cho SGP."""
    if cp_model is None:
        raise RuntimeError(f"Google OR-Tools unavailable: {_ORTOOLS_IMPORT_ERROR}")

    _validate_positive_int("w", w)
    _validate_positive_int("g", g)
    _validate_positive_int("s", s)
    if sb not in VALID_SB_MODES:
        raise ValueError(f"sb must be one of {VALID_SB_MODES}, got {sb!r}")

    n = g * s
    model = cp_model.CpModel()

    slot: dict[tuple[int, int, int], Any] = {}
    group_of: dict[tuple[int, int], Any] = {}
    num_int_vars = 0
    num_bool_vars = 0

    for k in range(w):
        flat_slots = []
        for j in range(g):
            for c in range(s):
                var = model.NewIntVar(0, n - 1, f"slot_w{k}_g{j}_c{c}")
                slot[(k, j, c)] = var
                flat_slots.append(var)
                num_int_vars += 1
            for c in range(s - 1):
                model.Add(slot[(k, j, c)] < slot[(k, j, c + 1)])

        model.AddAllDifferent(flat_slots)

        pos_vars = [model.NewIntVar(0, n - 1, f"pos_w{k}_p{i}") for i in range(n)]
        num_int_vars += n
        model.AddInverse(flat_slots, pos_vars)

        if s == 1:
            for i in range(n):
                group_of[(k, i)] = pos_vars[i]
        else:
            for i in range(n):
                grp_var = model.NewIntVar(0, g - 1, f"grp_w{k}_p{i}")
                model.AddDivisionEquality(grp_var, pos_vars[i], s)
                group_of[(k, i)] = grp_var
                num_int_vars += 1

    if w > 1 and s > 1:
        for i1, i2 in combinations(range(n), 2):
            meet_vars = []
            for k in range(w):
                same = model.NewBoolVar(f"meet_{i1}_{i2}_w{k}")
                model.Add(group_of[(k, i1)] == group_of[(k, i2)]).OnlyEnforceIf(same)
                model.Add(group_of[(k, i1)] != group_of[(k, i2)]).OnlyEnforceIf(same.Not())
                meet_vars.append(same)
                num_bool_vars += 1
            model.AddAtMostOne(meet_vars)

    if sb in ("sb1", "full"):
        for j in range(g):
            for c in range(s):
                model.Add(slot[(0, j, c)] == j * s + c)

    if sb == "full" and w > 1:
        limit = min(g, s)
        for k in range(1, w):
            for i in range(limit):
                model.Add(group_of[(k, i)] == i)

    num_total_vars = len(model.Proto().variables)
    num_constraints = len(model.Proto().constraints)
    model_stats = {
        "n": n,
        "g": g,
        "s": s,
        "w": w,
        "num_int_vars": num_int_vars,
        "num_bool_vars": num_bool_vars,
        "num_total_vars": num_total_vars,
        "num_constraints": num_constraints,
    }
    return model, slot, model_stats


def _extract_cp_schedule(
    solver: Any,
    slot: dict[tuple[int, int, int], Any],
    w: int,
    g: int,
    s: int,
) -> dict[int, dict[int, list[int]]]:
    """Trích xuất lịch từ nghiệm CP-SAT."""
    schedule: dict[int, dict[int, list[int]]] = {}
    for k in range(w):
        schedule[k] = {}
        for j in range(g):
            members = [int(solver.Value(slot[(k, j, c)])) for c in range(s)]
            schedule[k][j] = sorted(members)
    return schedule


def solve_sgp_cp(
    w: int,
    g: int,
    s: int,
    timeout_seconds: float | None = None,
    sb: str = "none",
    num_workers: int | None = None,
) -> dict[str, Any]:
    """Giải SGP bằng CP-SAT và kiểm chứng nghiệm."""
    _validate_positive_int("w", w)
    _validate_positive_int("g", g)
    _validate_positive_int("s", s)
    timeout_seconds = _validate_timeout(timeout_seconds)
    if sb not in VALID_SB_MODES:
        raise ValueError(f"sb must be one of {VALID_SB_MODES}, got {sb!r}")
    if num_workers is not None:
        _validate_positive_int("num_workers", num_workers)

    total_start = time.perf_counter()
    n = g * s

    base_result: dict[str, Any] = {
        "status": "ERROR",
        "method": "cp",
        "solver": "cp-sat",
        "backend": "ortools-cp-sat",
        "backend_type": "ortools",
        "solver_version": _get_ortools_version(),
        "ortools_version": _get_ortools_version(),
        "solver_status": None,
        "w": w,
        "g": g,
        "s": s,
        "n": n,
        "sb": sb,
        "num_workers": num_workers,
        "encode_time_seconds": None,
        "model_build_time_seconds": None,
        "solver_wall_time_seconds": None,
        "wall_time_seconds": 0.0,
        "cpu_time_seconds": None,
        "total_time_seconds": 0.0,
        "num_vars": None,
        "num_constraints": None,
        "conflicts": None,
        "branches": None,
        "stats": None,
        "schedule": None,
        "verified": False,
        "verification_errors": [],
        "error": None,
    }

    feasible_bound, w_max, unsat_reason = check_partner_bound(w, g, s)
    if not feasible_bound:
        elapsed = time.perf_counter() - total_start
        base_result.update(
            status="UNSAT",
            backend="theoretical-bound",
            backend_type="precheck",
            solver_wall_time_seconds=None,
            wall_time_seconds=elapsed,
            total_time_seconds=elapsed,
            stats={
                "n": n,
                "g": g,
                "s": s,
                "w": w,
                "w_max": w_max,
                "precheck_unsat": True,
                "unsat_reason": unsat_reason,
            },
        )
        return base_result

    if cp_model is None:
        elapsed = time.perf_counter() - total_start
        base_result.update(
            status="UNAVAILABLE",
            wall_time_seconds=elapsed,
            total_time_seconds=elapsed,
            error=f"Google OR-Tools unavailable: {_ORTOOLS_IMPORT_ERROR}",
        )
        return base_result

    try:
        build_start = time.perf_counter()
        model, slot, model_stats = build_cp_model(w, g, s, sb=sb)
        build_time = time.perf_counter() - build_start
        model_stats["w_max"] = w_max
        model_stats["precheck_unsat"] = False
        model_stats["unsat_reason"] = None
        base_result["encode_time_seconds"] = build_time
        base_result["model_build_time_seconds"] = build_time
        base_result["num_vars"] = model_stats["num_total_vars"]
        base_result["num_constraints"] = model_stats["num_constraints"]
        base_result["stats"] = model_stats

        solver = cp_model.CpSolver()
        if timeout_seconds is not None:
            solver.parameters.max_time_in_seconds = timeout_seconds
        if num_workers is not None:
            solver.parameters.num_search_workers = num_workers

        solve_cpu_start = time.process_time()
        solve_start = time.perf_counter()
        status_code = solver.Solve(model)
        solve_outer_wall = time.perf_counter() - solve_start
        solve_cpu = time.process_time() - solve_cpu_start
        base_result["solver_status"] = solver.StatusName(status_code)

        solver_wall = solver.WallTime()
        base_result["solver_wall_time_seconds"] = (
            float(solver_wall)
            if isinstance(solver_wall, (int, float)) and math.isfinite(solver_wall)
            else solve_outer_wall
        )
        base_result["wall_time_seconds"] = solve_outer_wall

        if math.isfinite(solve_cpu) and solve_cpu >= 0.0:
            base_result["cpu_time_seconds"] = float(solve_cpu)

        try:
            base_result["conflicts"] = int(solver.NumConflicts())
            base_result["branches"] = int(solver.NumBranches())
        except Exception:
            pass

        if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            schedule = _extract_cp_schedule(solver, slot, w, g, s)
            valid, errors = verify_schedule(schedule, w, g, s)
            if valid:
                base_result.update(
                    status="SAT",
                    schedule=schedule,
                    verified=True,
                    verification_errors=[],
                )
            else:
                base_result.update(
                    status="ERROR",
                    schedule=None,
                    verified=False,
                    verification_errors=errors,
                    error="CP-SAT model decoded to an invalid SGP schedule",
                )
        elif status_code == cp_model.INFEASIBLE:
            base_result["status"] = "UNSAT"
        elif status_code == cp_model.UNKNOWN:
            if timeout_seconds is not None:
                base_result.update(
                    status="TIMEOUT",
                    error=f"CP-SAT exceeded {timeout_seconds:g} seconds",
                )
            else:
                base_result.update(
                    status="ERROR",
                    error="CP-SAT returned UNKNOWN status without timeout",
                )
        else:
            base_result.update(
                status="ERROR",
                error=f"CP-SAT returned status {solver.StatusName(status_code)}",
            )
    except Exception as exc:
        base_result.update(status="ERROR", error=f"CP-SAT failed: {exc}")

    base_result["total_time_seconds"] = time.perf_counter() - total_start
    return base_result


def main(argv: list[str] | None = None) -> int:
    """Chạy CLI cho CP-SAT solver."""
    from .display import print_result

    configure_safe_stdio()
    parser = argparse.ArgumentParser(description="Standalone OR-Tools CP-SAT solver for SGP")
    parser.add_argument("-w", type=int, required=True, help="number of weeks")
    parser.add_argument("-g", type=int, required=True, help="groups per week")
    parser.add_argument("-s", type=int, required=True, help="players per group")
    parser.add_argument("--sb", default="none", choices=VALID_SB_MODES, help="symmetry breaking mode")
    parser.add_argument("--timeout", type=float, default=60.0, help="wall-time limit in seconds")
    parser.add_argument("--workers", type=int, default=None, help="CP-SAT search workers")
    parser.add_argument("--zero-based", action="store_true", help="display 0-based player indices")
    parser.add_argument("--json", action="store_true", help="print complete JSON result")
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help="output path to append benchmark CSV v1 row",
    )
    args = parser.parse_args(argv)

    try:
        result = solve_sgp_cp(
            args.w,
            args.g,
            args.s,
            timeout_seconds=args.timeout,
            sb=args.sb,
            num_workers=args.workers,
        )
    except ValueError as exc:
        parser.error(str(exc))

    if args.csv:
        csv_path = write_csv_v1_row(result, args.csv)
        if not args.json:
            safe_print(f"Appended CSV v1 row to: {csv_path}")

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=True))
    else:
        print_result(result, one_based=not args.zero_based)

    return 0 if result["status"] in ("SAT", "UNSAT", "TIMEOUT") else 1


if __name__ == "__main__":
    sys.exit(main())
