"""Statistical/censoring rules; no benchmark or operating-system mutation."""
import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("rq1_report_tests", ROOT / "scripts/table2_rq1_report.py")
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


def context(round_number=1, phase="formal"):
    return {"schema": "cs340-period-rq1-run-v1", "benchmark": "reorder_10_bad", "mode": "serial", "round": round_number,
            "phase": phase, "purpose": phase, "role": "unified", "protocol_sha256": "protocol"}


def analysis(first=None, state="BUDGET_EXHAUSTED", total=10000):
    return {"schema": "cs340-period-formal-evidence-v1", "status": "PASS", "validation": "PASS",
            "included": True, "valid_research_result": True, "benchmark": "reorder_10_bad", "mode": "serial",
            "termination_state": state, "total_schedules": total, "completed_schedules": total, "in_flight": 0,
            "protocol_sha256": "protocol",
            "error_interleavings": 0 if first is None else 1, "first_error": first, "timeouts": 0,
            "internal_seconds": 1.0, "external_seconds": 1.5, "exit_code": 0}


class FormalReportTests(unittest.TestCase):
    def test_budget_nd_stays_censored_and_out_of_first_error_mean(self):
        rows = [REPORT.normalize_round(context(1), analysis(), "/run1", "protocol"),
                REPORT.normalize_round(context(2), analysis(5), "/run2", "protocol"),
                REPORT.normalize_round(context(3), analysis(9), "/run3", "protocol")]
        group = next(g for g in REPORT.summarize(rows) if g["benchmark"] == "reorder_10_bad" and g["mode"] == "serial")
        self.assertEqual((group["valid"], group["detected"], group["undetected"]), (3, 2, 1))
        self.assertAlmostEqual(group["detection_rate"], 2 / 3)
        self.assertEqual(group["first_error_detected_only_mean"], 7)
        self.assertAlmostEqual(group["first_error_detected_only_sample_sd"], 8 ** 0.5)
        self.assertEqual(rows[0]["censor_at"], 10000)
        self.assertIsNone(rows[0]["first_error"])
        all_nd = next(g for g in REPORT.summarize([rows[0]]) if g["benchmark"] == "reorder_10_bad" and g["mode"] == "serial")
        self.assertEqual(all_nd["detection_rate"], 0)
        self.assertIsNone(all_nd["first_error_detected_only_mean"])

    def test_unfinished_or_failed_attempt_is_retained_but_not_a_censored_no_bug(self):
        bad = analysis()
        bad.update(termination_state="ROUND_TIMEOUT", status="BLOCKED", included=False,
                   valid_research_result=False, total_schedules=57, completed_schedules=56, in_flight=1)
        row = REPORT.normalize_round(context(), bad, "/bad", "protocol")
        self.assertFalse(row["included"])
        self.assertFalse(row["right_censored"])
        self.assertIsNone(row["bug_detected"])
        group = next(g for g in REPORT.summarize([row]) if g["benchmark"] == "reorder_10_bad" and g["mode"] == "serial")
        self.assertEqual((group["attempted"], group["valid"], group["invalid"]), (1, 0, 1))
        self.assertIsNone(group["detection_rate"])

    def test_budget_boundary_and_protocol_identity_cannot_be_waived(self):
        self.assertFalse(REPORT.normalize_round(context(), analysis(total=9999), "/bad", "protocol")["included"])
        self.assertFalse(REPORT.normalize_round(context(), analysis(), "/bad", "different")["included"])
        self.assertIsNone(REPORT.mean_sd([6])["sample_sd"])

    def test_collect_excludes_adaptation_and_rejects_duplicate_attempt_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for dirname, phase in (("formal1", "formal"), ("repeat1", "formal"), ("adapt", "adaptation")):
                run = root / dirname
                run.mkdir()
                (run / "run-context.json").write_text(json.dumps(context(1, phase)))
                (run / "analysis.json").write_text(json.dumps(analysis()))
                paths = (run / "run-context.json", run / "analysis.json")
                (run / "SHA256SUMS").write_text("\n".join(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name for path in paths))
            rows = REPORT.collect_rounds(root, "protocol")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(not row["included"] and "duplicate" in row["exclusion_reasons"] for row in rows))

    def test_checksum_or_missing_purpose_cannot_enter_formal_statistics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "run-context.json").write_text(json.dumps(context()))
            (root / "analysis.json").write_text(json.dumps(analysis()))
            paths = (root / "run-context.json", root / "analysis.json")
            (root / "SHA256SUMS").write_text("\n".join(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name for path in paths))
            self.assertTrue(REPORT.collect_rounds(root, "protocol")[0]["included"])
            (root / "stage-result.json").write_text(json.dumps({"phase_excluded": True}))
            self.assertFalse(REPORT.collect_rounds(root, "protocol")[0]["included"])
            (root / "stage-result.json").write_text(json.dumps({"phase_excluded": False}))
            (root / "analysis.json").write_text(json.dumps(analysis(5)))
            row = REPORT.collect_rounds(root, "protocol")[0]
            self.assertFalse(row["included"])
            self.assertIn("checksum", row["exclusion_reasons"])
        missing = context()
        del missing["purpose"]
        self.assertFalse(REPORT.normalize_round(missing, analysis(), "/missing", "protocol")["included"])

    def test_empty_report_does_not_invent_observed_zeroes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "protocol.json").write_text(json.dumps({"schedule_budget": 10000, "minimum_rounds": 3}))
            output = root / "report"
            summary = REPORT.write_report(root, output)
            self.assertEqual(summary["formal_attempts"], 0)
            self.assertFalse(summary["minimum_complete"])
            self.assertTrue(all(group["detection_rate"] is None and group["status"] == "NOT_RUN" for group in summary["groups"]))
            self.assertIn("NOT_RUN", (output / "report.md").read_text())
            with self.assertRaises(FileExistsError):
                REPORT.write_report(root, output)


if __name__ == "__main__":
    unittest.main()
