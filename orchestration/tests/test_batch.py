"""Focused outer sequencing tests; external phases never run in these checks."""
import copy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
previous_path = list(sys.path)
sys.path.insert(0, str(ROOT / "orchestration"))
try:
    import table2_rq1_batch as BATCH
finally:
    sys.path[:] = previous_path


def prepared_plan(blocked=()):
    return {"planned_formal_rounds": 24, "rounds_per_mode": 3,
            "benchmarks": [{"benchmark": benchmark, "planned_formal_rounds": 6,
                            "status": "BLOCKED_PREPARATION" if benchmark in blocked else "READY",
                            "reason": "missing existing binary/config" if benchmark in blocked else None,
                            "missing_artifacts": [benchmark] if benchmark in blocked else []}
                           for benchmark in BATCH.host.BENCHMARKS]}


def prepared_state():
    return {"benchmarks": {benchmark: ({"adaptation": {"status": "PASS"}}
                                     if benchmark == "reorder_3_bad" else {})
                           for benchmark in BATCH.host.BENCHMARKS}}


class BatchSequenceTests(unittest.TestCase):
    def phase_runner(self, state, failure=None):
        calls = []

        def run(phase, benchmark):
            calls.append((phase, benchmark))
            name = benchmark or "reorder_3_bad"
            if failure and (phase, benchmark) == failure[:2]:
                return {"failure_scope": failure[2], "reason": "synthetic phase failure",
                        "evidence": "synthetic-evidence", "state": copy.deepcopy(state)}
            if phase == "adapt":
                state["benchmarks"][name]["adaptation"] = {"status": "PASS"}
            else:
                state["benchmarks"][name]["formal_complete"] = True
                if phase == "reorder3":
                    state["reorder3_formal_complete"] = True
            return {"failure_scope": "none", "state": copy.deepcopy(state)}

        return run, calls

    def test_all_ready_benchmarks_use_exact_minimum_phase_sequence(self):
        state = prepared_state()
        runner, calls = self.phase_runner(state)
        execution = BATCH.execute_plan(prepared_plan(), state, runner)
        self.assertEqual(calls, [
            ("reorder3", None),
            ("adapt", "reorder_4_bad"), ("formal", "reorder_4_bad"),
            ("adapt", "reorder_5_bad"), ("formal", "reorder_5_bad"),
            ("adapt", "reorder_10_bad"), ("formal", "reorder_10_bad")])
        self.assertTrue(all(item["status"] == "FORMAL_COMPLETE"
                            for item in execution["benchmarks"]))
        self.assertIsNone(execution["global_failure"])

    def test_missing_other_benchmarks_are_recorded_without_external_commands(self):
        missing = ("reorder_4_bad", "reorder_5_bad", "reorder_10_bad")
        state = prepared_state()
        runner, calls = self.phase_runner(state)
        execution = BATCH.execute_plan(prepared_plan(missing), state, runner)
        self.assertEqual(calls, [("reorder3", None)])
        self.assertEqual(execution["benchmarks"][0]["status"], "FORMAL_COMPLETE")
        for item in execution["benchmarks"][1:]:
            self.assertEqual(item["status"], "BLOCKED_PREPARATION")
            self.assertEqual(item["reason"], "missing existing binary/config")
            self.assertTrue(item["missing_artifacts"])

    def test_local_adaptation_failure_skips_its_formal_phase_and_continues(self):
        state = prepared_state()
        runner, calls = self.phase_runner(state, ("adapt", "reorder_4_bad", "benchmark"))
        execution = BATCH.execute_plan(prepared_plan(), state, runner)
        self.assertNotIn(("formal", "reorder_4_bad"), calls)
        self.assertIn(("formal", "reorder_5_bad"), calls)
        self.assertIn(("formal", "reorder_10_bad"), calls)
        self.assertEqual(execution["benchmarks"][1]["status"], "BENCHMARK_FAILED")
        self.assertEqual(execution["benchmarks"][2]["status"], "FORMAL_COMPLETE")
        self.assertIsNone(execution["global_failure"])

    def test_global_failure_stops_later_benchmarks_and_retains_completed_status(self):
        state = prepared_state()
        runner, calls = self.phase_runner(state, ("adapt", "reorder_4_bad", "global"))
        execution = BATCH.execute_plan(prepared_plan(), state, runner)
        self.assertEqual(calls, [("reorder3", None), ("adapt", "reorder_4_bad")])
        self.assertEqual(execution["benchmarks"][0]["status"], "FORMAL_COMPLETE")
        self.assertEqual(execution["benchmarks"][1]["status"], "GLOBAL_FAILURE")
        self.assertTrue(all(item["status"] == "NOT_RUN_GLOBAL_STOP"
                            for item in execution["benchmarks"][2:]))
        self.assertEqual(execution["global_failure"], "synthetic phase failure")

    def test_retained_attempt_is_not_retried_and_completed_cohort_is_reused(self):
        state = prepared_state()
        state["reorder3_formal_complete"] = True
        state["benchmarks"]["reorder_3_bad"]["formal_complete"] = True
        state["benchmarks"]["reorder_4_bad"]["formal_attempted"] = True
        runner, calls = self.phase_runner(state)
        execution = BATCH.execute_plan(prepared_plan(), state, runner)
        self.assertEqual(execution["benchmarks"][0]["status"], "REUSED_COMPLETED")
        self.assertEqual(execution["benchmarks"][1]["status"], "BLOCKED_PREVIOUS_ATTEMPT")
        self.assertNotIn(("reorder3", None), calls)
        self.assertFalse(any(benchmark == "reorder_4_bad" for phase, benchmark in calls))
        self.assertIn(("formal", "reorder_5_bad"), calls)

    def test_final_status_requires_exactly_24_accepted_rounds_and_complete_groups(self):
        execution = {"global_failure": None}
        self.assertEqual(BATCH.final_status(
            {"minimum_complete": True, "valid_formal_rounds": 24}, execution, True),
            ("MINIMUM_24_PASSED", 0))
        for summary in (None, {"minimum_complete": False, "valid_formal_rounds": 24},
                        {"minimum_complete": True, "valid_formal_rounds": 6},
                        {"minimum_complete": True, "valid_formal_rounds": 80},
                        {"minimum_complete": True, "valid_formal_rounds": 30}):
            self.assertEqual(BATCH.final_status(summary, execution, True),
                             ("INCOMPLETE_MINIMUM_24", 3))
        complete = {"minimum_complete": True, "valid_formal_rounds": 24}
        self.assertEqual(BATCH.final_status(complete, execution, False), ("BLOCKED_GLOBAL", 2))
        self.assertEqual(BATCH.final_status(complete, {"global_failure": "integrity"}, True),
                         ("BLOCKED_GLOBAL", 2))

    def test_preparation_rejects_expansion_beyond_three_rounds_per_mode(self):
        with tempfile.TemporaryDirectory(prefix="rq1-plan-test-", dir=str(ROOT)) as temporary:
            session = Path(temporary)
            record = {"schema": BATCH.host.SCHEMA, "status": "PREPARED",
                      "harness_hashes": {}, "protocol_sha256": "synthetic-protocol"}
            for rounds, total in ((10, 80), (10, 24), (3, 80)):
                protocol = {"benchmarks": list(BATCH.host.BENCHMARKS),
                            "minimum_rounds": rounds, "initial_total_formal_rounds": total}
                with mock.patch.object(BATCH, "read_json", side_effect=[record, protocol]), \
                        mock.patch.object(BATCH, "harness_hashes", return_value={}), \
                        mock.patch.object(BATCH.host, "verify_frozen_pilot"), \
                        mock.patch.object(BATCH, "digest", return_value="synthetic-protocol"):
                    with self.assertRaisesRegex(ValueError, "minimum 24-round"):
                        BATCH.preparation_plan(session)

    def test_fresh_prepare_uses_printed_session_and_propagates_failure(self):
        with tempfile.TemporaryDirectory(prefix="rq1-fresh-prepare-", dir=str(ROOT)) as temporary:
            repo = Path(temporary)
            session = repo / "docs/results/new-session"
            session.mkdir(parents=True)
            (session / "session.json").write_text(json.dumps({
                "schema": BATCH.host.SCHEMA, "status": "PREPARED_WITH_BLOCKED_BENCHMARKS"}))
            for exit_code in (0, 2):
                with self.subTest(exit_code=exit_code), mock.patch.object(BATCH, "ROOT", repo), \
                        mock.patch.object(BATCH.subprocess, "Popen") as popen, \
                        contextlib.redirect_stdout(io.StringIO()) as captured:
                    process = popen.return_value.__enter__.return_value
                    process.stdout = io.StringIO("Session: %s\nchecking\nSession: %s\n" % (session, session))
                    process.wait.return_value = exit_code
                    result = BATCH.prepare_session()
                self.assertEqual(result, (session.resolve() if exit_code == 0 else None, exit_code))
                self.assertIn("checking", captured.getvalue())
                argv = popen.call_args[0][0]
                self.assertEqual(argv[-3:], ["prepare", "--protocol", str(repo / "config/table2-rq1-protocol.json")])
                self.assertTrue(popen.call_args[1]["universal_newlines"])
        with mock.patch.object(BATCH.sys, "platform", "linux"), \
                mock.patch.object(BATCH.platform, "machine", return_value="x86_64"), \
                mock.patch.object(BATCH.os, "geteuid", return_value=0, create=True), \
                mock.patch.object(BATCH, "prepare_session", return_value=(None, 2)), \
                mock.patch.object(BATCH, "run_batch") as run_batch:
            self.assertEqual(BATCH.main(["--prepare"]), 2)
        run_batch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
