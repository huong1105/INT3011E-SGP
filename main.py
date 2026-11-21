"""CLI chung giải bài toán SGP."""

from __future__ import annotations

import json
import sys
from typing import Any

from src.cp_solver import solve_sgp_cp
from src.display import print_result
from src.io_utils import (
    api_to_paper,
    configure_safe_stdio,
    export_dimacs,
    parse_args,
    safe_print,
    write_csv_v1_row,
)
from src.sat_direct_encoders import encode_sgp
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
    """Chạy solver SAT và kiểm chứng nghiệm."""
    sb_clauses = _load_symmetry_clauses(args.weeks, args.groups, args.size, args.sb)

    if args.export_cnf:
        clauses, num_vars, _ = encode_sgp(
            args.weeks,
            args.groups,
            args.size,
            encoding=args.amo,
            symmetry_clauses=sb_clauses,
        )
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
    )
    result["method"] = "sat"
    result["sb"] = args.sb

    if result.get("status") == "SAT" and result.get("schedule") is not None:
        valid, errors = verify_schedule(
            result["schedule"], args.weeks, args.groups, args.size
        )
        result["verified"] = valid
        result["verification_errors"] = errors
        if not valid:
            result["status"] = "ERROR"
            result["error"] = "Universal Verifier rejected SAT schedule"

    return result


def _run_cp(args: Any) -> dict[str, Any]:
    """Chạy solver CP-SAT."""
    return solve_sgp_cp(
        args.weeks,
        args.groups,
        args.size,
        timeout_seconds=args.timeout,
        sb=args.sb,
        num_workers=args.workers,
    )


def _run_order(args: Any) -> dict[str, Any]:
    """Chạy solver Order Encoding."""
    from src import order_encoder

    solver_fn = getattr(order_encoder, "solve_sgp_order", None)
    if not callable(solver_fn):
        raise NotImplementedError(
            "Method --method order requires src/order_encoder.py, which is not yet implemented."
        )
    result = solver_fn(
        args.weeks,
        args.groups,
        args.size,
        solver=args.solver,
        timeout_seconds=args.timeout,
        sb=args.sb,
    )
    if result.get("status") == "SAT" and result.get("schedule") is not None:
        valid, errors = verify_schedule(
            result["schedule"], args.weeks, args.groups, args.size
        )
        result["verified"] = valid
        result["verification_errors"] = errors
        if not valid:
            result["status"] = "ERROR"
            result["error"] = "Universal Verifier rejected Order Encoding schedule"
    return result


def _run_ilp(args: Any) -> dict[str, Any]:
    """Chạy solver ILP."""
    from src import ilp_solver

    solver_fn = getattr(ilp_solver, "solve_sgp_ilp", None)
    if not callable(solver_fn):
        raise NotImplementedError(
            "Method --method ilp requires src/ilp_solver.py, which is not yet implemented."
        )
    result = solver_fn(
        args.weeks,
        args.groups,
        args.size,
        timeout_seconds=args.timeout,
        sb=args.sb,
    )
    if result.get("status") == "SAT" and result.get("schedule") is not None:
        valid, errors = verify_schedule(
            result["schedule"], args.weeks, args.groups, args.size
        )
        result["verified"] = valid
        result["verification_errors"] = errors
        if not valid:
            result["status"] = "ERROR"
            result["error"] = "Universal Verifier rejected ILP schedule"
    return result


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

    if args.csv:
        csv_path = write_csv_v1_row(result, args.csv)
        if not args.json:
            safe_print(f"Appended CSV v1 row to: {csv_path}")

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
