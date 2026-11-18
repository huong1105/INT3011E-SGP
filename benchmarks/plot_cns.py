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

TIME_COLUMN_CANDIDATES = (
    "solver_wall_time_seconds",
    "wall_time_seconds",
    "total_time_seconds",
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


def load_results(csv_path: str | Path) -> pd.DataFrame:
    """Đọc và chuẩn hóa file results.csv."""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file dữ liệu thực nghiệm: {path}")

    df = pd.read_csv(path)
    if df.empty:
        raise ValueError(f"File dữ liệu rỗng: {path}")

    df = df.copy()
    rename_map: dict[str, str] = {}

    time_col = _resolve_column(df, TIME_COLUMN_CANDIDATES)
    if time_col is None:
        raise ValueError(
            f"Không tìm thấy cột thời gian trong CSV. Các cột hiện có: {list(df.columns)}"
        )
    if time_col != "solve_time":
        rename_map[time_col] = "solve_time"

    enc_col = _resolve_column(df, ("encoding", "amo", "encoder"))
    if enc_col is not None and enc_col != "encoding":
        rename_map[enc_col] = "encoding"

    if rename_map:
        df = df.rename(columns=rename_map)

    for col in ("method", "solver", "encoding", "sb", "status"):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()

    df["method"] = df["method"].str.lower()
    df["solver"] = df["solver"].str.lower()
    df["encoding"] = df["encoding"].str.lower()
    df["sb"] = df["sb"].str.lower().replace("", "none")
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

    if "verified" in df.columns:
        df["verified"] = (
            df["verified"].astype(str).str.lower().isin({"true", "1", "yes"})
        )
    else:
        df["verified"] = True

    return df


def _filter_solved(df: pd.DataFrame) -> pd.DataFrame:
    """Lọc các bản ghi giải thành công."""
    is_sat_ok = (df["status"] == "SAT") & df["verified"]
    is_unsat = df["status"] == "UNSAT"
    valid_time = df["solve_time"].notna() & (df["solve_time"] >= 0)
    return df.loc[(is_sat_ok | is_unsat) & valid_time].copy()


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
) -> list[Path]:
    """Vẽ Cactus Plot so sánh SAT, CP và ILP."""
    solved = _filter_solved(df)
    if sb is not None:
        solved = solved[solved["sb"] == sb.lower()]

    groups: list[tuple[str, pd.DataFrame]] = [
        (
            "SAT (CaDiCaL)",
            solved[
                (solved["method"] == "sat")
                & (solved["solver"] == sat_solver.lower())
                & ((solved["encoding"] == sat_encoding.lower()) | (solved["encoding"] == ""))
            ],
        ),
        ("CP (OR-Tools CP-SAT)", solved[solved["method"] == "cp"]),
        ("ILP (Gurobi)", solved[solved["method"] == "ilp"]),
    ]

    rows: list[dict[str, object]] = []
    hue_order: list[str] = []
    for label, sub in groups:
        if sub.empty:
            continue
        hue_order.append(label)
        sorted_times = sub["solve_time"].sort_values().to_numpy()
        for idx, t in enumerate(sorted_times, start=1):
            rows.append(
                {
                    "solved_instances": idx,
                    "solve_time": max(float(t), MIN_LOG_TIME),
                    "Method": label,
                }
            )

    if not rows:
        print("[Cảnh báo] Không đủ dữ liệu để vẽ Cactus Plot (SAT vs CP vs ILP).")
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
    ax.set_ylabel("Solve Time (s, log scale)")
    ax.set_title("Cactus Plot: SAT vs. CP-SAT vs. ILP on SGP")
    ax.grid(True, which="both", linestyle="--", alpha=0.35)
    cns.take_legend_out()

    return _save_both_formats(Path(output_dir), "cactus_sat_cp_ilp")


def plot_c2_encodings(
    df: pd.DataFrame,
    output_dir: str | Path,
    sat_solver: str = "cadical",
    sb: str = "none",
) -> list[Path]:
    """Vẽ Line Plot so sánh 4 bộ mã hóa C2."""
    solved = _filter_solved(df)
    sub = solved[
        (solved["method"] == "sat")
        & (solved["solver"] == sat_solver.lower())
        & (solved["sb"] == sb.lower())
        & (solved["encoding"].isin(C2_ENCODING_LABELS.keys()))
        & solved["n"].notna()
    ].copy()

    if sub.empty:
        print(
            f"[Cảnh báo] Không đủ dữ liệu SAT ({sat_solver}, sb={sb}) để vẽ Runtime Line Plot 4 bộ C2."
        )
        return []

    sub["C2 Encoding"] = sub["encoding"].map(C2_ENCODING_LABELS)
    sub["solve_time"] = sub["solve_time"].clip(lower=MIN_LOG_TIME)

    agg = (
        sub.groupby(["n", "C2 Encoding"], as_index=False)["solve_time"]
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
    ax.set_xlabel("Number of Golfers (n = g × s)")
    ax.set_ylabel("Mean Solve Time (s, log scale)")
    ax.set_title(f"C2 Exactly-s Encodings Comparison ({sat_solver.upper()}, SB={sb})")
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
) -> list[Path]:
    """Vẽ Bar Plot so sánh Direct và Order Encoding."""
    solved = _filter_solved(df)
    if sb is not None:
        solved = solved[solved["sb"] == sb.lower()]

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
            "[Cảnh báo] Thiếu dữ liệu Direct hoặc Order Encoding nên bỏ qua Bar Plot so sánh."
        )
        return []

    common_instances = sorted(set(direct["instance"]) & set(order["instance"]))
    if not common_instances:
        print("[Cảnh báo] Không có instance chung giữa Direct và Order Encoding để vẽ Bar Plot.")
        return []

    combined = pd.concat([direct, order], ignore_index=True)
    combined = combined[combined["instance"].isin(common_instances)].copy()
    combined["solve_time"] = combined["solve_time"].clip(lower=MIN_LOG_TIME)

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
    ax.set_ylabel("Solve Time (s, log scale)")
    ax.set_title("Direct Encoding vs. Order Encoding Runtime")
    ax.tick_params(axis="x", rotation=35)
    ax.grid(True, axis="y", which="both", linestyle="--", alpha=0.35)
    cns.take_legend_out()

    return _save_both_formats(Path(output_dir), "bar_direct_vs_order")


