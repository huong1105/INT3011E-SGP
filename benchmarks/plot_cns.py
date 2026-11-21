"""Vẽ biểu đồ thực nghiệm SGP bằng cnsplots."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

import matplotlib

matplotlib.use("Agg")

import cnsplots as cns
import matplotlib.pyplot as plt
import pandas as pd


C2_ENCODING_LABELS = {
    "nsc": "NSC",
    "seqcounter": "Sequential Counter",
    "totalizer": "Totalizer",
    "cardnetwrk": "Cardinality Network",
}

C2_ENCODING_ORDER = ["NSC", "Sequential Counter", "Totalizer", "Cardinality Network"]

SOLVER_DISPLAY_NAMES = {
    "cadical": "CaDiCaL",
    "glucose": "Glucose",
    "cp-sat": "OR-Tools CP-SAT",
    "ortools": "OR-Tools CP-SAT",
    "ortools-cp-sat": "OR-Tools CP-SAT",
    "gurobi": "Gurobi",
    "cplex": "CPLEX",
}

METHOD_SOLVER_LABELS = {
    ("sat", "cadical"): "SAT (CaDiCaL)",
    ("sat", "glucose"): "SAT (Glucose)",
    ("order", "cadical"): "Order SAT (CaDiCaL)",
    ("order", "glucose"): "Order SAT (Glucose)",
    ("cp", "cp-sat"): "CP (OR-Tools CP-SAT)",
    ("cp", "ortools"): "CP (OR-Tools CP-SAT)",
    ("cp", "ortools-cp-sat"): "CP (OR-Tools CP-SAT)",
    ("ilp", "gurobi"): "ILP (Gurobi)",
    ("ilp", "cplex"): "ILP (CPLEX)",
}


def _format_solver_name(solver: str) -> str:
    """Trả về tên hiển thị chuẩn của solver."""
    key = solver.strip().lower()
    return SOLVER_DISPLAY_NAMES.get(key, solver.strip() or "unknown")


def _format_sat_label(sat_solver: str) -> str:
    """Trả về nhãn hiển thị cho nhánh SAT theo solver được chọn."""
    key = sat_solver.strip().lower()
    return METHOD_SOLVER_LABELS.get(("sat", key), f"SAT ({_format_solver_name(sat_solver)})")


def _format_ilp_label(df: pd.DataFrame) -> str:
    """Trả về nhãn hiển thị cho nhánh ILP theo solver có trong dữ liệu."""
    ilp_rows = df[df["method"] == "ilp"]
    solvers = [
        item
        for item in ilp_rows["solver"].fillna("").astype(str).str.strip().str.lower().unique()
        if item
    ]
    if "cplex" in solvers and "gurobi" not in solvers:
        return METHOD_SOLVER_LABELS[("ilp", "cplex")]
    if solvers:
        key = solvers[0]
        return METHOD_SOLVER_LABELS.get(("ilp", key), f"ILP ({_format_solver_name(key)})")
    return "ILP (Gurobi)"


TIME_COLUMN_CANDIDATES = (
    "total_time_seconds",
    "solver_wall_time_seconds",
    "wall_time_seconds",
    "solve_time",
    "wall_time",
    "runtime",
    "time",
)

MIN_LOG_TIME = 1e-4


def _resolve_column(df: pd.DataFrame, candidates: Sequence[str]) -> str | None:
    """Tìm tên cột đầu tiên khớp danh sách."""
    lower_map = {col.lower(): col for col in df.columns}
    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    return None


def _normalize_results_df(df: pd.DataFrame, time_col: str | None = None) -> pd.DataFrame:
    """Chuẩn hóa DataFrame kết quả benchmark và loại bỏ dòng thử lại trùng lặp."""
    df = df.copy()
    rename_map: dict[str, str] = {}

    if time_col is not None:
        selected_time_col = _resolve_column(df, (time_col,))
        if selected_time_col is None:
            raise ValueError(
                f"Requested time column {time_col!r} not found in CSV. Available columns: {list(df.columns)}"
            )
    else:
        selected_time_col = _resolve_column(df, TIME_COLUMN_CANDIDATES)
        if selected_time_col is None:
            raise ValueError(
                f"No runtime column found in CSV. Available columns: {list(df.columns)}"
            )
    if selected_time_col != "solve_time":
        rename_map[selected_time_col] = "solve_time"

    enc_col = _resolve_column(df, ("encoding", "amo", "encoder"))
    if enc_col is not None and enc_col != "encoding":
        rename_map[enc_col] = "encoding"

    if rename_map:
        df = df.rename(columns=rename_map)

    had_sb = "sb" in df.columns
    for col in ("method", "solver", "encoding", "status", "backend_type"):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()

    if had_sb:
        df["sb"] = df["sb"].fillna("").astype(str).str.strip().str.lower().replace("", "none")
    else:
        df["sb"] = ""

    df["method"] = df["method"].str.lower()
    df["solver"] = df["solver"].str.lower()
    df["encoding"] = df["encoding"].str.lower()
    df["backend_type"] = df["backend_type"].str.lower()
    df["status"] = df["status"].str.upper()
    df["solve_time"] = pd.to_numeric(df["solve_time"], errors="coerce")

    if "n" not in df.columns:
        if "g" in df.columns and "s" in df.columns:
            df["n"] = pd.to_numeric(df["g"], errors="coerce") * pd.to_numeric(
                df["s"], errors="coerce"
            )
        else:
            df["n"] = pd.NA
    else:
        df["n"] = pd.to_numeric(df["n"], errors="coerce")

    if "instance" not in df.columns:
        if {"g", "s", "w"}.issubset(df.columns):
            df["instance"] = (
                df["g"].astype(str) + "-" + df["s"].astype(str) + "-" + df["w"].astype(str)
            )
        else:
            df["instance"] = [f"inst_{i}" for i in range(len(df))]
    else:
        df["instance"] = df["instance"].fillna("").astype(str).str.strip()

    if "verified" in df.columns:
        df["verified"] = (
            df["verified"].astype(str).str.lower().isin({"true", "1", "yes"})
        )
    else:
        df["verified"] = True

    key_cols = ["instance", "method", "encoding", "solver"] + (["sb"] if had_sb else [])
    if "attempt" in df.columns:
        df["_attempt_num"] = pd.to_numeric(df["attempt"], errors="coerce").fillna(0)
        df = df.sort_values("_attempt_num", ascending=True, kind="mergesort")
        df = df.drop_duplicates(subset=key_cols, keep="last").drop(columns=["_attempt_num"])
    else:
        df = df.drop_duplicates(subset=key_cols, keep="last")

    df.attrs["time_col"] = selected_time_col
    df.attrs["has_sb"] = had_sb
    return df


def load_results(csv_path: str | Path, time_col: str | None = None) -> pd.DataFrame:
    """Đọc và chuẩn hóa file results.csv."""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Benchmark CSV file not found: {path}")

    df = pd.read_csv(path)
    if df.empty:
        raise ValueError(f"Benchmark CSV file is empty: {path}")

    return _normalize_results_df(df, time_col=time_col)


def _filter_solved(df: pd.DataFrame, cutoff: float | None = None) -> pd.DataFrame:
    """Lọc các bản ghi giải thành công bởi solver và loại bỏ ca precheck."""
    not_precheck = df["status"] != "UNSAT_PRECHECK"
    if "backend_type" in df.columns:
        not_precheck = not_precheck & (
            df["backend_type"].fillna("").astype(str).str.strip().str.lower() != "precheck"
        )
    is_sat_ok = (df["status"] == "SAT") & df["verified"]
    is_unsat = df["status"] == "UNSAT"
    valid_time = df["solve_time"].notna() & (df["solve_time"] >= 0)
    mask = not_precheck & (is_sat_ok | is_unsat) & valid_time
    if cutoff is not None:
        mask = mask & (df["solve_time"] <= cutoff)
    filtered = df.loc[mask].copy()
    filtered.attrs.update(df.attrs)
    return filtered


def _apply_sb_filter(df: pd.DataFrame, sb: str | None) -> pd.DataFrame:
    """Lọc theo cấu hình SB khi dữ liệu đầu vào có cột sb không rỗng."""
    if sb is None or "sb" not in df.columns:
        return df
    has_nonempty_sb = (df["sb"].fillna("").astype(str).str.strip() != "").any()
    if not has_nonempty_sb:
        return df
    filtered = df[df["sb"] == sb.lower()].copy()
    filtered.attrs.update(df.attrs)
    return filtered


def _time_axis_label(df: pd.DataFrame, mean: bool = False) -> str:
    """Trả về nhãn trục thời gian khớp cột được dùng."""
    time_col = df.attrs.get("time_col", "total_time_seconds")
    prefix = "Mean " if mean else ""
    metric = "Total Time" if time_col == "total_time_seconds" else "Solve Time"
    return f"{prefix}{metric} (s, log scale)"


def _save_both_formats(output_dir: Path, stem: str, dpi: int = 300) -> list[Path]:
    """Lưu hình vẽ ra PDF và PNG."""
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for ext in ("pdf", "png"):
        out_path = output_dir / f"{stem}.{ext}"
        cns.savefig(out_path, dpi=dpi)
        saved.append(out_path)
    plt.close("all")
    return saved


def plot_cactus(
    df: pd.DataFrame,
    output_dir: str | Path,
    sat_encoding: str = "nsc",
    sb: str | None = None,
    sat_solver: str = "cadical",
    cutoff: float | None = None,
) -> list[Path]:
    """Vẽ Cactus Plot so sánh SAT, CP và ILP."""
    solved = _filter_solved(df, cutoff=cutoff)
    solved = _apply_sb_filter(solved, sb)

    sat_label = _format_sat_label(sat_solver)
    ilp_label = _format_ilp_label(df)
    groups: list[tuple[str, pd.DataFrame]] = [
        (
            sat_label,
            solved[
                (solved["method"] == "sat")
                & (solved["solver"] == sat_solver.lower())
                & ((solved["encoding"] == sat_encoding.lower()) | (solved["encoding"] == ""))
            ],
        ),
        ("CP (OR-Tools CP-SAT)", solved[solved["method"] == "cp"]),
        (ilp_label, solved[solved["method"] == "ilp"]),
    ]

    rows: list[dict[str, object]] = []
    hue_order: list[str] = []
    for label, sub in groups:
        if sub.empty:
            continue
        per_instance = sub.groupby("instance", as_index=False)["solve_time"].mean()
        hue_order.append(label)
        sorted_times = per_instance["solve_time"].sort_values().to_numpy()
        for idx, t in enumerate(sorted_times, start=1):
            rows.append(
                {
                    "solved_instances": idx,
                    "solve_time": max(float(t), MIN_LOG_TIME),
                    "Method": label,
                }
            )

    if not rows:
        print("[Warning] Not enough data to generate Cactus Plot (SAT vs CP vs ILP).")
        return []

    plot_df = pd.DataFrame(rows)

    cns.figure(width=5.4, height=3.6, unit="in", color_cycle="Nature")
    ax = cns.lineplot(
        data=plot_df,
        x="solved_instances",
        y="solve_time",
        hue="Method",
        style="Method",
        hue_order=hue_order,
        style_order=hue_order,
        markers=True,
        dashes=False,
        errorbar=None,
    )
    ax.set_yscale("log")
    ax.set_xlabel("Number of Solved Instances")
    ax.set_ylabel(_time_axis_label(df, mean=False))
    ax.set_title(f"Cactus Plot: {sat_label} vs. CP-SAT vs. ILP on SGP")
    ax.grid(True, which="both", linestyle="--", alpha=0.35)
    cns.take_legend_out()

    return _save_both_formats(Path(output_dir), "cactus_sat_cp_ilp")


def plot_c2_encodings(
    df: pd.DataFrame,
    output_dir: str | Path,
    sat_solver: str = "cadical",
    sb: str | None = "none",
    cutoff: float | None = None,
) -> list[Path]:
    """Vẽ Line Plot so sánh 4 bộ mã hóa C2."""
    solved = _filter_solved(df, cutoff=cutoff)
    solved = _apply_sb_filter(solved, sb)
    sub = solved[
        (solved["method"] == "sat")
        & (solved["solver"] == sat_solver.lower())
        & (solved["encoding"].isin(C2_ENCODING_LABELS.keys()))
        & solved["n"].notna()
    ].copy()

    if sub.empty:
        print(
            f"[Warning] Not enough SAT data ({sat_solver}, sb={sb}) to generate C2 encodings plot."
        )
        return []

    sub["C2 Encoding"] = sub["encoding"].map(C2_ENCODING_LABELS)
    sub["solve_time"] = sub["solve_time"].clip(lower=MIN_LOG_TIME)

    per_instance = sub.groupby(["n", "instance", "C2 Encoding"], as_index=False)[
        "solve_time"
    ].mean()
    agg = (
        per_instance.groupby(["n", "C2 Encoding"], as_index=False)["solve_time"]
        .mean()
        .sort_values("n")
    )
    present_order = [enc for enc in C2_ENCODING_ORDER if enc in set(agg["C2 Encoding"])]

    cns.figure(width=5.6, height=3.6, unit="in", color_cycle="Science")
    ax = cns.lineplot(
        data=agg,
        x="n",
        y="solve_time",
        hue="C2 Encoding",
        style="C2 Encoding",
        hue_order=present_order,
        style_order=present_order,
        markers=True,
        dashes=False,
        errorbar=None,
    )
    ax.set_yscale("log")
    ax.set_xlabel(r"Number of Golfers ($n = g \times s$)")
    ax.set_ylabel(_time_axis_label(df, mean=True))
    solver_name = _format_solver_name(sat_solver)
    has_nonempty_sb = "sb" in sub.columns and (sub["sb"].fillna("").astype(str).str.strip() != "").any()
    if has_nonempty_sb and sb is not None:
        ax.set_title(f"C2 Exactly-s Encodings Comparison ({solver_name}, SB={sb})")
    else:
        ax.set_title(f"C2 Exactly-s Encodings Comparison ({solver_name})")
    ax.grid(True, which="both", linestyle="--", alpha=0.35)
    cns.take_legend_out()

    return _save_both_formats(Path(output_dir), "runtime_c2_encodings")


def plot_direct_vs_order(
    df: pd.DataFrame,
    output_dir: str | Path,
    sat_encoding: str = "nsc",
    sat_solver: str = "cadical",
    sb: str | None = None,
    max_instances: int = 12,
    cutoff: float | None = None,
) -> list[Path]:
    """Vẽ Bar Plot so sánh Direct và Order Encoding."""
    solved = _filter_solved(df, cutoff=cutoff)
    solved = _apply_sb_filter(solved, sb)

    direct = solved[
        (solved["method"] == "sat")
        & (solved["solver"] == sat_solver.lower())
        & ((solved["encoding"] == sat_encoding.lower()) | (solved["encoding"] == ""))
    ].copy()
    direct["Approach"] = f"Direct ({C2_ENCODING_LABELS.get(sat_encoding, sat_encoding)})"

    order = solved[
        (solved["method"] == "order") & (solved["solver"] == sat_solver.lower())
    ].copy()
    order["Approach"] = "Order Encoding"

    if direct.empty or order.empty:
        print(
            "[Warning] Missing Direct or Order Encoding data; skipping Direct vs. Order bar plot."
        )
        return []

    common_instances = sorted(set(direct["instance"]) & set(order["instance"]))
    if not common_instances:
        print(
            "[Warning] No common instances between Direct and Order Encoding; skipping bar plot."
        )
        return []

    combined = pd.concat([direct, order], ignore_index=True)
    combined = combined[combined["instance"].isin(common_instances)].copy()
    combined["solve_time"] = combined["solve_time"].clip(lower=MIN_LOG_TIME)
    combined = combined.groupby(["instance", "n", "Approach"], as_index=False, dropna=False)[
        "solve_time"
    ].mean()

    inst_order = (
        combined[["instance", "n"]]
        .drop_duplicates()
        .sort_values(["n", "instance"], na_position="last")["instance"]
        .tolist()[:max_instances]
    )
    combined = combined[combined["instance"].isin(inst_order)]

    cns.figure(width=6.0, height=3.8, unit="in", color_cycle="Lancet")
    ax = cns.barplot(
        data=combined,
        x="instance",
        y="solve_time",
        hue="Approach",
        order=inst_order,
        errorbar=None,
    )
    ax.set_yscale("log")
    ax.set_xlabel("SGP Instance (g-p-w)")
    ax.set_ylabel(_time_axis_label(df, mean=False))
    solver_name = _format_solver_name(sat_solver)
    ax.set_title(f"Direct vs. Order Encoding Runtime ({solver_name})")
    ax.tick_params(axis="x", rotation=35)
    ax.grid(True, axis="y", which="both", linestyle="--", alpha=0.35)
    cns.take_legend_out()

    return _save_both_formats(Path(output_dir), "bar_direct_vs_order")


def build_demo_dataframe() -> pd.DataFrame:
    """Tạo dữ liệu mẫu theo đúng chuẩn 13 cột CSV benchmark v1."""
    instances = [
        ("2-2-3", 3, 2, 2),
        ("3-3-4", 4, 3, 3),
        ("4-3-4", 4, 4, 3),
        ("4-4-5", 5, 4, 4),
        ("5-3-6", 6, 5, 3),
        ("5-4-5", 5, 5, 4),
        ("6-3-7", 7, 6, 3),
        ("6-4-5", 5, 6, 4),
    ]
    rows: list[dict[str, object]] = []
    enc_factors = {"nsc": 1.0, "seqcounter": 1.35, "totalizer": 1.65, "cardnetwrk": 1.9}

    for idx, (label, w, g, s) in enumerate(instances):
        n = g * s
        base = 0.008 * (1.85 ** idx)
        sat_vars = n * g * w
        sat_clauses = int(sat_vars * 4.5)

        for enc, factor in enc_factors.items():
            wall = round(base * factor, 5)
            enc_t = round(0.001 + 0.0005 * idx, 5)
            rows.append(
                {
                    "instance": label,
                    "n": n,
                    "method": "sat",
                    "encoding": enc,
                    "solver": "cadical",
                    "status": "SAT",
                    "encode_time_seconds": enc_t,
                    "solver_wall_time_seconds": wall,
                    "total_time_seconds": round(enc_t + wall + 0.002, 5),
                    "num_vars": int(sat_vars * factor),
                    "num_clauses": int(sat_clauses * factor),
                    "num_constraints": "",
                    "error": "",
                }
            )

        order_wall = round(base * 2.4, 5)
        order_enc = round(0.002 + 0.001 * idx, 5)
        rows.append(
            {
                "instance": label,
                "n": n,
                "method": "order",
                "encoding": "order",
                "solver": "cadical",
                "status": "SAT",
                "encode_time_seconds": order_enc,
                "solver_wall_time_seconds": order_wall,
                "total_time_seconds": round(order_enc + order_wall + 0.002, 5),
                "num_vars": int(sat_vars * 2.2),
                "num_clauses": int(sat_clauses * 2.8),
                "num_constraints": "",
                "error": "",
            }
        )
        cp_ok = idx < 7
        cp_wall = round(base * 1.5, 5) if cp_ok else 60.0
        cp_enc = round(0.003 + 0.001 * idx, 5)
        rows.append(
            {
                "instance": label,
                "n": n,
                "method": "cp",
                "encoding": "",
                "solver": "cp-sat",
                "status": "SAT" if cp_ok else "TIMEOUT",
                "encode_time_seconds": cp_enc,
                "solver_wall_time_seconds": cp_wall,
                "total_time_seconds": round(cp_enc + cp_wall + 0.002, 5) if cp_ok else 60.01,
                "num_vars": int(sat_vars * 1.4),
                "num_clauses": "",
                "num_constraints": int(sat_vars * 1.8),
                "error": "" if cp_ok else "CP-SAT exceeded 60s timeout",
            }
        )
        ilp_ok = idx < 5
        ilp_wall = round(base * 4.2, 5) if ilp_ok else 60.0
        ilp_enc = round(0.004 + 0.001 * idx, 5)
        rows.append(
            {
                "instance": label,
                "n": n,
                "method": "ilp",
                "encoding": "",
                "solver": "gurobi",
                "status": "SAT" if ilp_ok else "TIMEOUT",
                "encode_time_seconds": ilp_enc,
                "solver_wall_time_seconds": ilp_wall,
                "total_time_seconds": round(ilp_enc + ilp_wall + 0.002, 5) if ilp_ok else 60.02,
                "num_vars": int(sat_vars * 1.6),
                "num_clauses": "",
                "num_constraints": int(sat_vars * 2.5),
                "error": "" if ilp_ok else "Gurobi exceeded 60s timeout",
            }
        )

    rows.append(
        {
            "instance": "2-2-4",
            "n": 4,
            "method": "sat",
            "encoding": "nsc",
            "solver": "cadical",
            "status": "UNSAT_PRECHECK",
            "encode_time_seconds": "",
            "solver_wall_time_seconds": "",
            "total_time_seconds": 0.0005,
            "num_vars": "",
            "num_clauses": "",
            "num_constraints": "",
            "error": "",
        }
    )

    columns = [
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
    ]
    return pd.DataFrame(rows, columns=columns)


def generate_all_plots(
    df: pd.DataFrame,
    output_dir: str | Path,
    sat_encoding: str = "nsc",
    sat_solver: str = "cadical",
    sb: str = "none",
    cutoff: float | None = None,
) -> list[Path]:
    """Vẽ toàn bộ 3 biểu đồ chuẩn CNSPlots."""
    saved: list[Path] = []
    saved.extend(
        plot_cactus(
            df,
            output_dir,
            sat_encoding=sat_encoding,
            sb=sb,
            sat_solver=sat_solver,
            cutoff=cutoff,
        )
    )
    saved.extend(
        plot_c2_encodings(
            df,
            output_dir,
            sat_solver=sat_solver,
            sb=sb,
            cutoff=cutoff,
        )
    )
    saved.extend(
        plot_direct_vs_order(
            df,
            output_dir,
            sat_encoding=sat_encoding,
            sat_solver=sat_solver,
            sb=sb,
            cutoff=cutoff,
        )
    )
    return saved


def _configure_safe_stdio() -> None:
    """Cấu hình stdout và stderr tránh lỗi encoding khi xuất đường dẫn Unicode."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(errors="backslashreplace")
            except Exception:
                pass


