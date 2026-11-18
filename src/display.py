"""Hiển thị lịch và kết quả SGP."""

from __future__ import annotations

from typing import Any

try:
    from tabulate import tabulate as _tabulate
except ImportError:
    _tabulate = None


def format_schedule(
    schedule: dict[int, dict[int, list[int]]],
    one_based: bool = True,
) -> str:
    """Định dạng lịch gọn theo tuần."""
    offset = 1 if one_based else 0
    lines: list[str] = []
    for week in sorted(schedule.keys()):
        groups_str: list[str] = []
        for group in sorted(schedule[week].keys()):
            players = [str(p + offset) for p in sorted(schedule[week][group])]
            groups_str.append("{" + ", ".join(players) + "}")
        lines.append(f"  Week {week + 1}: " + "  ".join(groups_str))
    return "\n".join(lines)


def _format_fallback_table(headers: list[str], rows: list[list[str]]) -> str:
    """Tạo bảng ASCII đơn giản."""
    widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    header_line = (
        "| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)) + " |"
    )
    lines = [sep, header_line, sep]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
            + " |"
        )
    lines.append(sep)
    return "\n".join(lines)


def format_schedule_table(
    schedule: dict[int, dict[int, list[int]]],
    w: int | None = None,
    g: int | None = None,
    s: int | None = None,
    one_based: bool = True,
    tablefmt: str = "grid",
) -> str:
    """Định dạng lịch thành bảng ma trận."""
    if not schedule:
        return "(Empty schedule)"

    offset = 1 if one_based else 0
    weeks = sorted(schedule.keys())
    groups = sorted(schedule[weeks[0]].keys()) if weeks else []

    headers = ["Week \\ Group"] + [f"Group {j + 1}" for j in groups]
    rows: list[list[str]] = []
    for week in weeks:
        row = [f"Week {week + 1}"]
        for group in groups:
            members = sorted(schedule[week].get(group, []))
            cell = "{" + ", ".join(str(p + offset) for p in members) + "}"
            row.append(cell)
        rows.append(row)

    title_parts: list[str] = []
    if w is not None and g is not None and s is not None:
        title_parts.append(f"SGP(w={w}, g={g}, s={s}) | n={g * s} players")
        title_parts.append(f"Paper label (g-p-w): {g}-{s}-{w}")

    if _tabulate is not None:
        table_str = _tabulate(rows, headers=headers, tablefmt=tablefmt)
    else:
        table_str = _format_fallback_table(headers, rows)

    if title_parts:
        return "\n".join(title_parts) + "\n" + table_str
    return table_str


def print_schedule(
    schedule: dict[int, dict[int, list[int]]],
    w: int | None = None,
    g: int | None = None,
    s: int | None = None,
    one_based: bool = True,
    tablefmt: str = "grid",
) -> None:
    """In bảng lịch ra màn hình."""
    print(format_schedule_table(schedule, w=w, g=g, s=s, one_based=one_based, tablefmt=tablefmt))


def _fmt_seconds(value: Any) -> str:
    """Định dạng số giây."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.6f}s"
    return "N/A"


def format_result_summary(result: dict[str, Any]) -> str:
    """Tạo chuỗi tóm tắt kết quả chạy."""
    w = result.get("w")
    g = result.get("g")
    s = result.get("s")
    n = g * s if isinstance(g, int) and isinstance(s, int) else result.get("n")
    method = result.get("method", "unknown")
    solver = result.get("solver", result.get("backend", "unknown"))
    status = result.get("status", "UNKNOWN")
    verified = result.get("verified", False)

    lines = [
        "=" * 64,
        f"Instance : SGP(w={w}, g={g}, s={s}) | n={n} | paper (g-p-w)={g}-{s}-{w}",
        f"Method   : {method} | Solver: {solver}",
    ]
    if result.get("encoding") is not None:
        lines.append(f"Encoding : {result['encoding']}")
    if result.get("sb") is not None:
        lines.append(f"Symmetry : {result['sb']}")

    lines.append(f"Status   : {status} | Verified: {verified}")

    build_t = result.get("model_build_time_seconds", result.get("encode_time_seconds"))
    if build_t is not None:
        label = "Encode time" if "encode_time_seconds" in result else "Build time "
        lines.append(f"{label}: {_fmt_seconds(build_t)}")
    if "solver_wall_time_seconds" in result:
        lines.append(f"Solve wall : {_fmt_seconds(result.get('solver_wall_time_seconds'))}")
    if "cpu_time_seconds" in result:
        lines.append(f"CPU time   : {_fmt_seconds(result.get('cpu_time_seconds'))}")
    if "total_time_seconds" in result:
        lines.append(f"Total time : {_fmt_seconds(result.get('total_time_seconds'))}")
    elif "wall_time_seconds" in result:
        lines.append(f"Wall time  : {_fmt_seconds(result.get('wall_time_seconds'))}")

    if result.get("error"):
        lines.append(f"Error    : {result['error']}")
    lines.append("=" * 64)
    return "\n".join(lines)


def print_result(
    result: dict[str, Any],
    one_based: bool = True,
    show_schedule: bool = True,
    tablefmt: str = "grid",
) -> None:
    """In tóm tắt kết quả và lịch."""
    print(format_result_summary(result))
    schedule = result.get("schedule")
    if show_schedule and result.get("status") == "SAT" and schedule:
        print()
        print_schedule(
            schedule,
            w=result.get("w"),
            g=result.get("g"),
            s=result.get("s"),
            one_based=one_based,
            tablefmt=tablefmt,
        )