def build_demo_dataframe() -> pd.DataFrame:
    """Tạo dữ liệu mẫu để kiểm thử vẽ đồ thị."""
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

        for enc, factor in enc_factors.items():
            rows.append(
                {
                    "instance": label,
                    "w": w,
                    "g": g,
                    "s": s,
                    "n": n,
                    "method": "sat",
                    "encoding": enc,
                    "solver": "cadical",
                    "sb": "none",
                    "status": "SAT",
                    "solver_wall_time_seconds": round(base * factor, 5),
                    "verified": True,
                }
            )

        rows.append(
            {
                "instance": label,
                "w": w,
                "g": g,
                "s": s,
                "n": n,
                "method": "order",
                "encoding": "order",
                "solver": "cadical",
                "sb": "none",
                "status": "SAT",
                "solver_wall_time_seconds": round(base * 2.4, 5),
                "verified": True,
            }
        )
        rows.append(
            {
                "instance": label,
                "w": w,
                "g": g,
                "s": s,
                "n": n,
                "method": "cp",
                "encoding": "",
                "solver": "cp-sat",
                "sb": "none",
                "status": "SAT" if idx < 7 else "TIMEOUT",
                "solver_wall_time_seconds": round(base * 1.5, 5) if idx < 7 else 60.0,
                "verified": idx < 7,
            }
        )
        rows.append(
            {
                "instance": label,
                "w": w,
                "g": g,
                "s": s,
                "n": n,
                "method": "ilp",
                "encoding": "",
                "solver": "gurobi",
                "sb": "none",
                "status": "SAT" if idx < 5 else "TIMEOUT",
                "solver_wall_time_seconds": round(base * 4.2, 5) if idx < 5 else 60.0,
                "verified": idx < 5,
            }
        )

    return pd.DataFrame(rows)


def generate_all_plots(
    df: pd.DataFrame,
    output_dir: str | Path,
    sat_encoding: str = "nsc",
    sat_solver: str = "cadical",
    sb: str = "none",
) -> list[Path]:
    """Vẽ toàn bộ 3 biểu đồ chuẩn CNSPlots."""
    saved: list[Path] = []
    saved.extend(
        plot_cactus(df, output_dir, sat_encoding=sat_encoding, sb=sb, sat_solver=sat_solver)
    )
    saved.extend(plot_c2_encodings(df, output_dir, sat_solver=sat_solver, sb=sb))
    saved.extend(
        plot_direct_vs_order(
            df, output_dir, sat_encoding=sat_encoding, sat_solver=sat_solver, sb=sb
        )
    )
    return saved


def main(argv: Sequence[str] | None = None) -> int:
    """Chạy CLI vẽ biểu đồ CNSPlots."""
    parser = argparse.ArgumentParser(
        description="Vẽ biểu đồ khoa học SGP bằng CNSPlots (Cactus, Runtime Line, Bar)"
    )
    parser.add_argument(
        "--input",
        type=str,
        default="benchmarks/results.csv",
        help="Đường dẫn file CSV kết quả thực nghiệm (mặc định: benchmarks/results.csv)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="paper/figures",
        help="Thư mục lưu hình vẽ PDF/PNG (mặc định: paper/figures)",
    )
    parser.add_argument(
        "--sat-encoding",
        default="nsc",
        choices=tuple(C2_ENCODING_LABELS.keys()),
        help="Bộ mã hóa SAT đại diện cho Cactus/Bar plot (mặc định: nsc)",
    )
    parser.add_argument(
        "--sat-solver",
        default="cadical",
        help="SAT solver dùng để so sánh (mặc định: cadical)",
    )
    parser.add_argument(
        "--sb",
        default="none",
        help="Cấu hình SB lọc khi vẽ biểu đồ (mặc định: none)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Dùng dữ liệu mô phỏng để kiểm thử script vẽ khi chưa có results.csv",
    )
    args = parser.parse_args(argv)

    if args.demo:
        df = build_demo_dataframe()
        df = df.rename(columns={"solver_wall_time_seconds": "solve_time"})
        df["status"] = df["status"].str.upper()
    else:
        df = load_results(args.input)

    saved_files = generate_all_plots(
        df,
        output_dir=args.output_dir,
        sat_encoding=args.sat_encoding,
        sat_solver=args.sat_solver,
        sb=args.sb,
    )

    if saved_files:
        print("Đã xuất thành công các biểu đồ CNSPlots:")
        for path in saved_files:
            print(f"  - {path}")
        return 0

    print("Không có biểu đồ nào được xuất.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
