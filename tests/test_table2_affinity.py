"""Pure CPU-list parsing/read-only affinity checks; never launch a benchmark."""
import importlib.util
from pathlib import Path
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/table2_scheduler_affinity.py"
SPEC = importlib.util.spec_from_file_location("table2_scheduler_affinity", str(MODULE_PATH))
affinity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(affinity)


class CpuListParsingTests(unittest.TestCase):
    def test_single_values_and_bounded_ranges(self):
        cases = (
            ("0", frozenset((0,))),
            ("7", frozenset((7,))),
            ("0-31", frozenset(range(32))),
            ("0-3,8,10-11", frozenset((0, 1, 2, 3, 8, 10, 11))),
            ("5-5", frozenset((5,))),
            ("1048575", frozenset((1048575,))),
        )
        for text, expected in cases:
            with self.subTest(cpu_list=text):
                result = affinity.parse_cpu_list(text)
                self.assertIsInstance(result, frozenset)
                self.assertEqual(result, expected)

    def test_unsorted_tokens_are_valid_without_repeated_cpus(self):
        self.assertEqual(affinity.parse_cpu_list("10-11,8,2-3,0-1"),
                         frozenset((0, 1, 2, 3, 8, 10, 11)))

    def test_whitespace_and_empty_tokens_are_rejected(self):
        invalid = ("", " ", "\t", "0\n", " 0", "0 ", "0, 1", "0\t,1",
                   "0 -1", "0- 1", "0-1\r\n", ",0", "0,", "0,,1", ",")
        for text in invalid:
            with self.subTest(cpu_list=repr(text)):
                with self.assertRaises(ValueError):
                    affinity.parse_cpu_list(text)

    def test_only_ascii_integer_and_range_syntax_is_allowed(self):
        invalid = ("-1", "+1", "1.0", "1e2", "0x1", "0_1", "cpu0", "1/2",
                   "1:2", "0--1", "0-1-2", "-0-1", "0-", "-", "1-0", "9-2",
                   "\uff11", "\u0661", "0,\u200b1")
        for text in invalid:
            with self.subTest(cpu_list=text):
                with self.assertRaises(ValueError):
                    affinity.parse_cpu_list(text)

    def test_duplicate_or_overlapping_cpus_are_rejected(self):
        invalid = ("0,0", "1-1,1", "0-3,3", "0-3,2-5", "8,7-9", "5-7,0,6")
        for text in invalid:
            with self.subTest(cpu_list=text):
                with self.assertRaises(ValueError):
                    affinity.parse_cpu_list(text)

    def test_cpu_id_upper_bound_is_enforced(self):
        for text in ("1048576", "0-1048576", "1048575-1048576", "99999999999999999999"):
            with self.subTest(cpu_list=text):
                with self.assertRaises(ValueError):
                    affinity.parse_cpu_list(text)

    def test_exact_expansion_limit_is_accepted(self):
        cpus = affinity.parse_cpu_list("0-65535")
        self.assertEqual(len(cpus), 65536)
        self.assertEqual(cpus, frozenset(range(65536)))
        disjoint = affinity.parse_cpu_list("0-32767,65536-98303")
        self.assertEqual(len(disjoint), 65536)
        self.assertIn(98303, disjoint)

    def test_expansion_limit_applies_to_total_union(self):
        for text in ("0-65536", "0-32767,32768-65536", "0-65535,1048575"):
            with self.subTest(cpu_list=text):
                with self.assertRaises(ValueError):
                    affinity.parse_cpu_list(text)


class AffinityVerificationTests(unittest.TestCase):
    def test_uses_getaffinity_without_changing_the_mask(self):
        with mock.patch.object(affinity.os, "sched_getaffinity", return_value={0, 1, 2, 3},
                               create=True) as getter:
            with mock.patch.object(affinity.os, "sched_setaffinity", create=True) as setter:
                result = affinity.verify_affinity("0-3")
        getter.assert_called_once_with(0)
        setter.assert_not_called()
        self.assertEqual({key: result[key] for key in ("expected_cpu_list", "expected_cpus", "actual_cpus")},
                         {"expected_cpu_list": "0-3", "expected_cpus": [0, 1, 2, 3],
                          "actual_cpus": [0, 1, 2, 3]})

    def test_explicit_mask_preserves_original_text_and_collection(self):
        actual = {0, 1, 2, 3, 8}
        before = set(actual)
        with mock.patch.object(affinity.os, "sched_getaffinity", create=True) as getter:
            with mock.patch.object(affinity.os, "sched_setaffinity", create=True) as setter:
                result = affinity.verify_affinity("8,0-3", actual_cpus=actual)
        getter.assert_not_called()
        setter.assert_not_called()
        self.assertEqual(actual, before)
        self.assertEqual({key: result[key] for key in ("expected_cpu_list", "expected_cpus", "actual_cpus")},
                         {"expected_cpu_list": "8,0-3", "expected_cpus": [0, 1, 2, 3, 8],
                          "actual_cpus": [0, 1, 2, 3, 8]})

    def test_same_size_different_cpus_missing_or_extra_are_mismatches(self):
        cases = (("0-3", {1, 2, 3, 4}), ("0-3", {0, 1, 2}),
                 ("0-3", {0, 1, 2, 3, 4}), ("0", set()))
        with mock.patch.object(affinity.os, "sched_setaffinity", create=True) as setter:
            for text, actual in cases:
                with self.subTest(expected=text, actual=actual):
                    before = set(actual)
                    with self.assertRaises(ValueError):
                        affinity.verify_affinity(text, actual_cpus=actual)
                    self.assertEqual(actual, before)
        setter.assert_not_called()

    def test_observed_mask_mismatch_fails_without_applying_a_fix(self):
        with mock.patch.object(affinity.os, "sched_getaffinity", return_value={4, 5},
                               create=True) as getter:
            with mock.patch.object(affinity.os, "sched_setaffinity", create=True) as setter:
                with self.assertRaises(ValueError):
                    affinity.verify_affinity("0-1")
        getter.assert_called_once_with(0)
        setter.assert_not_called()

    def test_invalid_expected_text_cannot_become_a_mask_change(self):
        with mock.patch.object(affinity.os, "sched_setaffinity", create=True) as setter:
            for text in ("", "0,0", "0-3,3", "0-65536"):
                with self.subTest(expected=text):
                    with self.assertRaises(ValueError):
                        affinity.verify_affinity(text, actual_cpus={0, 1, 2, 3})
        setter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
