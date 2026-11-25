"""Synthetic formal-result regressions; never execute targets or scheduling calls."""
import copy
import contextlib
import hashlib
import importlib.util
import itertools
import io
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("formal_evidence_test", ROOT / "scripts/table2_scheduler_evidence.py")
EVIDENCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVIDENCE)
LAYOUT = json.loads((ROOT / "tests/fixtures/period_runtime_3964_layout.json").read_text())
LAYOUT.pop("compilation_unit", None)
COMMIT = "b6f72a7b06d01ffa7114b640312873ec2578a5ea"


class FormalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="period-formal-evidence-synthetic-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.protocol = {"bug_depth": 3, "schedule_budget": 10000,
                         "target_timeout_seconds": 5, "round_timeout_seconds": 3600}

    def make_run(self, label, n=4, mode="serial", schedules=None, errors=(2,), status="COMPLETED"):
        benchmark = "reorder_" + str(n) + "_bad"
        kps = [2] * (n - 1) + [1]
        if schedules is None:
            order = list(range(n))
            other = [1, 0] + list(range(2, n))
            if mode == "serial":
                schedules = [[[t] * kps[t] for t in order], [[t] * kps[t] for t in other]]
            else:
                schedules = [[[0] * kps[0], [t for t in order[1:] for _ in range(kps[t])]],
                             [[1] * kps[1], [t for t in other[1:] for _ in range(kps[t])]]]
        run = self.root / label
        work = run / "work"
        work.mkdir(parents=True)
        binary, config = b"synthetic-target-never-execute", b"synthetic-config"
        (work / benchmark).write_bytes(binary)
        (work / ("ConConfig." + benchmark)).write_bytes(config)
        profile = {"benchmark": benchmark, "threads": n, "source_commit": COMMIT,
                   "binary": {"sha256": hashlib.sha256(binary).hexdigest()},
                   "config": {"sha256": hashlib.sha256(config).hexdigest()}}
        raw = work / ("out_" + benchmark + "_1")
        for name in ("Errors", "Timeouts", "DiffResult"):
            (raw / name).mkdir(parents=True)
        source = "/frozen/PERIOD/tool/DBDS/run_PDS.py"
        records = [{"event": "trace_start", "schema": "cs340-period-yield-trace-v1",
                    "expected_source": source, "expected_source_sha256": "e" * 64,
                    "driver_sha256": "d" * 64}]
        lines = ["ThreadNum: " + str(n), "MaxKpNum: 2", "kpNumArray: " + " ".join(map(str, kps))]
        saved = 0
        for ordinal, schedule in enumerate(schedules, 1):
            pattern = EVIDENCE.formal_yield_pattern(schedule, kps, 2)
            lines.append("test %04d: " % ordinal + repr(schedule))
            records.append({"event": "yield_write", "ordinal": ordinal, "period": len(schedule),
                            "schedule": schedule, "yield_pattern": pattern, "source_file": source})
            if ordinal in errors:
                saved += 1
                lines.append("[Error Found]: NO." + str(saved) + " assertion failed")
                (raw / "Errors" / ("%06d_%07d_assertion-failed" % (saved, ordinal))).write_text(
                    repr(pattern) + "\nBug found!\nassertion failed at reorder_bad.c:80\n")
        if status == "BUDGET_EXHAUSTED":
            lines.append("COMPARISON_BUDGET_EXHAUSTED")
        lines.extend(["End Testing!", "Total Error Interleavings: " + str(saved),
                      "Total Timeouts Interleavings: 0", "Round 0 " + str(len(schedules)),
                      "Time 00:00:00.00000 00:00:01.25000"])
        records.append({"event": "trace_summary", "driver_exit_code": 0, "yield_writes": len(schedules),
                        "pending_writes": 0, "observation_error": None})
        (run / "stdout.log").write_text("\n".join(lines) + "\n")
        (run / "stderr.log").write_text("")
        (run / "actual-yield.jsonl").write_text("\n".join(json.dumps(record) for record in records) + "\n")
        (run / "exit-code.txt").write_text("0\n")
        (run / "walltime.txt").write_text("external_wall_ns=1500000000\n")
        proof = {"status": "PASS", "abi_profile": "runtime-dwarf", "layout": LAYOUT,
                 "source_commit": COMMIT, "binary_sha256": profile["binary"]["sha256"],
                 "abi_layer_sha256": "a" * 64,
                 "identities": {"config": profile["config"], "driver": {"sha256": "d" * 64},
                                "reference": {"sha256": "d" * 64}}}
        metadata = {"status": status, "scheduler": "serial" if mode == "serial" else "parallel",
                    "role": "abi-only-parallel-reference" if mode == "reference" else "unified-scheduler-comparison",
                    "depth": 3, "budget": 10000, "target_timeout_seconds": 5, "exit_code": 0,
                    "abi_validation": "PASS", "abi_proof": proof, "abi_layout": LAYOUT,
                    "abi_layer_sha256": "a" * 64, "permission_proof": {"status": "PASS"},
                    "original_source_sha256": "e" * 64,
                    "upstream_statistics": {"rounds": len(schedules), "total_errors_interleavings": [saved],
                                            "total_timeouts_interleavings": [0]},
                    "process_launches_including_preparation": [
                        {"executed_argv": ["./" + benchmark]} for _ in range(len(schedules) + 2)]}
        if mode != "reference":
            metadata["accounting"] = {"limit": 10000, "executed": len(schedules), "completed": len(schedules),
                                      "in_flight": 0, "retests": 0, "retests_completed": 0,
                                      "physical_launches": len(schedules),
                                      "generated": len(schedules) + int(status == "BUDGET_EXHAUSTED"),
                                      "budget_hit": status == "BUDGET_EXHAUSTED"}
        (run / "adapter-metadata.json").write_text(json.dumps(metadata))
        return run, profile

    def update_metadata(self, run, change):
        path = run / "adapter-metadata.json"
        metadata = json.loads(path.read_text())
        change(metadata)
        path.write_text(json.dumps(metadata))

    def test_dynamic_four_thread_serial_dimensions_and_no_paper_filter(self):
        run, profile = self.make_run("four")
        result = EVIDENCE.analyze_formal(run, "serial", profile, self.protocol)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["kps"], [2, 2, 2, 1])
        self.assertEqual(result["matrix_shape"], [4, 2])
        self.assertEqual((result["total_schedules"], result["first_error"]), (2, 2))
        self.assertEqual(result["error_interleavings"], 1)

    def test_no_detection_is_null_and_censored_at_actual_completed_count(self):
        run, profile = self.make_run("none", n=5, errors=())
        result = EVIDENCE.analyze_formal(run, "serial", profile, self.protocol)
        self.assertTrue(result["included"], result)
        self.assertIsNone(result["first_error"])
        self.assertFalse(result["bug_detected"])
        self.assertEqual(result["censoring"], {"right_censored": True, "censor_at": 2,
                                               "reason": "SEARCH_SPACE_COMPLETED_WITHOUT_BUG"})

    def test_real_budget_boundary_is_valid_without_fabricated_first_bug(self):
        n = 10
        kps = [2] * 9 + [1]
        schedules = [[[thread] * kps[thread] for thread in order]
                     for order in itertools.islice(itertools.permutations(range(n)), 10000)]
        run, profile = self.make_run("budget", n=n, schedules=schedules, errors=(), status="BUDGET_EXHAUSTED")
        result = EVIDENCE.analyze_formal(run, "serial", profile, self.protocol)
        self.assertTrue(result["included"], result.get("exclusion_reasons"))
        self.assertEqual(result["termination_state"], "BUDGET_EXHAUSTED")
        self.assertEqual(result["total_schedules"], 10000)
        self.assertIsNone(result["first_error"])
        self.assertEqual(result["censoring"]["censor_at"], 10000)
        self.update_metadata(run, lambda metadata: metadata["accounting"].update(completed=9999, in_flight=1))
        invalid = EVIDENCE.analyze_formal(run, "serial", profile, self.protocol)
        self.assertFalse(invalid["included"])
        self.assertEqual(invalid["completed_schedules"], 9999)
        self.assertEqual(invalid["in_flight"], 1)

    def test_fake_early_budget_stop_and_extra_unexecuted_schedule_are_rejected(self):
        run, profile = self.make_run("early", status="BUDGET_EXHAUSTED")
        result = EVIDENCE.analyze_formal(run, "serial", profile, self.protocol)
        self.assertFalse(result["included"])
        self.assertIn("boundary", " ".join(result["exclusion_reasons"]))
        self.update_metadata(run, lambda metadata: metadata.update(status="COMPLETED"))
        self.update_metadata(run, lambda metadata: metadata["accounting"].update(executed=1, completed=1, budget_hit=False))
        result = EVIDENCE.analyze_formal(run, "serial", profile, self.protocol)
        self.assertFalse(result["included"])
        self.assertEqual(result["executed_schedules"], 1)
        self.assertEqual(result["printed_schedule_count"], 2)

    def test_target_round_infrastructure_and_driver_failures_remain_distinct(self):
        for state in ("TARGET_TIMEOUT", "ROUND_TIMEOUT", "INFRASTRUCTURE_FAILURE", "DRIVER_EXCEPTION"):
            run, profile = self.make_run(state)
            if state == "TARGET_TIMEOUT":
                path = run / "stdout.log"
                path.write_text(path.read_text().replace("Total Timeouts Interleavings: 0", "Total Timeouts Interleavings: 1"))
            elif state == "ROUND_TIMEOUT":
                (run / "exit-code.txt").write_text("124")
            elif state == "INFRASTRUCTURE_FAILURE":
                self.update_metadata(run, lambda metadata: metadata.update(cleanup_errors=[{"error": "cleanup denied"}]))
            else:
                self.update_metadata(run, lambda metadata: metadata.update(status="FAILED", exception="generator failed"))
            result = EVIDENCE.analyze_formal(run, "serial", profile, self.protocol)
            self.assertEqual(result["termination_state"], state, result)
            self.assertFalse(result["included"])
            self.assertIsNone(result["bug_detected"])

    def test_observed_runtime_profile_and_matrix_corruption_cannot_be_accepted(self):
        run, profile = self.make_run("profile")
        runtime = {"benchmark": profile["benchmark"], "threads": 4, "kps": [2, 2, 2, 1],
                   "matrix_width": 2, "binary_sha256": profile["binary"]["sha256"],
                   "config_sha256": profile["config"]["sha256"]}
        self.assertTrue(EVIDENCE.analyze_formal(run, "serial", profile, self.protocol, runtime)["included"])
        (run / "run-context.json").write_text(json.dumps({"benchmark": profile["benchmark"], "mode": "serial",
                                                         "phase": "formal", "protocol_sha256": "f" * 64}))
        self.assertFalse(EVIDENCE.analyze_formal(run, "serial", profile, self.protocol)["included"])
        self.assertTrue(EVIDENCE.analyze_formal(run, "serial", profile, self.protocol, runtime)["included"])
        protocol_path = self.root / "frozen-protocol.json"
        protocol_path.write_text(json.dumps(self.protocol))
        self.assertFalse(EVIDENCE.analyze_formal(run, "serial", profile, protocol_path, runtime)["included"])
        (run / "run-context.json").unlink()
        bad = copy.deepcopy(runtime)
        bad["kps"] = [2, 2, 1]
        self.assertFalse(EVIDENCE.analyze_formal(run, "serial", profile, self.protocol, bad)["included"])
        path = run / "actual-yield.jsonl"
        records = [json.loads(line) for line in path.read_text().splitlines()]
        records[1]["yield_pattern"][0][0] += 1
        path.write_text("\n".join(json.dumps(value) for value in records))
        self.assertFalse(EVIDENCE.analyze_formal(run, "serial", profile, self.protocol)["included"])

    def test_parallel_reference_regression_uses_actual_values_not_historical_counts(self):
        reference, profile = self.make_run("A1", n=5, mode="reference")
        candidate, _ = self.make_run("B", n=5, mode="parallel")
        result = EVIDENCE.compare_formal(reference, candidate, profile, self.protocol)
        self.assertEqual(result["status"], "PASS", result)
        path = candidate / "stdout.log"
        path.write_text(path.read_text().replace("[Error Found]: NO.1 assertion failed", ""))
        self.assertEqual(EVIDENCE.compare_formal(reference, candidate, profile, self.protocol)["status"], "BLOCKED")

    def test_dynamic_schedule_legality_and_prefix_are_checked_without_permutation_oracle(self):
        kps = [2, 2, 2, 1]
        schedule = [[0], [1, 1], [0], [2, 2], [3]]
        EVIDENCE.valid_formal_schedule(schedule, "serial", kps, prefix=[[0], [1]])
        with self.assertRaises(ValueError):
            EVIDENCE.valid_formal_schedule(schedule, "serial", kps, prefix=[[1]])
        with self.assertRaises(ValueError):
            EVIDENCE.valid_formal_schedule([[0, 1], [0], [1], [2, 2], [3]], "serial", kps)
        with self.assertRaisesRegex(ValueError, "more than one controlled thread"):
            EVIDENCE.valid_formal_schedule([[0], [1], [2], [0, 1, 3]], "parallel", [2, 2, 1, 1])

    def test_extra_physical_target_launch_and_failed_cli_cannot_report_pass(self):
        run, profile = self.make_run("ledger")
        self.update_metadata(run, lambda metadata: metadata["process_launches_including_preparation"].append(
            {"executed_argv": ["./reorder_4_bad"]}))
        result = EVIDENCE.analyze_formal(run, "serial", profile, self.protocol)
        self.assertFalse(result["included"])
        manifest_path, protocol_path = self.root / "benchmark.json", self.root / "protocol.json"
        manifest_path.write_text(json.dumps(profile))
        protocol_path.write_text(json.dumps(self.protocol))
        output = self.root / "failed-analysis.json"
        with contextlib.redirect_stdout(io.StringIO()):
            code = EVIDENCE.main(["formal-analyze", "--run-dir", str(run), "--mode", "serial",
                                  "--benchmark-manifest", str(manifest_path), "--protocol", str(protocol_path),
                                  "--output", str(output)])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.read_text())["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
