"""Xử lý CLI, cận đối tác, DIMACS và CSV."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Iterable, Iterator, Mapping, Sequence, TextIO

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

BENCHMARK_CSV_V1_FIELDS = (
    "instance",
    "n",
    "method",
    "encoding",
    "solver",
    "status",
    "encode_time_seconds",
    "solver_wall_time_seconds",
    "total_time_seconds",
    "num_vars",
    "num_clauses",
    "num_constraints",
    "error",
)
CSV_V1_KEY_FIELDS = ("instance", "method", "encoding", "solver")


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


def configure_safe_stdio() -> None:
    """Cấu hình stdout và stderr tránh lỗi encoding khi xuất đường dẫn Unicode."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(errors="backslashreplace")
            except Exception:
                pass


def safe_print(message: str, stream: Any = None) -> None:
    """In chuỗi an toàn theo encoding của stream."""
    target = sys.stdout if stream is None else stream
    try:
        print(message, file=target)
    except UnicodeEncodeError:
        encoding = getattr(target, "encoding", None) or "ascii"
        encoded = message.encode(encoding, errors="backslashreplace").decode(encoding)
        print(encoded, file=target)


def _csv_cell(value: Any) -> Any:
    """Chuyển None thành chuỗi rỗng để ghi CSV."""
    return "" if value is None else value


def _is_plain_int(value: Any) -> bool:
    """Kiểm tra giá trị là số nguyên thuần (không phải bool)."""
    return isinstance(value, int) and not isinstance(value, bool)


def result_to_csv_v1_row(result: dict[str, Any]) -> dict[str, Any]:
    """Chuẩn hóa kết quả solver thành một dòng chuẩn CSV benchmark v1."""
    w = result.get("w")
    g = result.get("g")
    s = result.get("s")
    if _is_plain_int(w) and _is_plain_int(g) and _is_plain_int(s):
        instance = f"{g}-{s}-{w}"
    else:
        instance = str(result.get("instance") or "").strip()

    if _is_plain_int(g) and _is_plain_int(s):
        n: Any = g * s
    else:
        n = _csv_cell(result.get("n"))

    method = str(result.get("method") or "").strip().lower()
    if method == "sat":
        encoding = str(result.get("encoding") or "").strip().lower()
    elif method == "order":
        encoding = "order"
    else:
        encoding = ""

    solver = str(result.get("solver") or "").strip().lower()
    if not solver:
        if method == "cp":
            solver = "cp-sat"
        elif method == "ilp":
            solver = "gurobi"

    stats = result.get("stats")
    is_precheck = (result.get("backend_type") == "precheck") or (
        isinstance(stats, dict) and bool(stats.get("precheck_unsat"))
    )
    status = (
        "UNSAT_PRECHECK"
        if is_precheck
        else str(result.get("status") or "ERROR").strip().upper()
    )
    error = " ".join(str(result.get("error") or "").split())
    if status == "SAT" and result.get("verified") is not True:
        status = "ERROR"
        error = error or "SAT schedule was not verified"
    if status in ("SAT", "UNSAT", "UNSAT_PRECHECK"):
        error = ""
    elif status == "TIMEOUT" and not error:
        error = "Time limit exceeded"

    if status in ("UNSAT_PRECHECK", "SKIPPED_RESOURCE_LIMIT"):
        encode_time: Any = ""
        solver_wall: Any = ""
        num_vars: Any = ""
        num_clauses: Any = ""
        num_constraints: Any = ""
        total_time: Any = _csv_cell(result.get("total_time_seconds"))
    else:
        encode_val = result.get("encode_time_seconds")
        if encode_val is None:
            encode_val = result.get("model_build_time_seconds")
        encode_time = _csv_cell(encode_val)
        solver_wall = _csv_cell(result.get("solver_wall_time_seconds"))
        total_time = _csv_cell(result.get("total_time_seconds"))
        num_vars = _csv_cell(result.get("num_vars"))
        num_clauses = _csv_cell(result.get("num_clauses")) if method in ("sat", "order") else ""
        num_constraints = (
            _csv_cell(result.get("num_constraints")) if method in ("cp", "ilp") else ""
        )

    return {
        "instance": instance,
        "n": n,
        "method": method,
        "encoding": encoding,
        "solver": solver,
        "status": status,
        "encode_time_seconds": encode_time,
        "solver_wall_time_seconds": solver_wall,
        "total_time_seconds": total_time,
        "num_vars": num_vars,
        "num_clauses": num_clauses,
        "num_constraints": num_constraints,
        "error": error,
    }


