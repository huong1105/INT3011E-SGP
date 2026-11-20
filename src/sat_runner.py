"""Giải CNF hoặc SGP bằng SAT solver trong subprocess và kiểm chứng nghiệm."""

from __future__ import annotations

import argparse
from collections import Counter
from importlib.metadata import PackageNotFoundError, version
from itertools import combinations
import json
import math
import numbers
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

try:
    from pysat.solvers import NoSuchSolverError, Solver
except (ImportError, OSError) as exc:
    Solver = None
    _PYSAT_IMPORT_ERROR = str(exc)

    class NoSuchSolverError(Exception):
        """Biểu diễn lỗi thiếu backend khi PySAT chưa được cài."""
else:
    _PYSAT_IMPORT_ERROR = None


SOLVER_BACKENDS = {"cadical": "cadical153", "glucose": "glucose4"}
_BACKEND_VERSIONS = {"cadical153": "1.5.3", "glucose4": "4.1"}
_WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _empty_result(backend: str, num_vars: int, num_clauses: int) -> dict:
    """Tạo kết quả mặc định cùng các trường trạng thái và thống kê."""
    return {
        "status": "ERROR", "backend": backend, "backend_type": "pysat",
        "solver_version": _BACKEND_VERSIONS.get(backend),
        "pysat_version": None, "model": None,
        "num_vars": num_vars, "num_clauses": num_clauses,
        "wall_time_seconds": 0.0, "solver_wall_time_seconds": None,
        "cpu_time_seconds": None, "conflicts": None, "decisions": None,
        "propagations": None, "model_verified": False, "error": None,
        "statistics_error": None,
    }


def _normalise_cnf(clauses, num_vars):
    """Chuẩn hóa clause và kiểm tra số biến có bao phủ mọi literal."""
    if isinstance(clauses, (str, bytes, dict)):
        raise ValueError("clauses must be an iterable of clauses")
    normalised = []
    largest = 0
    try:
        for clause in clauses:
            if isinstance(clause, (str, bytes, dict)):
                raise ValueError("each clause must be an iterable of literals")
            row = list(clause)
            for literal in row:
                if type(literal) is not int or literal == 0:
                    raise ValueError("DIMACS literals must be nonzero integers")
                largest = max(largest, abs(literal))
            normalised.append(row)
    except TypeError as exc:
        raise ValueError("clauses must be an iterable of iterable literals") from exc
    if num_vars is None:
        num_vars = largest
    if type(num_vars) is not int or num_vars < largest or num_vars < 0:
        raise ValueError("num_vars must be a nonnegative integer covering all literals")
    return normalised, num_vars


def _normalise_options(solver, timeout_seconds):
    """Kiểm tra tên solver và giới hạn thời gian."""
    if not isinstance(solver, str) or solver.lower() not in SOLVER_BACKENDS:
        raise ValueError(f"solver must be one of {', '.join(SOLVER_BACKENDS)}")
    if timeout_seconds is not None:
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, numbers.Real):
            raise ValueError("timeout_seconds must be a finite positive number or None")
        try:
            timeout_seconds = float(timeout_seconds)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError("timeout_seconds must be a finite positive number or None") from exc
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be a finite positive number or None")
    return solver.lower(), timeout_seconds


def _model_satisfies(clauses, model, num_vars):
    """Kiểm tra model nhất quán và thỏa mọi clause đầu vào."""
    if not isinstance(model, list):
        return False
    assignment = {}
    for literal in model:
        if type(literal) is not int or literal == 0 or abs(literal) > num_vars:
            return False
        variable, value = abs(literal), literal > 0
        if variable in assignment and assignment[variable] != value:
            return False
        assignment[variable] = value
    return all(any(assignment.get(abs(lit)) == (lit > 0) for lit in clause)
               for clause in clauses)


