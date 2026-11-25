"""Focused launch/security regression checks; real permission acceptance is CLI-only."""
import copy
import importlib.util
import json
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("table2_permissions_test", ROOT / "scripts/table2_scheduler_permissions.py")
PERMISSIONS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PERMISSIONS)


class PermissionLaunchTests(unittest.TestCase):
    def test_root_preserves_finalized_sudo_environment_without_shell(self):
        original = ["sudo", "Dry_Run=0", "DBDS_Run=1", "ASAN_OPTIONS=abort_on_error=1:detect_leaks=1",
                    "TSAN_OPTIONS=report_bugs=1", "./reorder_3_bad", "literal;$()"]
        kwargs = {"env": {"Con_PATH": "/frozen/config", "Dry_Run": "old"}, "close_fds": True}
        command, options = PERMISSIONS.prepare_process_launch(original, kwargs, euid=0)
        self.assertEqual(command, ["./reorder_3_bad", "literal;$()"])
        self.assertEqual(options["env"], {"Con_PATH": "/frozen/config", "Dry_Run": "0", "DBDS_Run": "1",
                                         "ASAN_OPTIONS": "abort_on_error=1:detect_leaks=1",
                                         "TSAN_OPTIONS": "report_bugs=1"})
        self.assertEqual(original[0], "sudo")
        self.assertEqual(kwargs["env"]["Dry_Run"], "old")
        self.assertNotIn("shell", options)

    def test_root_kill_and_nonroot_commands_use_same_policy(self):
        self.assertEqual(PERMISSIONS.privilege_command(["kill", "123"], euid=0), ["kill", "123"])
        self.assertEqual(PERMISSIONS.normalize_official_command(["sudo", "kill", "123"], euid=0), ["kill", "123"])
        original = ["sudo", "Dry_Run=1", "./reorder_3_bad"]
        self.assertEqual(PERMISSIONS.prepare_process_launch(original, {}, euid=1000)[0],
                         ["sudo", "-n", "Dry_Run=1", "./reorder_3_bad"])
        self.assertEqual(PERMISSIONS.prepare_process_launch(["sudo", "-n", "kill", "123"], {}, euid=1000)[0],
                         ["sudo", "-n", "kill", "123"])

    def test_root_inherits_context_and_keeps_assignments_after_target_as_arguments(self):
        with mock.patch.object(PERMISSIONS.os, "environ", {"Con_PATH": "expected"}):
            command, options = PERMISSIONS.prepare_process_launch(
                ["sudo", "NO_Trace=1", "./target", "Dry_Run=literal"], {}, euid=0)
        self.assertEqual(command, ["./target", "Dry_Run=literal"])
        self.assertEqual(options["env"]["Con_PATH"], "expected")
        self.assertEqual(options["env"]["NO_Trace"], "1")

    def test_unsupported_sudo_forms_fail_closed(self):
        for command, kwargs in ((["sudo", "-u", "other", "./target"], {}),
                                (["sudo", "Dry_Run=1"], {}),
                                (["sudo", "./target"], {"shell": True})):
            with self.assertRaises(ValueError):
                PERMISSIONS.prepare_process_launch(command, kwargs, euid=0)

    def test_non_sudo_launch_is_unchanged(self):
        command = ["./target", "literal=value"]
        kwargs = {"env": {"keep": "yes"}}
        self.assertEqual(PERMISSIONS.prepare_process_launch(command, kwargs, euid=0), (command, kwargs))

    def test_cleanup_signals_owned_group_after_leader_exit(self):
        process = mock.Mock(pid=7654321, returncode=0)
        process.poll.return_value = 0
        process.communicate.return_value = ("", "")
        with mock.patch.object(PERMISSIONS, "kill_process_group", return_value=True) as kill:
            result = PERMISSIONS.cleanup_owned_process(process)
        kill.assert_called_once_with(7654321, PERMISSIONS.SIGKILL)
        process.communicate.assert_called_once_with(timeout=2)
        self.assertTrue(result["group_signaled"])

    def test_root_signal_denial_propagates_without_sudo(self):
        with mock.patch.object(PERMISSIONS.os, "getpgrp", return_value=10, create=True), \
             mock.patch.object(PERMISSIONS.os, "killpg", side_effect=PermissionError("denied"), create=True), \
             mock.patch.object(PERMISSIONS.os, "geteuid", return_value=0, create=True), \
             mock.patch.object(PERMISSIONS.subprocess, "check_call") as sudo:
            with self.assertRaises(PermissionError):
                PERMISSIONS.kill_process_group(22, PERMISSIONS.SIGKILL)
        sudo.assert_not_called()

    def test_nonroot_signal_fallback_is_noninteractive(self):
        with mock.patch.object(PERMISSIONS.os, "getpgrp", return_value=10, create=True), \
             mock.patch.object(PERMISSIONS.os, "killpg", side_effect=PermissionError("denied"), create=True), \
             mock.patch.object(PERMISSIONS.os, "geteuid", return_value=1000, create=True), \
             mock.patch.object(PERMISSIONS.subprocess, "check_call") as sudo:
            PERMISSIONS.kill_process_group(22, PERMISSIONS.SIGKILL)
        sudo.assert_called_once_with(["sudo", "-n", "kill", "-9", "--", "-22"])


