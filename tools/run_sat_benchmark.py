"""Run a SAT-only pilot with one wall-time budget for the entire pipeline."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
ENCODINGS = ("nsc", "seqcounter", "totalizer", "cardnetwrk")
SOLVERS = ("cadical", "glucose")
PILOT_CASES = ("3-2-2", "4-3-3", "5-3-2", "5-3-3", "5-3-4",
               "5-3-7", "5-4-4", "3-6-6", "5-7-5", "8-4-2")
WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
_WINDOWS_GATE = (
    "import subprocess,sys; "
    "token=sys.stdin.buffer.readline().strip(); "
    "sys.exit(125) if token != b'GO' else None; "
    "sys.exit(subprocess.call(sys.argv[1:], creationflags=0x08000000))"
)
FIELDS = (
    "paper_label", "w", "g", "s", "source_status", "encoding", "solver",
    "status", "reference_check", "backend", "backend_type", "solver_version",
    "pysat_version", "verified", "model_verified", "num_vars", "num_clauses",
    "pipeline_time_limit_seconds", "pipeline_wall_time_seconds",
    "encode_time_seconds", "wall_time_seconds", "solver_wall_time_seconds",
    "cpu_time_seconds", "total_time_seconds", "conflicts", "decisions",
    "propagations", "estimated_clause_floor", "raw_result_file", "error",
)


def load_instances(path):
    records = []
    with Path(path).open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            try:
                record = {key: int(row[key]) for key in ("w", "g", "s")}
                record.update(paper_label=row["paper_label"],
                              source_status=row["source_status"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("invalid source dataset columns or dimensions") from exc
            if (min(record[key] for key in ("w", "g", "s")) < 1
                    or record["paper_label"] != f"{record['g']}-{record['s']}-{record['w']}"
                    or record["source_status"] not in ("SAT", "UNSAT", "UNKNOWN")):
                raise ValueError(f"invalid source dataset record: {record}")
            records.append(record)
    if not records or len({row["paper_label"] for row in records}) != len(records):
        raise ValueError("source dataset must be nonempty with unique instance labels")
    return records


def estimated_clause_floor(instance):
    w, g, s = (instance[key] for key in ("w", "g", "s"))
    n = g * s
    if s > 1 and w > (n - 1) // (s - 1):
        return 1
    return n * w * (1 + math.comb(g, 2)) + math.comb(w, 2) * g * g * math.comb(n, 2)


class _WindowsJob:
    """Own exactly one gated worker tree, including descendants after its exit."""

    def __init__(self):
        class BasicLimit(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

        class ExtendedLimit(ctypes.Structure):
            _fields_ = [("basic", BasicLimit), ("io", IoCounters)] + [
                (name, ctypes.c_size_t) for name in (
                    "process_memory", "job_memory", "peak_process_memory", "peak_job_memory")]

        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        self._kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel.SetInformationJobObject.argtypes = (
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        self._kernel.SetInformationJobObject.restype = wintypes.BOOL
        self._kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        self._kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self._kernel.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        self._kernel.TerminateJobObject.restype = wintypes.BOOL
        self._kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self._kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimit()
        limits.basic.flags = 0x2000
        if not self._kernel.SetInformationJobObject(
                self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, process):
        if not self._kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def terminate(self):
        if self.handle and not self._kernel.TerminateJobObject(self.handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            if not self._kernel.CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())


def _terminate_tree(process, job=None):
    if job is not None:
        job.terminate()
    elif os.name != "nt":


        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:


        process.kill()


def run_bounded(command, limit_seconds, cwd=ROOT):
    """Return exit/timing data, killing this worker and descendants on timeout."""
    if isinstance(limit_seconds, bool) or not isinstance(limit_seconds, (int, float)):
        raise ValueError("limit_seconds must be a finite positive number")
    try:
        limit_seconds = float(limit_seconds)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("limit_seconds must be a finite positive number") from exc
    if not math.isfinite(limit_seconds) or limit_seconds <= 0:
        raise ValueError("limit_seconds must be a finite positive number")
    started = time.perf_counter()
    process, job = None, None
    stdout, stderr, cleanup_errors = "", "", []
    timed_out = False
    try:
        if os.name == "nt":
            job = _WindowsJob()
            command = [sys.executable, "-c", _WINDOWS_GATE, *command]
        process = subprocess.Popen(
            command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.PIPE if job is not None else subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", creationflags=WINDOW_FLAGS,
            start_new_session=os.name != "nt",
        )
        if job is not None:
            job.assign(process)
        remaining = max(0.0, limit_seconds - (time.perf_counter() - started))
        try:
            stdout, stderr = process.communicate(
                input="GO\n" if job is not None else None, timeout=remaining)
            timed_out = time.perf_counter() - started > limit_seconds
        except subprocess.TimeoutExpired:


            completed_code = process.poll()
            timed_out = completed_code is None or completed_code == 0
            try:
                _terminate_tree(process, job)
            except OSError as exc:
                cleanup_errors.append(str(exc))
                if job is not None:
                    job.close()
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired as exc:
                cleanup_errors.append("worker pipes did not close after tree termination")
                stdout = exc.stdout or ""
                stderr = exc.stderr or ""
    finally:
        if job is not None:
            try:
                job.close()
            except OSError as exc:
                cleanup_errors.append(str(exc))
        if process is not None:
            try:
                _terminate_tree(process)
                process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired) as exc:
                cleanup_errors.append(str(exc))
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    return {
        "timed_out": timed_out, "returncode": process.returncode,
        "elapsed": time.perf_counter() - started,
        "stdout": stdout, "stderr": stderr,
        "cleanup_error": "; ".join(cleanup_errors) or None,
    }


def run_case(instance, encoding, solver, limit_seconds, max_clauses=1_000_000):
    result = dict(instance, encoding=encoding, solver=solver, status="ERROR",
                  verified=False, model_verified=False, error=None,
                  pipeline_time_limit_seconds=limit_seconds,
                  pipeline_wall_time_seconds=0.0,
                  estimated_clause_floor=estimated_clause_floor(instance))
    if max_clauses and result["estimated_clause_floor"] > max_clauses:
        result.update(status="SKIPPED_RESOURCE_LIMIT", backend_type="resource-check",
                      error="C1+C3 clause estimate exceeds the configured construction cap")
    else:
        with tempfile.TemporaryDirectory(prefix="sgp-pipeline-") as directory:
            input_path, output_path = Path(directory) / "input.json", Path(directory) / "result.json"
            input_path.write_text(json.dumps({
                "instance": instance, "encoding": encoding, "solver": solver,
            }), encoding="utf-8")
            try:
                outcome = run_bounded(
                    [sys.executable, "-m", "tools.run_sat_benchmark", "--_worker",
                     str(input_path), str(output_path)], limit_seconds,
                )
                result["pipeline_wall_time_seconds"] = outcome["elapsed"]
                if outcome["timed_out"]:
                    result.update(status="TIMEOUT", error="Whole-pipeline wall-time limit reached")
                elif outcome["returncode"]:
                    result["error"] = f"Pipeline worker exited {outcome['returncode']}: {outcome['stderr'][-1500:]}"
                else:
                    candidate = json.loads(output_path.read_text(encoding="utf-8"))
                    if (not isinstance(candidate, dict) or candidate.get("status") not in
                            {"SAT", "UNSAT", "TIMEOUT", "UNAVAILABLE", "ERROR"}):
                        raise ValueError("invalid pipeline worker result")
                    if candidate["status"] == "SAT" and not (
                            candidate.get("verified") and candidate.get("model_verified")):
                        raise ValueError("pipeline returned SAT without both verification checks")
                    result.update(candidate)
                if outcome.get("cleanup_error"):
                    result["error"] = "; ".join(filter(None, (
                        result.get("error"), f"Cleanup: {outcome['cleanup_error']}")))
                    if result["status"] != "TIMEOUT":
                        result["status"] = "ERROR"
            except subprocess.TimeoutExpired as exc:
                result.update(status="TIMEOUT", error=f"Pipeline deadline: {exc}")
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                result.update(status="ERROR", error=f"Pipeline failed: {exc}")
    reference = instance["source_status"]
    if result["status"] in ("SAT", "UNSAT") and reference != "UNKNOWN":
        result["reference_check"] = "MATCH" if result["status"] == reference else "MISMATCH"
    else:
        result["reference_check"] = "NOT_COMPARED"
    return result


def machine_metadata():
    cpu_name, ram_bytes = platform.processor(), None
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                cpu_name = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                    (name, ctypes.c_ulonglong) for name in (
                        "physical", "available", "pagefile", "available_pagefile",
                        "virtual", "available_virtual", "extended_virtual")]
            memory = MemoryStatus()
            memory.length = ctypes.sizeof(memory)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
                ram_bytes = memory.physical
        except (OSError, AttributeError):
            pass
    else:
        try:
            ram_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        except (ValueError, OSError, AttributeError):
            pass
    return {"cpu_model": cpu_name, "ram_bytes": ram_bytes,
            "logical_processors": os.cpu_count(), "platform": platform.platform(),
            "python_version": platform.python_version(), "pysat_version": version("python-sat"),
            "solver_thread_options": "backend defaults; no thread options set"}


def write_summary(path, rows, limit_seconds, source_path=None):
    groups = {}
    for row in rows:
        counts = groups.setdefault((row["encoding"], row["solver"]), Counter())
        status = row["status"]
        if status == "SAT":
            key = "SAT"
        elif status == "UNSAT":
            key = "Pre" if row.get("backend_type") == "precheck" else "UNSAT"
        elif status == "TIMEOUT":
            key = "TO"
        else:
            key = "Other"
        counts[key] += 1
        counts["Mismatch"] += row["reference_check"] == "MISMATCH"
    instance_labels = list(dict.fromkeys(row["paper_label"] for row in rows))
    source_path = (Path(source_path) if source_path is not None
                   else ROOT / "data/sgp_paper_instances.csv").resolve()
    try:
        source_label = source_path.relative_to(ROOT).as_posix()
    except ValueError:
        source_label = source_path.as_posix()
    lines = [
        "% Generated by python -m tools.run_sat_benchmark.",
        r"\begin{table}[htbp]", r"\centering\small",
        rf"\caption{{SAT-only pilot outcomes for {len(instance_labels)} instances and {len(rows)} configurations, with a {limit_seconds:g}\,s whole-pipeline wall limit per configuration. Pre denotes theoretical-bound UNSAT; TO denotes timeout.}}",
        r"\label{tab:sat-pilot-outcomes}", r"\begin{tabular}{llrrrrrr}", r"\toprule",
        r"C2 & Solver & SAT & UNSAT & Pre & TO & Other & Mismatch \\", r"\midrule",
    ]
    labels = {"nsc": "NSC", "seqcounter": "SC", "totalizer": "TOT", "cardnetwrk": "CARD"}
    for (encoding, solver), counts in groups.items():
        lines.append(f"{labels[encoding]} & {solver} & " + " & ".join(
            str(counts[key]) for key in ("SAT", "UNSAT", "Pre", "TO", "Other", "Mismatch")) + r" \\")
    lines.extend((
        r"\bottomrule", r"\end{tabular}", r"\end{table}",
        r"\noindent Instance labels $(g,s,w)$: "
        + ", ".join(r"\texttt{" + label + "}" for label in instance_labels) + ".",
        r"\noindent Source dataset: \texttt{\detokenize{" + source_label + r"}}.",
        r"Configuration outcomes: \texttt{\detokenize{sat_paper_benchmark.csv}}.",
        "Reported source statuses are cross-checks; UNKNOWN labels are not treated as ground truth. "
        "Other includes unavailable backends, errors and resource-limit skips. "
        "This is a single-run SAT-only subset; the source CPU-time and symmetry/ordering protocol "
        "are not reproduced, and no runtime ranking is inferred.", "",
    ))
    path.write_text("\n".join(lines), encoding="utf-8")


def _worker(input_path, output_path):
    from src.sat_runner import solve_sgp
    payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    instance = payload["instance"]
    result = solve_sgp(instance["w"], instance["g"], instance["s"],
                       encoding=payload["encoding"], solver=payload["solver"],
                       timeout_seconds=None)
    Path(output_path).write_text(json.dumps(result), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instances", type=Path, default=ROOT / "data/sgp_paper_instances.csv")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--cases", nargs="+", help="source (g-p-w) labels; defaults to ten pilot cases")
    selection.add_argument("--all-instances", action="store_true")
    parser.add_argument("--encodings", nargs="+", choices=ENCODINGS, default=list(ENCODINGS))
    parser.add_argument("--solvers", nargs="+", choices=SOLVERS, default=["cadical", "glucose"])
    parser.add_argument("--time-limit", type=float, default=3.0, help="whole-pipeline wall budget per run")
    parser.add_argument("--max-clauses", type=int, default=1_000_000,
                        help="skip if the C1+C3 lower estimate exceeds this cap; 0 disables")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "paper/data")
    arguments = parser.parse_args(argv)
    if not math.isfinite(arguments.time_limit) or arguments.time_limit <= 0 or arguments.max_clauses < 0:
        parser.error("time limit must be finite/positive and max clauses nonnegative")
    try:
        source = load_instances(arguments.instances)
        selected = source if arguments.all_instances else [
            next(row for row in source if row["paper_label"] == label)
            for label in (arguments.cases or PILOT_CASES)]
    except (OSError, ValueError, StopIteration) as exc:
        parser.error(f"invalid dataset or unknown case: {exc}")
    if (len(set(arguments.encodings)) != len(arguments.encodings)
            or len(set(arguments.solvers)) != len(arguments.solvers)
            or len({row["paper_label"] for row in selected}) != len(selected)):
        parser.error("duplicate cases, encodings and solvers are not permitted")
    output = arguments.output_dir
    raw = output / "sat_paper_benchmark_raw"
    raw.mkdir(parents=True, exist_ok=True)
    rows = []
    csv_path = output / "sat_paper_benchmark.csv"
    for instance in selected:
        for encoding in arguments.encodings:
            for solver in arguments.solvers:
                result = run_case(instance, encoding, solver, arguments.time_limit, arguments.max_clauses)
                result["raw_result_file"] = f"sat_paper_benchmark_raw/{instance['paper_label']}_{encoding}_{solver}.json"
                (output / result["raw_result_file"]).write_text(
                    json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                rows.append(result)
                with csv_path.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=FIELDS, extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(rows)
                print(f"{instance['paper_label']} ({instance['w']},{instance['g']},{instance['s']}) "
                      f"{encoding}/{solver}: {result['status']} {result['reference_check']}", flush=True)
    hashes = {}
    for path in (ROOT / "src/sat_direct_encoders.py", ROOT / "src/sat_runner.py",
                 Path(__file__), arguments.instances.resolve()):
        path = path.resolve()
        try:
            label = str(path.relative_to(ROOT))
        except ValueError:
            label = str(path)
        hashes[label] = hashlib.sha256(path.read_bytes()).hexdigest()
    metadata = dict(machine_metadata(), generated_at_utc=datetime.now(timezone.utc).isoformat(),
                    selected_instances=selected, configurations=len(rows),
                    encodings=arguments.encodings, solvers=arguments.solvers,
                    wall_time_limit_seconds=arguments.time_limit, max_clause_floor=arguments.max_clauses,
                    symmetry="none", constraint_order=["C1", "C2", "C3"], source_hashes=hashes,
                    status_counts=dict(Counter(row["status"] for row in rows)),
                    precheck_unsat=sum(row.get("backend_type") == "precheck" for row in rows),
                    reference_mismatches=sum(row["reference_check"] == "MISMATCH" for row in rows),
                    protocol="One fresh worker/solver per configuration; single-run SAT-only pilot. "
                             "Wall budget covers imports, encoding, CNF serialization, solver and verification. "
                             "Timeout cleanup may add overhead. Source CPU timings and symmetry/ordering protocol "
                             "are not reproduced; no cross-hardware runtime comparison or performance ranking.")
    (output / "sat_paper_benchmark_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_summary(output / "sat_paper_benchmark_summary.tex", rows, arguments.time_limit,
                  source_path=arguments.instances)
    print(f"Completed {len(rows)} configurations: {metadata['status_counts']}")
    return int(any(row["status"] in ("ERROR", "UNAVAILABLE")
                   or row["reference_check"] == "MISMATCH" for row in rows))


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--_worker":
        _worker(sys.argv[2], sys.argv[3])
    else:
        sys.exit(main())