def read_csv_v1_rows(handle: TextIO) -> Iterator[dict[str, str]]:
    """Đọc và kiểm tra các dòng CSV v1."""
    if handle.read(1) != "\ufeff":
        handle.seek(0)
    reader = csv.DictReader(handle, strict=True)
    try:
        header = tuple(reader.fieldnames or ())
    except csv.Error as exc:
        raise ValueError(f"Invalid CSV v1 header: {exc}") from exc
    if header != BENCHMARK_CSV_V1_FIELDS:
        raise ValueError(
            "CSV header does not match benchmark v1. "
            f"Use a new file or provide this header: {','.join(BENCHMARK_CSV_V1_FIELDS)}"
        )
    try:
        for row in reader:
            if None in row or None in row.values():
                raise ValueError(f"Wrong number of benchmark CSV columns on line {reader.line_num}")
            yield row
    except csv.Error as exc:
        raise ValueError(f"Invalid benchmark CSV on line {reader.line_num}: {exc}") from exc


@contextmanager
def benchmark_csv_lock(path: str | Path) -> Iterator[None]:
    """Khóa file kết quả cho phiên ghi."""
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = target.with_name(f"{target.name}.lock")
    with lock.open("a+b") as handle:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise OSError(f"Could not lock {target}; another writer may be using it") from exc
        yield


def load_benchmark_csv_rows(path: str | Path) -> dict[tuple[str, ...], dict[str, str]]:
    """Đọc kết quả CSV v1 theo khóa từng ca."""
    target = Path(path)
    rows = {}
    if not target.exists() or target.stat().st_size == 0:
        return rows
    with target.open(encoding="utf-8", newline="") as handle:
        for row in read_csv_v1_rows(handle):
            key = tuple(row[field] for field in CSV_V1_KEY_FIELDS)
            if key in rows:
                raise ValueError(f"Duplicate benchmark case {key}")
            rows[key] = row
    return rows


@contextmanager
def _atomic_text_file(target: Path) -> Iterator[TextIO]:
    """Ghi file bằng cách thay thế nguyên tử."""
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", dir=target.parent,
        prefix=f".{target.name}-", suffix=".tmp", delete=False,
    )
    pending = Path(handle.name)
    try:
        with handle:
            yield handle
            handle.flush()
            os.fsync(handle.fileno())
        pending.replace(target)
    finally:
        pending.unlink(missing_ok=True)


def save_benchmark_csv_rows(
    path: str | Path, rows: Mapping[tuple[str, ...], Mapping[str, Any]],
) -> None:
    """Lưu bảng kết quả CSV v1."""
    with _atomic_text_file(Path(path)) as handle:
        writer = csv.DictWriter(handle, fieldnames=BENCHMARK_CSV_V1_FIELDS)
        writer.writeheader()
        writer.writerows(rows.values())


def set_benchmark_csv_config(
    path: str | Path, config: Mapping[str, Any], *, resume: bool,
) -> None:
    """Lưu hoặc kiểm tra cấu hình benchmark."""
    target = Path(path)
    metadata = target.with_name(f"{target.name}.meta.json")
    if resume:
        if not metadata.is_file() or json.loads(metadata.read_text(encoding="utf-8")) != config:
            raise ValueError("Missing or different benchmark settings in the companion .meta.json; "
                             "use a new CSV file for this benchmark")
        return

    with _atomic_text_file(metadata) as handle:
        json.dump(dict(config), handle, indent=2)
        handle.write("\n")


