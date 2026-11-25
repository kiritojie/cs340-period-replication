"""Recovery permission policy tests; never invoke Podman or a benchmark."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("permission_resume", ROOT / "scripts/resume_table2_podman.py")
RESUME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESUME)


class RecoveryPermissionTests(unittest.TestCase):
    def test_effective_root_uses_no_sudo_even_with_nonroot_real_uid(self):
        with mock.patch.object(RESUME.os, "geteuid", return_value=0, create=True), \
                mock.patch.object(RESUME.os, "getuid", return_value=1000, create=True):
            self.assertEqual(RESUME.host_privilege_prefix(), [])

    def test_nonroot_retains_noninteractive_sudo_for_rootful_engine(self):
        with mock.patch.object(RESUME.os, "geteuid", return_value=1000, create=True):
            self.assertEqual(RESUME.host_privilege_prefix(), ["sudo", "-n"])

    def test_security_boundary_is_required_and_never_weakened(self):
        good = {"HostConfig": {"Privileged": False, "CapDrop": ["ALL"],
                               "CapAdd": ["CAP_SYS_NICE"], "SecurityOpt": ["no-new-privileges"]}}
        self.assertEqual(RESUME.validate_security_configuration(good)["cap_add"], ["SYS_NICE"])
        for key, value in (("Privileged", True), ("Privileged", None), ("CapDrop", []),
                           ("CapAdd", ["SYS_NICE", "KILL"]), ("CapAdd", []), ("SecurityOpt", [])):
            bad = copy.deepcopy(good)
            bad["HostConfig"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                RESUME.validate_security_configuration(bad)

    def test_podman_resolved_all_requires_the_original_creation_flag(self):
        recorded = {"Config": {"CreateCommand": ["podman", "run", "--cap-drop=ALL"]},
                    "HostConfig": {"Privileged": False, "CapAdd": ["CAP_SYS_NICE"],
                                   "SecurityOpt": ["no-new-privileges"],
                                   "CapDrop": ["CAP_" + name for name in (
                                       "AUDIT_WRITE", "CHOWN", "DAC_OVERRIDE", "FOWNER", "FSETID", "KILL",
                                       "MKNOD", "NET_BIND_SERVICE", "NET_RAW", "SETFCAP", "SETGID",
                                       "SETPCAP", "SETUID", "SYS_CHROOT")]}}
        self.assertEqual(RESUME.validate_security_configuration(recorded)["cap_drop"], ["ALL"])
        recorded["Config"]["CreateCommand"] = ["podman", "run"]
        with self.assertRaises(ValueError):
            RESUME.validate_security_configuration(recorded)

    def test_successful_arm_results_cannot_waive_missing_or_failed_permission_gate(self):
        result = {"status": "PILOT_PASSED", "reference_role": "ABI_ONLY_CORRECTED_PARALLEL",
                  "runs": {arm: {"validation": "PASS"} for arm in ("A1", "B", "C")}}
        self.assertFalse(RESUME.native_pilot_passed(result))
        for permission in ({"schema": "cs340-period-permissions-v1", "status": "BLOCKED"},
                           {"schema": "unexpected", "status": "PASS"}):
            result["permissions"] = permission
            self.assertFalse(RESUME.native_pilot_passed(result))
        result["permissions"] = {"schema": "cs340-period-permissions-v1", "status": "PASS"}
        self.assertFalse(RESUME.native_pilot_passed(result))
        result["permissions"]["probes"] = {probe: {"status": "PASS", "exit_code": 0}
                                              for probe in ("process_control", "sched_deadline")}
        self.assertTrue(RESUME.native_pilot_passed(result))
        result["runs"]["C"]["validation"] = "BLOCKED"
        self.assertFalse(RESUME.native_pilot_passed(result))


if __name__ == "__main__":
    unittest.main()
