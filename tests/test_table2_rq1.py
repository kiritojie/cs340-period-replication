"""Focused protocol/phase regressions; never run Podman or a benchmark."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


before = list(sys.path)
sys.path.insert(0, str(ROOT / "scripts"))
try:
    HOST = load("rq1_host_under_test", "table2_rq1.py")
    try:
        import fcntl
        NATIVE = load("rq1_native_under_test", "table2_rq1_native.py")
    except ImportError:
        with mock.patch.dict(sys.modules, {"fcntl": types.ModuleType("fcntl")}):
            NATIVE = load("rq1_native_under_test", "table2_rq1_native.py")
finally:
    sys.path[:] = before


class ProtocolAndPhaseTests(unittest.TestCase):
    def setUp(self):
        previous = list(sys.path)
        sys.path.insert(0, str(ROOT / "scripts"))
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), previous))
        self.temp = tempfile.TemporaryDirectory(prefix="rq1-synthetic-", dir=str(ROOT))
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        protocol = ROOT / "config/table2-rq1-protocol.json"
        if not protocol.is_file():
            protocol = ROOT / "protocol.json"  # exact frozen bytes in the staged container
        self.protocol = json.loads(protocol.read_text())

    def test_host_watchdog_covers_all_six_round_limits(self):
        self.assertGreater(HOST.phase_timeout("formal", self.protocol), 6 * (3600 + 20))
        self.assertGreater(HOST.phase_timeout("adapt", self.protocol), 3 * (3600 + 20))
        self.assertEqual(HOST.phase_timeout("prepare", self.protocol), 600)

    def test_frozen_timeout_and_cpu_policy_cannot_silently_change(self):
        NATIVE.validate_protocol(self.protocol)
        for key, value in (("round_timeout_seconds", 600), ("expected_cpus", list(range(8))),
                           ("schedule_budget", 9999), ("minimum_rounds", 10)):
            altered = copy.deepcopy(self.protocol)
            altered[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                NATIVE.validate_protocol(altered)

    def test_runtime_profile_uses_observed_four_thread_counts(self):
        (self.base / "stdout.log").write_text("ThreadNum: 4\nMaxKpNum: 2\nkpNumArray: 2 2 2 1 \n")
        manifest = {"benchmark": "reorder_4_bad", "threads": 4, "binary": {"sha256": "binary"},
                    "config": {"sha256": "config"}}
        profile = NATIVE.observed_profile(self.base, manifest)
        self.assertEqual(profile["kps"], [2, 2, 2, 1])
        self.assertEqual(profile["matrix_width"], 2)
        manifest["threads"] = 3
        with self.assertRaisesRegex(ValueError, "runtime dimensions"):
            NATIVE.observed_profile(self.base, manifest)

    def state(self):
        return {"root": str(self.base), "benchmarks": {"reorder_3_bad": {
            "manifest": "unused", "adaptation": {"status": "PASS"}, "runtime_profile": {"threads": 3}}}}

    def test_formal_attempt_is_checkpointed_before_first_launch_and_not_retried(self):
        state = self.state()
        attempts = []
        def run(*args):
            persisted = json.loads((self.base / "state.json").read_text())
            self.assertTrue(persisted["benchmarks"]["reorder_3_bad"]["formal_attempted"])
            attempts.append((args[2], args[3], args[4]))
            return self.base, {"included": True}
        args = types.SimpleNamespace(phase="reorder3", benchmark=None)
        with mock.patch.object(NATIVE, "run_one", side_effect=run):
            result = NATIVE.execute_phase(self.base, args, state, self.protocol, "proof")
        self.assertEqual(result, "FORMAL_BENCHMARK_PASSED")
        self.assertEqual(attempts, [(mode, "formal", n) for n in (1, 2, 3) for mode in ("parallel", "serial")])
        with mock.patch.object(NATIVE, "run_one") as launch:
            with self.assertRaises(ValueError):
                NATIVE.execute_phase(self.base, args, state, self.protocol, "proof")
        launch.assert_not_called()

    def test_invalid_round_stops_phase_without_filling_missing_rounds(self):
        state = self.state()
        with mock.patch.object(NATIVE, "run_one", return_value=(self.base, {"included": False})) as launch:
            with self.assertRaisesRegex(ValueError, "invalid formal round"):
                NATIVE.execute_phase(self.base, types.SimpleNamespace(phase="reorder3", benchmark=None),
                                     state, self.protocol, "proof")
        self.assertEqual(launch.call_count, 1)
        self.assertTrue(state["benchmarks"]["reorder_3_bad"]["formal_attempted"])
        self.assertNotIn("formal_complete", state["benchmarks"]["reorder_3_bad"])

    def test_other_program_cannot_adapt_before_reorder3_formal_completion(self):
        with mock.patch.object(NATIVE, "run_one") as launch:
            with self.assertRaisesRegex(ValueError, "six reorder_3"):
                NATIVE.execute_phase(self.base, types.SimpleNamespace(phase="adapt", benchmark="reorder_4_bad"),
                                     self.state(), self.protocol, "proof")
        launch.assert_not_called()

    def test_late_gate_rollback_revokes_completions_but_preserves_attempt(self):
        original = self.state()
        mutated = copy.deepcopy(original)
        item = mutated["benchmarks"]["reorder_3_bad"]
        item.update(formal_attempted=True, formal_complete=True)
        mutated["reorder3_formal_complete"] = True
        NATIVE.rollback_promotions(mutated, original)
        self.assertTrue(item["formal_attempted"])
        self.assertNotIn("formal_complete", item)
        self.assertNotIn("reorder3_formal_complete", mutated)
        self.assertEqual(item["adaptation"], {"status": "PASS"})

    def test_halted_host_session_blocks_any_later_phase(self):
        (self.base / "HALTED.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "halted"):
            HOST.validate_session({}, {}, ROOT, self.base)


if __name__ == "__main__":
    unittest.main()
