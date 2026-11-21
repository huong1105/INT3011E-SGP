"""Chạy benchmark SGP trên bốn phương pháp và xuất results.csv cho CNSPlots."""

from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime
from pathlib import Path

from src.io_utils import parse_paper_instance
from src.verifier import verify_schedule

METHODS = ("sat", "order", "cp", "ilp")
C2_ENCODINGS = ("nsc", "seqcounter", "totalizer", "cardnetwrk")
SAT_SOLVERS = ("cadical", "glucose")
SB_MODES = ("none", "sb1", "full")

FIELDS = [
    "instance", "w", "g", "s", "n",
    "method", "encoding", "solver", "sb",
    "status", "verified",
    "solver_wall_time_seconds", "encode_time_seconds",
    "total_time_seconds", "cpu_time_seconds",
    "num_vars", "num_clauses", "conflicts",
    "expected_status", "error", "timestamp",
]


def _split(value, allowed, flag):
    """Tách và kiểm tra danh sách giá trị CLI."""
    items = tuple(item.strip().lower() for item in value.split(",") if item.strip())
    for item in items:
        if item not in allowed:
            raise SystemExit(f"{flag}: invalid value {item!r}; choose from {allowed}")
    if not items:
        raise SystemExit(f"{flag}: at least one value required")
    return items


def load_instances(path):
    """Đọc CSV instance (label,w,g,s,expected_status,enabled,note), bỏ dòng enabled=0."""
    rows = []
    skipped = 0
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "label" not in reader.fieldnames:
            raise ValueError(f"{path}: missing 'label' column")
        for raw in reader:
            label = (raw.get("label") or "").strip()
            if not label:
                continue
            if (raw.get("enabled") or "1").strip().lower() in ("0", "false", "no"):
                skipped += 1
                continue
            w, g, s = raw.get("w"), raw.get("g"), raw.get("s")
            if w and g and s:
                w, g, s = int(w), int(g), int(s)
            else:
                w, g, s = parse_paper_instance(label)
            rows.append({
                "label": label, "w": w, "g": g, "s": s,
                "expected_status": (raw.get("expected_status") or "").strip().upper(),
            })
    if not rows:
        raise ValueError(f"{path}: no instances")
    if skipped:
        print(f"[skip] {skipped} instance có enabled=0")
    return rows


def build_cases(methods, encodings, solvers, sb_modes):
    """Sinh tổ hợp cấu hình hợp lệ theo từng phương pháp."""
    cases = []
    for sb in sb_modes:
        for method in methods:
            if method == "sat":
                for encoding in encodings:
                    for solver in solvers:
                        cases.append((method, encoding, solver, sb))
            elif method == "order":
                if sb == "full":
                    print("[skip] order + sb=full: SB2 not supported by Order Encoding")
                    continue
                for solver in solvers:
                    cases.append((method, "order", solver, sb))
            elif method == "cp":
                cases.append((method, "", "cp-sat", sb))
            else:
                cases.append((method, "", "gurobi", sb))
    return cases


def run_case(instance, case, timeout_seconds):
    """Chạy một cấu hình và trả kết quả thô của solver tương ứng."""
    method, encoding, solver, sb = case
    w, g, s = instance["w"], instance["g"], instance["s"]

    if method == "sat":
        from src.sat_runner import solve_sgp
        from src.symmetry import generate_symmetry_clauses

        clauses = None if sb == "none" else generate_symmetry_clauses(w, g, s, mode=sb)
        return solve_sgp(w, g, s, encoding=encoding, solver=solver,
                         timeout_seconds=timeout_seconds, symmetry_clauses=clauses)
    if method == "order":
        from src.order_encoder import solve_sgp_order

        return solve_sgp_order(w, g, s, solver=solver,
                               timeout_seconds=timeout_seconds, sb=sb)
    if method == "cp":
        from src.cp_solver import solve_sgp_cp

        return solve_sgp_cp(w, g, s, timeout_seconds=timeout_seconds, sb=sb)

    from src.ilp_solver import solve_sgp_ilp

    return solve_sgp_ilp(w, g, s, timeout_seconds=timeout_seconds, sb=sb)


