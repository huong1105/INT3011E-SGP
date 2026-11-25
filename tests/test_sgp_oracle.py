"""Compare complete tiny partition search with SAT, without a SAT-based oracle."""

from collections import Counter
import csv
from functools import lru_cache
from itertools import combinations
from math import factorial
from pathlib import Path
import unittest

from pysat.solvers import Solver

from src.sat_direct_encoders import encode_sgp


ENCODINGS = ("nsc", "seqcounter", "totalizer", "cardnetwrk")
DATASET = Path(__file__).resolve().parents[1] / "data" / "sgp_paper_instances.csv"


@lru_cache(maxsize=None)
def weekly_partitions(n, s):
    """All partitions into unlabeled groups of size s, each emitted once."""
    def split(remaining):
        if not remaining:
            yield ()
            return


        anchor, others = remaining[0], remaining[1:]
        for peers in combinations(others, s - 1):
            group = (anchor,) + peers
            selected = set(group)
            rest = tuple(player for player in remaining if player not in selected)
            for tail in split(rest):
                yield (group,) + tail

    return tuple(split(tuple(range(n))))


@lru_cache(maxsize=None)
def tiny_oracle_schedule(w, g, s):
    """Return a complete-search witness, or None if the tiny SGP is UNSAT."""
    n = g * s
    first_week = tuple(tuple(range(group * s, (group + 1) * s))
                       for group in range(g))
    if s == 1:

        return (first_week,) * w
    partitions = weekly_partitions(n, s)
    pair_sets = tuple(frozenset(pair for group in partition
                                for pair in combinations(group, 2))
                      for partition in partitions)
    first_index = partitions.index(first_week)

    @lru_cache(maxsize=None)
    def complete_search(weeks_left, start, already_met):
        if weeks_left == 0:
            return ()
        for index in range(start, len(partitions)):
            if pair_sets[index].isdisjoint(already_met):
                tail = complete_search(weeks_left - 1, index + 1,
                                       already_met | pair_sets[index])
                if tail is not None:
                    return (partitions[index],) + tail
        return None


    remainder = complete_search(w - 1, 0, pair_sets[first_index])
    return None if remainder is None else (first_week,) + remainder


def tiny_instances():
    """Positive g,s<=3, gs<=6; include one week above the finite pair bound."""
    for g in range(1, 4):
        for s in range(1, 4):
            if g * s > 6:
                continue
            final_week = 4 if s == 1 else (g * s - 1) // (s - 1) + 1
            for w in range(1, final_week + 1):
                yield w, g, s


def paper_label_to_api(label):
    groups, size, weeks = map(int, label.split("-"))
    return weeks, groups, size


def primary_model_schedule(model, w, g, s):
    """Decode via the documented ID formula, without the production decoder."""
    true_variables = {literal for literal in model if literal > 0}
    return tuple(tuple(tuple(player for player in range(g * s)
                             if (player * g + group) * w + week + 1 in true_variables)
                       for group in range(g))
                 for week in range(w))


def assert_schedule(test, schedule, w, g, s):
    """Check weekly coverage, exact sizes and social pairs without src helpers."""
    test.assertEqual(len(schedule), w)
    seen_pairs = set()
    for week in schedule:
        test.assertEqual(len(week), g)
        all_players = []
        for group in week:
            test.assertEqual(len(group), s)
            test.assertTrue(all(type(player) is int for player in group))
            all_players.extend(group)
            pairs = set(combinations(sorted(group), 2))
            test.assertTrue(pairs.isdisjoint(seen_pairs))
            seen_pairs.update(pairs)
        test.assertEqual(sorted(all_players), list(range(g * s)))


