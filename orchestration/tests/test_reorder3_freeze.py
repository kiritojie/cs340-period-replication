"""Frozen-evidence integrity regressions; no target or native calls are run."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
_previous = list(sys.path)
sys.path.insert(0, str(ROOT / "orchestration"))
try:
    import rq1_reorder3_freeze as FREEZE
finally:
    sys.path[:] = _previous


class FormalFreezeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rq1-freeze-synthetic-", dir=str(ROOT))
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.batch = self.repo / "docs/results/batch"
        self.session = self.repo / "docs/results/session"
        (self.batch / "statistics").mkdir(parents=True)
        (self.batch / "statistics/summary.json").write_text('{"synthetic":true}')
        FREEZE.seal_tree(self.batch / "statistics")
        (self.session / "prepare").mkdir(parents=True)
        (self.session / "prepare/proof.json").write_text('{"synthetic":true}')
        protocol = {"source_commit": "synthetic-fixed-source", "minimum_rounds": 3,
                    "bug_depth": 3, "schedule_budget": 10000}
        (self.session / "protocol.json").write_text(json.dumps(protocol))
        original = {"protocol_sha256": FREEZE.digest(self.session / "protocol.json"),
                    "container_id": "synthetic-container", "runtime_identity": {"pid": 1},
                    "launch_configuration": {"Image": "synthetic"}, "harness_hashes": {}}
        (self.session / "session.json").write_text(json.dumps(original))
        (self.batch / "batch-result.json").write_text(json.dumps({"session": str(self.session)}))
        records = []
        for mode in ("parallel", "serial"):
            for number in (1, 2, 3):
                run = self.session / "stage/native-evidence" / ("formal-%02d-%s" % (number, mode))
                run.mkdir(parents=True)
                (run / "run-context.json").write_text('{"synthetic":true}')
                (run / "analysis.json").write_text('{"synthetic":true}')
                records.append({"run_dir": str(run), "benchmark": "reorder_3_bad", "mode": mode,
                                "round": number, "included": True, "first_error": None,
                                "total_schedules": 2, "completed_schedules": 2, "physical_launches": 2,
                                "error_interleavings": 0, "timeouts": 0, "internal_seconds": 0.1,
                                "external_seconds": 0.2, "exit_code": 0, "termination_state": "COMPLETED",
                                "context_sha256": FREEZE.digest(run / "run-context.json"),
                                "analysis_sha256": FREEZE.digest(run / "analysis.json")})
        self.audited = {"session": self.session, "session_record": original, "protocol": protocol,
                        "protocol_sha256": original["protocol_sha256"], "records": records,
                        "groups": [], "raw_verification": {"status": "synthetic"}}
        self.output = self.repo / "docs/frozen/synthetic-six"

    def test_freeze_is_portable_repeat_safe_and_does_not_claim_new_rounds(self):
        original_bytes = (self.session / "stage/native-evidence/formal-01-parallel/analysis.json").read_bytes()
        with mock.patch.object(FREEZE, "audit_six", return_value=self.audited):
            record = FREEZE.freeze_reorder3(self.repo, self.batch, self.output)
            frozen_bytes = (self.output / "FREEZE.json").read_bytes()
            self.assertEqual(record["session"], "docs/results/session")
            self.assertEqual(record["formal_rounds"], 6)
            self.assertTrue(all(not Path(row["run_dir"]).is_absolute() for row in record["records"]))
            # Later benchmark data stays separate from the immutable six-round index.
            later = self.session / "later-benchmark"
            later.mkdir()
            (later / "new-data.log").write_text("synthetic future data")
            self.assertEqual(FREEZE.freeze_reorder3(self.repo, self.batch, self.output)["formal_rounds"], 6)
            self.assertEqual((self.output / "FREEZE.json").read_bytes(), frozen_bytes)
        self.assertEqual((self.session / "stage/native-evidence/formal-01-parallel/analysis.json").read_bytes(), original_bytes)

    def test_frozen_raw_file_change_is_rejected(self):
        with mock.patch.object(FREEZE, "audit_six", return_value=self.audited):
            FREEZE.freeze_reorder3(self.repo, self.batch, self.output)
            (self.session / "stage/native-evidence/formal-01-parallel/analysis.json").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "frozen formal evidence changed"):
                FREEZE.verify_reorder3_freeze(self.repo, self.output / "FREEZE.json")

    def test_duplicate_or_missing_round_identity_cannot_be_frozen(self):
        duplicate = [dict(row) for row in self.audited["records"]]
        duplicate[-1]["round"] = 2
        with mock.patch.object(FREEZE, "verify_tree", return_value={"status": "synthetic"}), \
                mock.patch.object(FREEZE, "collect_rounds", return_value=duplicate):
            with self.assertRaisesRegex(ValueError, "exactly the six"):
                FREEZE.audit_six(self.repo, self.batch, self.session)


if __name__ == "__main__":
    unittest.main()
