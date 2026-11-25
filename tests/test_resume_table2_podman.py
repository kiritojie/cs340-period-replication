"""Pure helpers and mocked bridge orchestration; no Podman/WSL/benchmark calls."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "resume_table2_podman_under_test", ROOT / "scripts" / "resume_table2_podman.py")
RESUME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESUME)


def record_fixture(name=None, prefix=None):
    name = name or RESUME.CONTAINERS[0][0]
    prefix = prefix or RESUME.CONTAINERS[0][1]
    return {
        "Id": prefix + "0" * (64 - len(prefix)), "Name": name,
        "Image": "sha256:" + RESUME.IMAGE,
        "State": {"Status": "exited", "Running": False, "Pid": 0},
        "Config": {"Entrypoint": [], "Cmd": ["/bin/bash"],
                   "OpenStdin": True, "Tty": True, "Env": ["ROOT_DIR=/workdir/PERIOD"]},
        "Path": "/bin/bash", "Args": [],
        "HostConfig": {"Privileged": True, "CapAdd": ["SYS_NICE"], "CpusetCpus": "0-7",
                       "IpcMode": "private", "NetworkMode": "bridge"},
        "Mounts": [{"Source": "/synthetic/lab", "Destination": "/lab", "RW": True}],
        "OCIRuntime": "crun",
    }


class ContainerHelperTests(unittest.TestCase):
    def test_inspect_requires_exactly_one_dictionary(self):
        record = record_fixture()
        self.assertEqual(RESUME.one_inspect(json.dumps([record])), record)
        for value in ({}, [], [record, record], [None], ["container"], "string"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                RESUME.one_inspect(json.dumps(value))

    def test_container_identity_is_bound_to_name_prefix_and_confirmed_image(self):
        name, prefix = RESUME.CONTAINERS[0]
        good = record_fixture()
        self.assertEqual(RESUME.validate_container(good, name, prefix), good["Id"])
        for field, value in (("Id", "a" * 64), ("Name", RESUME.CONTAINERS[1][0]),
                             ("Image", "b" * 64), ("Image", None), ("Id", None)):
            record = copy.deepcopy(good)
            record[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                RESUME.validate_container(record, name, prefix)

    def test_slash_prefixed_names_and_sha256_image_prefix_are_equivalent(self):
        name, prefix = RESUME.CONTAINERS[0]
        record = record_fixture()
        record["Name"] = "/" + name
        self.assertEqual(RESUME.validate_container(record, name, prefix), record["Id"])
        record["Image"] = RESUME.IMAGE
        self.assertEqual(RESUME.validate_container(record, name, prefix), record["Id"])

    def test_unknown_removing_or_paused_container_state_is_rejected(self):
        name, prefix = RESUME.CONTAINERS[0]
        for state in ("paused", "removing", "dead", "unknown", ""):
            record = record_fixture()
            record["State"]["Status"] = state
            with self.subTest(state=state), self.assertRaises(ValueError):
                RESUME.validate_container(record, name, prefix)

    def test_idle_shell_requires_persistent_tty_and_stdin(self):
        self.assertEqual(RESUME.safe_idle_start(record_fixture()), ["/bin/bash"])
        for flag in ("OpenStdin", "Tty"):
            for value in (False, None, "true", 1):
                record = record_fixture()
                record["Config"][flag] = value
                with self.subTest(flag=flag, value=value), self.assertRaises(ValueError):
                    RESUME.safe_idle_start(record)

    def test_shell_command_strings_experiments_and_unproven_argv_are_rejected(self):
        commands = (["bash", "-c", "python3 run_PDS.py ./reorder_3_bad"],
                    ["/bin/bash", "-lc", "sleep infinity"],
                    ["python3", "run_PDS.py", "./reorder_3_bad"],
                    ["./reorder_3_bad"], [], "/bin/bash", [None])
        for command in commands:
            record = record_fixture()
            record["Config"]["Cmd"] = command
            with self.subTest(command=command), self.assertRaises(ValueError):
                RESUME.safe_idle_start(record)
        record = record_fixture()
        record["Config"]["Entrypoint"] = "/bin/bash -c"
        with self.assertRaises(ValueError):
            RESUME.safe_idle_start(record)

    def test_config_and_actual_path_arguments_must_agree(self):
        record = record_fixture()
        record["Args"] = ["-c", "old-experiment"]
        with self.assertRaises(ValueError):
            RESUME.safe_idle_start(record)
        record = record_fixture()
        record["Path"] = "/bin/python3"
        with self.assertRaises(ValueError):
            RESUME.safe_idle_start(record)

    def test_explicit_infinite_sleep_is_safe_without_interactive_tty(self):
        record = record_fixture()
        record["Config"].update(Cmd=["/bin/sleep", "infinity"], Tty=False, OpenStdin=False)
        record["Path"] = "/bin/sleep"
        record["Args"] = ["infinity"]
        self.assertEqual(RESUME.safe_idle_start(record), ["/bin/sleep", "infinity"])

    def test_launch_snapshot_ignores_state_but_pins_actual_launch_configuration(self):
        original = record_fixture()
        changed_state = copy.deepcopy(original)
        changed_state["State"] = {"Status": "running", "Running": True, "Pid": 12345}
        self.assertEqual(RESUME.launch_configuration(original), RESUME.launch_configuration(changed_state))
        variations = []
        for key, value in (("Privileged", False), ("CapAdd", []), ("CpusetCpus", "0-3"),
                           ("IpcMode", "host"), ("NetworkMode", "host")):
            changed = copy.deepcopy(original)
            changed["HostConfig"][key] = value
            variations.append(changed)
        for key, value in (("Image", "changed"), ("Mounts", []), ("OCIRuntime", "runc")):
            changed = copy.deepcopy(original)
            changed[key] = value
            variations.append(changed)
        changed = copy.deepcopy(original)
        changed["Config"]["Cmd"] = ["bash", "-c", "experiment"]
        variations.append(changed)
        for changed in variations:
            with self.subTest(changed=changed):
                self.assertNotEqual(RESUME.launch_configuration(original), RESUME.launch_configuration(changed))


class MockedBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="period-mocked-podman-bridge-")
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        self.repo = base / "repo"
        self.repo.mkdir()
        self.output = base / "evidence"
        self.history = base / "history"
        self.history.mkdir()
        self.commands = []
        self.records = {name: record_fixture(name, prefix) for name, prefix in RESUME.CONTAINERS}

    @staticmethod
    def fake_digest(path):
        label = Path(path).name.replace("post-", "")
        if label == "binary":
            return RESUME.BINARY_SHA
        if label == "config":
            return RESUME.CONFIG_SHA
        if label == "runtime_object":
            return "c" * 64
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def run_mocked(self, missing_original=False, bad_original=False, missing_both=False,
                   execute=False, changed_after=False, fail_copy_label=None, unsafe_start=False):
        def fake_command(controller, label, argv, timeout=60, required=True):
            args = [str(item) for item in argv]
            self.commands.append((label, args))
            stdout, stderr, rc = b"", b"", 0
            if args[:4] == ["sudo", "-n", "podman", "inspect"]:
                requested = args[4]
                if requested in self.records:
                    original_missing = requested == RESUME.CONTAINERS[0][0] and missing_original
                    if missing_both or original_missing:
                        rc, stderr = 125, b"synthetic inspect unavailable"
                    else:
                        record = copy.deepcopy(self.records[requested])
                        if requested == RESUME.CONTAINERS[0][0] and bad_original:
                            record["Image"] = "wrong-image"
                        if requested == RESUME.CONTAINERS[0][0] and unsafe_start:
                            record["Config"]["Cmd"] = ["bash", "-c", "old-experiment"]
                            record["Path"], record["Args"] = "bash", ["-c", "old-experiment"]
                        stdout = json.dumps([record]).encode("utf-8")
                else:
                    record = next((row for row in self.records.values() if row["Id"] == requested), None)
                    stdout = json.dumps([record] if record else []).encode("utf-8")
            elif args[:4] == ["sudo", "-n", "podman", "cp"]:
                if label == fail_copy_label:
                    rc, stderr = 125, b"synthetic copy failure"
                else:
                    destination = Path(args[-1])
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(b"synthetic product snapshot; not executable")
            elif args[:5] == ["sudo", "-n", "podman", "image", "inspect"]:
                stdout = json.dumps([{"Id": "sha256:" + RESUME.IMAGE}]).encode("utf-8")
            if required and rc:
                raise ValueError("synthetic " + label + " failed")
            return {"argv": args, "exit_code": rc}, stdout, stderr

        def fake_digest(path):
            if changed_after and Path(path).name == "post-binary":
                return "different-after-inspection"
            return self.fake_digest(path)

        arguments = ["--repo", str(self.repo), "--history", str(self.history),
                     "--output-root", str(self.output)]
        if execute:
            arguments.insert(0, "--execute")
        with mock.patch.object(RESUME.platform, "system", return_value="Linux"), \
                mock.patch.object(RESUME.shutil, "which", side_effect=lambda name: None if name == "readelf" else "/synthetic/" + name), \
                mock.patch.object(RESUME.Commands, "run", autospec=True, side_effect=fake_command), \
                mock.patch.object(RESUME, "digest", side_effect=fake_digest), \
                mock.patch.object(RESUME.os, "getuid", return_value=1000, create=True), \
                mock.patch.object(RESUME.os, "geteuid", return_value=1000, create=True), \
                mock.patch.object(RESUME.os, "getgid", return_value=1000, create=True), \
                mock.patch.object(RESUME.os, "getegid", return_value=1000, create=True):
            code = RESUME.main(arguments)
        summaries = list(self.output.glob("*/resume-summary.json"))
        self.assertEqual(len(summaries), 1)
        return code, json.loads(summaries[0].read_text(encoding="utf-8"))

    def assert_no_mutating_podman_operation(self):
        forbidden = {"start", "exec", "pull", "build", "rm", "rmi", "commit", "create", "run", "stop", "kill"}
        for label, args in self.commands:
            if "podman" in args:
                self.assertEqual(args[:3], ["sudo", "-n", "podman"])
                self.assertFalse(forbidden.intersection(args[3:]), (label, args))

    def test_default_mode_only_inspects_and_preserves_products_without_start_or_exec(self):
        code, result = self.run_mocked()
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "INSPECTED_NO_BENCHMARK")
        self.assertEqual(result["benchmarks"], "NOT_RUN")
        self.assertEqual(result["formal_four_program_batch"], "NOT_STARTED")
        self.assert_no_mutating_podman_operation()
        self.assertEqual(result["original_products"]["binary"]["sha256"], RESUME.BINARY_SHA)

    def test_missing_original_never_selects_v2_automatically(self):
        code, result = self.run_mocked(missing_original=True, execute=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["benchmarks"], "NOT_RUN")
        self.assertIn("v2 is not selected automatically", result["reason"])
        self.assertFalse(any(label.startswith("copy-existing-") for label, unused in self.commands))
        self.assert_no_mutating_podman_operation()

    def test_inspect_failures_are_preserved_and_stop_before_any_restart_or_target(self):
        code, result = self.run_mocked(missing_both=True, execute=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIsNone(result["container"])
        self.assert_no_mutating_podman_operation()

    def test_image_identity_failure_stops_before_copying_or_starting(self):
        code, result = self.run_mocked(bad_original=True, execute=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("confirmed existing image", result["reason"])
        self.assertFalse(any(label.startswith("copy-existing-") for label, unused in self.commands))
        self.assert_no_mutating_podman_operation()

    def test_finally_integrity_failure_overrides_an_earlier_success_return(self):
        code, result = self.run_mocked(changed_after=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("original binary changed", result["integrity_error"])
        self.assert_no_mutating_podman_operation()

    def test_execute_flag_does_not_authorize_starting_a_historical_command(self):
        code, result = self.run_mocked(execute=True, unsafe_start=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["benchmarks"], "NOT_RUN")
        self.assertIn("startup may execute a historical experiment", result["reason"])
        self.assert_no_mutating_podman_operation()

    def test_partial_initial_copy_does_not_invent_a_changed_product(self):
        code, result = self.run_mocked(fail_copy_label="copy-existing-config")
        self.assertNotEqual(code, 0)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(set(result["original_products"]), {"binary"})
        self.assertIn("copy-existing-config", result["reason"])
        self.assertNotIn("integrity_error", result)
        self.assert_no_mutating_podman_operation()

    def test_missing_final_product_recheck_is_not_claimed_unchanged(self):
        code, result = self.run_mocked(fail_copy_label="recheck-original-binary")
        self.assertNotEqual(code, 0)
        self.assertEqual(result["status"], "BLOCKED")
        self.assert_no_mutating_podman_operation()


if __name__ == "__main__":
    unittest.main(verbosity=2)
