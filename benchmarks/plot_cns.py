"""Vẽ biểu đồ thực nghiệm SGP bằng cnsplots."""

from __future__ import annotations

import argparse
import json
from math import isfinite
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


def _format_sat_label(sat_solver: str, sat_encoding: str | None = None) -> str:
    """Trả về nhãn hiển thị cho nhánh SAT theo solver và mã hóa C2 được chọn."""
    key = sat_solver.strip().lower()
    if sat_encoding:
        enc_key = sat_encoding.strip().lower()
        enc_label = C2_ENCODING_LABELS.get(enc_key, sat_encoding.strip().upper())
        return f"SAT ({enc_label} + {_format_solver_name(sat_solver)})"
    return METHOD_SOLVER_LABELS.get(("sat", key), f"SAT ({_format_solver_name(sat_solver)})")


def _take_line_legend_out(
    ax: plt.Axes,
    title: str | None = None,
    handlelength: float = 2.4,
    markerscale: float = 0.95,
) -> None:
    """Đưa legend ra ngoài vùng vẽ với nét liền rõ ràng và marker sắc nét."""
    from matplotlib.lines import Line2D

    legend = ax.get_legend()
    handles = None
    labels = None
    if legend is not None:
        raw_handles = legend.legend_handles
        labels = [t.get_text() for t in legend.texts]
        if title is None:
            title = legend.get_title().get_text()
        handles = []
        for h in raw_handles:
            if isinstance(h, Line2D):
                color = h.get_color()
                handles.append(
                    Line2D(
                        [0],
                        [0],
                        color=color,
                        linestyle="-",
                        linewidth=max(h.get_linewidth(), 1.6),
                        marker=h.get_marker(),
                        markersize=max(h.get_markersize(), 5.5),
                        markerfacecolor=color,
                        markeredgecolor=color,
                        markeredgewidth=0.6,
                    )
                )
            else:
                handles.append(h)
    if title is None:
        title = ""
    ax.legend(
        handles=handles,
        labels=labels,
        bbox_to_anchor=cns.settings.legend_out_bbox_to_anchor,
        loc=cns.settings.legend_out_loc,
        title=title,
        handlelength=handlelength,
        markerscale=markerscale,
        frameon=False,
    )


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
    df["solve_time"] = pd.to_numeric(df[selected_time_col], errors="coerce")
    total_time_col = _resolve_column(df, ("total_time_seconds",))
    if total_time_col is not None:
        df[total_time_col] = pd.to_numeric(df[total_time_col], errors="coerce")

    enc_col = _resolve_column(df, ("encoding", "amo", "encoder"))
    if enc_col is not None:
        df["encoding"] = df[enc_col]

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
    df["solver"] = df["solver"].str.lower().replace(
        {"ortools": "cp-sat", "ortools-cp-sat": "cp-sat"}
    )
    df["encoding"] = df["encoding"].str.lower()
    df["backend_type"] = df["backend_type"].str.lower()
    df["status"] = df["status"].str.upper()

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
            df["verified"].astype(str).str.strip().str.lower().isin({"true", "1", "1.0", "yes"})
        )
    else:
        df["verified"] = True

    precheck = df["backend_type"] == "precheck"
    if ((df["status"] == "UNSAT") & (df["backend_type"] == "")).any():
        sizes = df["instance"].str.extract(r"^([1-9][0-9]*)-([1-9][0-9]*)-([1-9][0-9]*)$")
        sizes.columns = ["g", "s", "w"]
        for col in sizes:
            sizes[col] = pd.to_numeric(sizes[col], errors="coerce")
            if col in df:
                sizes[col] = pd.to_numeric(df[col], errors="coerce").fillna(sizes[col])
        g, s, w = sizes["g"], sizes["s"], sizes["w"]
        past_bound = (g >= 1) & (s > 1) & (w >= 1) & (w * (s - 1) > g * s - 1)
        precheck |= (df["status"] == "UNSAT") & (df["backend_type"] == "") & past_bound
    df.loc[precheck, "status"] = "UNSAT_PRECHECK"

    legacy_timeout = None
    legacy_scope = None
    if "timeout_seconds" in df:
        raw_timeout = df["timeout_seconds"].fillna("").astype(str).str.strip()
        timeouts = pd.to_numeric(raw_timeout, errors="coerce")
        invalid = (raw_timeout != "") & ~(timeouts.gt(0) & timeouts.lt(float("inf")))
        if invalid.any() or timeouts.nunique(dropna=False) > 1:
            raise ValueError("CSV mixes or has invalid timeouts; use one benchmark configuration per file.")
        if timeouts.notna().any():
            legacy_timeout = float(timeouts.iloc[0])
    if "timeout_scope" in df:
        scopes = df["timeout_scope"].fillna("").astype(str).str.strip().str.lower().unique()
        if len(scopes) > 1:
            raise ValueError("CSV mixes timeout scopes; use one benchmark configuration per file.")
        legacy_scope = scopes[0]

    key_cols = ["instance", "method", "encoding", "solver"] + (["sb"] if had_sb else [])
    if "attempt" in df.columns:
        df = df.sort_values(
            "attempt", key=lambda col: pd.to_numeric(col, errors="coerce").fillna(0), kind="mergesort"
        )
    df = df.drop_duplicates(subset=key_cols, keep="last").reset_index(drop=True)

    df.attrs["time_col"] = selected_time_col
    df.attrs["cutoff_time_col"] = total_time_col or "solve_time"
    if legacy_scope == "total" and legacy_timeout is not None:
        if total_time_col is None:
            raise ValueError("A recorded whole-run cutoff requires total_time_seconds.")
        df.attrs["run_budget_seconds"] = legacy_timeout
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

    df = _normalize_results_df(df, time_col=time_col)
    metadata = path.with_name(f"{path.name}.meta.json")
    if metadata.exists():
        settings = json.loads(metadata.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            raise ValueError(f"{metadata}: expected a benchmark settings object")
        sb = settings.get("sb")
        if sb not in ("none", "sb1", "full"):
            raise ValueError(f"{metadata}: invalid benchmark SB mode")
        if df.attrs["has_sb"] and set(df["sb"]) != {sb}:
            raise ValueError(f"{metadata}: SB configuration conflicts with the CSV")
        df.attrs["benchmark_sb"] = sb
        if settings.get("timeout_scope") == "total":
            timeout = settings.get("timeout_seconds")
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not (
                isfinite(timeout) and timeout > 0
            ):
                raise ValueError(f"{metadata}: invalid total benchmark cutoff")
            if "total_time_seconds" not in {name.lower() for name in df}:
                raise ValueError(f"{metadata}: total cutoff requires total_time_seconds")
            df.attrs["run_budget_seconds"] = timeout
    return df


def _filter_solved(df: pd.DataFrame, cutoff: float | None = None) -> pd.DataFrame:
    """Lọc các bản ghi giải thành công bởi solver và loại bỏ ca precheck."""
    not_precheck = df["status"] != "UNSAT_PRECHECK"
    if "backend_type" in df.columns:
        not_precheck = not_precheck & (
            df["backend_type"].fillna("").astype(str).str.strip().str.lower() != "precheck"
        )
    is_sat_ok = (df["status"] == "SAT") & df["verified"]
    is_unsat = df["status"] == "UNSAT"
    valid_time = df["solve_time"].ge(0) & df["solve_time"].lt(float("inf"))
    mask = not_precheck & (is_sat_ok | is_unsat) & valid_time
    budget = df.attrs.get("run_budget_seconds")
    if cutoff is None:
        cutoff = budget
    if cutoff is not None:
        if not isfinite(cutoff) or cutoff <= 0:
            raise ValueError("Cutoff must be a finite positive number.")
        if budget is not None and cutoff > budget:
            raise ValueError(f"Cutoff cannot exceed the benchmark's {budget:g}s whole-run budget.")
        runtime = df[df.attrs.get("cutoff_time_col", "solve_time")]
        mask &= runtime.ge(0) & runtime.le(cutoff)
    filtered = df.loc[mask].copy()
    filtered.attrs.update(df.attrs)
    return filtered


def _apply_sb_filter(df: pd.DataFrame, sb: str | None) -> pd.DataFrame:
    """Lọc dữ liệu theo cấu hình SB."""
    recorded = df.attrs.get("benchmark_sb")
    mode = sb.lower() if sb is not None else recorded or "none"
    if recorded is not None and mode != recorded:
        raise ValueError(f"CSV uses sb={recorded}; cannot plot it with sb={mode}.")
    if "sb" not in df.columns or not df.attrs.get("has_sb"):
        return df
    filtered = df[df["sb"] == mode].copy()
    filtered.attrs.update(df.attrs)
    return filtered


def _time_axis_label(df: pd.DataFrame, mean: bool = False) -> str:
    """Trả về nhãn trục thời gian khớp cột được dùng."""
    time_col = df.attrs.get("time_col", "total_time_seconds").lower()
    prefix = "Mean " if mean else ""
    metric = {
        "total_time_seconds": "Total Time",
        "solver_wall_time_seconds": "Solve Time",
        "solve_time": "Solve Time",
        "encode_time_seconds": "Build Time",
        "model_build_time_seconds": "Build Time",
        "cpu_time_seconds": "CPU Time",
    }.get(time_col, "Time")
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


def _representative_sat(df: pd.DataFrame, encoding: str, solver: str) -> pd.DataFrame:
    """Chọn mã hóa SAT đại diện."""
    sat = df[(df["method"] == "sat") & (df["solver"] == solver.lower())]
    selected = sat["encoding"] == encoding.lower()
    return sat[selected if selected.any() else sat["encoding"] == ""]


def plot_cactus(
    df: pd.DataFrame,
    output_dir: str | Path,
    sat_encoding: str = "nsc",
    sb: str | None = None,
    sat_solver: str = "cadical",
    cutoff: float | None = None,
) -> list[Path]:
    """Vẽ Cactus Plot so sánh SAT, CP và ILP."""
    selected = _apply_sb_filter(df, sb)
    attempted = selected["status"].isin({"SAT", "UNSAT", "TIMEOUT"}) & selected["instance"].ne("")
    attempts = selected[attempted]
    sat = _representative_sat(selected, sat_encoding, sat_solver)
    used_enc = (
        sat_encoding
        if (not sat.empty and (sat["encoding"] == sat_encoding.lower()).any())
        else None
    )
    sat_label = _format_sat_label(sat_solver, used_enc)
    groups = {sat_label: sat[attempted.loc[sat.index]]}
    if groups[sat_label].empty:
        print(f"[Warning] No attempted cases for {sat_label}; skipping the three-method cactus plot.")
        return []
    for method in ("cp", "ilp"):
        sub = attempts[attempts["method"] == method]
        solvers = sub["solver"].unique()
        if len(solvers) != 1:
            print(f"[Warning] Cactus requires one {method.upper()} solver with attempted cases; "
                  "skipping the three-method cactus plot.")
            return []
        solver = solvers[0]
        label = METHOD_SOLVER_LABELS.get(
            (method, solver), f"{method.upper()} ({_format_solver_name(solver)})"
        )
        groups[label] = sub

    common = set.intersection(*(set(sub["instance"]) for sub in groups.values()))
    if not common:
        print("[Warning] SAT, CP and ILP share no attempted instances; skipping the cactus plot.")
        return []

    rows: list[dict[str, object]] = []
    counts = {}
    for label, sub in groups.items():
        solved = _filter_solved(sub[sub["instance"].isin(common)], cutoff=cutoff)
        per_instance = solved.groupby("instance")["solve_time"].mean()
        counts[label] = len(per_instance)
        sorted_times = per_instance.sort_values().to_numpy()
        for idx, t in enumerate(sorted_times, start=1):
            rows.append(
                {
                    "solved_instances": idx,
                    "solve_time": max(float(t), MIN_LOG_TIME),
                    "Method": label,
                }
            )

    if not rows:
        print("[Warning] No shared case was solved within the cutoff; skipping the cactus plot.")
        return []

    print(
        f"Cactus on {len(common)} shared attempted instances: "
        + ", ".join(f"{label}: {count} solved" for label, count in counts.items())
    )
    plot_df = pd.DataFrame(rows)
    hue_order = [label for label in groups if counts[label]]

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
    active_sb = df.attrs.get("benchmark_sb") or (
        selected["sb"].iloc[0] if not selected.empty and selected["sb"].iloc[0] else ""
    )
    sb_suffix = f", SB={active_sb}" if active_sb else ""
    title = f"Cactus Plot ({len(common)} Shared SGP Instances{sb_suffix})"
    zero_solved = [label for label in groups if counts[label] == 0]
    if zero_solved:
        title += "\nNo solved cases: " + ", ".join(zero_solved)
    ax.set_title(title)
    ax.grid(True, which="both", linestyle="--", alpha=0.35)
    _take_line_legend_out(ax)

    return _save_both_formats(Path(output_dir), "cactus_sat_cp_ilp")


def plot_c2_encodings(
    df: pd.DataFrame,
    output_dir: str | Path,
    sat_solver: str = "cadical",
    sb: str | None = None,
    cutoff: float | None = None,
) -> list[Path]:
    """So sánh thời gian C2 trên cùng tập bài đã giải."""
    selected = _apply_sb_filter(df, sb)
    sat = selected[
        (selected["method"] == "sat")
        & (selected["solver"] == sat_solver.lower())
        & selected["encoding"].isin(C2_ENCODING_LABELS)
        & selected["instance"].ne("")
        & selected["n"].gt(0)
        & selected["n"].lt(float("inf"))
    ]
    encodings = set(sat["encoding"])
    if len(encodings) < 2:
        print(f"[Warning] Need at least two C2 encodings for {sat_solver}; skipping the C2 plot.")
        return []
    missing = C2_ENCODING_LABELS.keys() - encodings
    if missing:
        print(f"[Warning] Missing C2 data for {', '.join(sorted(missing))}.")

    solved = _filter_solved(sat, cutoff=cutoff)
    matched = solved.groupby(["n", "instance"])["encoding"].transform("nunique").eq(len(encodings))
    sub = solved[matched].copy()
    if sub.empty:
        print("[Warning] No common instance solved by all selected encodings; skipping the C2 plot.")
        return []

    sub["C2 Encoding"] = sub["encoding"].map(C2_ENCODING_LABELS)
    n_paired = len(sub[["n", "instance"]].drop_duplicates())
    print(f"C2 means use {n_paired} shared solved instances across {sub['n'].nunique()} golfer counts.")

    per_instance = sub.groupby(["n", "instance", "C2 Encoding"], as_index=False)[
        "solve_time"
    ].mean()
    agg = (
        per_instance.groupby(["n", "C2 Encoding"], as_index=False)["solve_time"]
        .mean()
        .sort_values("n")
    )
    agg["solve_time"] = agg["solve_time"].clip(lower=MIN_LOG_TIME)
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
    active_sb = df.attrs.get("benchmark_sb") or sub["sb"].iloc[0]
    if active_sb:
        solver_name = f"{solver_name}, SB={active_sb}"
    ax.set_title(f"C2 Exactly-s Encodings Comparison ({solver_name})")
    ax.grid(True, which="both", linestyle="--", alpha=0.35)

    inst_counts = per_instance.groupby("n")["instance"].nunique()
    multi_n = inst_counts[inst_counts > 1]
    if not multi_n.empty:
        multi_note = "Multi-instance means: " + ", ".join(
            f"n={int(n_val)} ({int(cnt)})" for n_val, cnt in multi_n.items()
        )
        ax.text(
            0.985,
            0.03,
            multi_note,
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=6.8,
            color="#333333",
            bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": "#cccccc", "alpha": 0.9},
        )

    _take_line_legend_out(ax)

    return _save_both_formats(Path(output_dir), "runtime_c2_encodings")


def plot_c2_runtime_breakdown(
    df: pd.DataFrame,
    output_dir: str | Path,
    sat_solver: str = "cadical",
    sb: str | None = None,
    cutoff: float | None = None,
) -> list[Path]:
    """Phân rã thời gian của ba instance lớn nhất có đủ kết quả SAT ở cả bốn mã hóa."""
    phase_columns = ("encode_time_seconds", "solver_wall_time_seconds", "total_time_seconds")
    resolved = [_resolve_column(df, (column,)) for column in phase_columns]
    if None in resolved:
        print("[Warning] Skipping the C2 runtime breakdown because phase timings are missing.")
        return []

    selected = _apply_sb_filter(df, sb)
    sat = selected.loc[
        selected["method"].eq("sat")
        & selected["solver"].eq(sat_solver.lower())
        & selected["status"].eq("SAT")
        & selected["encoding"].isin(C2_ENCODING_LABELS)
        & selected["instance"].ne("")
        & selected["n"].gt(0)
        & selected["n"].lt(float("inf"))
    ].copy()
    timing_names = ["build_time", "solver_time", "total_time"]
    sat[timing_names] = sat[resolved].apply(pd.to_numeric, errors="coerce")
    sat["solve_time"] = sat["total_time"]
    sat = _filter_solved(sat, cutoff=cutoff)
    timings = sat[timing_names]
    complete = timings.ge(0).all(axis=1) & timings.lt(float("inf")).all(axis=1)
    remaining = sat["total_time"] - sat["build_time"] - sat["solver_time"]
    tolerance = sat["total_time"].mul(1e-9).clip(lower=1e-9)
    sat = sat.loc[complete & remaining.ge(-tolerance)].copy()
    sat["remaining_time"] = remaining.clip(lower=0)

    encoding_counts = sat.groupby(["n", "instance"])["encoding"].transform("nunique")
    matched = encoding_counts.eq(len(C2_ENCODING_LABELS))
    data = sat.loc[matched]
    if data.empty:
        print("[Warning] Skipping the C2 runtime breakdown because no SAT instance has all four timings.")
        return []

    instances = data[["n", "instance"]].drop_duplicates().sort_values(["n", "instance"]).tail(3)
    print(f"C2 runtime breakdown uses {sat_solver}: {', '.join(instances['instance'])}.")

    phases = (
        ("build_time", "CNF construction", "#2f7d80"),
        ("solver_time", "SAT solve", "#d78931"),
        ("remaining_time", "Remaining time", "#a9bdd0"),
    )
    positions = range(len(C2_ENCODING_LABELS))
    fig = cns.figure(width=6.0, height=2.65, unit="in")
    axes = fig.subplots(1, len(instances), sharey=True, squeeze=False)[0]
    for ax, (n, instance) in zip(axes, instances.itertuples(index=False, name=None)):
        case = data.loc[data["n"].eq(n) & data["instance"].eq(instance)]
        case = case.set_index("encoding").reindex(C2_ENCODING_LABELS)
        bottom = pd.Series(0.0, index=case.index)
        for column, label, color in phases:
            ax.bar(positions, case[column], bottom=bottom, color=color, width=0.67, label=label)
            bottom += case[column]
        ax.set_title(f"{instance} ({n:g} players)", fontsize=10, pad=9)
        ax.set_xticks(positions, ["NSC", "Seq.\nCounter", "Totalizer", "Card.\nNetwork"], fontsize=8)
        ax.set_axisbelow(True)
        ax.grid(axis="y", color="#dde3eb", linewidth=0.6)

    axes[0].set_ylim(bottom=0)
    axes[0].set_ylabel("Total wall time (s)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncols=3, frameon=False)
    fig.subplots_adjust(left=0.1, right=0.98, bottom=0.19, top=0.76, wspace=0.18)
    return _save_both_formats(Path(output_dir), "runtime_c2_breakdown")


def plot_direct_vs_order(
    df: pd.DataFrame,
    output_dir: str | Path,
    sat_encoding: str = "nsc",
    sat_solver: str = "cadical",
    sb: str | None = None,
    max_instances: int | None = None,
    cutoff: float | None = None,
) -> list[Path]:
    """Vẽ biểu đồ Cleveland dot/dumbbell trục log so sánh Direct và Order Encoding."""
    selected = _apply_sb_filter(df, sb)
    solved = _filter_solved(selected, cutoff=cutoff)
    direct = _filter_solved(_representative_sat(selected, sat_encoding, sat_solver), cutoff=cutoff)
    direct_label = f"Direct ({C2_ENCODING_LABELS.get(sat_encoding, sat_encoding)})"
    direct["Approach"] = direct_label

    order = solved[
        (solved["method"] == "order") & (solved["solver"] == sat_solver.lower())
    ].copy()
    order_label = "Order Encoding"
    order["Approach"] = order_label

    if direct.empty or order.empty:
        print(
            "[Warning] Missing Direct or Order Encoding data; skipping Direct vs. Order plot."
        )
        return []

    common_instances = (set(direct["instance"]) & set(order["instance"])) - {""}
    if not common_instances:
        print(
            "[Warning] No common instances between Direct and Order Encoding; skipping plot."
        )
        return []

    combined = pd.concat([direct, order], ignore_index=True)
    combined = combined[combined["instance"].isin(common_instances)].copy()
    combined["solve_time"] = combined["solve_time"].clip(lower=MIN_LOG_TIME)
    combined = combined.groupby(["instance", "n", "Approach"], as_index=False, dropna=False)[
        "solve_time"
    ].mean()

    inst_meta = (
        combined[["instance", "n"]]
        .drop_duplicates()
        .sort_values(["n", "instance"], na_position="last")
    )
    if max_instances is not None:
        inst_meta = inst_meta.head(max_instances)
    inst_order = inst_meta["instance"].tolist()
    pivot = (
        combined[combined["instance"].isin(inst_order)]
        .pivot(index="instance", columns="Approach", values="solve_time")
        .reindex(inst_order)
    )

    y_labels = [
        f"{row.instance} (n={int(row.n)})" if pd.notna(row.n) else str(row.instance)
        for row in inst_meta.itertuples(index=False)
    ]
    y_positions = list(range(len(inst_order)))

    fig_height = max(3.4, 0.195 * len(inst_order) + 0.95)
    fig = cns.figure(width=6.4, height=fig_height, unit="in")
    ax = fig.subplots()

    direct_color = "#00468B"
    order_color = "#ED0000"
    for idx, inst in enumerate(inst_order):
        t_dir = float(pivot.loc[inst, direct_label])
        t_ord = float(pivot.loc[inst, order_label])
        ax.plot([t_dir, t_ord], [idx, idx], color="#9aa5b4", linewidth=1.35, zorder=2)

    ax.scatter(
        pivot[direct_label].to_numpy(dtype=float),
        y_positions,
        color=direct_color,
        marker="o",
        s=34,
        label=direct_label,
        zorder=3,
    )
    ax.scatter(
        pivot[order_label].to_numpy(dtype=float),
        y_positions,
        color=order_color,
        marker="D",
        s=32,
        label=order_label,
        zorder=3,
    )

    ax.set_xscale("log")
    min_t = float(pivot.min().min())
    max_t = float(pivot.max().max())
    candidate_ticks = [0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0]
    visible_ticks = [t for t in candidate_ticks if min_t * 0.85 <= t <= max_t * 1.35]
    if len(visible_ticks) >= 3:
        ax.set_xticks(visible_ticks)
        ax.set_xticklabels([f"{t:g}" for t in visible_ticks])
    ax.set_yticks(y_positions, y_labels, fontsize=7.6)
    ax.invert_yaxis()
    ax.set_xlabel(_time_axis_label(df, mean=False))
    ax.set_ylabel("SGP Instance (g-p-w)")

    solver_name = _format_solver_name(sat_solver)
    active_sb = df.attrs.get("benchmark_sb") or (
        selected["sb"].iloc[0] if not selected.empty and selected["sb"].iloc[0] else ""
    )
    if active_sb:
        solver_name = f"{solver_name}, SB={active_sb}"
    ax.set_title(
        f"Direct vs. Order Encoding Runtime ({solver_name}, {len(inst_order)} Shared Instances)",
        pad=22,
    )
    ax.set_axisbelow(True)
    ax.grid(True, axis="x", which="both", linestyle="--", alpha=0.35)
    ax.grid(True, axis="y", linestyle=":", alpha=0.28)
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, 1.005),
        ncols=2,
        frameon=False,
        fontsize=8,
        markerscale=1.0,
    )

    return _save_both_formats(Path(output_dir), "bar_direct_vs_order")


