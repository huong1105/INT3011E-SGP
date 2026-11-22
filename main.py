"""CLI chung giải bài toán SGP."""

from __future__ import annotations

import json
import sys
import time
from typing import Any

from src.cp_solver import solve_sgp_cp
from src.display import print_result
from src.io_utils import (
    api_to_paper,
    check_partner_bound,
    configure_safe_stdio,
    export_dimacs,
    parse_args,
    safe_print,
    write_csv_v1_row,
)
from src.sat_runner import solve_sgp
from src.verifier import verify_schedule


def _load_symmetry_clauses(
    w: int,
    g: int,
    s: int,
    sb: str,
) -> list[list[int]] | None:
    """Nạp mệnh đề symmetry breaking từ src/symmetry.py."""
    if sb == "none":
        return None
    try:
        from src import symmetry as sb_module
    except ImportError as exc:
        raise RuntimeError(f"Could not import src.symmetry: {exc}") from exc

    for fn_name in ("generate_symmetry_clauses", "encode_symmetry", "get_symmetry_clauses"):
        fn = getattr(sb_module, fn_name, None)
        if callable(fn):
            return fn(w, g, s, mode=sb)

    raise NotImplementedError(
        f"Flag --sb {sb} requires src/symmetry.py, which is not yet implemented."
    )


def _run_sat(args: Any) -> dict[str, Any]:
    """Chạy SAT và xuất CNF theo yêu cầu."""
    setup_started = time.perf_counter()
    sb_clauses = _load_symmetry_clauses(args.weeks, args.groups, args.size, args.sb)
    setup_time = time.perf_counter() - setup_started

    def export_cnf(clauses: list[list[int]], num_vars: int) -> None:
        pg, pp, pw = api_to_paper(args.weeks, args.groups, args.size)
        out_path = export_dimacs(
            clauses,
            num_vars,
            args.export_cnf,
            comments=[
                f"Social Golfer Problem SGP(w={args.weeks}, g={args.groups}, s={args.size})",
                f"Paper label (g-p-w): {pg}-{pp}-{pw}",
                f"C2 encoding: {args.amo}, sb: {args.sb}",
            ],
        )
        if not args.json:
            safe_print(f"Exported DIMACS CNF to: {out_path}")

    result = solve_sgp(
        args.weeks,
        args.groups,
        args.size,
        encoding=args.amo,
        solver=args.solver,
        timeout_seconds=args.timeout,
        symmetry_clauses=sb_clauses,
        on_encoded=export_cnf if args.export_cnf else None,
    )
    result.update(method="sat", sb=args.sb)
    result["total_time_seconds"] += setup_time
    return result


def _run_cp(args: Any) -> dict[str, Any]:
    """Chạy solver CP-SAT."""
    return solve_sgp_cp(
        args.weeks,
        args.groups,
        args.size,
        timeout_seconds=args.timeout,
        sb=args.sb,
        num_workers=(args.workers or 1) if args.csv else args.workers,
    )


def _run_order(args: Any) -> dict[str, Any]:
    """Chạy solver Order Encoding."""
    from src import order_encoder

    solver_fn = getattr(order_encoder, "solve_sgp_order", None)
    if not callable(solver_fn):
        raise NotImplementedError(
            "Method --method order requires src/order_encoder.py, which is not yet implemented."
        )
    return solver_fn(
        args.weeks,
        args.groups,
        args.size,
        solver=args.solver,
        timeout_seconds=args.timeout,
        sb=args.sb,
    )


def _run_ilp(args: Any) -> dict[str, Any]:
    """Chạy solver ILP."""
    from src import ilp_solver

    solver_fn = getattr(ilp_solver, "solve_sgp_ilp", None)
    if not callable(solver_fn):
        raise NotImplementedError(
            "Method --method ilp requires src/ilp_solver.py, which is not yet implemented."
        )
    w, g, s = args.weeks, args.groups, args.size
    if args.csv and check_partner_bound(w, g, s)[0]:
        failure = ilp_solver.prepare_gurobi()
        if failure is not None:
            return dict(failure, method="ilp", w=w, g=g, s=s, n=g * s, sb=args.sb)
    return solver_fn(
        w, g, s, timeout_seconds=args.timeout, sb=args.sb, num_threads=1 if args.csv else None
    )


def main(argv: list[str] | None = None) -> int:
    """Điểm vào chính của CLI."""
    configure_safe_stdio()
    args = parse_args(argv)

    dispatch = {
        "sat": _run_sat,
        "cp": _run_cp,
        "order": _run_order,
        "ilp": _run_ilp,
    }

    try:
        result = dispatch[args.method](args)
    except NotImplementedError as exc:
        safe_print(f"[Not implemented] {exc}", stream=sys.stderr)
        return 2
    except Exception as exc:
        safe_print(f"[Error] {exc}", stream=sys.stderr)
        return 1

    result.setdefault("solver", args.solver)
    if result.get("status") == "SAT":
        verification_started = time.perf_counter()
        valid, errors = verify_schedule(
            result.get("schedule"), args.weeks, args.groups, args.size
        )
        result.update(verified=valid, verification_errors=errors)
        if not valid:
            result.update(status="ERROR", error="Universal Verifier rejected the schedule")
        result["total_time_seconds"] += time.perf_counter() - verification_started

    if args.csv:
        config = {
            "sb": args.sb,
            "timeout_seconds": args.timeout,
            "timeout_scope": "solver",
            "num_threads": args.workers or 1,
        }
        try:
            csv_path = write_csv_v1_row(result, args.csv, config=config)
        except (OSError, ValueError) as exc:
            safe_print(f"[Error] Could not write CSV {args.csv}: {exc}", stream=sys.stderr)
            return 1
        if not args.json:
            safe_print(f"Saved CSV v1 row to: {csv_path}")

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=True))
    else:
        print_result(
            result,
            one_based=not args.zero_based,
            show_schedule=not args.no_schedule,
        )

    return 0 if result.get("status") in ("SAT", "UNSAT", "TIMEOUT") else 1


if __name__ == "__main__":
    sys.exit(main())
