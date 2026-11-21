"""Mã hóa SGP bằng Order Encoding và giải bằng SAT runner."""

from __future__ import annotations

import argparse
import json
import sys
import time

from pysat.card import CardEnc, EncType

from .io_utils import VALID_SB_MODES, check_partner_bound, configure_safe_stdio
from .sat_runner import solve_cnf
from .verifier import verify_schedule

def encode_order_sgp(w: int, g: int, s: int, sb: str = "none"):
    """Sinh CNF Order Encoding, trả (clauses, num_vars, stats).

    Biến P_{k,j,c} in [1..n] được mã hóa bằng B_{k,j,c,v} <=> (P <= v), v in [1..n-1].
    """
    for name, value in (("w", w), ("g", g), ("s", s)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer, got {value!r}")
    if sb not in VALID_SB_MODES:
        raise ValueError(f"sb must be one of {VALID_SB_MODES}, got {sb!r}")

    n = g * s
    n_thresholds = n - 1
    n_b = w * g * s * n_thresholds
    n_e = w * n * g

    def b(k, j, c, v):
        """ID biến trật tự B_{k,j,c,v} (1-based)."""
        return ((k * g + j) * s + c) * n_thresholds + v

    def e(k, player, j):
        """ID biến thành viên e_{k,player,j}, player 0-based."""
        return n_b + (k * n + player) * g + j + 1

    clauses: list[list[int]] = []
    n_order = n_strict = n_alldiff = n_reify = n_sb = n_c3 = 0
    top_id = n_b + n_e

    if n > 1:
        # 1) Mệnh đề trật tự: (P <= v) -> (P <= v+1)
        for k in range(w):
            for j in range(g):
                for c in range(s):
                    for v in range(1, n - 1):
                        clauses.append([-b(k, j, c, v), b(k, j, c, v + 1)])
                        n_order += 1

        # 2) Thứ tự tăng nghiêm ngặt trong nhóm: X < Y
        for k in range(w):
            for j in range(g):
                for c in range(s - 1):
                    clauses.append([-b(k, j, c + 1, 1)])
                    clauses.append([b(k, j, c, n - 1)])
                    n_strict += 2
                    for v in range(2, n):
                        clauses.append([-b(k, j, c + 1, v), b(k, j, c, v - 1)])
                        n_strict += 1

        # 3) AllDifferent theo lớp ngưỡng: #{slot : P <= v} = v
        for k in range(w):
            for v in range(1, n):
                lits = [b(k, j, c, v) for j in range(g) for c in range(s)]
                cnf = CardEnc.equals(
                    lits=lits, bound=v, encoding=EncType.seqcounter, top_id=top_id
                )
                clauses.extend(cnf.clauses)
                n_alldiff += len(cnf.clauses)
                top_id = max(top_id, cnf.nv)

        # 4) Reification một chiều: (P = i) -> e
        for k in range(w):
            for j in range(g):
                for c in range(s):
                    for value in range(c + 1, n - s + c + 2):
                        member = e(k, value - 1, j)
                        if value == 1:
                            clauses.append([-b(k, j, c, 1), member])
                        elif value == n:
                            clauses.append([b(k, j, c, n - 1), member])
                        else:
                            clauses.append(
                                [-b(k, j, c, value), b(k, j, c, value - 1), member]
                            )
                        n_reify += 1

        # 5) SB1: tuần 0 chuẩn tắc
        if sb == "sb1":
            for j in range(g):
                for c in range(s):
                    fixed = j * s + c + 1
                    for v in range(1, n):
                        clauses.append(
                            [b(0, j, c, v)] if v >= fixed else [-b(0, j, c, v)]
                        )
                        n_sb += 1

        # 6) C3: không gặp lại
        for i1 in range(n):
            for i2 in range(i1 + 1, n):
                for k1 in range(w):
                    for k2 in range(k1 + 1, w):
                        for j1 in range(g):
                            for j2 in range(g):
                                clauses.append([-e(k1, i1, j1), -e(k1, i2, j1), -e(k2, i1, j2), -e(k2, i2, j2)])
                                n_c3 += 1

    largest = max((abs(lit) for clause in clauses for lit in clause), default=0)
    if largest > top_id:
        raise AssertionError(f"literal {largest} exceeds num_vars {top_id}")

    stats = {
        "n": n, "g": g, "s": s, "w": w,
        "n_order_vars": n_b, "n_member_vars": n_e,
        "n_aux_vars": top_id - (n_b + n_e), "n_total_vars": top_id,
        "n_order_clauses": n_order, "n_strict_clauses": n_strict,
        "n_alldiff_clauses": n_alldiff, "n_reify_clauses": n_reify,
        "n_c3_clauses": n_c3, "n_sb": n_sb, "n_total_clauses": len(clauses),
    }
    return clauses, top_id, stats

def decode_order_model(model, w: int, g: int, s: int):
    """Đọc giá trị P từ biến trật tự và trả schedule[week][group] 0-based."""
    n = g * s
    n_thresholds = n - 1
    true_literals = {lit for lit in model if lit > 0}
    schedule = {k: {j: [] for j in range(g)} for k in range(w)}

    for k in range(w):
        for j in range(g):
            for c in range(s):
                base = ((k * g + j) * s + c) * n_thresholds
                value = n
                for v in range(1, n):
                    if base + v in true_literals:
                        value = v
                        break
                schedule[k][j].append(value - 1)
            schedule[k][j].sort()
    return schedule

def solve_sgp_order(w: int, g: int, s: int, solver: str = "cadical",
                    timeout_seconds: float | None = None, sb: str = "none"):
    """Sinh CNF Order Encoding, giải và kiểm chứng lịch."""
    started = time.perf_counter()

    if sb == "full":
        raise NotImplementedError(
            "SB2 cannot be expressed in the slot-based Order Encoding; use --sb sb1"
        )

    feasible_bound, w_max, unsat_reason = check_partner_bound(w, g, s)
    if not feasible_bound:
        return {
            "status": "UNSAT", "method": "order", "encoding": "order",
            "backend_type": "precheck", "w": w, "g": g, "s": s, "n": g * s, "sb": sb,
            "num_vars": None, "num_clauses": None, "schedule": None,
            "verified": False, "error": None, "solver_wall_time_seconds": 0.0,
            "total_time_seconds": time.perf_counter() - started,
            "stats": {"precheck_unsat": True, "w_max": w_max, "unsat_reason": unsat_reason},
        }

    encode_start = time.perf_counter()
    clauses, num_vars, stats = encode_order_sgp(w, g, s, sb=sb)
    encode_time = time.perf_counter() - encode_start

    cnf = solve_cnf(clauses, solver=solver, timeout_seconds=timeout_seconds,
                    num_vars=num_vars)

    result = {
        "status": cnf["status"], "method": "order", "encoding": "order",
        "solver": solver, "backend": cnf.get("backend"),
        "solver_version": cnf.get("solver_version"),
        "w": w, "g": g, "s": s, "n": g * s, "sb": sb,
        "num_vars": num_vars, "num_clauses": len(clauses),
        "encode_time_seconds": encode_time, "model_build_time_seconds": encode_time,
        "solver_wall_time_seconds": cnf.get("solver_wall_time_seconds"),
        "wall_time_seconds": cnf.get("wall_time_seconds"),
        "cpu_time_seconds": cnf.get("cpu_time_seconds"),
        "conflicts": cnf.get("conflicts"), "decisions": cnf.get("decisions"),
        "propagations": cnf.get("propagations"),
        "stats": stats, "schedule": None, "verified": False,
        "verification_errors": [], "error": cnf.get("error"),
    }

    if cnf["status"] == "SAT":
        schedule = decode_order_model(cnf.get("model") or [], w, g, s)
        valid, errors = verify_schedule(schedule, w, g, s)
        result["verification_errors"] = errors
        if valid:
            result.update(schedule=schedule, verified=True)
        else:
            result.update(status="ERROR",
                          error="Order model decoded to an invalid SGP schedule")

    result["total_time_seconds"] = time.perf_counter() - started
    return result

def main(argv=None):
    """CLI độc lập để chạy và tự kiểm tra Order Encoding."""
    from .display import print_result

    configure_safe_stdio()
    parser = argparse.ArgumentParser(description="Standalone Order Encoding solver for SGP")
    parser.add_argument("-w", type=int, required=True)
    parser.add_argument("-g", type=int, required=True)
    parser.add_argument("-s", type=int, required=True)
    parser.add_argument("--solver", default="cadical", choices=("cadical", "glucose"))
    parser.add_argument("--sb", default="none", choices=VALID_SB_MODES)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--zero-based", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = solve_sgp_order(args.w, args.g, args.s, solver=args.solver,
                             timeout_seconds=args.timeout, sb=args.sb)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_result(result, one_based=not args.zero_based)
    return 0 if result["status"] in ("SAT", "UNSAT", "TIMEOUT") else 1


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(main())
    # Không có tham số: chạy bảng tự kiểm tra nhanh.
    for w, g, s in [(2, 2, 2), (3, 2, 2), (3, 3, 3), (2, 2, 3)]:
        r = solve_sgp_order(w, g, s, timeout_seconds=60)
        print(f"{w}-{g}-{s}: {r['status']} verified={r['verified']} "
              f"vars={r.get('num_vars')} clauses={r.get('num_clauses')}")