"""Chạy benchmark SGP trên bốn phương pháp và xuất results.csv cho CNSPlots.

Quy ước CSV:
- `backend_type=precheck`: lượt kết luận bằng cận đối tác, `solver_wall_time_seconds`
  để trống cho cả bốn phương pháp và không đưa vào biểu đồ so sánh solver.
- `solver_status`: trạng thái backend (ví dụ `TIME_LIMIT` của Gurobi) tách khỏi `status`.
- `--resume` yêu cầu CSV có đúng tiêu đề cột và giữ kết quả `SAT`/`UNSAT` đã có.
  Lượt `SKIPPED_RESOURCE_LIMIT` được thử lại nếu ngưỡng hiện tại cho phép.
- Lượt CNF vượt `--max-clauses` bị ghi `SKIPPED_RESOURCE_LIMIT` trước khi dựng CNF.
- `--run-budget` chạy mỗi lượt trong worker riêng và hard-cap toàn bộ thời gian kể từ
  lúc bắt đầu dựng mô hình; khi đó `timeout_scope=total`, `timeout_seconds` là ngân sách.
- Khi vẽ, mỗi khóa chỉ lấy dòng có `attempt` lớn nhất để tránh đếm lặp; so sánh
  hiệu năng dùng `total_time_seconds <= timeout_seconds` và loại dòng precheck.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime
from math import comb
from pathlib import Path

from src.io_utils import configure_safe_stdio, parse_paper_instance
from src.verifier import verify_schedule

METHODS = ("sat", "order", "cp", "ilp")
C2_ENCODINGS = ("nsc", "seqcounter", "totalizer", "cardnetwrk")
SAT_SOLVERS = ("cadical", "glucose")
SB_MODES = ("none", "sb1", "full")

CNF_METHODS = ("sat", "order")
TERMINAL_STATUSES = ("SAT", "UNSAT")
DEFAULT_MAX_CLAUSES = 5_000_000
TIMEOUT_SCOPE = "solver"
WORKER_FLAG = "--_worker"
STARTUP_ALLOWANCE = 15.0

FIELDS = [
    "instance", "w", "g", "s", "n",
    "method", "encoding", "solver", "sb",
    "timeout_seconds", "timeout_scope", "attempt",
    "status", "verified", "backend_type", "solver_status",
    "solver_wall_time_seconds", "encode_time_seconds",
    "total_time_seconds", "cpu_time_seconds",
    "num_vars", "num_clauses", "conflicts",
    "expected_status", "error", "timestamp",
]


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
    return items


def load_instances(path):
    """Đọc CSV instance (label|paper_label,w,g,s,expected_status,enabled,note), bỏ dòng enabled=0."""
    rows = []
    skipped = 0
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        if "label" not in fieldnames and "paper_label" not in fieldnames:
            raise ValueError(f"{path}: missing 'label' or 'paper_label' column")
        for raw in reader:
            label = (raw.get("label") or raw.get("paper_label") or "").strip()
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


def build_row(instance, case, result, timeout_seconds, timeout_scope, attempt):
    """Chuẩn hóa kết quả solver thành một dòng CSV, kiểm chứng lại độc lập."""
    method, encoding, solver, sb = case
    w, g, s = instance["w"], instance["g"], instance["s"]
    status = result.get("status", "ERROR")
    verified = bool(result.get("verified"))
    schedule = result.get("schedule")
    if status == "SAT" and schedule:
        independent, _ = verify_schedule(schedule, w, g, s)
        verified = verified and independent
    precheck = result.get("backend_type") == "precheck"
    solver_wall = None if precheck else result.get("solver_wall_time_seconds")
    return {
        "instance": instance["label"], "w": w, "g": g, "s": s, "n": g * s,
        "method": method, "encoding": encoding,
        "solver": result.get("solver", solver), "sb": sb,
        "timeout_seconds": timeout_seconds, "timeout_scope": timeout_scope,
        "attempt": attempt,
        "status": status, "verified": verified,
        "backend_type": "precheck" if precheck else "",
        "solver_status": result.get("solver_status") or "",
        "solver_wall_time_seconds": solver_wall,
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


def _schedule_to_lists(schedule, w, g):
    """Chuyển schedule[week][group] sang list lồng để ghi JSON."""
    return [[list(schedule[k][j]) for j in range(g)] for k in range(w)]


def _schedule_from_lists(data, w, g):
    """Dựng lại schedule[week][group] từ list lồng."""
    return {k: {j: list(data[k][j]) for j in range(g)} for k in range(w)}


def _kill_tree(proc):
    """Kết thúc worker cùng tiến trình con (solver) của nó."""
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=15)
        except Exception:
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


def _run_case_isolated(instance, case, timeout_seconds, run_budget, work_dir,
                       startup_allowance):
    """Chạy một lượt trong worker riêng, hard-cap tính từ lúc bắt đầu dựng mô hình."""
    token = uuid.uuid4().hex
    spec_path = work_dir / f".spec-{token}.json"
    out_path = work_dir / f".out-{token}.json"
    start_path = work_dir / f".start-{token}.txt"
    spec = {
        "label": instance["label"], "w": instance["w"], "g": instance["g"],
        "s": instance["s"], "expected_status": instance["expected_status"],
        "method": case[0], "encoding": case[1], "solver": case[2], "sb": case[3],
        "timeout_seconds": timeout_seconds, "start_path": str(start_path),
    }
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "benchmarks.run_all", WORKER_FLAG,
             str(spec_path), str(out_path)],
            cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
        wait_until = time.time() + startup_allowance
        while time.time() < wait_until and not start_path.exists():
            if proc.poll() is not None:
                break
            time.sleep(0.005)
        if not start_path.exists():
            _kill_tree(proc)
            _, stderr = _drain(proc)
            detail = (stderr or "").strip()[-1000:]
            return {"status": "ERROR", "error": f"worker did not start: {detail}"}

        started_at = float(start_path.read_text(encoding="utf-8").strip())
        remaining = run_budget - (time.time() - started_at)
        if remaining <= 0:
            _kill_tree(proc)
            _drain(proc)
            return {
                "status": "TIMEOUT",
                "error": (f"whole-run budget {run_budget:g}s exhausted before "
                          "the model was built"),
                "total_time_seconds": time.time() - started_at,
            }
        try:
            _, stderr = proc.communicate(timeout=remaining)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            _, stderr = _drain(proc)
            return {
                "status": "TIMEOUT",
                "error": f"whole-run budget {run_budget:g}s exceeded (build included)",
                "total_time_seconds": time.time() - started_at,
            }

        if proc.returncode != 0 or not out_path.exists():
            detail = (stderr or "").strip()[-1000:]
            return {"status": "ERROR",
                    "error": f"worker exited with code {proc.returncode}: {detail}"}
        result = json.loads(out_path.read_text(encoding="utf-8"))
        if isinstance(result.get("schedule"), list):
            result["schedule"] = _schedule_from_lists(
                result["schedule"], instance["w"], instance["g"])
        return result
    finally:
        for path in (spec_path, out_path, start_path):
            try:
                path.unlink()
            except OSError:
                pass


def _worker_main(spec_path, out_path):
    """Worker chạy một lượt benchmark và ghi kết quả JSON."""
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    instance = {
        "label": spec["label"], "w": spec["w"], "g": spec["g"], "s": spec["s"],
        "expected_status": spec.get("expected_status", ""),
    }
    case = (spec["method"], spec["encoding"], spec["solver"], spec["sb"])

    # Nạp sẵn module solver trước khi mở đồng hồ để import không tính vào ngân sách.
    if case[0] == "sat":
        from src.sat_runner import solve_cnf  # noqa: F401
    elif case[0] == "order":
        from src.order_encoder import solve_sgp_order  # noqa: F401
    elif case[0] == "cp":
        from src.cp_solver import solve_sgp_cp  # noqa: F401
    else:
        from src.ilp_solver import solve_sgp_ilp  # noqa: F401

    start_path = spec.get("start_path")
    if start_path:
        Path(start_path).write_text(str(time.time()), encoding="utf-8")
    try:
        result = run_case(instance, case, spec["timeout_seconds"])
    except NotImplementedError as exc:
        result = {"status": "UNAVAILABLE", "error": str(exc)}
    except Exception as exc:
        result = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
    result.pop("model", None)
    if result.get("schedule"):
        result["schedule"] = _schedule_to_lists(result["schedule"], spec["w"], spec["g"])
    Path(out_path).write_text(
        json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


def _load_done(path):
    """Đọc trạng thái các lượt đã có: khóa (gồm timeout và scope) -> (status, attempt)."""
    done = {}
    if not path.exists() or path.stat().st_size == 0:
        return done
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != FIELDS:
            raise ValueError(
                f"{path}: incompatible CSV header; use a new --output file "
                "or migrate the existing CSV before using --resume"
            )
        for row in reader:
            key = (row.get("instance", ""), row.get("method", ""),
                   row.get("encoding", ""), row.get("solver", ""),
                   row.get("sb", ""), row.get("timeout_seconds", ""),
                   row.get("timeout_scope", ""))
            try:
                attempt = int(row.get("attempt") or 1)
            except (TypeError, ValueError):
                attempt = 1
            previous = done.get(key)
            done[key] = (row.get("status", "").upper(),
                         max(attempt, previous[1] if previous else attempt))
    return done


def main(argv=None):
    """Chạy suite benchmark theo tham số CLI và ghi results.csv tăng dần."""
    configure_safe_stdio()
    parser = argparse.ArgumentParser(description="SGP benchmark suite -> results.csv")
    parser.add_argument("--instances", default="benchmarks/benchmark_instances.csv")
    parser.add_argument("--output", default="benchmarks/results.csv")
    parser.add_argument("--methods", default=",".join(METHODS))
    parser.add_argument("--encodings", default=",".join(C2_ENCODINGS))
    parser.add_argument("--solvers", default=",".join(SAT_SOLVERS))
    parser.add_argument("--sb", default="none")
    parser.add_argument("--timeout", type=float, default=60.0,
                        help="giới hạn cho tiến trình solver (không gồm dựng CNF)")
    parser.add_argument("--run-budget", type=float, default=0.0,
                        help="giới hạn toàn lượt, tính từ lúc bắt đầu dựng mô hình; "
                             "khi bật, --timeout được thay bằng ngân sách này (0 = tắt)")
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
    run_budget = max(0.0, args.run_budget)
    timeout_scope = "total" if run_budget > 0 else TIMEOUT_SCOPE
    case_timeout = run_budget if run_budget > 0 else args.timeout
    try:
        done = _load_done(output) if args.resume else {}
    except ValueError as exc:
        parser.error(str(exc))
    mode = "a" if args.resume and output.exists() else "w"
    start_all = time.perf_counter()
    written = 0
    error_rows = 0
    precheck_rows = 0
    counts = {}
    stopped = False

    with output.open(mode, encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if mode == "w" or output.stat().st_size == 0:
            writer.writeheader()
            handle.flush()

        for index, instance in enumerate(instances, start=1):
            estimate = estimate_cnf_clauses(instance["w"], instance["g"], instance["s"])
            for case in cases:
                key = ((instance["label"],) + case
                       + (f"{case_timeout:g}", timeout_scope))
                previous = done.get(key)
                if previous is not None and previous[0] in TERMINAL_STATUSES:
                    continue
                over_cap = (case[0] in CNF_METHODS and args.max_clauses > 0
                            and estimate > args.max_clauses)
                if previous is not None and previous[0] == "SKIPPED_RESOURCE_LIMIT" and over_cap:
                    continue
                attempt = previous[1] + 1 if previous is not None else 1
                if (args.budget_seconds is not None
                        and time.perf_counter() - start_all > args.budget_seconds):
                    print("[stop] budget-seconds exhausted")
                    stopped = True
                    break
                started = time.perf_counter()
                if over_cap:
                    result = {
                        "status": "SKIPPED_RESOURCE_LIMIT",
                        "error": (f"estimated {estimate:,} C3 clauses (lower bound) "
                                  f"> cap {args.max_clauses:,}"),
                    }
                else:
                    try:
                        if run_budget > 0:
                            result = _run_case_isolated(
                                instance, case, case_timeout, run_budget,
                                output.parent, args.startup_allowance)
                        else:
                            result = run_case(instance, case, case_timeout)
                    except NotImplementedError as exc:
                        result = {"status": "UNAVAILABLE", "error": str(exc)}
                    except Exception as exc:
                        result = {"status": "ERROR",
                                  "error": f"{type(exc).__name__}: {exc}"}
                row = build_row(instance, case, result, f"{case_timeout:g}",
                                timeout_scope, attempt)
                writer.writerow({field: _format(row[field]) for field in FIELDS})
                handle.flush()
                written += 1
                done[key] = (row["status"], attempt)
                if row["status"] == "ERROR":
                    error_rows += 1
                if row["backend_type"] == "precheck":
                    precheck_rows += 1
                elapsed = time.perf_counter() - started
                counts[(case[0], row["status"])] = counts.get(
                    (case[0], row["status"]), 0) + 1
                mark = ""
                if row["expected_status"] and row["status"] != row["expected_status"]:
                    mark = f"  [!] expected {row['expected_status']}"
                print(f"[{index}/{len(instances)}] {instance['label']:>7} "
                      f"{case[0]:>5} {case[1] or '-':>11} {case[2]:>7} sb={case[3]:<4} "
                      f"-> {row['status']:>21} {elapsed:6.2f}s{mark}", flush=True)
            if stopped:
                break

    print(f"\nWritten rows: {written} -> {output}")
    for (method, status), count in sorted(counts.items()):
        print(f"  {method:>5} {status:>21}: {count}")
    print(f"  precheck (decided by bound): {precheck_rows}")
    if error_rows:
        print(f"[error] {error_rows} lượt kết thúc với status=ERROR", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == WORKER_FLAG:
        raise SystemExit(_worker_main(sys.argv[2], sys.argv[3]))
    raise SystemExit(main())
