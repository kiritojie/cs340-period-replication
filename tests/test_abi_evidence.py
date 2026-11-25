"""Corrected-ABI evidence tests with synthetic files only; no PERIOD execution."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "corrected_abi_evidence_under_test", ROOT / "scripts/table2_scheduler_evidence.py")
EVIDENCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVIDENCE)
LAYOUT = json.loads((ROOT / "tests/fixtures/period_runtime_3964_layout.json").read_text(encoding="utf-8"))
LAYOUT.pop("compilation_unit", None)  # Driver metadata uses canonical transport layout.


class CorrectedBaselineEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="period-synthetic-corrected-baseline-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = "/synthetic/PERIOD/tool/DBDS/run_PDS.py"
        # Deliberately unlike the historical 27/6 path: corrected results must
        # not be filtered merely to make them agree with old measurements.
        self.schedules = [[[0, 0], [1, 1, 2]], [[0], [2], [0, 1, 1]]]
        self.output_counter = 0

    def make_run(self, label, mode):
        run = self.root / label
        run.mkdir()
        (run / "exit-code.txt").write_text("0\n", encoding="utf-8")
        (run / "stderr.log").write_text("", encoding="utf-8")
        lines = ["ThreadNum: 3", "kpNumArray: 2 2 1"]
        for ordinal, schedule in enumerate(self.schedules, 1):
            lines.append("test {0:04d}: {1}".format(ordinal, schedule))
            if ordinal == 2:
                lines.append("\t[Error Found]: NO.1 assertion failed")
        lines += ["End Testing!", "Total Error Interleavings: 1",
                  "Total Timeouts Interleavings: 0", "Round\t0\t\t2"]
        (run / "stdout.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        output = run / "work/out_reorder_3_bad_1"
        for directory in ("Errors", "Timeouts", "DiffResult"):
            (output / directory).mkdir(parents=True)
        pattern = EVIDENCE.yield_pattern(self.schedules[1])
        (output / "Errors/000001_0000002_assertion-failed").write_text(
            str(pattern) + "\nAssertion failed at reorder_bad.c:80\n", encoding="utf-8")
        trace = [{"event": "trace_start", "schema": "cs340-period-yield-trace-v1",
                  "expected_source": self.source, "expected_source_sha256": "a" * 64,
                  "driver_sha256": "b" * 64}]
        for ordinal, schedule in enumerate(self.schedules, 1):
            trace.append({"event": "yield_write", "ordinal": ordinal, "period": len(schedule),
                          "schedule": schedule, "yield_pattern": EVIDENCE.yield_pattern(schedule),
                          "source_file": self.source})
        trace.append({"event": "trace_summary", "driver_exit_code": 0, "yield_writes": 2,
                      "pending_writes": 0, "observation_error": None})
        (run / "actual-yield.jsonl").write_text(
            "\n".join(json.dumps(row) for row in trace) + "\n", encoding="utf-8")
        metadata = {"status": "COMPLETED", "exit_code": 0, "scheduler": "parallel", "depth": 3,
                    "target_timeout_seconds": 5, "budget": 10000,
                    "abi_proof": {"status": "PASS", "abi_profile": "runtime-dwarf",
                                  "layout": copy.deepcopy(LAYOUT)},
                    "abi_layout": copy.deepcopy(LAYOUT),
                    "abi_layer_sha256": "c" * 64,
                    "role": "abi-only-parallel-reference" if mode == "reference" else "unified-comparison",
                    "accounting": {"limit": 10000, "executed": 2, "completed": 2,
                                   "in_flight": 0, "retests": 0, "retests_completed": 0,
                                   "physical_launches": 2, "budget_hit": False},
                    "upstream_statistics": {"rounds": 2}}
        self.write_metadata(run, metadata)
        return run, metadata

    def write_metadata(self, run, metadata):
        (run / "adapter-metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    def compare(self, reference, candidate):
        self.output_counter += 1
        output = self.root / ("comparison-{0}.json".format(self.output_counter))
        code = EVIDENCE.main(["compare", "--baseline", "abi-corrected",
                              "--reference-dir", str(reference), "--candidate-dir", str(candidate),
                              "--output", str(output)])
        return code, json.loads(output.read_text(encoding="utf-8"))

    def test_corrected_reference_is_accepted_and_historical_difference_is_preserved(self):
        run, unused = self.make_run("A1", "reference")
        result = EVIDENCE.analyze(run, "reference", "abi-corrected")
        self.assertEqual((result["first_error"], result["total_schedules"], result["error_interleavings"]), (2, 2, 1))
        self.assertFalse(result["historical_comparison"]["matches"])
        self.assertEqual(result["historical_comparison"]["reference_only"]["total_schedules"], 27)
        self.assertEqual(result["driver_role"], "abi-only-parallel-reference")
        with self.assertRaisesRegex(ValueError, "differs from archived"):
            EVIDENCE.analyze(run, "reference", "historical")

    def test_matching_corrected_A1_and_B_can_pass_without_matching_historical_counts(self):
        reference, unused = self.make_run("A1", "reference")
        candidate, unused = self.make_run("B", "parallel")
        code, result = self.compare(reference, candidate)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["reference"]["historical_comparison"]["matches"])
        self.assertFalse(result["candidate"]["historical_comparison"]["matches"])
        self.assertIn("A0: audit only", result["unmodified_historical_driver"])

    def test_historical_raw_driver_cannot_masquerade_as_corrected_reference(self):
        run, metadata = self.make_run("A1", "reference")
        (run / "adapter-metadata.json").unlink()
        with self.assertRaises((OSError, ValueError)):
            EVIDENCE.analyze(run, "reference", "abi-corrected")
        for role in (None, "unmodified-official", "historical", "unified-comparison"):
            value = copy.deepcopy(metadata)
            if role is None:
                del value["role"]
            else:
                value["role"] = role
            self.write_metadata(run, value)
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, "labeled separately"):
                EVIDENCE.analyze(run, "reference", "abi-corrected")

    def test_failed_proof_missing_layer_and_wrong_reference_configuration_block(self):
        run, metadata = self.make_run("A1", "reference")
        cases = []
        value = copy.deepcopy(metadata); value["abi_proof"] = {"status": "BLOCKED"}; cases.append(value)
        value = copy.deepcopy(metadata); del value["abi_layout"]; cases.append(value)
        value = copy.deepcopy(metadata); value["abi_layer_sha256"] = "short"; cases.append(value)
        value = copy.deepcopy(metadata); value["budget"] = 9999; cases.append(value)
        value = copy.deepcopy(metadata); value["scheduler"] = "serial"; cases.append(value)
        value = copy.deepcopy(metadata); value["depth"] = 2; cases.append(value)
        value = copy.deepcopy(metadata); value["target_timeout_seconds"] = 6; cases.append(value)
        value = copy.deepcopy(metadata); value["status"] = "BUDGET_EXHAUSTED"; cases.append(value)
        for value in cases:
            self.write_metadata(run, value)
            with self.subTest(metadata=value), self.assertRaises(ValueError):
                EVIDENCE.analyze(run, "reference", "abi-corrected")

    def test_A1_and_B_must_have_identical_concrete_ABI_and_layer_hash(self):
        reference, unused = self.make_run("A1", "reference")
        candidate, metadata = self.make_run("B", "parallel")
        for field in ("abi_layout", "abi_layer_sha256"):
            value = copy.deepcopy(metadata)
            if field == "abi_layout":
                # A different internally valid layout must still not compare
                # equal across arms, even if each arm binds its own proof.
                value[field]["byte_size"] = 12160
                for member in value[field]["members"][5:]:
                    member["dimensions"] = [1990]
                value[field]["members"][6]["offset"] = 4200
                value[field]["members"][7]["offset"] = 8180
                value["abi_proof"]["layout"] = copy.deepcopy(value[field])
            else:
                value[field] = "d" * 64
            self.write_metadata(candidate, value)
            code, result = self.compare(reference, candidate)
            with self.subTest(field=field):
                self.assertNotEqual(code, 0)
                self.assertEqual(result["status"], "BLOCKED")
                self.assertIn("common ABI mismatch", result["reason"])

    def test_identical_invalid_layout_in_both_arms_cannot_pass_by_comparing_equal(self):
        reference, left = self.make_run("A1", "reference")
        candidate, right = self.make_run("B", "parallel")
        for metadata, run in ((left, reference), (right, candidate)):
            metadata["abi_layout"]["members"][-1]["offset"] += 2
            metadata["abi_proof"]["layout"] = copy.deepcopy(metadata["abi_layout"])
            self.write_metadata(run, metadata)
        code, result = self.compare(reference, candidate)
        self.assertNotEqual(code, 0)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("offset", result["reason"])

    def test_layout_and_runtime_profile_must_be_bound_to_measured_proof(self):
        run, metadata = self.make_run("A1", "reference")
        cases = []
        value = copy.deepcopy(metadata); del value["abi_proof"]["abi_profile"]; cases.append(value)
        value = copy.deepcopy(metadata); value["abi_proof"]["abi_profile"] = "legacy-1990"; cases.append(value)
        value = copy.deepcopy(metadata); del value["abi_proof"]["layout"]; cases.append(value)
        value = copy.deepcopy(metadata); value["abi_proof"]["layout"]["byte_size"] = 12160; cases.append(value)
        for value in cases:
            self.write_metadata(run, value)
            with self.subTest(proof=value["abi_proof"]), self.assertRaisesRegex(ValueError, "bound to its measured runtime proof"):
                EVIDENCE.analyze(run, "reference", "abi-corrected")

    def test_unified_accounting_is_not_waived_by_new_baseline(self):
        run, metadata = self.make_run("B", "parallel")
        for field, replacement in (("completed", 1), ("executed", 3), ("limit", 9999),
                                    ("in_flight", 1), ("retests", 1), ("budget_hit", True)):
            value = copy.deepcopy(metadata)
            value["accounting"][field] = replacement
            self.write_metadata(run, value)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "accounting"):
                EVIDENCE.analyze(run, "parallel", "abi-corrected")


if __name__ == "__main__":
    unittest.main(verbosity=2)