def write_csv_v1_row(
    result: dict[str, Any],
    filepath: str | Path,
    append: bool = True,
    *,
    config: Mapping[str, Any],
) -> Path:
    """Ghi hoặc thay dòng kết quả CSV v1."""
    path = Path(filepath)
    target = path.resolve()
    row = result_to_csv_v1_row(result)
    key = tuple(row[field] for field in CSV_V1_KEY_FIELDS)
    with benchmark_csv_lock(target):
        rows = load_benchmark_csv_rows(target) if append else {}
        if not append and target.exists():
            save_benchmark_csv_rows(target, rows)
        set_benchmark_csv_config(target, config, resume=bool(rows))
        rows[key] = row
        save_benchmark_csv_rows(target, rows)
    return path


def build_arg_parser() -> argparse.ArgumentParser:
    """Tạo CLI parser chung cho dự án."""
    parser = argparse.ArgumentParser(
        description="Social Golfer Problem (SGP) Unified Solver CLI (SAT / Order / CP / ILP)"
    )
    parser.add_argument("-w", "--weeks", type=int, required=True, help="number of weeks (w >= 1)")
    parser.add_argument("-g", "--groups", type=int, required=True, help="groups per week (g >= 1)")
    parser.add_argument(
        "-s", "--size", type=int, required=True, help="players per group (s >= 1, paper label p)"
    )
    parser.add_argument(
        "--method",
        default="sat",
        choices=VALID_METHODS,
        help="solving method: sat, order, cp, ilp (default: sat)",
    )
    parser.add_argument(
        "--amo",
        "--encoding",
        dest="amo",
        default=None,
        choices=VALID_C2_ENCODINGS,
        help="C2 Exactly-s encoding (default: nsc)",
    )
    parser.add_argument(
        "--solver",
        default=None,
        choices=VALID_SOLVERS,
        help="solver backend (cadical, glucose, cp-sat, gurobi); defaults by --method",
    )
    parser.add_argument(
        "--sb",
        default="none",
        choices=VALID_SB_MODES,
        help="symmetry breaking mode: none, sb1, full (default: none)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="wall-time limit in seconds (default: 60.0)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="search workers for OR-Tools CP-SAT (optional)",
    )
    parser.add_argument(
        "--export-cnf",
        type=str,
        default=None,
        help="output path for DIMACS .cnf export (when --method sat)",
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help="output path for a benchmark CSV v1 row",
    )
    parser.add_argument(
        "--zero-based",
        action="store_true",
        help="display 0-based player indices instead of 1-based",
    )
    parser.add_argument(
        "--no-schedule",
        action="store_true",
        help="suppress schedule matrix output and print summary only",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the complete JSON result",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Phân tích và kiểm tra tham số CLI."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    for name, value in (("w", args.weeks), ("g", args.groups), ("s", args.size)):
        if value < 1:
            parser.error(f"Parameter -{name} must be a positive integer (got {value})")

    if args.timeout is not None and (not math.isfinite(args.timeout) or args.timeout <= 0):
        parser.error("--timeout must be a finite positive number")

    if args.workers is not None and args.workers < 1:
        parser.error("--workers must be a positive integer")

    if args.method != "sat" and args.amo is not None:
        parser.error("--amo/--encoding is only available with --method sat")
    if args.method != "sat" and args.export_cnf is not None:
        parser.error("--export-cnf is only available with --method sat")
    if args.method != "cp" and args.workers is not None:
        parser.error("--workers is only available with --method cp")
    if args.method == "order" and args.sb == "full":
        parser.error("--method order only supports --sb none or sb1")
    if args.csv and args.export_cnf and Path(args.csv).resolve() == Path(args.export_cnf).resolve():
        parser.error("--csv and --export-cnf must use different output files")

    args.amo = args.amo or "nsc"
    if args.solver is None:
        args.solver = DEFAULT_SOLVER_BY_METHOD[args.method]
    else:
        if args.method in ("sat", "order") and args.solver not in ("cadical", "glucose"):
            parser.error(
                f"Method --method {args.method} only supports --solver cadical or glucose"
            )
        if args.method == "cp" and args.solver != "cp-sat":
            parser.error("Method --method cp only supports --solver cp-sat")
        if args.method == "ilp" and args.solver != "gurobi":
            parser.error("Method --method ilp only supports --solver gurobi")

    return args
