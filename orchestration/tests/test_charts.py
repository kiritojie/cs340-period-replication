"""Chart interpretation regressions; synthetic groups, no target execution."""
import copy
import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
previous = list(sys.path)
sys.path.insert(0, str(ROOT / "orchestration"))
try:
    import rq1_charts as CHARTS
finally:
    sys.path[:] = previous


class ChartTests(unittest.TestCase):
    def groups(self):
        groups = []
        for benchmark in CHARTS.BENCHMARKS:
            for mode in CHARTS.MODES:
                group = {"benchmark": benchmark, "mode": mode, "planned_minimum": 3,
                         "attempted": 0, "valid": 0, "detected": 0, "undetected": 0,
                         "budget_exhausted": 0, "detection_rate": None,
                         "paper_first_error": None if benchmark == "reorder_10_bad" and mode == "serial" else 9,
                         "paper_total_schedules": 10000, "paper_error_interleavings": 0,
                         "paper_budget_censored": benchmark == "reorder_10_bad" and mode == "serial"}
                for metric, unused, unused2, unused3 in CHARTS.METRICS:
                    if metric != "detection_rate":
                        group.update({metric + "_n": 0, metric + "_mean": None, metric + "_sample_sd": None})
                groups.append(group)
        return groups

    def nd(self, group):
        group.update(attempted=3, valid=3, detected=0, undetected=3, budget_exhausted=3, detection_rate=0.0)
        for metric in ("total_schedules", "error_interleavings", "external_seconds"):
            group.update({metric + "_n": 3, metric + "_mean": 10000.0 if metric == "total_schedules" else 0.0,
                          metric + "_sample_sd": 0.0})

    def test_undetected_first_error_is_categorical_but_zero_errors_are_observed(self):
        groups = self.groups()
        self.nd(groups[-1])
        rows = CHARTS.chart_rows(groups)
        last = {row["metric"]: row for row in rows if row["benchmark"] == "reorder_10_bad" and row["mode"] == "serial"}
        self.assertEqual(last["first_error_detected_only"]["ours_status"], "ND")
        self.assertIsNone(last["first_error_detected_only"]["ours_mean"])
        self.assertEqual(last["error_interleavings"]["ours_status"], "VALID")
        self.assertEqual(last["error_interleavings"]["ours_mean"], 0.0)
        self.assertEqual(last["detection_rate"]["ours_mean"], 0.0)
        self.assertEqual(last["first_error_detected_only"]["paper_status"], "ND")
        groups[-1]["first_error_detected_only_mean"] = 10000
        with self.assertRaisesRegex(ValueError, "numeric substitutes"):
            CHARTS.chart_rows(groups)

    def test_missing_and_invalid_only_groups_are_not_measured_zero(self):
        groups = self.groups()
        groups[1]["attempted"] = 1
        rows = CHARTS.chart_rows(groups)
        self.assertTrue(all(row["ours_status"] == "NOT_RUN" for row in rows[:5]))
        self.assertTrue(all(row["ours_status"] == "NO_VALID_RUNS" for row in rows[5:10]))
        self.assertTrue(all(row["ours_mean"] is None for row in rows))

    def test_complete_artifacts_preserve_exact_values_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="rq1-chart-test-", dir=str(ROOT)) as temporary:
            base = Path(temporary)
            source = base / "statistics"
            source.mkdir()
            groups = self.groups()
            self.nd(groups[-1])
            (source / "summary.json").write_text(json.dumps({"schema": "cs340-period-rq1-report-v1",
                "protocol_sha256": "a" * 64, "valid_formal_rounds": 3, "groups": groups}))
            CHARTS.seal_tree(source)
            output = base / "charts"
            result = CHARTS.write_charts(source, output)
            self.assertEqual(result["chart_count"], 5)
            CHARTS.verify_tree(output)
            self.assertEqual(len(list(output.glob("*.svg"))), 5)
            tree = ET.parse(str(output / "first_error_detected_only.svg"))
            self.assertFalse(any(node.get("class") == "ours-bar" for node in tree.iter()))
            zero_tree = ET.parse(str(output / "error_interleavings.svg"))
            self.assertTrue(any(node.get("class") == "ours-bar" and node.get("data-value") == "0.0" for node in zero_tree.iter()))
            with (output / "chart-data.csv").open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 40)
            with self.assertRaises(FileExistsError):
                CHARTS.write_charts(source, output)


if __name__ == "__main__":
    unittest.main()
