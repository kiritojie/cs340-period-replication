"""Focused classification and receipt regressions; never call Podman."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
before_path = list(sys.path)
sys.path.insert(0, str(ROOT / "orchestration"))
try:
    import rq1_phase as PHASE
finally:
    sys.path[:] = before_path


class PhaseClassificationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rq1-outer-test-", dir=str(ROOT))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def analysis(self, state):
        run = self.root / "formal-01-parallel"
        run.mkdir()
        (run / "analysis.json").write_text(json.dumps({
            "included": False, "termination_state": state}))

    def test_infrastructure_cannot_be_mistaken_for_local_timeout(self):
        self.analysis("INFRASTRUCTURE_FAILURE")
        result = {"status": "BLOCKED", "phase_excluded": False,
                  "error": "ValueError: invalid formal round retained; phase stopped: run"}
        self.assertEqual(PHASE.classify_native(result, self.root), "global")

    def test_timeout_is_local_only_for_expected_phase_failure(self):
        self.analysis("TARGET_TIMEOUT")
        result = {"status": "BLOCKED", "error": "ValueError: adaptation failed: run"}
        self.assertEqual(PHASE.classify_native(result, self.root), "benchmark")
        result["error"] = "ValueError: unexpected identity failure"
        self.assertEqual(PHASE.classify_native(result, self.root), "global")
        result["error"] = "ValueError: adaptation failed: run"
        result["phase_excluded"] = True
        self.assertEqual(PHASE.classify_native(result, self.root), "global")

    def test_regression_difference_requires_preserved_explicit_fail(self):
        result = {"status": "BLOCKED", "error": "ValueError: A1/B adaptation regression differs"}
        self.assertEqual(PHASE.classify_native(result, self.root), "global")
        (self.root / "A1B-regression.json").write_text(json.dumps({
            "status": "BLOCKED", "reference": {"included": True}, "candidate": {"included": True},
            "reason": "A1/B mismatch in error_ordinals"}))
        self.assertEqual(PHASE.classify_native(result, self.root), "benchmark")
        (self.root / "A1B-regression.json").write_text(json.dumps({
            "status": "BLOCKED", "reference": {"included": True}, "candidate": {"included": True},
            "reason": "A1/B mismatch in abi_layer_sha256"}))
        self.assertEqual(PHASE.classify_native(result, self.root), "global")

    def test_driver_exception_and_unknown_status_fail_globally(self):
        self.analysis("DRIVER_EXCEPTION")
        self.assertEqual(PHASE.classify_native({"status": "BLOCKED",
            "error": "ValueError: invalid formal round retained; phase stopped: run"}, self.root), "global")
        self.assertEqual(PHASE.classify_native({"status": "UNKNOWN"}, self.root), "global")

    def test_failing_pre_guard_never_invokes_native_and_is_sealed(self):
        session = self.root / "session"
        session.mkdir()
        with mock.patch.object(PHASE, "verify_tree"), mock.patch.object(
                PHASE, "global_guard", side_effect=ValueError("container restarted")), mock.patch.object(
                PHASE.host, "Commands") as commands:
            result = PHASE.run_phase(ROOT, session, "reorder3")
        commands.return_value.run.assert_not_called()
        self.assertEqual(result["failure_scope"], "global")
        self.assertIn("container restarted", result["reason"])
        receipt = Path(result["evidence"])
        self.assertTrue((receipt / "SHA256SUMS").is_file())
        self.assertEqual(json.loads((receipt / "stage-result.json").read_text())["reason"], result["reason"])

    def exercise_failed_phase(self, termination, post_error=None):
        session = self.root / "session"
        session.mkdir()
        (session / "protocol.json").write_text("{}")
        old = session / "prepare"
        old.mkdir()
        (old / "proof.json").write_text("{}")
        PHASE.seal_tree(old)
        state = {"benchmarks": {"reorder_3_bad": {"formal_attempted": True}}}
        guard = {"container_id": "container", "container_root": "/tmp/cs340-rq1-" + "a" * 32,
                 "state": state, "runtime_identity": {"pid": 1}, "launch_configuration": {"Image": "frozen"}}
        native_result = {"phase": "reorder3", "benchmark": None, "status": "BLOCKED", "phase_excluded": False,
                         "error": "ValueError: invalid formal round retained; phase stopped: run"}

        class SyntheticCommands:
            def __init__(unused, output):
                unused.output = Path(output)

            def run(unused, label, argv, **kwargs):
                if label == "export-native-evidence":
                    native = Path(argv[-1])
                    native.mkdir()
                    (native / "phase-result.json").write_text(json.dumps(native_result))
                    (native / "state-after.json").write_text(json.dumps(state))
                    passed = native / "formal-01-parallel"
                    passed.mkdir()
                    (passed / "analysis.json").write_text('{"included":true,"termination_state":"COMPLETED"}')
                    failed = native / "formal-01-serial"
                    failed.mkdir()
                    (failed / "analysis.json").write_text(json.dumps({"included": False, "termination_state": termination}))
                    PHASE.seal_tree(passed)
                    PHASE.seal_tree(failed)
                    PHASE.seal_tree(native)
                return {"exit_code": 2 if label == "native-phase" else 0}, b"", b""

        responses = [guard, post_error if post_error else guard]
        with mock.patch.object(PHASE, "global_guard", side_effect=responses), mock.patch.object(
                PHASE.host, "Commands", SyntheticCommands), mock.patch.object(PHASE.host, "phase_timeout", return_value=1):
            result = PHASE.run_phase(ROOT, session, "reorder3")
        PHASE.verify_tree(session)
        return result

    def test_local_timeout_keeps_earlier_round_and_phase_inclusion(self):
        result = self.exercise_failed_phase("TARGET_TIMEOUT")
        self.assertEqual(result["failure_scope"], "benchmark")
        self.assertFalse(result["phase_excluded"])
        self.assertIn("invalid formal round", result["reason"])

    def test_native_infrastructure_stops_without_discarding_prior_valid_round(self):
        result = self.exercise_failed_phase("INFRASTRUCTURE_FAILURE")
        self.assertEqual(result["failure_scope"], "global")
        self.assertFalse(result["phase_excluded"])

    def test_post_environment_failure_is_global_and_preserves_original_reason(self):
        result = self.exercise_failed_phase("TARGET_TIMEOUT", ValueError("container restarted"))
        self.assertEqual(result["failure_scope"], "global")
        self.assertTrue(result["phase_excluded"])
        self.assertIn("invalid formal round", result["reason"])
        self.assertIn("container restarted", result["post_guard_error"])
        self.assertIn("ValueError: container restarted", result["post_guard_traceback"])

    def test_export_timeout_retains_completed_checkpoint_without_false_drift(self):
        session = self.root / "session"
        session.mkdir()
        (session / "protocol.json").write_text("{}")
        prepared = session / "prepare"
        prepared.mkdir()
        (prepared / "proof.json").write_text("{}")
        PHASE.seal_tree(prepared)
        before_state = {"benchmarks": {"reorder_5_bad": {"adaptation": {"status": "PASS"}}}}
        after_state = {"benchmarks": {"reorder_5_bad": {
            "adaptation": {"status": "PASS"}, "formal_attempted": True, "formal_complete": True}}}
        before = {"container_id": "container", "container_root": "/tmp/cs340-rq1-" + "a" * 32,
                  "state": before_state, "runtime_identity": {"pid": 1},
                  "launch_configuration": {"Image": "frozen"}}
        after = dict(before, state=after_state)
        calls = []

        class SyntheticCommands:
            def __init__(unused, output):
                unused.output = Path(output)

            def run(unused, label, argv, **kwargs):
                calls.append((label, kwargs))
                if label == "export-native-evidence":
                    raise ValueError("export-native-evidence failed; command timed out")
                return {"exit_code": 0}, b"", b""

        with mock.patch.object(PHASE, "global_guard", side_effect=[before, after]) as guard, \
                mock.patch.object(PHASE.host, "Commands", SyntheticCommands), \
                mock.patch.object(PHASE.host, "phase_timeout", return_value=1):
            result = PHASE.run_phase(ROOT, session, "formal", "reorder_5_bad")
        self.assertEqual(guard.call_count, 2)
        self.assertEqual(result["native_exit_code"], 0)
        self.assertEqual(result["failure_scope"], "global")
        self.assertTrue(result["phase_excluded"])
        self.assertIn("export-native-evidence failed", result["export_error"])
        self.assertEqual(result["reason"], result["export_error"])
        self.assertNotIn("post_guard_error", result)
        self.assertEqual(result["state"], after_state)
        exported = [kwargs for label, kwargs in calls if label == "export-native-evidence"]
        self.assertEqual(exported, [{"timeout": 1800}])
        PHASE.verify_tree(session)

    def test_guard_isolates_and_exports_each_permission_probe_directory(self):
        session = self.root / "session"
        session.mkdir()
        native_root = "/tmp/cs340-rq1-" + "a" * 32
        (session / "session.json").write_text(json.dumps({
            "container_root": native_root, "harness_hashes": {}, "input_hashes": {}}))
        (session / "protocol.json").write_text('{"expected_cpus":[0]}')
        commands = mock.Mock(output=self.root)
        calls = []

        def response(label, argv, **kwargs):
            calls.append((label, argv))
            raw = {"cpus": [0]} if label.endswith("-live") else {"state": {}} if label.endswith("-native-guard") else {}
            return {"exit_code": 0}, json.dumps(raw).encode("utf-8"), b""

        commands.run.side_effect = response
        names = ("verify_frozen_pilot", "one_inspect", "validate_container", "validate_security_configuration",
                 "validate_session", "validate_live", "runtime_identity", "launch_configuration")
        patches = [mock.patch.object(PHASE.host, name, return_value="container" if name == "validate_container" else {})
                   for name in names]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        PHASE.global_guard(ROOT, session, commands, "before")
        PHASE.global_guard(ROOT, session, commands, "after")
        directories = [argv[-1] for label, argv in calls if label.endswith("-fresh-proof-directory")]
        self.assertEqual(len(set(directories)), 2)
        for label, argv in calls:
            if label.endswith("-real-permissions"):
                self.assertIn(str(Path(argv[-1]).parent).replace("\\", "/"), directories)
            if label.endswith("-export-permissions"):
                self.assertIn(argv[-2].split(":", 1)[1], directories)

        def failed_probe_response(label, argv, **kwargs):
            info, stdout, stderr = response(label, argv, **kwargs)
            if label.endswith("-real-permissions"):
                info["exit_code"] = 2
            return info, stdout, stderr

        commands.run.side_effect = failed_probe_response
        with self.assertRaisesRegex(ValueError, "fresh real permission acceptance failed"):
            PHASE.global_guard(ROOT, session, commands, "failed")
        self.assertEqual(calls[-1][0], "failed-export-permissions")


if __name__ == "__main__":
    unittest.main()