def main(argv: Sequence[str] | None = None) -> int:
    """Chạy CLI vẽ biểu đồ CNSPlots."""
    _configure_safe_stdio()
    parser = argparse.ArgumentParser(
        description="Generate SGP publication figures with CNSPlots (Cactus, Runtime Line, Bar)"
    )
    parser.add_argument(
        "--input",
        type=str,
        default="benchmarks/results.csv",
        help="Path to benchmark results CSV (default: benchmarks/results.csv)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="paper/figures",
        help="Output directory for PDF/PNG figures (default: paper/figures)",
    )
    parser.add_argument(
        "--sat-encoding",
        default="nsc",
        choices=tuple(C2_ENCODING_LABELS.keys()),
        help="Representative SAT C2 encoding for Cactus/Bar plots (default: nsc)",
    )
    parser.add_argument(
        "--sat-solver",
        default="cadical",
        help="SAT solver to plot (default: cadical)",
    )
    parser.add_argument(
        "--sb",
        default="none",
        help="Symmetry breaking mode filter (default: none)",
    )
    parser.add_argument(
        "--cutoff",
        type=float,
        default=None,
        help="Maximum time in seconds to count as solved (optional)",
    )
    parser.add_argument(
        "--time-col",
        type=str,
        default=None,
        help="Runtime column name in CSV (default: total_time_seconds)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use synthetic demo data when benchmarks/results.csv is not yet available",
    )
    args = parser.parse_args(argv)

    if args.demo:
        df = _normalize_results_df(build_demo_dataframe(), time_col=args.time_col)
    else:
        df = load_results(args.input, time_col=args.time_col)

    saved_files = generate_all_plots(
        df,
        output_dir=args.output_dir,
        sat_encoding=args.sat_encoding,
        sat_solver=args.sat_solver,
        sb=args.sb,
        cutoff=args.cutoff,
    )

    if saved_files:
        print("Exported CNSPlots figures:")
        for path in saved_files:
            print(f"  - {path}")
        return 0

    print("No figures were exported.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