class PermissionProofTests(unittest.TestCase):
    def setUp(self):
        self.identity = {"uid": 0, "euid": 0, "gid": 0, "egid": 0,
                         "status_fields": {"NoNewPrivs": "1"},
                         "capabilities": {name: PERMISSIONS.SYS_NICE for name in PERMISSIONS.CAP_FIELDS},
                         "effective_capabilities": ["SYS_NICE"], "no_new_privileges": 1}
        self.proof = {"schema": PERMISSIONS.SCHEMA, "status": "PASS", "identity": self.identity,
                      "helper_sha256": PERMISSIONS.helper_hash(), "supervisor_sha256": PERMISSIONS.supervisor_hash(),
                      "policy": {"mode": "root-direct"},
                      "probes": {name: {"status": "PASS", "exit_code": 0}
                                 for name in ("process_control", "sched_deadline")}}
        self.proof["probes"]["process_control"].update({
            "euid": 0, "environment_preserved": True,
            "term": {"passed": True, "returncode": -signal.SIGTERM},
            "timeout_kill": {"passed": True, "returncode": -PERMISSIONS.SIGKILL, "timeout_observed": True},
            "descendant_cleanup": {"passed": True, "no_remaining_processes": True},
            "exited_leader_cleanup": {"passed": True},
            "outer_watchdog_supervisor_cleanup": {"passed": True, "timeout_exit_code": 124, "cleanup_completed": True,
                                                    "descendant_reaped": True, "subreaper_restored": True}})
        attr = {"policy": 6, "flags": 0, "priority": 0, "runtime": 10000000,
                "deadline": 20000000, "period": 20000000}
        self.proof["probes"]["sched_deadline"].update({"euid": 0, "identity": self.identity,
            "sched_setattr": {"return": 0}, "sched_getattr": {"return": 0},
            "sched_getscheduler": 6, "yield_returned": True, "restore": {"return": 0},
            "restored_scheduler": 0, "requested": attr, "readback": dict(attr)})

    def validate(self, proof, current=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "permission-proof.json"
            path.write_text(json.dumps(proof), encoding="utf-8")
            with mock.patch.object(PERMISSIONS, "identity", return_value=current or self.identity), \
                 mock.patch.object(PERMISSIONS, "permission_policy", return_value={"mode": "root-direct"}):
                return PERMISSIONS.validate_permission_proof(path)

    def test_exact_historical_masks_are_accepted(self):
        self.assertEqual(PERMISSIONS.identity_errors(self.identity), [])
        self.assertEqual(self.validate(self.proof)["status"], "PASS")

    def test_uid_capability_or_no_new_privs_drift_blocks(self):
        for key, value in (("euid", 1000), ("no_new_privileges", 0)):
            changed = copy.deepcopy(self.identity)
            changed[key] = value
            with self.assertRaises(RuntimeError):
                self.validate(self.proof, changed)
        for name in PERMISSIONS.CAP_FIELDS:
            changed = copy.deepcopy(self.identity)
            changed["capabilities"][name] |= 1 << 7
            with self.assertRaises(RuntimeError):
                self.validate(self.proof, changed)

    def test_missing_actual_probe_or_implementation_change_blocks(self):
        for key in ("helper_sha256", "supervisor_sha256"):
            changed = copy.deepcopy(self.proof)
            changed[key] = "stale"
            with self.assertRaises(RuntimeError):
                self.validate(changed)
        for name in ("process_control", "sched_deadline"):
            changed = copy.deepcopy(self.proof)
            del changed["probes"][name]
            with self.assertRaises(RuntimeError):
                self.validate(changed)

    def test_failed_or_skipped_acceptance_cannot_be_validated(self):
        changed = copy.deepcopy(self.proof)
        changed["status"] = "BLOCKED"
        with self.assertRaises(RuntimeError):
            self.validate(changed)

    def test_nominal_pass_without_actual_inner_readbacks_is_rejected(self):
        for probe, key in (("process_control", "term"), ("sched_deadline", "readback"),
                           ("sched_deadline", "restore")):
            changed = copy.deepcopy(self.proof)
            del changed["probes"][probe][key]
            with self.assertRaises(RuntimeError):
                self.validate(changed)


if __name__ == "__main__":
    unittest.main()
