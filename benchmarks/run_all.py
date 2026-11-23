"""Chạy benchmark SGP và xuất CSV v1."""

from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from math import comb, isfinite
from pathlib import Path

from src.io_utils import (
    benchmark_csv_lock,
    check_partner_bound,
    configure_safe_stdio,
    load_benchmark_csv_rows,
    parse_paper_instance,
    read_text_with_retry,
    replace_file_with_retry,
    result_to_csv_v1_row,
    save_benchmark_csv_rows,
    set_benchmark_csv_config,
)
from src.verifier import verify_schedule

METHODS = ("sat", "order", "cp", "ilp")
C2_ENCODINGS = ("nsc", "seqcounter", "totalizer", "cardnetwrk")
SAT_SOLVERS = ("cadical", "glucose")
SB_MODES = ("none", "sb1", "full")

CNF_METHODS = ("sat", "order")
TERMINAL_STATUSES = ("SAT", "UNSAT", "UNSAT_PRECHECK")
DEFAULT_MAX_CLAUSES = 5_000_000
DEFAULT_RUN_BUDGET = 60.0
WORKER_FLAG = "--_worker"
STARTUP_ALLOWANCE = 15.0

def estimate_cnf_clauses(w, g, s):
    """Ước lượng cận dưới số clause CNF; C3 chiếm phần lớn ở instance lớn."""
    n = g * s
    return comb(n, 2) * comb(w, 2) * g * g


def _split(value, allowed, flag):
    """Tách và kiểm tra danh sách giá trị CLI."""
    items = tuple(item.strip().lower() for item in value.split(",") if item.strip())
    for item in items:
        if item not in allowed:
            raise SystemExit(f"{flag}: invalid value {item!r}; choose from {allowed}")
    if not items:
        raise SystemExit(f"{flag}: at least one value required")
    return tuple(dict.fromkeys(items))