def build_row(instance, case, result):
    """Chuẩn hóa kết quả solver thành một dòng CSV, kiểm chứng lại độc lập."""
    method, encoding, solver, sb = case
    w, g, s = instance["w"], instance["g"], instance["s"]
    status = result.get("status", "ERROR")
    verified = bool(result.get("verified"))
    schedule = result.get("schedule")
    if status == "SAT" and schedule:
        independent, _ = verify_schedule(schedule, w, g, s)
        verified = verified and independent
    return {
        "instance": instance["label"], "w": w, "g": g, "s": s, "n": g * s,
        "method": method, "encoding": encoding,
        "solver": result.get("solver", solver), "sb": sb,
        "status": status, "verified": verified,
        "solver_wall_time_seconds": result.get("solver_wall_time_seconds"),
        "encode_time_seconds": result.get("encode_time_seconds",
                                          result.get("model_build_time_seconds")),
        "total_time_seconds": result.get("total_time_seconds"),
        "cpu_time_seconds": result.get("cpu_time_seconds"),
        "num_vars": result.get("num_vars"),
        "num_clauses": result.get("num_clauses", result.get("num_constraints")),
        "conflicts": result.get("conflicts"),
        "expected_status": instance["expected_status"],
        "error": " ".join(str(result.get("error") or "").split()),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


def _format(value):
    """Chuyển None thành chuỗi rỗng để CSV sạch."""
    return "" if value is None else value


def _load_done(path):
    """Đọc khóa các dòng đã có để --resume bỏ qua."""
    done = set()
    if not path.exists() or path.stat().st_size == 0:
        return done
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            done.add((row["instance"], row["method"], row["encoding"],
                      row["solver"], row["sb"]))
    return done


def main(argv=None):
    """Chạy suite benchmark theo tham số CLI và ghi results.csv tăng dần."""
    parser = argparse.ArgumentParser(description="SGP benchmark suite -> results.csv")
    parser.add_argument("--instances", default="data/sgp_paper_instances.csv")
    parser.add_argument("--output", default="benchmarks/results.csv")
    parser.add_argument("--methods", default=",".join(METHODS))
    parser.add_argument("--encodings", default=",".join(C2_ENCODINGS))
    parser.add_argument("--solvers", default=",".join(SAT_SOLVERS))
    parser.add_argument("--sb", default="none")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--limit", type=int, default=None,
                        help="chỉ chạy N instance đầu tiên (đã sắp theo n tăng dần)")
    parser.add_argument("--budget-seconds", type=float, default=None,
                        help="dừng an toàn sau số giây này, chạy tiếp bằng --resume")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not Path(args.instances).exists():
        raise SystemExit(f"Instance file not found: {args.instances}")

    instances = load_instances(args.instances)
    if args.limit is not None:
        instances = instances[:args.limit]
    methods = _split(args.methods, METHODS, "--methods")
    encodings = _split(args.encodings, C2_ENCODINGS, "--encodings")
    solvers = _split(args.solvers, SAT_SOLVERS, "--solvers")
    sb_modes = _split(args.sb, SB_MODES, "--sb")

    cases = build_cases(methods, encodings, solvers, sb_modes)
    print(f"Instances: {len(instances)} | configs: {len(cases)} | "
          f"planned runs: {len(instances) * len(cases)}")
    if args.dry_run:
        for case in cases:
            print("   ", case)
        return 0

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    done = _load_done(output) if args.resume else set()
    mode = "a" if args.resume and output.exists() else "w"
    start_all = time.perf_counter()
    written = 0
    counts = {}
    stopped = False

    with output.open(mode, encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if mode == "w" or output.stat().st_size == 0:
            writer.writeheader()
            handle.flush()

        for index, instance in enumerate(instances, start=1):
            for case in cases:
                key = (instance["label"],) + case
                if key in done:
                    continue
                if (args.budget_seconds is not None
                        and time.perf_counter() - start_all > args.budget_seconds):
                    print("[stop] budget-seconds exhausted")
                    stopped = True
                    break
                started = time.perf_counter()
                try:
                    result = run_case(instance, case, args.timeout)
                except NotImplementedError as exc:
                    result = {"status": "UNAVAILABLE", "error": str(exc)}
                except Exception as exc:
                    result = {"status": "ERROR",
                              "error": f"{type(exc).__name__}: {exc}"}
                row = build_row(instance, case, result)
                writer.writerow({field: _format(row[field]) for field in FIELDS})
                handle.flush()
                written += 1
                done.add(key)
                elapsed = time.perf_counter() - started
                counts[(case[0], row["status"])] = counts.get(
                    (case[0], row["status"]), 0) + 1
                mark = ""
                if row["expected_status"] and row["status"] != row["expected_status"]:
                    mark = f"  [!] expected {row['expected_status']}"
                print(f"[{index}/{len(instances)}] {instance['label']:>7} "
                      f"{case[0]:>5} {case[1] or '-':>11} {case[2]:>7} sb={case[3]:<4} "
                      f"-> {row['status']:>7} {elapsed:6.2f}s{mark}", flush=True)
            if stopped:
                break

    print(f"\nWritten rows: {written} -> {output}")
    for (method, status), count in sorted(counts.items()):
        print(f"  {method:>5} {status:>11}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