def _solve_pysat_in_process(clauses, backend, num_vars):
    """Nạp CNF, gọi PySAT và thu kết quả cùng thống kê trong worker."""
    result = _empty_result(backend, num_vars, len(clauses))
    if Solver is None:
        result.update(status="UNAVAILABLE", error=f"PySAT unavailable: {_PYSAT_IMPORT_ERROR}")
        return result
    try:
        result["pysat_version"] = version("python-sat")
    except PackageNotFoundError:
        pass
    cpu_start = time.process_time()
    wall_start = time.perf_counter()
    try:
        instance = Solver(name=backend, bootstrap_with=clauses)
    except (NoSuchSolverError, ImportError, OSError, AttributeError, NotImplementedError) as exc:
        result.update(status="UNAVAILABLE", error=f"{backend} unavailable: {exc}")
        return result
    except Exception as exc:
        result["error"] = f"Could not initialise {backend}: {exc}"
        return result
    try:
        with instance:
            solve_start = time.perf_counter()
            satisfiable = instance.solve()
            result["solver_wall_time_seconds"] = time.perf_counter() - solve_start
            if satisfiable is True:
                result.update(status="SAT", model=instance.get_model())
            elif satisfiable is False:
                result["status"] = "UNSAT"
            else:
                result["error"] = "Solver returned an indeterminate result"
            try:
                stats = instance.accum_stats()
                if stats is None:
                    stats = {}
                if not isinstance(stats, dict):
                    raise TypeError("accum_stats() did not return a dictionary")
                for field in ("conflicts", "decisions", "propagations"):
                    value = stats.get(field)
                    if type(value) is int and value >= 0:
                        result[field] = value
            except Exception as exc:


                result["statistics_error"] = f"{backend} statistics unavailable: {exc}"
    except Exception as exc:
        result.update(status="ERROR", model=None, error=f"{backend} failed: {exc}")
    result["cpu_time_seconds"] = time.process_time() - cpu_start
    result["wall_time_seconds"] = time.perf_counter() - wall_start
    return result


def _run_pysat(clauses, backend, timeout_seconds, num_vars):
    """Chạy worker PySAT với giới hạn thời gian và đọc kết quả JSON."""
    result = _empty_result(backend, num_vars, len(clauses))
    try:
        with tempfile.TemporaryDirectory(prefix="sgp-sat-") as directory:
            input_path = Path(directory) / "input.json"
            output_path = Path(directory) / "result.json"
            input_path.write_text(json.dumps({"clauses": clauses, "backend": backend,
                                             "num_vars": num_vars}), encoding="utf-8")
            started = time.perf_counter()
            try:
                completed = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), "--_worker",
                     str(input_path), str(output_path)],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=timeout_seconds, creationflags=_WINDOW_FLAGS,
                )
                if completed.returncode != 0:
                    result["error"] = (f"Worker exited with code {completed.returncode}: "
                                       f"{completed.stderr[-2000:]}")
                else:
                    candidate = json.loads(output_path.read_text(encoding="utf-8"))
                    if (not isinstance(candidate, dict)
                            or candidate.get("status") not in
                            {"SAT", "UNSAT", "UNAVAILABLE", "ERROR"}):
                        raise ValueError("invalid worker result")
                    result.update(candidate)
            finally:
                result["wall_time_seconds"] = time.perf_counter() - started
    except subprocess.TimeoutExpired:
        result.update(status="TIMEOUT", error=f"Backend exceeded {timeout_seconds:g} seconds")
    except OverflowError as exc:
        result.update(status="ERROR", model=None, error=f"Backend timeout out of range: {exc}")
    except OSError as exc:
        result.update(status="ERROR", model=None, error=f"Worker I/O failed: {exc}")
    except ValueError as exc:
        result.update(status="ERROR", model=None, error=f"Invalid worker data: {exc}")
    return result


def solve_cnf(clauses, solver="cadical", timeout_seconds=None, num_vars=None):
    """Giải CNF bằng solver được chọn và kiểm tra model trước khi trả SAT."""
    clauses, num_vars = _normalise_cnf(clauses, num_vars)
    solver_requested = solver
    solver, timeout_seconds = _normalise_options(solver, timeout_seconds)
    backend = SOLVER_BACKENDS[solver]
    result = _run_pysat(clauses, backend, timeout_seconds, num_vars)
    result["solver"] = solver
    result["solver_requested"] = solver_requested
    result["model_verified"] = False
    if result["status"] == "SAT":
        if _model_satisfies(clauses, result["model"], num_vars):
            result["model_verified"] = True
        else:
            result.update(status="ERROR", model=None,
                          error="Solver returned a missing, inconsistent or unsatisfying model")
    else:
        result["model"] = None
    return result


