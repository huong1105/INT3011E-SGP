"""Semantic checks for the TV2 encoders, independent of the shared verifier."""

import itertools
import unittest

from pysat.card import CardEnc, EncType
from pysat.solvers import Solver

from src import sat_direct_encoders as enc


ENCODINGS = ("nsc", "seqcounter", "totalizer", "cardnetwrk")


def assert_valid_schedule(test, schedule, w, g, s):
    """Check actual player assignments rather than encoder statistics."""
    n = g * s
    seen_pairs = set()
    test.assertEqual(set(schedule), set(range(w)))
    for week in range(w):
        test.assertEqual(set(schedule[week]), set(range(g)))
        players = []
        for group in range(g):
            members = schedule[week][group]
            test.assertEqual(len(members), s)
            players.extend(members)
            for pair in itertools.combinations(sorted(members), 2):
                test.assertNotIn(pair, seen_pairs)
                seen_pairs.add(pair)
        test.assertEqual(sorted(players), list(range(n)))


class VariableMappingTests(unittest.TestCase):
    def test_round_trip_is_bijective_and_dimacs_is_one_based(self):
        n, g, w = 5, 3, 4
        ids = set()
        for player, group, week in itertools.product(range(n), range(g), range(w)):
            variable = enc.var(player, group, week, g, w)
            ids.add(variable)
            self.assertEqual(enc.decode_var(variable, g, w), (player, group, week))
        self.assertEqual(ids, set(range(1, n * g * w + 1)))

    def test_invalid_coordinates_and_dimacs_ids_are_rejected(self):
        for args in ((-1, 0, 0, 2, 2), (0, -1, 0, 2, 2),
                     (0, 2, 0, 2, 2), (0, 0, 2, 2, 2),
                     (True, 0, 0, 2, 2), (0, 0, 0, 0, 2)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                enc.var(*args)
        for variable in (0, -1, True, 1.5):
            with self.subTest(variable=variable), self.assertRaises(ValueError):
                enc.decode_var(variable, 2, 2)


class CardinalityTests(unittest.TestCase):
    def test_all_encodings_project_to_exactly_k_including_boundaries(self):


        for encoding in ENCODINGS:
            for n in range(1, 7):
                for k in range(n + 1):
                    clauses, top_id = enc.encode_c2(n, 1, k, 1, encoding=encoding)
                    self.assertGreaterEqual(top_id, n)
                    with Solver(name="glucose4", bootstrap_with=clauses) as solver:
                        for bits in itertools.product((False, True), repeat=n):
                            assumptions = [i + 1 if bit else -(i + 1)
                                           for i, bit in enumerate(bits)]
                            with self.subTest(encoding=encoding, n=n, k=k, bits=bits):
                                self.assertEqual(solver.solve(assumptions=assumptions),
                                                 sum(bits) == k)

    def test_group_counters_remain_independent_with_reserved_variable_ids(self):
        n, g, w, reserved = 3, 2, 2, 100
        for encoding in ENCODINGS:
            clauses, top_id = enc.encode_c2(n, g, 1, w, encoding=encoding,
                                           top_id=reserved)
            self.assertGreaterEqual(top_id, reserved)
            primary_max = n * g * w
            auxiliaries = {abs(lit) for clause in clauses for lit in clause
                           if abs(lit) > primary_max}
            self.assertTrue(all(variable > reserved for variable in auxiliaries))
            with Solver(name="glucose4", bootstrap_with=clauses) as solver:
                for choices in itertools.product(range(n), repeat=g * w):
                    assumptions = []
                    for group, week in itertools.product(range(g), range(w)):
                        selected = choices[group * w + week]
                        for player in range(n):
                            variable = enc.var(player, group, week, g, w)
                            assumptions.append(variable if player == selected else -variable)
                    with self.subTest(encoding=encoding, choices=choices):
                        self.assertTrue(solver.solve(assumptions=assumptions))

    def test_boundary_encodings_never_reduce_reserved_top_id(self):


        for encoding, k in itertools.product(ENCODINGS, (0, 4)):
            with self.subTest(encoding=encoding, k=k):
                clauses, top_id = enc.encode_c2(4, 3, k, 2, encoding=encoding,
                                               top_id=100)
                self.assertGreaterEqual(top_id, 100)
                self.assertTrue(all(abs(lit) <= top_id
                                    for clause in clauses for lit in clause))

    def test_invalid_cardinality_dimensions_and_top_ids(self):
        for encoding in ENCODINGS:
            for args in ((0, 1, 0, 1), (3, 0, 1, 1), (3, 1, 1, 0),
                         (3, 1, -1, 1), (3, 1, 4, 1), (3, 1, True, 1)):
                with self.subTest(encoding=encoding, args=args), self.assertRaises(ValueError):
                    enc.encode_c2(*args, encoding=encoding)
            for top_id in (11, -1, True, 12.5, "12"):
                with self.subTest(encoding=encoding, top_id=top_id), self.assertRaises(ValueError):
                    enc.encode_c2(3, 2, 1, 2, encoding=encoding, top_id=top_id)
        with self.assertRaises(ValueError):
            enc.encode_c2(3, 1, 1, 1, encoding="commander")

    def test_paper_nsc_and_sequential_counter_size_formulas(self):


        def sc_atmost_size(n, q):
            if q == 0:
                return 0, n
            if q == n:
                return 0, 0
            if q == n - 1:
                return 0, 1
            return q * (n - q), (n - q) * (2 * q + 1) - q

        for n in range(2, 13):
            for k in range(1, n):
                with self.subTest(n=n, k=k):
                    nsc_aux = k * (2 * n - k - 1) // 2
                    nsc_clauses = 4 * nsc_aux - 2 * k + 2 + int(k >= 2)
                    clauses, top = enc.encode_c2_nsc(n, 1, k, 1)
                    self.assertEqual(top - n, nsc_aux)
                    self.assertEqual(len(clauses), nsc_clauses)

                    upper_aux, upper_clauses = sc_atmost_size(n, k)
                    lower_aux, lower_clauses = sc_atmost_size(n, n - k)

                    atmost = CardEnc.atmost(list(range(1, n + 1)), bound=k,
                                            encoding=EncType.seqcounter)
                    self.assertEqual(atmost.nv - n, upper_aux)
                    self.assertEqual(len(atmost.clauses), upper_clauses)
                    clauses, top = enc.encode_c2_pysat(n, 1, k, 1,
                                                      encoding="seqcounter")
                    self.assertEqual(top - n, upper_aux + lower_aux)
                    self.assertEqual(len(clauses), upper_clauses + lower_clauses)


class AssignmentConstraintTests(unittest.TestCase):
    def test_c1_allows_exactly_one_group_for_every_player_and_week(self):
        n, g, w = 2, 3, 2
        clauses = enc.encode_c1(n, g, w)
        with Solver(name="glucose4", bootstrap_with=clauses) as solver:
            for player, week in itertools.product(range(n), range(w)):
                for bits in itertools.product((False, True), repeat=g):
                    assumptions = [enc.var(player, group, week, g, w) * (1 if bit else -1)
                                   for group, bit in enumerate(bits)]
                    with self.subTest(player=player, week=week, bits=bits):
                        self.assertEqual(solver.solve(assumptions=assumptions), sum(bits) == 1)

    def test_c3_rejects_a_repeated_pair_even_when_group_labels_change(self):
        n, g, w = 4, 2, 2
        clauses = enc.encode_c3(n, g, w)
        with Solver(name="glucose4", bootstrap_with=clauses) as solver:
            for first_group, second_group in itertools.product(range(g), repeat=2):
                repeated_pair = [enc.var(player, group, week, g, w)
                                 for week, group in ((0, first_group), (1, second_group))
                                 for player in (0, 1)]
                with self.subTest(groups=(first_group, second_group)):
                    self.assertFalse(solver.solve(assumptions=repeated_pair))
            different_pairs = [enc.var(player, group, week, g, w)
                               for week, group, players in ((0, 0, (0, 1)), (1, 1, (0, 2)))
                               for player in players]
            self.assertTrue(solver.solve(assumptions=different_pairs))

    def test_c1_and_c3_reject_nonpositive_dimensions(self):
        for helper in (enc.encode_c1, enc.encode_c3):
            for args in ((0, 2, 2), (2, 0, 2), (2, 2, 0), (True, 2, 2)):
                with self.subTest(helper=helper.__name__, args=args), self.assertRaises(ValueError):
                    helper(*args)


class FullEncodingTests(unittest.TestCase):
    def test_sat_instances_decode_to_independently_valid_schedules(self):
        cases = ((2, 2, 2), (3, 3, 3), (1, 1, 1), (1, 1, 2), (2, 2, 1))
        for encoding, (w, g, s) in itertools.product(ENCODINGS, cases):
            with self.subTest(encoding=encoding, instance=(w, g, s)):
                clauses, num_vars, stats = enc.encode_sgp(w, g, s, encoding=encoding)
                self.assertEqual(stats["n_total_vars"], num_vars)
                self.assertEqual(stats["n_total_clauses"], len(clauses))
                self.assertGreaterEqual(num_vars, max((abs(lit) for clause in clauses
                                                      for lit in clause), default=0))
                with Solver(name="glucose4", bootstrap_with=clauses) as solver:
                    self.assertTrue(solver.solve())
                    model = solver.get_model()
                schedule = enc.extract_schedule(model, g * s, g, s, w)
                assert_valid_schedule(self, schedule, w, g, s)

    def test_actual_unsat_below_pair_count_bound(self):


        for encoding in ENCODINGS:
            with self.subTest(encoding=encoding):
                clauses, _, stats = enc.encode_sgp(2, 2, 3, encoding=encoding)
                self.assertFalse(stats.get("precheck_unsat", False))
                with Solver(name="glucose4", bootstrap_with=clauses) as solver:
                    self.assertFalse(solver.solve())

    def test_above_bound_is_logically_unsat_without_an_argument_error(self):
        for encoding in ENCODINGS:
            with self.subTest(encoding=encoding):
                clauses, _, stats = enc.encode_sgp(4, 2, 2, encoding=encoding)
                self.assertIn([], clauses)
                self.assertTrue(stats["precheck_unsat"])
                self.assertTrue(stats["unsat_reason"])
                self.assertEqual(stats["n_precheck"], 1)

    def test_invalid_problem_inputs_are_rejected(self):
        for index in range(3):
            for value in (0, -1, True, 1.5, "2", None):
                args = [2, 2, 2]
                args[index] = value
                with self.subTest(args=args), self.assertRaises(ValueError):
                    enc.encode_sgp(*args)
        with self.assertRaises(ValueError):
            enc.encode_sgp(2, 2, 2, encoding="binary")

    def test_primary_only_symmetry_clauses_and_empty_contradiction(self):
        fixed = enc.var(0, 0, 0, 2, 2)
        for symmetry_clauses in ([[fixed]], (iter(row) for row in [[fixed]])):
            with self.subTest(symmetry_clauses=symmetry_clauses):
                clauses, _, stats = enc.encode_sgp(2, 2, 2, symmetry_clauses=symmetry_clauses)
                self.assertEqual(stats["n_sb"], 1)
                with Solver(name="glucose4", bootstrap_with=clauses) as solver:
                    self.assertTrue(solver.solve())
                    self.assertIn(fixed, solver.get_model())
        clauses, _, stats = enc.encode_sgp(2, 2, 2, symmetry_clauses=[[]])
        self.assertEqual(stats["n_sb"], 1)
        with Solver(name="glucose4", bootstrap_with=clauses) as solver:
            self.assertFalse(solver.solve())

    def test_symmetry_cannot_claim_encoder_auxiliary_ids(self):
        for clauses in ([[17]], [[-17]], [[0]], [[True]], [[1.5]], [None]):
            with self.subTest(clauses=clauses), self.assertRaises(ValueError):
                enc.encode_sgp(2, 2, 2, symmetry_clauses=clauses)

    def test_symmetry_rejects_text_binary_and_mappings(self):
        for container in ("", b"", bytearray(), {}, {(): None}):
            for clauses in (container, [container]):
                with self.subTest(clauses=clauses), self.assertRaises(ValueError):
                    enc.encode_sgp(2, 2, 2, symmetry_clauses=clauses)

    def test_model_extraction_requires_complete_unique_primary_assignments(self):
        self.assertEqual(enc.extract_schedule([1, 2, -3], 1, 1, 1, 1),
                         {0: {0: [0]}})
        for model in (None, 123, [], [2], [1, 1], [1, -1], [1, 2, 2],
                      [0], [True], [1.5], ["1"]):
            with self.subTest(model=model), self.assertRaises(ValueError):
                enc.extract_schedule(model, 1, 1, 1, 1)
        clauses, _, _ = enc.encode_sgp(2, 2, 2)
        with Solver(name="glucose4", bootstrap_with=clauses) as solver:
            self.assertTrue(solver.solve())
            model = solver.get_model()
        missing_primary = [literal for literal in model if abs(literal) != 16]
        with self.assertRaises(ValueError):
            enc.extract_schedule(missing_primary, 4, 2, 2, 2)


if __name__ == "__main__":
    unittest.main()
