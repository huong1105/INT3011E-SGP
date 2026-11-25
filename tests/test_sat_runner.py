"""Public runner checks and deterministic failures for optional backends."""

import json
import io
import subprocess
import unittest
from unittest import mock

from src import sat_runner as runner


RESULT_FIELDS = {
    "status", "backend", "model", "num_vars", "num_clauses",
    "wall_time_seconds", "cpu_time_seconds", "conflicts", "decisions",
    "propagations", "error",
}


class SatRunnerTests(unittest.TestCase):
    def test_only_two_solver_choices_and_unknown_solver_is_rejected(self):
        self.assertEqual(set(runner.SOLVER_BACKENDS), {"cadical", "glucose"})
        with mock.patch.object(runner, "_run_pysat") as worker:
            for solver in ("unknown", "unsupported", ""):
                with self.assertRaises(ValueError):
                    runner.solve_cnf([[1]], solver=solver)
            worker.assert_not_called()

    def assert_result_contract(self, result, status):
        self.assertTrue(RESULT_FIELDS <= result.keys(), result)
        self.assertEqual(result["status"], status, result)
        self.assertGreaterEqual(result["wall_time_seconds"], 0)
        if result["cpu_time_seconds"] is not None:
            self.assertGreaterEqual(result["cpu_time_seconds"], 0)
        json.dumps(result, allow_nan=False)

    def test_sat_cnf_has_a_satisfying_model_and_structured_statistics(self):
        clauses = [[1, 2], [-1, 2], [-2, 3]]
        result = runner.solve_cnf(clauses, solver="glucose", num_vars=7)
        self.assert_result_contract(result, "SAT")
        self.assertEqual(result["backend"], "glucose4")
        self.assertEqual(result["num_vars"], 7)
        self.assertEqual(result["num_clauses"], len(clauses))
        model = set(result["model"])
        self.assertTrue(all(any(literal in model for literal in clause)
                            for clause in clauses))
        for field in ("conflicts", "decisions", "propagations"):
            self.assertIsInstance(result[field], int)
            self.assertGreaterEqual(result[field], 0)
        self.assertIsNone(result["error"])

    def test_empty_formula_is_sat_and_contradictions_are_unsat(self):
        for clauses, expected in (([], "SAT"), ([[]], "UNSAT"),
                                  ([[1], [-1]], "UNSAT")):
            with self.subTest(clauses=clauses):
                result = runner.solve_cnf(clauses, solver="glucose")
                self.assert_result_contract(result, expected)
                if expected == "UNSAT":
                    self.assertIsNone(result["model"])

    def test_all_four_sgp_encodings_return_verified_schedules(self):
        for encoding in ("nsc", "seqcounter", "totalizer", "cardnetwrk"):
            with self.subTest(encoding=encoding):
                result = runner.solve_sgp(2, 2, 2, encoding=encoding, solver="glucose")
                self.assert_result_contract(result, "SAT")
                self.assertTrue(result["verified"])
                self.assertGreaterEqual(result["encode_time_seconds"], 0)
                schedule = result["schedule"]
                seen_pairs = set()
                for week in range(2):
                    members = []
                    for group in range(2):
                        players = schedule[week][group]
                        self.assertEqual(len(players), 2)
                        members.extend(players)
                        pair = tuple(sorted(players))
                        self.assertNotIn(pair, seen_pairs)
                        seen_pairs.add(pair)
                    self.assertEqual(sorted(members), list(range(4)))

    def test_unsat_sgp_does_not_return_a_schedule(self):
        for instance in ((2, 2, 3), (4, 2, 2)):
            with self.subTest(instance=instance):
                result = runner.solve_sgp(*instance, solver="glucose")
                self.assert_result_contract(result, "UNSAT")
                self.assertIsNone(result["model"])
                self.assertIsNone(result["schedule"])

    def test_theoretical_unsat_precheck_never_launches_a_solver(self):
        with mock.patch.object(runner, "solve_cnf") as solve:
            result = runner.solve_sgp(4, 2, 2, solver="cadical")
        solve.assert_not_called()
        self.assert_result_contract(result, "UNSAT")
        self.assertEqual(result["backend"], "theoretical-bound")
        self.assertEqual(result["backend_type"], "precheck")
        self.assertIsNone(result["cpu_time_seconds"])
        self.assertIsNone(result["solver_wall_time_seconds"])
        self.assertIsNone(result["model"])
        self.assertIsNone(result["schedule"])

    def test_model_extraction_failure_is_an_error_result(self):
        answer = runner._empty_result("glucose4", 36, 116)
        answer.update(status="SAT", model=[1])
        with mock.patch.object(runner, "solve_cnf", return_value=answer), \
                mock.patch("src.sat_direct_encoders.extract_schedule",
                           side_effect=ValueError("incomplete primary assignment")):
            result = runner.solve_sgp(2, 2, 2, solver="glucose")
        self.assert_result_contract(result, "ERROR")
        self.assertIsNone(result["model"])
        self.assertIsNone(result["schedule"])
        self.assertFalse(result["verified"])
        self.assertIn("incomplete primary assignment", result["error"])

    def test_invalid_solver_and_cnf_arguments_fail_before_launch(self):
        malformed = (None, "1 0", [[0]], [[True]], [[1.5]], [["1"]], [[1], "2"])
        with mock.patch.object(runner, "_run_pysat") as launch:
            for clauses in malformed:
                with self.subTest(clauses=clauses), self.assertRaises(ValueError):
                    runner.solve_cnf(clauses, solver="glucose")
            for timeout in (0, -1, True, "1", float("nan"), float("inf"), 10 ** 400):
                with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                    runner.solve_cnf([[1]], solver="glucose", timeout_seconds=timeout)
            for num_vars in (0, -1, True, 1.5):
                with self.subTest(num_vars=num_vars), self.assertRaises(ValueError):
                    runner.solve_cnf([[1]], solver="glucose", num_vars=num_vars)
            with self.assertRaises(ValueError):
                runner.solve_cnf([[1]], solver="imaginary-backend")
            launch.assert_not_called()

    def test_subprocess_deadline_becomes_timeout_status(self):
        failure = subprocess.TimeoutExpired(cmd="sat worker", timeout=0.05)
        with mock.patch.object(runner.subprocess, "run", side_effect=failure) as launch:
            result = runner.solve_cnf([[1]], solver="glucose", timeout_seconds=0.05)
        self.assert_result_contract(result, "TIMEOUT")
        self.assertIsNone(result["model"])
        self.assertTrue(result["error"])
        self.assertEqual(launch.call_args.kwargs["timeout"], 0.05)

    def test_unrepresentable_subprocess_timeout_becomes_error_status(self):
        with mock.patch.object(runner.subprocess, "run",
                               side_effect=OverflowError("timeout value is too large")):
            result = runner.solve_cnf([[1]], timeout_seconds=1e300)
        self.assert_result_contract(result, "ERROR")
        self.assertIsNone(result["model"])
        self.assertIn("timeout out of range", result["error"])

    def test_temporary_worker_directory_failure_becomes_error_status(self):
        with mock.patch.object(runner.tempfile, "TemporaryDirectory",
                               side_effect=PermissionError("temporary directory unavailable")), \
                mock.patch.object(runner.subprocess, "run") as launch:
            result = runner.solve_cnf([[1]])
        self.assert_result_contract(result, "ERROR")
        self.assertIn("temporary directory unavailable", result["error"])
        launch.assert_not_called()

    def test_worker_input_write_failure_is_reported_as_cli_json(self):
        message = "Cannot write thư_mục/input.json"
        with io.TextIOWrapper(io.BytesIO(), encoding="ascii") as output:
            with mock.patch.object(runner.Path, "write_text", side_effect=PermissionError(message)), \
                    mock.patch("sys.stdout", output):
                exit_code = runner.main(["-w", "1", "-g", "1", "-s", "1", "--json"])
            output.flush()
            result = json.loads(output.buffer.getvalue())
        self.assertEqual(exit_code, 1)
        self.assert_result_contract(result, "ERROR")
        self.assertIn(message, result["error"])

    def test_worker_crash_becomes_error_status(self):
        completed = subprocess.CompletedProcess(args=["sat worker"], returncode=3,
                                                 stdout="", stderr="worker crashed")
        with mock.patch.object(runner.subprocess, "run", return_value=completed):
            result = runner.solve_cnf([[1]], solver="glucose", timeout_seconds=1)
        self.assert_result_contract(result, "ERROR")
        self.assertIsNone(result["model"])
        self.assertTrue(result["error"])

    def test_missing_native_backend_is_unavailable_not_unsat(self):
        with mock.patch.object(runner, "Solver",
                               side_effect=runner.NoSuchSolverError("backend not built")):
            unavailable = runner._solve_pysat_in_process([[1]], "cadical153", 1)
        with mock.patch.object(runner, "_run_pysat", return_value=unavailable):
            result = runner.solve_cnf([[1]], solver="cadical")
        self.assert_result_contract(result, "UNAVAILABLE")
        self.assertIsNone(result["model"])
        self.assertIn("backend not built", result["error"])


    def test_bogus_sat_models_become_errors(self):
        for model in (None, [], [-1], [1, -1], [True], [2]):
            with self.subTest(model=model):
                answer = runner._empty_result("glucose4", 1, 1)
                answer.update(status="SAT", model=model)
                with mock.patch.object(runner, "_run_pysat", return_value=answer):
                    result = runner.solve_cnf([[1]], solver="glucose")
                self.assert_result_contract(result, "ERROR")
                self.assertIsNone(result["model"])
                self.assertTrue(result["error"])

    def test_optional_statistics_failure_cannot_discard_a_valid_answer(self):
        for satisfiable in (True, False):
            for bad_stats in (RuntimeError("optional statistics failed"), [1, 2]):
                with self.subTest(satisfiable=satisfiable, bad_stats=bad_stats):
                    instance = mock.MagicMock()
                    instance.__enter__.return_value = instance
                    instance.solve.return_value = satisfiable
                    instance.get_model.return_value = [1]
                    if isinstance(bad_stats, Exception):
                        instance.accum_stats.side_effect = bad_stats
                    else:
                        instance.accum_stats.return_value = bad_stats
                    with mock.patch.object(runner, "Solver", return_value=instance):
                        result = runner._solve_pysat_in_process([[1]], "glucose4", 1)
                    self.assert_result_contract(result, "SAT" if satisfiable else "UNSAT")
                    self.assertIsNone(result["error"])
                    self.assertTrue(result["statistics_error"])
                    self.assertIsNone(result["conflicts"])
                    self.assertEqual(result["model"], [1] if satisfiable else None)

    def test_indeterminate_native_answer_never_becomes_unsat(self):
        instance = mock.MagicMock()
        instance.__enter__.return_value = instance
        instance.solve.return_value = None
        instance.accum_stats.return_value = {}
        with mock.patch.object(runner, "Solver", return_value=instance):
            result = runner._solve_pysat_in_process([[1]], "glucose4", 1)
        self.assert_result_contract(result, "ERROR")
        self.assertIsNone(result["model"])
        self.assertIn("indeterminate", result["error"])

    def test_partial_cnf_witness_is_accepted_only_when_it_satisfies_every_clause(self):
        for clauses, model, expected in (
                ([[1, 2], [1, -2]], [1], "SAT"),
                ([[1, 2], [1, -2]], [1, 1], "SAT"),
                ([[1], [2]], [1], "ERROR"),
                ([[1]], [1, -1], "ERROR")):
            with self.subTest(clauses=clauses, model=model):
                answer = runner._empty_result("glucose4", 2, len(clauses))
                answer.update(status="SAT", model=model)
                with mock.patch.object(runner, "_run_pysat", return_value=answer):
                    result = runner.solve_cnf(clauses, solver="glucose", num_vars=2)
                self.assert_result_contract(result, expected)
                self.assertEqual(result["model_verified"], expected == "SAT")

    def test_requested_alias_and_exact_backend_are_recorded_separately(self):
        answer = runner._empty_result("glucose4", 1, 1)
        answer.update(status="SAT", model=[1])
        with mock.patch.object(runner, "_run_pysat", return_value=answer):
            result = runner.solve_cnf([[1]], solver="Glucose")
        self.assertEqual(result["solver_requested"], "Glucose")
        self.assertEqual(result["solver"], "glucose")
        self.assertEqual(result["backend"], "glucose4")
        self.assertEqual(result["solver_version"], "4.1")


    def test_cli_exit_codes_keep_unsat_distinct_from_backend_failures(self):
        for status, exit_code in (("SAT", 0), ("UNSAT", 0), ("ERROR", 1),
                                  ("UNAVAILABLE", 3), ("TIMEOUT", 4)):
            answer = runner._empty_result("glucose4", 1, 1)
            answer.update(status=status, schedule=None, encoding="nsc", encode_time_seconds=0)
            with self.subTest(status=status), \
                    mock.patch.object(runner, "solve_sgp", return_value=answer), \
                    mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertEqual(runner.main(["-w", "1", "-g", "1", "-s", "1", "--json"]),
                                 exit_code)
                self.assertEqual(json.loads(output.getvalue())["status"], status)

    def test_schedule_verifier_rejects_each_kind_of_sgp_violation(self):
        valid = {0: {0: [0, 1], 1: [2, 3]}, 1: {0: [0, 2], 1: [1, 3]}}
        self.assertTrue(runner.verify_sat_schedule(valid, 2, 2, 2))
        invalid = (
            {0: valid[0]},
            {0: valid[0], 1: {0: [0, 1], 1: [2, 3]}},
            {0: valid[0], 1: {0: [0, 2], 1: [1, 2]}},
            {0: valid[0], 1: {0: [0, 2], 1: [1, 4]}},
            {0: valid[0], 1: {0: [0], 1: [1, 2, 3]}},
        )
        for schedule in invalid:
            with self.subTest(schedule=schedule):
                self.assertFalse(runner.verify_sat_schedule(schedule, 2, 2, 2))

    def test_schedule_verifier_rejects_invalid_dimensions_and_boolean_keys(self):
        for index in range(3):
            for value in (0, -1, True, 1.5, "1", None):
                dimensions = [1, 1, 1]
                dimensions[index] = value
                with self.subTest(dimensions=dimensions):
                    self.assertFalse(runner.verify_sat_schedule({0: {0: [0]}}, *dimensions))
        self.assertFalse(runner.verify_sat_schedule({False: {0: [0]}}, 1, 1, 1))
        self.assertFalse(runner.verify_sat_schedule({0: {False: [0]}}, 1, 1, 1))


if __name__ == "__main__":
    unittest.main()