def load_instances(path):
    """Đọc CSV instance (label|paper_label,w,g,s,expected_status,enabled,note), bỏ dòng enabled=0."""
    rows = []
    skipped = 0
    seen = set()
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        fieldnames = reader.fieldnames or []
        if "label" not in fieldnames and "paper_label" not in fieldnames:
            raise ValueError(f"{path}: missing 'label' or 'paper_label' column")
        for raw in reader:
            if None in raw or None in raw.values():
                raise ValueError(f"{path}:{reader.line_num}: incorrect input column count")
            label = (raw.get("label") or raw.get("paper_label") or "").strip()
            if not label:
                continue
            if (raw.get("enabled") or "1").strip().lower() in ("0", "false", "no"):
                skipped += 1
                continue
            w, g, s = parse_paper_instance(label)
            dimensions = tuple((raw.get(field) or "").strip() for field in ("w", "g", "s"))
            if any(dimensions) and (not all(dimensions) or tuple(map(int, dimensions)) != (w, g, s)):
                raise ValueError(f"{path}:{reader.line_num}: dimensions do not match {label!r}")
            label = f"{g}-{s}-{w}"
            if label in seen:
                raise ValueError(f"{path}:{reader.line_num}: duplicate instance {label}")
            seen.add(label)
            expected = (raw.get("expected_status") or raw.get("source_status") or "").strip().upper()
            if expected not in ("", "UNKNOWN", "SAT", "UNSAT"):
                raise ValueError(f"{path}:{reader.line_num}: invalid expected status {expected!r}")
            rows.append({
                "label": label, "w": w, "g": g, "s": s,
                "expected_status": expected,
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


def run_case(instance, case, timeout_seconds, num_threads=None):
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

        return solve_sgp_cp(w, g, s, timeout_seconds=timeout_seconds, sb=sb, num_workers=num_threads)

    from src.ilp_solver import solve_sgp_ilp

    return solve_sgp_ilp(w, g, s, timeout_seconds=timeout_seconds, sb=sb, num_threads=num_threads)


def _prepare_case(method):
    """Chuẩn bị solver trước khi đo."""
    try:
        if method == "sat":
            from src import sat_direct_encoders, sat_runner, symmetry  # noqa: F401
        elif method == "order":
            from src import order_encoder  # noqa: F401
        elif method == "cp":
            from src import cp_solver  # noqa: F401
        else:
            from src.ilp_solver import prepare_gurobi

            return prepare_gurobi()
    except ImportError as exc:
        return {"status": "UNAVAILABLE", "error": str(exc)}
    return None


def _execute_case(instance, case, timeout_seconds, num_threads, started):
    """Chạy và đo một ca có kiểm chứng lịch."""
    try:
        result = run_case(instance, case, timeout_seconds, num_threads)
    except (ImportError, NotImplementedError) as exc:
        result = {"status": "UNAVAILABLE", "error": str(exc)}
    except Exception as exc:
        result = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}

    if result.get("status") == "SAT":
        valid, _ = verify_schedule(
            result.get("schedule"), instance["w"], instance["g"], instance["s"]
        )
        if not (result.get("verified") and valid):
            result.update(
                status="ERROR", verified=False, error="Benchmark schedule verification failed"
            )
    result["total_time_seconds"] = time.perf_counter() - started
    return result


def build_row(instance, case, result):
    """Chuẩn hóa kết quả thành một dòng CSV v1."""
    method, encoding, solver, _ = case
    w, g, s = instance["w"], instance["g"], instance["s"]
    return result_to_csv_v1_row(
        dict(result, w=w, g=g, s=s, method=method, encoding=encoding, solver=solver)
    )


def _kill_tree(proc):
    """Kết thúc worker cùng tiến trình con (solver) của nó."""
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.poll() is None:
        proc.kill()


def _drain(proc, timeout=5):
    """Đọc nốt stdout/stderr sau khi kill, không treo nếu cháu còn giữ pipe."""
    try:
        return proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            return proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            return None, None


def _run_case_isolated(instance, case, run_budget, num_threads, work_dir, startup_allowance):
    """Chạy một lượt trong worker riêng, hard-cap tính từ lúc bắt đầu dựng mô hình."""
    work_dir = work_dir.resolve()
    token = uuid.uuid4().hex
    spec_path = work_dir / f".spec-{token}.json"
    out_path = work_dir / f".out-{token}.json"
    start_path = work_dir / f".start-{token}.txt"
    spec = {
        "label": instance["label"], "w": instance["w"], "g": instance["g"],
        "s": instance["s"],
        "method": case[0], "encoding": case[1], "solver": case[2], "sb": case[3],
        "timeout_seconds": run_budget, "num_threads": num_threads,
        "start_path": str(start_path),
    }
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    proc = None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "benchmarks.run_all", WORKER_FLAG,
             str(spec_path), str(out_path)],
            cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            start_new_session=os.name != "nt",
        )
        wait_until = time.perf_counter() + startup_allowance
        while time.perf_counter() < wait_until and not start_path.exists():
            if proc.poll() is not None:
                break
            time.sleep(0.005)
        if not start_path.exists():
            if proc.poll() == 0 and out_path.exists():
                return json.loads(read_text_with_retry(out_path))
            _kill_tree(proc)
            _, stderr = _drain(proc)
            detail = (stderr or "").strip()[-1000:]
            return {"status": "ERROR", "error": f"worker did not start: {detail}"}

        started_at = float(read_text_with_retry(start_path).strip())
        remaining = max(0.0, run_budget - (time.perf_counter() - started_at))
        try:
            _, stderr = proc.communicate(timeout=remaining)
        except subprocess.TimeoutExpired:
            elapsed = time.perf_counter() - started_at
            completed = (
                json.loads(read_text_with_retry(out_path)) if out_path.exists() else None
            )
            _kill_tree(proc)
            _drain(proc)
            if completed is not None and completed["total_time_seconds"] <= run_budget:
                return completed
            return {
                "status": "TIMEOUT",
                "error": f"whole-run budget {run_budget:g}s exceeded (build included)",
                "total_time_seconds": elapsed,
            }

        if proc.returncode != 0 or not out_path.exists():
            detail = (stderr or "").strip()[-1000:]
            return {"status": "ERROR",
                    "error": f"worker exited with code {proc.returncode}: {detail}"}
        result = json.loads(read_text_with_retry(out_path))
        if result["total_time_seconds"] > run_budget:
            return {
                "status": "TIMEOUT",
                "error": f"whole-run budget {run_budget:g}s exceeded (verification included)",
                "total_time_seconds": result["total_time_seconds"],
            }
        return result
    finally:
        if proc is not None and proc.poll() is None:
            _kill_tree(proc)
            _drain(proc)
        for path in (spec_path, out_path, out_path.with_suffix(".tmp"),
                     start_path, start_path.with_suffix(".tmp")):
            try:
                path.unlink()
            except OSError:
                pass


