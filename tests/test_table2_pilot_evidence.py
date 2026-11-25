"""Synthetic JSONL evidence validation; never run PERIOD or an instrumented target."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "pilot_evidence_under_test", ROOT / "scripts" / "table2_scheduler_evidence.py")
EVIDENCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVIDENCE)


class ActualYieldTraceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="period-synthetic-yield-evidence-")
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name)
        self.path = self.run / "actual-yield.jsonl"
        self.source = "/synthetic/PERIOD/tool/DBDS/run_PDS.py"
        self.schedules = [[[0, 0], [1, 1, 2]], [[0], [2], [0, 1, 1]]]
        self.patterns = [[[0, 0], [1, 0], [1, 0]], [[0, 2], [2, 0], [1, 0]]]
        self.records = [{
            "event": "trace_start", "schema": "cs340-period-yield-trace-v1",
            "expected_source": self.source,
            "expected_source_sha256": "a" * 64, "driver_sha256": "b" * 64,
        }]
        for ordinal, (schedule, pattern) in enumerate(zip(self.schedules, self.patterns), 1):
            self.records.append({
                "event": "yield_write", "ordinal": ordinal, "schedule": schedule,
                "period": len(schedule), "source_file": self.source,
                "yield_pattern": pattern,
            })
        self.records.append({
            "event": "trace_summary", "driver_exit_code": 0, "yield_writes": 2,
            "pending_writes": 0, "observation_error": None,
        })

    def validate(self, records=None, schedules=None):
        rows = self.records if records is None else records
        self.path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        return EVIDENCE.actual_yield_trace(
            self.run, self.schedules if schedules is None else schedules)

    def test_complete_synthetic_write_trace_reconciles_with_expected_matrices(self):
        result = self.validate()
        self.assertEqual(result["actual_yield_patterns"], self.patterns)
        self.assertEqual(result["observed_source"], self.source)
        self.assertEqual(result["observed_source_sha256"], "a" * 64)
        self.assertEqual(result["trace_sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_missing_trace_cannot_be_replaced_by_derived_yields(self):
        with self.assertRaisesRegex(ValueError, "missing actual"):
            EVIDENCE.actual_yield_trace(self.run, self.schedules)

    def test_schema_namespace_and_both_identity_hashes_are_required(self):
        mutations = (("schema", "unsupported"), ("expected_source", ""),
                     ("expected_source_sha256", "a" * 63),
                     ("expected_source_sha256", "G" * 64),
                     ("driver_sha256", ""), ("driver_sha256", "B" * 64))
        for field, value in mutations:
            rows = copy.deepcopy(self.records)
            rows[0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.validate(rows)

    def test_duplicate_or_missing_start_and_summary_are_rejected(self):
        variants = (
            self.records[1:], self.records[:-1],
            [self.records[0]] + self.records,
            self.records + [self.records[-1]], [],
        )
        for rows in variants:
            with self.subTest(events=[row["event"] for row in rows]), self.assertRaises(ValueError):
                self.validate(rows)

    def test_event_order_unknown_events_and_explicit_observer_errors_are_rejected(self):
        variants = (
            self.records[1:2] + self.records[:1] + self.records[2:],
            self.records[:-2] + self.records[-1:] + self.records[-2:-1],
            self.records[:-1] + [{"event": "trace_error"}] + self.records[-1:],
            self.records[:-1] + [{"event": "unknown"}] + self.records[-1:],
        )
        for rows in variants:
            with self.subTest(events=[row["event"] for row in rows]), self.assertRaises(ValueError):
                self.validate(rows)

    def test_exit_counts_pending_writes_and_observation_failure_are_not_waived(self):
        for field, value in (("driver_exit_code", 124), ("yield_writes", 3),
                             ("pending_writes", 1), ("observation_error", "write failed")):
            rows = copy.deepcopy(self.records)
            rows[-1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(rows)

    def test_actual_write_count_must_equal_printed_executed_schedule_count(self):
        rows = copy.deepcopy(self.records)
        del rows[2]
        rows[-1]["yield_writes"] = 1
        with self.assertRaisesRegex(ValueError, "count differs"):
            self.validate(rows)

    def test_every_write_must_bind_its_schedule_period_ordinal_and_source(self):
        for field, value in (("ordinal", 9), ("schedule", self.schedules[1]),
                             ("period", 4), ("source_file", "/different/run_PDS.py")):
            rows = copy.deepcopy(self.records)
            rows[1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(rows)

    def test_yield_matrix_requires_uint16_shape_and_exact_actual_conversion(self):
        invalid = (
            [[0, 0], [1, 0]],
            [[0], [1, 0], [1, 0]],
            [[0, 0], [-1, 0], [1, 0]],
            [[0, 0], [65536, 0], [1, 0]],
            [[0, 0], [True, 0], [1, 0]],
            [[0, 0], [1.0, 0], [1, 0]],
            [[0, 0], [2, 0], [1, 0]],
        )
        for pattern in invalid:
            rows = copy.deepcopy(self.records)
            rows[1]["yield_pattern"] = pattern
            with self.subTest(pattern=pattern), self.assertRaises(ValueError):
                self.validate(rows)


if __name__ == "__main__":
    unittest.main(verbosity=2)
