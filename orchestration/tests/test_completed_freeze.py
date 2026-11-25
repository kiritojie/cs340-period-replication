"""Completed-round scope and integrity checks; no native or target execution."""
import csv
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
    import rq1_completed_freeze as FREEZE
finally:
    sys.path[:] = _previous


class CompletedFreezeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rq1-twelve-synthetic-", dir=str(ROOT))
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.session = self.repo / "docs/results/session"
        self.batch = self.repo / "docs/results/source-batch"
        self.batch.mkdir(parents=True)
        self.session.mkdir(parents=True)
        (self.batch / "source.json").write_text('{"synthetic":true}')
        FREEZE.seal_tree(self.batch)
        protocol = {"minimum_rounds": 3, "schedule_budget": 10000, "bug_depth": 3,
                    "source_commit": "synthetic-pinned-source"}
        (self.session / "protocol.json").write_text(json.dumps(protocol))
        original = {"protocol_sha256": FREEZE.digest(self.session / "protocol.json"),
                    "container_id": "synthetic-container", "runtime_identity": {"pid": 1},
                    "launch_configuration": {}, "harness_hashes": {}}
        (self.session / "session.json").write_text(json.dumps(original))
        self.phase = self.session / "accepted-phase"
        records = []
        for name in FREEZE.BENCHMARKS:
            for mode in ("parallel", "serial"):
                for number in (1, 2, 3):
                    run = self.phase / name / ("formal-%02d-%s" % (number, mode))
                    run.mkdir(parents=True)
                    (run / "run-context.json").write_text('{"synthetic":true}')
                    (run / "analysis.json").write_text('{"synthetic":true}')
                    records.append({"run_dir": str(run), "benchmark": name, "mode": mode,
                                    "round": number, "included": True, "first_error": 1,
                                    "total_schedules": 2, "completed_schedules": 2, "physical_launches": 2,
                                    "error_interleavings": 1, "timeouts": 0, "internal_seconds": 0.1,
                                    "external_seconds": 0.2, "exit_code": 0, "termination_state": "COMPLETED",
                                    "context_sha256": FREEZE.digest(run / "run-context.json"),
                                    "analysis_sha256": FREEZE.digest(run / "analysis.json")})
        FREEZE.seal_tree(self.phase)
        self.audited = {"session": self.session, "session_record": original, "protocol": protocol,
                        "protocol_sha256": original["protocol_sha256"], "records": records,
                        "groups": [{"benchmark": "synthetic", "valid": 12}],
                        "roots": [self.batch, self.phase], "raw_verification": {}}
        self.output = self.repo / "docs/frozen/synthetic-twelve"

    def test_failed_export_is_preserved_outside_accepted_freeze_scope(self):
        failed = self.session / "failed-export/native-evidence"
        failed.mkdir(parents=True)
        (failed / "SHA256SUMS").write_text("0" * 64 + "  missing-raw.log\n")
        with mock.patch.object(FREEZE, "audit_completed", return_value=self.audited):
            record = FREEZE.freeze_completed(self.repo, self.batch, self.output)
            original = (self.output / "FREEZE.json").read_bytes()
            self.assertEqual(record["formal_rounds"], 12)
            self.assertEqual(record["session"], "docs/results/session")
            self.assertFalse(any("failed-export" in name for name in record["trusted_file_digests"]))
            (failed / "new-partial.log").write_text("still not accepted")
            self.assertEqual(FREEZE.verify_completed_freeze(self.repo, self.output / "FREEZE.json")["formal_rounds"], 12)
            self.assertEqual(FREEZE.freeze_completed(self.repo, self.batch, self.output)["formal_rounds"], 12)
            self.assertEqual((self.output / "FREEZE.json").read_bytes(), original)
        self.assertTrue((failed / "SHA256SUMS").is_file())

    def test_changed_accepted_round_is_rejected(self):
        with mock.patch.object(FREEZE, "audit_completed", return_value=self.audited):
            FREEZE.freeze_completed(self.repo, self.batch, self.output)
            path = Path(self.audited["records"][0]["run_dir"]) / "analysis.json"
            path.write_text("changed accepted data")
            with self.assertRaisesRegex(ValueError, "frozen accepted evidence changed"):
                FREEZE.verify_completed_freeze(self.repo, self.output / "FREEZE.json")

    def test_duplicate_source_round_cannot_enter_completed_freeze(self):
        stats = self.batch / "statistics"
        stats.mkdir()
        (stats / "summary.json").write_text('{"valid_formal_rounds":12}')
        (self.batch / "batch-result.json").write_text(json.dumps({
            "session": str(self.session), "valid_formal_rounds": 12}))
        rows = [{"benchmark": row["benchmark"], "mode": row["mode"], "round": row["round"],
                 "included": "True", "run_dir": row["run_dir"]} for row in self.audited["records"]]
        rows[-1]["round"] = 2
        with (stats / "per-round.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        with self.assertRaisesRegex(ValueError, "exactly twelve"):
            FREEZE.audit_completed(self.repo, self.batch)


if __name__ == "__main__":
    unittest.main()
