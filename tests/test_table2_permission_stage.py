"""Stage boundaries and cached evidence identity; never run Podman or targets."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
try:
    SPEC = importlib.util.spec_from_file_location("permission_stage_tests", ROOT / "scripts/table2_permission_stage.py")
    STAGE = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(STAGE)
finally:
    sys.path.pop(0)


def record():
    return {"Id": "8661e83e39a4" + "0" * 52, "Name": "period-table2-reorder3",
            "Image": STAGE.validate_container.__globals__["IMAGE"], "Config": {},
            "HostConfig": {"Privileged": False, "CapDrop": ["ALL"],
                           "CapAdd": ["SYS_NICE"], "SecurityOpt": ["no-new-privileges"]},
            "State": {"Pid": 1234, "StartedAt": "2026-11-24T14:56:00Z", "Running": True, "Status": "running"}}


def live():
    return {"uid": 0, "euid": 0, "cpus": [0, 1], "active": [],
            "ipc": "key shmid perms size cpid lpid nattch uid\n"}


class StageEvidenceTests(unittest.TestCase):
    def test_restart_or_harness_change_invalidates_cached_permission_session(self):
        original = record()
        hashes = {"scripts/example.py": "abc"}
        session = {"schema": STAGE.SCHEMA, "status": "PERMISSIONS_PASSED",
                   "container_id": original["Id"], "runtime_identity": STAGE.runtime_identity(original),
                   "launch_configuration": STAGE.launch_configuration(original), "harness_hashes": hashes,
                   "container_root": "/tmp/cs340-permission-stage-" + "a" * 32}
        with mock.patch.object(STAGE, "harness_hashes", return_value=hashes):
            STAGE.validate_session(session, original, ROOT)
            restarted = copy.deepcopy(original)
            restarted["State"]["StartedAt"] = "later"
            with self.assertRaisesRegex(ValueError, "restarted"):
                STAGE.validate_session(session, restarted, ROOT)
        with mock.patch.object(STAGE, "harness_hashes", return_value={"changed": "xyz"}):
            with self.assertRaisesRegex(ValueError, "harness changed"):
                STAGE.validate_session(session, original, ROOT)

    def test_fresh_active_process_affinity_and_ipc_checks_cannot_be_reused(self):
        previous = live()
        for changed in ({**live(), "active": [{"pid": 42}]}, {**live(), "cpus": [0]},
                        {**live(), "ipc": "key size nattch\n1111 24008 1\n"}):
            with self.assertRaises(ValueError):
                STAGE.validate_live(changed, previous)

    def run_permissions(self, failure_label=None):
        temporary = tempfile.TemporaryDirectory(prefix="period-stage-synthetic-")
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name) / "evidence"
        output.mkdir()
        labels = []
        hashes = {"scripts/example.py": "abc"}

        class FakeCommands:
            def __init__(self, path):
                pass

            def run(self, label, argv, **kwargs):
                labels.append((label, argv))
                if label == failure_label:
                    raise RuntimeError("synthetic after-stage failure")
                raw = b""
                if label.startswith("inspect-"):
                    raw = json.dumps([record()]).encode("utf-8")
                elif label.startswith("live-environment"):
                    raw = json.dumps(live()).encode("utf-8")
                elif label == "verify-copied-harness":
                    raw = json.dumps(hashes).encode("utf-8")
                return {"exit_code": 0}, raw, b""

        with mock.patch.object(STAGE.sys, "platform", "linux"), \
             mock.patch.object(STAGE.platform, "machine", return_value="x86_64"), \
             mock.patch.object(STAGE.os, "geteuid", return_value=0, create=True), \
             mock.patch.object(STAGE.shutil, "which", return_value="/usr/bin/podman"), \
             mock.patch.object(STAGE.shutil, "copytree"), \
             mock.patch.object(STAGE, "harness_hashes", return_value=hashes), \
             mock.patch.object(STAGE.tempfile, "mkdtemp", return_value=str(output)), \
             mock.patch.object(STAGE, "Commands", FakeCommands), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = STAGE.main(["--permissions-only"])
        return code, json.loads((output / "stage-session.json").read_text()), labels

    def test_permission_stage_never_invokes_pilot_or_historical_recovery(self):
        code, session, commands = self.run_permissions()
        self.assertEqual(code, 0)
        self.assertEqual(session["status"], "PERMISSIONS_PASSED")
        self.assertIn("real-permission-acceptance", [name for name, _ in commands])
        self.assertTrue(all("table2_scheduler_pilot.sh" not in " ".join(argv) for _, argv in commands))
        self.assertTrue(all("resume_table2_podman.py" not in " ".join(argv) for _, argv in commands))
        self.assertTrue(all("start" not in argv for _, argv in commands))

    def test_post_acceptance_live_failure_cannot_leave_a_passing_session(self):
        code, session, commands = self.run_permissions("live-environment-after")
        self.assertEqual(code, 2)
        self.assertEqual(session["status"], "BLOCKED")
        self.assertIn("synthetic after-stage failure", session["error"])
        self.assertIn("Traceback (most recent call last)", session["traceback"])
        self.assertIn("export-native-evidence", [name for name, _ in commands])


if __name__ == "__main__":
    unittest.main()
