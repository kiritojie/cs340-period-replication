"""Recovery acceptance regressions; never call Podman or execute a target."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
previous = list(sys.path)
sys.path.insert(0, str(ROOT / "orchestration"))
try:
    import rq1_recover_export as RECOVERY
finally:
    sys.path[:] = previous


class ExportRecoveryTests(unittest.TestCase):
    def test_actual_record_identifies_transport_timeout_not_experiment_failure(self):
        batch = ROOT / "docs/results/table2-rq1-batch-20261124T164754Z-zphvi2gi"
        if not batch.is_dir():
            self.skipTest("original user evidence is not present in this checkout")
        metadata = ROOT / "docs/results/table2-rq1-session-20261124T162432Z-f2xe6bx0/session.json"
        before = RECOVERY.digest(metadata)
        with mock.patch.object(RECOVERY.host, "Commands") as commands:
            diagnosis = RECOVERY.inspect_failure(ROOT, batch)
        commands.assert_not_called()
        self.assertEqual(diagnosis["native_root"], "/tmp/cs340-rq1-17a41a9cb8fd4518aa3ca616bc37246e")
        self.assertTrue(diagnosis["native_source"].endswith("/batch-formal-20261124T170619Z-dexbvcg_"))
        self.assertTrue(diagnosis["historical_after_state"]["benchmarks"]["reorder_5_bad"]["formal_complete"])
        self.assertGreater(diagnosis["export_timeout_seconds"], 60)
        self.assertEqual(RECOVERY.digest(metadata), before)

    def test_selected_outer_diagnostic_requires_its_original_hash(self):
        with tempfile.TemporaryDirectory(prefix="rq1-recovery-proof-", dir=str(ROOT)) as temporary:
            folder = Path(temporary)
            target = folder / "guard.stdout.log"
            target.write_text("original proof\n")
            (folder / "SHA256SUMS").write_text(RECOVERY.digest(target) + "  guard.stdout.log\n")
            self.assertEqual(RECOVERY.checked_diagnostic(folder, target.name), RECOVERY.digest(target))
            target.write_text("changed proof\n")
            with self.assertRaisesRegex(ValueError, "diagnostic was changed"):
                RECOVERY.checked_diagnostic(folder, target.name)

    def test_incomplete_native_source_is_rejected_without_export_or_launch(self):
        commands = mock.Mock()
        commands.run.return_value = ({"exit_code": 0}, json.dumps({
            "phase_result": {"status": "BLOCKED", "phase": "formal", "benchmark": "reorder_5_bad"},
            "state_after": {}}).encode("utf-8"), b"")
        with self.assertRaisesRegex(ValueError, "not a complete accepted"):
            RECOVERY._inventory(commands, "container", "/tmp/source", "/tmp/helper.py", "inventory")
        self.assertEqual(commands.run.call_count, 1)
        self.assertEqual(commands.run.call_args[0][1][:2], ["podman", "exec"])

    def test_native_input_reference_cannot_escape_the_original_evidence_root(self):
        root = "/tmp/cs340-rq1-" + "a" * 32
        self.assertEqual(RECOVERY._native_stage(root, root + "/evidence/build/benchmark-manifest.json"), "build")
        for path in (root + "/other/build/proof.json", root + "/evidence/../old/proof.json"):
            with self.assertRaises(ValueError):
                RECOVERY._native_stage(root, path)

    def test_original_native_layout_has_after_environment_per_round_only(self):
        session = ROOT / "docs/results/table2-rq1-session-20261124T162432Z-f2xe6bx0"
        phase = session / "batch-formal-20261124T165114Z-rgf4h0aw/native-evidence"
        if not phase.is_dir():
            self.skipTest("original completed phase is not present in this checkout")
        self.assertFalse((phase / "environment-after.json").exists())
        protocol = json.loads((session / "protocol.json").read_text())
        RECOVERY._round_guards(phase / "formal-01-parallel", protocol)


if __name__ == "__main__":
    unittest.main()