def plot_symmetry_breaking(
    df_none: pd.DataFrame,
    df_sb1: pd.DataFrame | None,
    df_full: pd.DataFrame | None,
    output_dir: str | Path,
    sat_encoding: str = "nsc",
    cutoff: float | None = None,
) -> list[Path]:
    """Vẽ biểu đồ hai khung so sánh tác động của phá đối xứng (none, sb1, full)."""
    from matplotlib.patches import Patch

    datasets: dict[str, pd.DataFrame] = {"none": _apply_sb_filter(df_none, "none")}
    if df_sb1 is not None:
        datasets["sb1"] = _apply_sb_filter(df_sb1, "sb1")
    if df_full is not None:
        datasets["full"] = _apply_sb_filter(df_full, "full")

    if len(datasets) < 2:
        print("[Warning] Need at least two SB modes; skipping symmetry-breaking comparison plot.")
        return []

    configs = [
        ("sat", sat_encoding.lower(), "cadical", f"SAT {C2_ENCODING_LABELS.get(sat_encoding, sat_encoding)}\n(CaDiCaL)"),
        ("sat", sat_encoding.lower(), "glucose", f"SAT {C2_ENCODING_LABELS.get(sat_encoding, sat_encoding)}\n(Glucose)"),
        ("order", "order", "cadical", "Order\n(CaDiCaL)"),
        ("order", "order", "glucose", "Order\n(Glucose)"),
        ("cp", "", "cp-sat", "CP-SAT"),
        ("ilp", "", "gurobi", "Gurobi\nILP"),
    ]
    sb_styles = {
        "none": ("SB=none", "#4c72b0"),
        "sb1": ("SB=sb1", "#dd8452"),
        "full": ("SB=full (SB1+SB2)", "#55a868"),
    }

    decided_records: list[dict[str, object]] = []
    runtime_records: list[dict[str, object]] = []

    for method, enc, solver, cfg_label in configs:
        solved_by_sb: dict[str, pd.DataFrame] = {}
        for sb_mode, sub_df in datasets.items():
            if method == "order" and sb_mode == "full":
                continue
            sub = sub_df[
                (sub_df["method"] == method)
                & (sub_df["encoding"] == enc)
                & (sub_df["solver"] == solver)
            ]
            if sub.empty:
                continue
            solved = _filter_solved(sub, cutoff=cutoff)
            solved_by_sb[sb_mode] = solved
            sat_cnt = int((solved["status"] == "SAT").sum())
            unsat_cnt = int((solved["status"] == "UNSAT").sum())
            decided_records.append(
                {
                    "config": cfg_label,
                    "sb": sb_mode,
                    "sat": sat_cnt,
                    "unsat": unsat_cnt,
                    "total": sat_cnt + unsat_cnt,
                }
            )

        if not solved_by_sb:
            continue
        sat_sets = [
            set(df_mode.loc[df_mode["status"] == "SAT", "instance"])
            for df_mode in solved_by_sb.values()
        ]
        shared_sat = set.intersection(*sat_sets) if sat_sets else set()
        if shared_sat:
            for sb_mode, df_mode in solved_by_sb.items():
                sat_sub = df_mode[(df_mode["status"] == "SAT") & (df_mode["instance"].isin(shared_sat))]
                mean_t = float(sat_sub.groupby("instance")["solve_time"].mean().mean())
                runtime_records.append(
                    {
                        "config": cfg_label,
                        "sb": sb_mode,
                        "mean_time": mean_t,
                        "n_shared": len(shared_sat),
                    }
                )

    if not decided_records:
        print("[Warning] No matching configurations for symmetry-breaking comparison plot.")
        return []

    dec_df = pd.DataFrame(decided_records)
    rt_df = pd.DataFrame(runtime_records)
    cfg_labels = [c[3] for c in configs if c[3] in set(dec_df["config"])]
    modes = [m for m in ("none", "sb1", "full") if m in datasets]

    fig = cns.figure(width=8.8, height=4.0, unit="in")
    ax1, ax2 = fig.subplots(1, 2)

    width = 0.25
    x_pos = {lbl: idx for idx, lbl in enumerate(cfg_labels)}
    cfg_modes_dec = {
        lbl: [m for m in modes if m in set(dec_df.loc[dec_df["config"] == lbl, "sb"])]
        for lbl in cfg_labels
    }

    def _bar_x(cfg_label: str, sb_mode: str) -> float:
        present = cfg_modes_dec[cfg_label]
        idx = present.index(sb_mode)
        return x_pos[cfg_label] + (idx - (len(present) - 1) / 2.0) * width

    # Panel (a): Solver-decided instances (solid SAT + hatched solver-proved UNSAT)
    max_dec = int(dec_df["total"].max())
    for row in dec_df.itertuples(index=False):
        x = _bar_x(row.config, row.sb)
        _, color = sb_styles[row.sb]
        if row.sat > 0:
            ax1.bar(x, row.sat, width=width * 0.9, color=color, edgecolor="none")
        if row.unsat > 0:
            ax1.bar(
                x,
                row.unsat,
                bottom=row.sat,
                width=width * 0.9,
                color=color,
                alpha=0.45,
                hatch="///",
                edgecolor=color,
                linewidth=0.7,
            )
        ax1.text(
            x,
            row.total + 0.6,
            str(row.total),
            ha="center",
            va="bottom",
            fontsize=6.8,
            color="#222222",
        )

    ax1.set_xticks(range(len(cfg_labels)), cfg_labels, fontsize=7.5)
    ax1.set_ylim(0, max_dec * 1.18)
    ax1.set_ylabel("Solver-Decided Instances (Excl. Precheck)")
    ax1.set_title("(a) Solved Coverage: SAT (solid) + UNSAT (hatched)", fontsize=9.5, pad=8)
    ax1.set_axisbelow(True)
    ax1.grid(axis="y", linestyle="--", alpha=0.35)

    # Panel (b): Mean total time across shared solved SAT instances
    max_rt = float(rt_df["mean_time"].max()) if not rt_df.empty else 1.0
    for row in rt_df.itertuples(index=False):
        x = _bar_x(row.config, row.sb)
        _, color = sb_styles[row.sb]
        ax2.bar(x, row.mean_time, width=width * 0.9, color=color, edgecolor="none")
        ax2.text(
            x,
            row.mean_time + max_rt * 0.02,
            f"{row.mean_time:.2f}",
            ha="center",
            va="bottom",
            fontsize=6.6,
            rotation=90,
            color="#222222",
        )

    n_sh_map = (
        rt_df.groupby("config")["n_shared"].first().to_dict() if not rt_df.empty else {}
    )
    rt_tick_labels = [
        f"{lbl}\n($n_{{\\mathrm{{sh}}}}={int(n_sh_map[lbl])}$)" if lbl in n_sh_map else lbl
        for lbl in cfg_labels
    ]
    ax2.set_xticks(range(len(cfg_labels)), rt_tick_labels, fontsize=7.3)
    ax2.set_ylim(0, max_rt * 1.24)
    ax2.set_ylabel("Mean Total Time on Shared SAT (s)")
    ax2.set_title("(b) Paired Mean Runtime on Shared Solved SAT", fontsize=9.5, pad=8)
    ax2.set_axisbelow(True)
    ax2.grid(axis="y", linestyle="--", alpha=0.35)

    legend_handles = [
        Patch(facecolor=sb_styles[m][1], edgecolor="none", label=sb_styles[m][0])
        for m in modes
    ]
    legend_handles.append(
        Patch(
            facecolor="#d9d9d9",
            edgecolor="#555555",
            hatch="///",
            label="Hatched top = solver-proved UNSAT",
        )
    )
    fig.legend(
        handles=legend_handles,
        loc="upper center",
        ncols=len(legend_handles),
        frameon=False,
        fontsize=8,
    )
    fig.subplots_adjust(left=0.07, right=0.985, bottom=0.22, top=0.81, wspace=0.22)

    return _save_both_formats(Path(output_dir), "bar_symmetry_breaking")


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
    sb: str | None = None,
    cutoff: float | None = None,
) -> list[Path]:
    """Vẽ các biểu đồ CNSPlots tương ứng với dữ liệu benchmark."""
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
        plot_c2_runtime_breakdown(
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
        description="Generate SGP publication figures with CNSPlots"
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
        type=str.lower,
        choices=("none", "sb1", "full"),
        help="Symmetry breaking mode (defaults to benchmark metadata or none)",
    )
    parser.add_argument(
        "--sb1-input",
        type=str,
        default=None,
        help="Optional CSV path for SB=sb1 results to generate bar_symmetry_breaking",
    )
    parser.add_argument(
        "--sb-full-input",
        type=str,
        default=None,
        help="Optional CSV path for SB=full results to generate bar_symmetry_breaking",
    )
    parser.add_argument(
        "--sb-only",
        action="store_true",
        help="Only export bar_symmetry_breaking without regenerating baseline figures",
    )
    parser.add_argument(
        "--cutoff",
        type=float,
        default=None,
        help="Cutoff in seconds, applied to total time when available (defaults to recorded whole-run budget)",
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

    if args.cutoff is not None and (not isfinite(args.cutoff) or args.cutoff <= 0):
        parser.error("--cutoff must be a finite positive number")
    try:
        if args.demo:
            df = _normalize_results_df(build_demo_dataframe(), time_col=args.time_col)
        else:
            df = load_results(args.input, time_col=args.time_col)

        saved_files: list[Path] = []
        if not args.sb_only:
            saved_files.extend(
                generate_all_plots(
                    df,
                    output_dir=args.output_dir,
                    sat_encoding=args.sat_encoding,
                    sat_solver=args.sat_solver,
                    sb=args.sb,
                    cutoff=args.cutoff,
                )
            )
        if args.sb1_input or args.sb_full_input:
            df_sb1 = load_results(args.sb1_input, time_col=args.time_col) if args.sb1_input else None
            df_full = (
                load_results(args.sb_full_input, time_col=args.time_col) if args.sb_full_input else None
            )
            saved_files.extend(
                plot_symmetry_breaking(
                    df,
                    df_sb1,
                    df_full,
                    output_dir=args.output_dir,
                    sat_encoding=args.sat_encoding,
                    cutoff=args.cutoff,
                )
            )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    if saved_files:
        print("Exported CNSPlots figures:")
        for path in saved_files:
            print(f"  - {path}")
        return 0

    print("No figures were exported.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