class PaperDatasetTests(unittest.TestCase):
    def read_records(self):
        with DATASET.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(reader.fieldnames,
                             ["paper_label", "g", "s", "w", "source_status", "source_pdf_page"])
            return list(reader)

    def test_dataset_has_all_66_distinct_source_rows_and_page_locations(self):
        records = self.read_records()
        self.assertEqual(len(records), 66)
        self.assertEqual(len({row["paper_label"] for row in records}), 66)
        self.assertEqual(Counter(int(row["source_pdf_page"]) for row in records),
                         {31: 33, 32: 33})
        self.assertEqual(records[0]["paper_label"], "3-2-2")
        self.assertEqual(records[32]["paper_label"], "7-7-3")
        self.assertEqual(records[33]["paper_label"], "7-7-8")
        self.assertEqual(records[-1]["paper_label"], "19-10-2")

    def test_dataset_parameters_match_original_labels_and_api_order(self):
        for row in self.read_records():
            with self.subTest(label=row["paper_label"]):
                w, g, s = (int(row[column]) for column in ("w", "g", "s"))
                self.assertTrue(all(parameter > 0 for parameter in (w, g, s)))
                self.assertEqual(paper_label_to_api(row["paper_label"]), (w, g, s))
        self.assertEqual(paper_label_to_api("2-2-3"), (3, 2, 2))
        self.assertEqual(paper_label_to_api("6-3-8"), (8, 6, 3))

    def test_source_unknowns_remain_distinct_from_unsat(self):
        records = self.read_records()
        self.assertEqual(Counter(row["source_status"] for row in records),
                         {"SAT": 41, "UNSAT": 15, "UNKNOWN": 10})
        expected_unknowns = {
            "6-4-7", "7-3-10", "8-4-9", "8-4-10", "9-3-12", "9-4-9",
            "9-4-10", "10-3-13", "10-6-7", "13-13-14",
        }
        self.assertEqual({row["paper_label"] for row in records
                          if row["source_status"] == "UNKNOWN"}, expected_unknowns)


class TinyOracleTests(unittest.TestCase):
    def test_partition_enumeration_is_complete_by_independent_count(self):
        for n, s in ((1, 1), (2, 1), (3, 1), (2, 2), (3, 3), (4, 2), (6, 2), (6, 3)):
            g = n // s
            partitions = weekly_partitions(n, s)
            expected_count = factorial(n) // (factorial(s) ** g * factorial(g))
            with self.subTest(n=n, s=s):
                self.assertEqual(len(partitions), expected_count)
                self.assertEqual(len(set(partitions)), expected_count)
                for partition in partitions:
                    assert_schedule(self, (partition,), 1, g, s)

    def test_source_example_and_necessary_bound_counterexample(self):
        instance = paper_label_to_api("2-2-3")
        witness = tiny_oracle_schedule(*instance)
        self.assertIsNotNone(witness)
        assert_schedule(self, witness, *instance)


        self.assertLessEqual(2, (2 * 3 - 1) // (3 - 1))
        self.assertIsNone(tiny_oracle_schedule(2, 2, 3))
        self.assertIsNone(tiny_oracle_schedule(4, 2, 2))

    def compare_with_oracle(self, fixed_first_week):
        for w, g, s in tiny_instances():
            witness = tiny_oracle_schedule(w, g, s)
            if witness is not None:
                assert_schedule(self, witness, w, g, s)
            sb_clauses = None
            if fixed_first_week:


                sb_clauses = [[(player * g + player // s) * w + 1]
                              for player in range(g * s)]
            for encoding in ENCODINGS:
                with self.subTest(instance=(w, g, s), encoding=encoding,
                                  fixed_first_week=fixed_first_week):
                    clauses, _, _ = encode_sgp(w, g, s, encoding=encoding,
                                              symmetry_clauses=sb_clauses)
                    with Solver(name="glucose4", bootstrap_with=clauses) as solver:
                        actual = solver.solve()
                        self.assertEqual(actual, witness is not None)
                        if actual:
                            schedule = primary_model_schedule(solver.get_model(), w, g, s)
                            assert_schedule(self, schedule, w, g, s)
                            if fixed_first_week:
                                expected_first = tuple(tuple(range(group * s, (group + 1) * s))
                                                       for group in range(g))
                                self.assertEqual(schedule[0], expected_first)

    def test_all_four_encodings_agree_with_complete_tiny_oracle(self):
        self.compare_with_oracle(fixed_first_week=False)

    def test_safe_first_week_clauses_preserve_tiny_oracle_answers(self):
        self.compare_with_oracle(fixed_first_week=True)


if __name__ == "__main__":
    unittest.main()