def _worker_main(spec_path, out_path):
    """Worker chạy một lượt benchmark và ghi kết quả JSON."""
    spec = json.loads(read_text_with_retry(Path(spec_path)))
    instance = {
        "label": spec["label"], "w": spec["w"], "g": spec["g"], "s": spec["s"],
    }
    case = (spec["method"], spec["encoding"], spec["solver"], spec["sb"])

    result = _prepare_case(case[0])
    if result is None:
        started = time.perf_counter()
        start_path = Path(spec["start_path"])
        start_temp = start_path.with_suffix(".tmp")
        start_temp.write_text(str(started), encoding="utf-8")
        replace_file_with_retry(start_temp, start_path)
        result = _execute_case(instance, case, spec["timeout_seconds"], spec["num_threads"], started)
    result.pop("model", None)
    result.pop("schedule", None)
    output = Path(out_path)
    pending = output.with_suffix(".tmp")
    pending.write_text(json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8")
    replace_file_with_retry(pending, output)
    return 0


def _reference_mismatch(status, expected):
    """Phát hiện kết luận lệch dữ liệu tham khảo."""
    actual = "UNSAT" if status == "UNSAT_PRECHECK" else status
    return expected in ("SAT", "UNSAT") and status in TERMINAL_STATUSES and actual != expected


def main(argv=None):
    """Chạy suite benchmark theo tham số CLI và ghi results.csv tăng dần."""
    configure_safe_stdio()
    parser = argparse.ArgumentParser(description="SGP benchmark suite -> results.csv")
    parser.add_argument("--instances", default="benchmarks/benchmark_instances.csv")
    parser.add_argument("--output", default="benchmarks/results.csv")
    parser.add_argument("--methods", default=",".join(METHODS))
    parser.add_argument("--encodings", default=",".join(C2_ENCODINGS))
    parser.add_argument("--solvers", default=",".join(SAT_SOLVERS))
    parser.add_argument("--sb", default="none", choices=SB_MODES)
    parser.add_argument("--timeout", type=float,
                        help="giới hạn riêng của backend, phạm vi khác nhau theo phương pháp")
    parser.add_argument("--run-budget", type=float,
                        help="giới hạn từ dựng mô hình đến kiểm chứng, mặc định 60 giây "
                             "khi không có --timeout; 0 dùng giới hạn backend")
    parser.add_argument("--threads", type=int, default=1,
                        help="số luồng CP/ILP (mặc định 1); SAT/Order luôn dùng 1")
    parser.add_argument("--startup-allowance", type=float, default=STARTUP_ALLOWANCE,
                        help="thời gian chờ worker khởi động trước khi áp ngân sách")
    parser.add_argument("--max-clauses", type=int, default=DEFAULT_MAX_CLAUSES,
                        help="chặn trước khi dựng CNF nếu C3 ước lượng vượt ngưỡng (0 = tắt)")
    parser.add_argument("--limit", type=int, default=None,
                        help="chỉ chạy N instance đầu tiên (đã sắp theo n tăng dần)")
    parser.add_argument("--budget-seconds", type=float, default=None,
                        help="dừng an toàn sau số giây này, chạy tiếp bằng --resume")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.timeout is not None and (not isfinite(args.timeout) or args.timeout <= 0):
        parser.error("--timeout must be a finite positive number")
    if args.run_budget is not None and (not isfinite(args.run_budget) or args.run_budget < 0):
        parser.error("--run-budget must be a finite non-negative number")
    if args.threads < 1:
        parser.error("--threads must be a positive integer")
    if not isfinite(args.startup_allowance) or args.startup_allowance <= 0:
        parser.error("--startup-allowance must be a finite positive number")
    if args.budget_seconds is not None and (not isfinite(args.budget_seconds) or args.budget_seconds < 0):
        parser.error("--budget-seconds must be a finite non-negative number")
    if args.max_clauses < 0 or (args.limit is not None and args.limit < 0):
        parser.error("--max-clauses and --limit must be non-negative")

    instance_path = Path(args.instances).resolve()
    try:
        instances = load_instances(instance_path)
    except (OSError, ValueError, csv.Error) as exc:
        parser.error(str(exc))
    if args.limit is not None:
        instances = instances[:args.limit]
    methods = _split(args.methods, METHODS, "--methods")
    encodings = _split(args.encodings, C2_ENCODINGS, "--encodings")
    solvers = _split(args.solvers, SAT_SOLVERS, "--solvers")
    cases = build_cases(methods, encodings, solvers, (args.sb,))
    if not cases:
        parser.error("No method supports the selected SB")
    if args.threads != 1 and any(case[0] in CNF_METHODS for case in cases):
        parser.error("--threads must be 1 when the benchmark includes SAT or Order")
    if args.run_budget is None:
        run_budget = DEFAULT_RUN_BUDGET if args.timeout is None else 0.0
    else:
        run_budget = args.run_budget
    case_timeout = run_budget or args.timeout or DEFAULT_RUN_BUDGET
    timeout_scope = "total" if run_budget else "solver"
    print(f"Instances: {len(instances)} | configs: {len(cases)} | "
          f"planned runs: {len(instances) * len(cases)} | "
          f"timeout: {case_timeout:g}s ({timeout_scope}) | threads: {args.threads}")
    if args.dry_run:
        for case in cases:
            print("   ", case)
        return 0

    output = Path(args.output).resolve()
    if output == instance_path or (output.exists() and instance_path.samefile(output)):
        parser.error("--output must be separate from the instance input")
    config = {
        "sb": args.sb, "timeout_seconds": case_timeout, "timeout_scope": timeout_scope,
        "num_threads": args.threads,
    }
    try:
        with benchmark_csv_lock(output):
            rows = load_benchmark_csv_rows(output) if args.resume else {}
            if not rows:
                save_benchmark_csv_rows(output, rows)
            set_benchmark_csv_config(output, config, resume=bool(rows))
            return _run_suite(args, instances, cases, output, rows, run_budget, case_timeout)
    except (OSError, ValueError, csv.Error) as exc:
        parser.error(f"{output}: {exc}")


def _run_suite(args, instances, cases, output, rows, run_budget, case_timeout):
    """Chạy và lưu kết quả từng ca benchmark."""
    start_all = time.perf_counter()
    written = 0
    error_rows = 0
    precheck_rows = 0
    reference_mismatches = 0
    counts = {}
    stopped = False

    for index, instance in enumerate(instances, start=1):
        w, g, s = instance["w"], instance["g"], instance["s"]
        label = f"{g}-{s}-{w}"
        estimate = estimate_cnf_clauses(w, g, s)
        expected = instance["expected_status"]
        for case in cases:
            key = (label, *case[:3])
            previous = rows[key]["status"] if key in rows else ""
            if previous in TERMINAL_STATUSES:
                if _reference_mismatch(previous, expected):
                    reference_mismatches += 1
                    print(f"[!] {label} {case[0]} saved {previous}; expected {expected}")
                continue
            if (args.budget_seconds is not None
                    and time.perf_counter() - start_all > args.budget_seconds):
                print("[stop] budget-seconds exhausted")
                stopped = True
                break
            started = time.perf_counter()
            feasible, _, _ = check_partner_bound(w, g, s)
            over_cap = (case[0] in CNF_METHODS and args.max_clauses > 0
                        and estimate > args.max_clauses)
            if not feasible:
                result = {
                    "status": "UNSAT", "backend_type": "precheck",
                    "total_time_seconds": time.perf_counter() - started,
                }
            elif previous == "SKIPPED_RESOURCE_LIMIT" and over_cap:
                continue
            elif over_cap:
                result = {
                    "status": "SKIPPED_RESOURCE_LIMIT",
                    "error": (f"estimated {estimate:,} C3 clauses (lower bound) "
                              f"> cap {args.max_clauses:,}"),
                    "total_time_seconds": time.perf_counter() - started,
                }
            elif run_budget > 0:
                try:
                    result = _run_case_isolated(
                        instance, case, run_budget, args.threads,
                        output.parent, args.startup_allowance)
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    result = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
            else:
                result = _prepare_case(case[0])
                if result is None:
                    result = _execute_case(
                        instance, case, case_timeout, args.threads, time.perf_counter()
                    )

            row = build_row(instance, case, result)
            rows[key] = row
            save_benchmark_csv_rows(output, rows)
            written += 1
            status = row["status"]
            error_rows += status == "ERROR"
            precheck_rows += status == "UNSAT_PRECHECK"
            counts[(case[0], status)] = counts.get((case[0], status), 0) + 1
            mismatch = _reference_mismatch(status, expected)
            reference_mismatches += mismatch
            mark = f"  [!] expected {expected}" if mismatch else ""
            elapsed = time.perf_counter() - started
            print(f"[{index}/{len(instances)}] {label:>7} "
                  f"{case[0]:>5} {case[1] or '-':>11} {case[2]:>7} sb={case[3]:<4} "
                  f"-> {status:>21} {elapsed:6.2f}s{mark}", flush=True)
        if stopped:
            break

    print(f"\nWritten rows: {written} -> {output}")
    for (method, status), count in sorted(counts.items()):
        print(f"  {method:>5} {status:>21}: {count}")
    print(f"  precheck (decided by bound): {precheck_rows}")
    if error_rows:
        print(f"[error] {error_rows} lượt kết thúc với status=ERROR", file=sys.stderr)
    if reference_mismatches:
        print(f"[error] {reference_mismatches} kết luận khác dữ liệu tham khảo", file=sys.stderr)
    return int(bool(error_rows or reference_mismatches))


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == WORKER_FLAG:
        raise SystemExit(_worker_main(sys.argv[2], sys.argv[3]))
    raise SystemExit(main())
