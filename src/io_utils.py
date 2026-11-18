"""Xử lý CLI, cận đối tác và xuất DIMACS CNF."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Iterable, Sequence

VALID_METHODS = ("sat", "order", "cp", "ilp")
VALID_C2_ENCODINGS = ("nsc", "seqcounter", "totalizer", "cardnetwrk")
VALID_SOLVERS = ("cadical", "glucose", "cp-sat", "gurobi")
VALID_SB_MODES = ("none", "sb1", "full")

DEFAULT_SOLVER_BY_METHOD = {
    "sat": "cadical",
    "order": "cadical",
    "cp": "cp-sat",
    "ilp": "gurobi",
}


def _validate_positive_int(name: str, value: int) -> None:
    """Kiểm tra tham số nguyên dương."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")


def max_weeks_bound(g: int, s: int) -> int | None:
    """Tính cận trên số tuần khi s > 1."""
    _validate_positive_int("g", g)
    _validate_positive_int("s", s)
    if s == 1:
        return None
    return (g * s - 1) // (s - 1)


def check_partner_bound(w: int, g: int, s: int) -> tuple[bool, int | None, str | None]:
    """Kiểm tra điều kiện cận đối tác."""
    _validate_positive_int("w", w)
    _validate_positive_int("g", g)
    _validate_positive_int("s", s)
    w_max = max_weeks_bound(g, s)
    if w_max is not None and w > w_max:
        return (
            False,
            w_max,
            f"w={w} exceeds partner bound floor((gs-1)/(s-1))={w_max}",
        )
    return True, w_max, None


def paper_to_api(g: int, p: int, w: int) -> tuple[int, int, int]:
    """Quy đổi (g, p, w) sang (w, g, s)."""
    _validate_positive_int("g", g)
    _validate_positive_int("p", p)
    _validate_positive_int("w", w)
    return (w, g, p)


def api_to_paper(w: int, g: int, s: int) -> tuple[int, int, int]:
    """Quy đổi (w, g, s) sang (g, p, w)."""
    _validate_positive_int("w", w)
    _validate_positive_int("g", g)
    _validate_positive_int("s", s)
    return (g, s, w)


def parse_paper_instance(label: str) -> tuple[int, int, int]:
    """Đọc nhãn dạng g-p-w thành (w, g, s)."""
    parts = [part.strip() for part in label.strip().split("-")]
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(
            f"Invalid paper instance label {label!r}; expected 'g-p-w' (e.g. '2-2-3')"
        )
    g, p, w = (int(part) for part in parts)
    return paper_to_api(g, p, w)


def format_dimacs(
    clauses: Iterable[Iterable[int]],
    num_vars: int | None = None,
    comments: Sequence[str] | None = None,
) -> str:
    """Tạo chuỗi định dạng DIMACS CNF."""
    normalized: list[list[int]] = []
    max_var = 0
    for clause in clauses:
        row = list(clause)
        for lit in row:
            if isinstance(lit, bool) or not isinstance(lit, int) or lit == 0:
                raise ValueError(f"DIMACS literal must be a nonzero integer, got {lit!r}")
            max_var = max(max_var, abs(lit))
        normalized.append(row)

    if num_vars is None:
        resolved_vars = max_var
    else:
        if isinstance(num_vars, bool) or not isinstance(num_vars, int) or num_vars < max_var:
            raise ValueError(
                f"num_vars must be an integer >= max literal ({max_var}), got {num_vars!r}"
            )
        resolved_vars = num_vars

    lines: list[str] = []
    if comments:
        for line in comments:
            for subline in str(line).splitlines():
                lines.append(f"c {subline}")
    lines.append(f"p cnf {resolved_vars} {len(normalized)}")
    for row in normalized:
        if row:
            lines.append(" ".join(str(lit) for lit in row) + " 0")
        else:
            lines.append("0")
    return "\n".join(lines) + "\n"


