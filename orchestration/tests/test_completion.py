"""Remaining-cohort sequencing checks; no build, Podman or target execution."""
import copy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
previous_path = list(sys.path)
sys.path.insert(0, str(ROOT / "orchestration"))
try:
    import table2_rq1_batch as BATCH
finally:
    sys.path[:] = previous_path


def cohort():
    plan = {"benchmarks": [
        {"benchmark": name, "status": "READY" if name == "reorder_3_bad" else "BLOCKED_PREPARATION",
         "planned_formal_rounds": 6, "missing_artifacts": []}
        for name in BATCH.host.BENCHMARKS]}
    state = {"reorder3_formal_complete": True, "benchmarks": {
        name: ({"formal_complete": True} if name == "reorder_3_bad" else {"status": "BLOCKED"})
        for name in BATCH.host.BENCHMARKS}}
    return plan, state


class RemainingCohortTests(unittest.TestCase):
    def runner(self, state, failure=None):
        calls = []

        def run(phase, name):
            self.assertNotEqual(name, "reorder_3_bad")
            calls.append((phase, name))
            if failure and (phase, name) == failure[:2]:
                return {"failure_scope": failure[2], "reason": "preserved synthetic failure",
                        "evidence": "synthetic-only", "state": copy.deepcopy(state)}
            item = state["benchmarks"][name]
            if phase == "build":
                item.update(build_attempted=True, manifest="measured-manifest", abi_proof="measured-proof")
            elif phase == "adapt":
                item["adaptation"] = {"status": "PASS"}
            elif phase == "formal":
                item["formal_complete"] = True
            else:
                self.fail("unexpected remaining-cohort phase: " + phase)
            return {"failure_scope": "none", "state": copy.deepcopy(state), "evidence": "synthetic-only"}

        return run, calls

    def test_only_remaining_three_programs_build_adapt_then_formal(self):
        plan, state = cohort()
        frozen_three = copy.deepcopy(state["benchmarks"]["reorder_3_bad"])
        runner, calls = self.runner(state)
        result = BATCH.execute_remaining(plan, state, runner)
        self.assertEqual(calls, [(phase, name) for name in BATCH.host.BENCHMARKS[1:]
                                 for phase in ("build", "adapt", "formal")])
        self.assertEqual(result["benchmarks"][0]["status"], "REUSED_FROZEN_SIX")
        self.assertEqual(state["benchmarks"]["reorder_3_bad"], frozen_three)
        self.assertTrue(all(item["status"] == "FORMAL_COMPLETE" for item in result["benchmarks"][1:]))
        self.assertIsNone(result["global_failure"])

    def test_local_build_failure_retains_reason_and_continues_other_programs(self):
        plan, state = cohort()
        runner, calls = self.runner(state, ("build", "reorder_4_bad", "benchmark"))
        result = BATCH.execute_remaining(plan, state, runner)
        self.assertNotIn(("adapt", "reorder_4_bad"), calls)
        self.assertNotIn(("formal", "reorder_4_bad"), calls)
        self.assertIn(("formal", "reorder_5_bad"), calls)
        self.assertIn(("formal", "reorder_10_bad"), calls)
        self.assertEqual(result["benchmarks"][1]["status"], "BENCHMARK_FAILED")
        self.assertEqual(result["benchmarks"][1]["reason"], "preserved synthetic failure")
        self.assertIsNone(result["global_failure"])

    def test_global_failure_stops_later_execution_and_keeps_completed_programs(self):
        plan, state = cohort()
        runner, calls = self.runner(state, ("adapt", "reorder_5_bad", "global"))
        result = BATCH.execute_remaining(plan, state, runner)
        self.assertFalse(any(name == "reorder_10_bad" for phase, name in calls))
        self.assertEqual(result["benchmarks"][0]["status"], "REUSED_FROZEN_SIX")
        self.assertEqual(result["benchmarks"][1]["status"], "FORMAL_COMPLETE")
        self.assertEqual(result["benchmarks"][2]["status"], "GLOBAL_FAILURE")
        self.assertEqual(result["benchmarks"][3]["status"], "NOT_RUN_GLOBAL_STOP")

    def test_previous_build_or_formal_attempt_is_not_replaced(self):
        plan, state = cohort()
        state["benchmarks"]["reorder_4_bad"]["formal_attempted"] = True
        state["benchmarks"]["reorder_5_bad"]["build_attempted"] = True
        state["benchmarks"]["reorder_10_bad"].update(
            manifest="accepted", abi_proof="accepted", adaptation={"status": "PASS"})
        runner, calls = self.runner(state)
        result = BATCH.execute_remaining(plan, state, runner)
        self.assertEqual(calls, [("formal", "reorder_10_bad")])
        self.assertEqual(result["benchmarks"][1]["status"], "BLOCKED_PREVIOUS_ATTEMPT")
        self.assertEqual(result["benchmarks"][2]["status"], "BLOCKED_PREVIOUS_BUILD")

    def test_no_remaining_phase_without_completed_reorder3_checkpoint(self):
        plan, state = cohort()
        state["reorder3_formal_complete"] = False
        runner, calls = self.runner(state)
        with self.assertRaisesRegex(ValueError, "six completed"):
            BATCH.execute_remaining(plan, state, runner)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