def verify_sat_schedule(schedule, w, g, s):
    """Kiểm tra phủ đủ người, đúng kích thước nhóm và không lặp cặp."""
    if any(type(value) is not int or value <= 0 for value in (w, g, s)):
        return False
    if (not isinstance(schedule, dict) or any(type(key) is not int for key in schedule)
            or set(schedule) != set(range(w))):
        return False
    n = g * s
    met = set()
    for week in range(w):
        groups = schedule[week]
        if (not isinstance(groups, dict) or any(type(key) is not int for key in groups)
                or set(groups) != set(range(g))):
            return False
        players = []
        for group in range(g):
            members = groups[group]
            if (not isinstance(members, list) or len(members) != s
                    or any(type(player) is not int or not 0 <= player < n for player in members)):
                return False
            players.extend(members)
            for pair in combinations(sorted(members), 2):
                if pair in met:
                    return False
                met.add(pair)
        if Counter(players) != Counter(range(n)):
            return False
    return True


def solve_sgp(w, g, s, encoding="nsc", solver="cadical", timeout_seconds=None,
              symmetry_clauses=None):
    """Sinh CNF, giải và kiểm chứng lịch; cận tuần vô nghiệm trả UNSAT bằng precheck."""
    solver_requested = solver
    solver, timeout_seconds = _normalise_options(solver, timeout_seconds)
    from .sat_direct_encoders import encode_sgp, extract_schedule

    started = time.perf_counter()
    clauses, num_vars, stats = encode_sgp(w, g, s, encoding, symmetry_clauses)
    encode_time = time.perf_counter() - started
    if stats.get("precheck_unsat"):
        result = _empty_result("theoretical-bound", num_vars, len(clauses))
        result.update(status="UNSAT", backend_type="precheck", solver=solver)
    else:
        result = solve_cnf(clauses, solver, timeout_seconds, num_vars)
    result.update(w=w, g=g, s=s, encoding=encoding, stats=stats,
                  encode_time_seconds=encode_time, schedule=None, verified=False,
                  solver_requested=solver_requested)
    if result["status"] == "SAT":
        try:
            schedule = extract_schedule(result["model"], g * s, g, s, w)
        except ValueError as exc:
            result.update(status="ERROR", model=None, model_verified=False,
                          error=f"Could not decode SAT model: {exc}")
        else:
            if verify_sat_schedule(schedule, w, g, s):
                result.update(schedule=schedule, verified=True)
            else:
                result.update(status="ERROR", model=None, model_verified=False,
                              error="SAT model decoded to an invalid SGP schedule")
    result["total_time_seconds"] = time.perf_counter() - started
    return result


def main(argv=None):
    """Đọc tham số CLI, giải SGP và xuất kết quả hoặc lịch."""
    parser = argparse.ArgumentParser(description="Standalone TV2 SAT runner for SGP")
    parser.add_argument("-w", type=int, required=True, help="number of weeks")
    parser.add_argument("-g", type=int, required=True, help="groups per week")
    parser.add_argument("-s", type=int, required=True, help="players per group")
    parser.add_argument("--encoding", "--amo", default="nsc",
                        choices=("nsc", "seqcounter", "totalizer", "cardnetwrk"))
    parser.add_argument("--solver", default="cadical", choices=tuple(SOLVER_BACKENDS))
    parser.add_argument("--timeout", type=float, default=60.0,
                        help="backend wall-time limit in seconds (default: 60), including "
                             "startup/loading/solve and excluding encoding/input serialization")
    parser.add_argument("--json", action="store_true", help="print the complete JSON result")
    arguments = parser.parse_args(argv)
    try:
        result = solve_sgp(arguments.w, arguments.g, arguments.s, arguments.encoding,
                           arguments.solver, arguments.timeout)
    except ValueError as exc:
        parser.error(str(exc))
    except (ImportError, OSError) as exc:
        print(f"UNAVAILABLE: {exc}", file=sys.stderr)
        return 3
    if arguments.json:
        print(json.dumps(result))
    else:
        print(f"{result['status']} | {result['backend']} | {result['encoding']} | "
              f"vars={result['num_vars']} clauses={result['num_clauses']} | "
              f"encode={result['encode_time_seconds']:.6f}s "
              f"backend_wall={result['wall_time_seconds']:.6f}s")
        if result["schedule"] is not None:
            from .sat_direct_encoders import format_schedule
            print(format_schedule(result["schedule"]))
            print("Schedule verified: True")
        if result["error"]:
            print(result["error"], file=sys.stderr)
    return {"SAT": 0, "UNSAT": 0, "ERROR": 1, "UNAVAILABLE": 3, "TIMEOUT": 4}[result["status"]]


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--_worker":
        payload = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        answer = _solve_pysat_in_process(payload["clauses"], payload["backend"], payload["num_vars"])
        Path(sys.argv[3]).write_text(json.dumps(answer), encoding="utf-8")
    else:
        raise SystemExit(main())