def export_dimacs(
    clauses: Iterable[Iterable[int]],
    num_vars: int | None,
    filepath: str | Path,
    comments: Sequence[str] | None = None,
) -> Path:
    """Xuất CNF ra file DIMACS."""
    target = Path(filepath)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = format_dimacs(clauses, num_vars=num_vars, comments=comments)
    target.write_text(content, encoding="utf-8")
    return target


def build_arg_parser() -> argparse.ArgumentParser:
    """Tạo CLI parser chung cho dự án."""
    parser = argparse.ArgumentParser(
        description="Social Golfer Problem (SGP) Unified Solver CLI (SAT / Order / CP / ILP)"
    )
    parser.add_argument("-w", "--weeks", type=int, required=True, help="Số tuần thi đấu (w >= 1)")
    parser.add_argument("-g", "--groups", type=int, required=True, help="Số nhóm mỗi tuần (g >= 1)")
    parser.add_argument(
        "-s", "--size", type=int, required=True, help="Số người mỗi nhóm (s >= 1, bài nguồn ký hiệu p)"
    )
    parser.add_argument(
        "--method",
        default="sat",
        choices=VALID_METHODS,
        help="Phương pháp giải: sat, order, cp, ilp (mặc định: sat)",
    )
    parser.add_argument(
        "--amo",
        "--encoding",
        dest="amo",
        default="nsc",
        choices=VALID_C2_ENCODINGS,
        help="Bộ mã hóa Exactly-s cho C2 (mặc định: nsc)",
    )
    parser.add_argument(
        "--solver",
        default=None,
        choices=VALID_SOLVERS,
        help="Solver cụ thể (cadical, glucose, cp-sat, gurobi); để trống sẽ tự chọn theo --method",
    )
    parser.add_argument(
        "--sb",
        default="none",
        choices=VALID_SB_MODES,
        help="Cấu hình Symmetry Breaking: none, sb1, full (SB1+SB2 nguồn; mặc định: none)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Giới hạn wall-time giải theo giây (mặc định: 60.0)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Số luồng tìm kiếm cho OR-Tools CP-SAT (tùy chọn, mặc định dùng cấu hình solver)",
    )
    parser.add_argument(
        "--export-cnf",
        type=str,
        default=None,
        help="Đường dẫn xuất file DIMACS .cnf (áp dụng khi chạy phương pháp SAT)",
    )
    parser.add_argument(
        "--zero-based",
        action="store_true",
        help="Hiển thị chỉ số người chơi bắt đầu từ 0 thay vì 1",
    )
    parser.add_argument(
        "--no-schedule",
        action="store_true",
        help="Không in bảng lịch thi đấu, chỉ in tóm tắt kết quả",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Xuất toàn bộ kết quả dưới dạng JSON",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Phân tích và kiểm tra tham số CLI."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    for name, value in (("w", args.weeks), ("g", args.groups), ("s", args.size)):
        if value < 1:
            parser.error(f"Tham số -{name} phải là số nguyên dương (nhận {value})")

    if args.timeout is not None and (not math.isfinite(args.timeout) or args.timeout <= 0):
        parser.error("--timeout phải là số thực dương hữu hạn")

    if args.workers is not None and args.workers < 1:
        parser.error("--workers phải là số nguyên dương")

    if args.solver is None:
        args.solver = DEFAULT_SOLVER_BY_METHOD[args.method]
    else:
        if args.method in ("sat", "order") and args.solver not in ("cadical", "glucose"):
            parser.error(
                f"Phương pháp --method {args.method} chỉ hỗ trợ --solver cadical hoặc glucose"
            )
        if args.method == "cp" and args.solver != "cp-sat":
            parser.error("Phương pháp --method cp chỉ hỗ trợ --solver cp-sat")
        if args.method == "ilp" and args.solver != "gurobi":
            parser.error("Phương pháp --method ilp chỉ hỗ trợ --solver gurobi")

    return args
