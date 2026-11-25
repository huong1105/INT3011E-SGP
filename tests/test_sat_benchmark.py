"""Whole-pipeline budgets and owned-process cleanup, independent of CP/ILP."""

import csv
import ctypes
from ctypes import wintypes
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from tools import run_sat_benchmark as benchmark


def _pid_alive(pid):
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                raise ctypes.WinError(ctypes.get_last_error())
            return code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False

    stat = Path(f"/proc/{pid}/stat")
    return not stat.exists() or stat.read_text().split()[2] != "Z"


class SatBenchmarkTests(unittest.TestCase):
    def instance(self, source_status="SAT"):
        return dict(paper_label="2-2-2", w=2, g=2, s=2, source_status=source_status)

    def test_actual_whole_pipeline_returns_verified_sat(self):
        result = benchmark.run_case(self.instance(), "nsc", "glucose", 5)
        self.assertEqual(result["status"], "SAT", result)
        self.assertTrue(result["verified"])
        self.assertTrue(result["model_verified"])
        self.assertEqual(result["reference_check"], "MATCH")
        self.assertGreater(result["pipeline_wall_time_seconds"], 0)

    def test_actual_timeout_kills_descendant_even_after_worker_exits(self):
        for parent_exits in (False, True):
            with self.subTest(parent_exits=parent_exits), tempfile.TemporaryDirectory() as folder:
                marker = Path(folder) / "child.pid"
                child_code = (
                    "import os,time;from pathlib import Path;"
                    f"Path({str(marker)!r}).write_text(str(os.getpid()));time.sleep(30)"
                )
                parent_code = (
                    "import os,subprocess,sys,time;"
                    f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}]);"
                    + ("time.sleep(0.4);os._exit(7)" if parent_exits else "time.sleep(30)")
                )
                outcome = benchmark.run_bounded([sys.executable, "-c", parent_code], 1.5)
                self.assertTrue(marker.exists(), outcome)
                child_pid = int(marker.read_text())
                try:
                    for _ in range(20):
                        if not _pid_alive(child_pid):
                            break
                        time.sleep(0.05)
                    self.assertFalse(_pid_alive(child_pid), outcome)
                finally:


                    if _pid_alive(child_pid):
                        if os.name == "nt":
                            subprocess.run(["taskkill", "/PID", str(child_pid), "/F"],
                                           capture_output=True, timeout=5,
                                           creationflags=benchmark.WINDOW_FLAGS)
                        else:
                            os.kill(child_pid, signal.SIGKILL)
                self.assertIsNone(outcome["cleanup_error"])
                self.assertLess(outcome["elapsed"], 5)
                if parent_exits:
                    self.assertEqual(outcome["returncode"], 7)
                    self.assertFalse(outcome["timed_out"])
                else:
                    self.assertTrue(outcome["timed_out"])

    def test_resource_cap_skips_before_launching_any_worker(self):
        with mock.patch.object(benchmark, "run_bounded") as launch:
            result = benchmark.run_case(self.instance(), "nsc", "glucose", 1, max_clauses=1)
        launch.assert_not_called()
        self.assertEqual(result["status"], "SKIPPED_RESOURCE_LIMIT")
        self.assertEqual(result["reference_check"], "NOT_COMPARED")

    def test_unknown_reference_is_not_treated_as_ground_truth(self):
        result = benchmark.run_case(self.instance("UNKNOWN"), "nsc", "glucose", 5)
        self.assertEqual(result["status"], "SAT", result)
        self.assertTrue(result["verified"])
        self.assertEqual(result["source_status"], "UNKNOWN")
        self.assertEqual(result["reference_check"], "NOT_COMPARED")

    def test_timeout_exception_keeps_a_timeout_result(self):
        with mock.patch.object(benchmark, "run_bounded",
                               side_effect=subprocess.TimeoutExpired("worker", 1)):
            result = benchmark.run_case(self.instance(), "nsc", "glucose", 1)
        self.assertEqual(result["status"], "TIMEOUT")
        self.assertEqual(result["reference_check"], "NOT_COMPARED")

    def test_invalid_dataset_and_unknown_case_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.csv"
            source.write_text("paper_label,w,g,s,source_status\n2-2-2,2,2,2,SAT\n",
                              encoding="utf-8")
            self.assertEqual(len(benchmark.load_instances(source)), 1)
            with mock.patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
                benchmark.main(["--instances", str(source), "--cases", "missing"])
            source.write_text("paper_label,w,g,s,source_status\n2-2-2,3,2,2,SAT\n",
                              encoding="utf-8")
            with self.assertRaises(ValueError):
                benchmark.load_instances(source)

    def test_metadata_accepts_an_external_absolute_dataset_path(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "external-source.csv"
            source.write_text("paper_label,w,g,s,source_status\n2-2-2,2,2,2,UNKNOWN\n",
                              encoding="utf-8")
            output = Path(folder) / "results"
            with mock.patch("sys.stdout", new_callable=io.StringIO):
                code = benchmark.main(["--instances", str(source), "--all-instances",
                                       "--encodings", "nsc", "--solvers", "glucose",
                                       "--time-limit", "5", "--max-clauses", "1",
                                       "--output-dir", str(output)])
            self.assertEqual(code, 0)
            metadata = json.loads((output / "sat_paper_benchmark_metadata.json").read_text())
            self.assertIn(str(source.resolve()), metadata["source_hashes"])
            with (output / "sat_paper_benchmark.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source_status"], "UNKNOWN")
            summary = (output / "sat_paper_benchmark_summary.tex").read_text(encoding="utf-8")
            self.assertIn("1 instances and 1 configurations", summary)
            self.assertIn("5\\,s whole-pipeline", summary)
            self.assertIn("2-2-2", summary)
            self.assertIn(source.resolve().as_posix(), summary)
            self.assertIn("sat_paper_benchmark.csv", summary)


if __name__ == "__main__":
    unittest.main()
