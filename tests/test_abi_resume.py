"""Mocked stopped-container extraction; no Podman, WSL or native IPC is used."""
import copy
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from test_table2_preflight import dwarf_fixture


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "abi_resume_under_test", ROOT / "scripts/resume_table2_podman.py")
RESUME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESUME)
VENDOR = ROOT / "scripts/vendor/period_b6f72a7"


def actual_podman_shape(name=None, prefix=None):
    name = name or RESUME.CONTAINERS[0][0]
    prefix = prefix or RESUME.CONTAINERS[0][1]
    return {"Id": prefix + "0" * (64 - len(prefix)), "Name": name,
            "Image": RESUME.IMAGE, "State": {"Status": "exited", "Running": False},
            "Config": {"Entrypoint": "/bin/bash", "Cmd": None, "OpenStdin": True,
                       "Tty": True, "Env": ["ROOT_DIR=/workdir/PERIOD"]},
            "Path": "/bin/bash", "Args": ["/bin/bash"],
            "HostConfig": {"Privileged": False, "CapAdd": ["CAP_SYS_NICE"],
                           "CapDrop": ["ALL"], "IpcMode": "private",
                           "SecurityOpt": ["no-new-privileges"], "CpusetCpus": ""},
            "Mounts": [{"Source": "/synthetic/old-evidence", "Destination": "/evidence", "RW": True}],
            "OCIRuntime": "crun"}


class AbiResumeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="period-mocked-abi-extraction-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "evidence"
        self.history = self.root / "history"
        self.history.mkdir()
        self.calls = []

    def test_actual_podman_string_entrypoint_and_redundant_args_are_supported(self):
        record = actual_podman_shape()
        self.assertEqual(RESUME.safe_idle_start(record), ["/bin/bash"])
        record["Args"] = []
        self.assertEqual(RESUME.safe_idle_start(record), ["/bin/bash"])
        for entry in ("/bin/bash -c", "/bin/bash\n", "bash", "/bin/sh -c old", " /bin/bash"):
            value = copy.deepcopy(record)
            value["Config"]["Entrypoint"] = entry
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                RESUME.safe_idle_start(value)

    def run_mocked_extract(self, packed=False, object_capacity=3964, missing_source=None, head=None):
        def fake_command(controller, label, argv, timeout=60, required=True):
            args = [str(item) for item in argv]
            self.calls.append((label, args))
            stdout, stderr, code = b"", b"", 0
            if args[:4] == ["sudo", "-n", "podman", "inspect"]:
                selected = next((actual_podman_shape(name, prefix) for name, prefix in RESUME.CONTAINERS
                                 if args[-1] in (name, prefix + "0" * (64 - len(prefix)))), None)
                stdout = json.dumps([selected] if selected else []).encode("utf-8")
            elif args[:5] == ["sudo", "-n", "podman", "image", "inspect"]:
                stdout = json.dumps([{"Id": RESUME.IMAGE}]).encode("utf-8")
            elif args[:4] == ["sudo", "-n", "podman", "cp"]:
                source = args[-2].split(":/workdir/PERIOD/", 1)[1]
                destination = Path(args[-1])
                destination.parent.mkdir(parents=True, exist_ok=True)
                if source == missing_source:
                    code, stderr = 125, b"synthetic source missing"
                elif source == ".git/HEAD":
                    value = head if head is not None else ("ref: refs/heads/main" if packed else RESUME.PINNED_COMMIT)
                    destination.write_text(value + "\n", encoding="utf-8")
                elif source == ".git/packed-refs":
                    if packed:
                        destination.write_text("# pack-refs\n" + RESUME.PINNED_COMMIT + " refs/heads/main\n", encoding="utf-8")
                    else:
                        code = 125
                elif source.startswith(".git/refs/"):
                    code = 125  # Explicitly exercise packed-ref resolution.
                elif source in RESUME.SOURCE_FILES:
                    destination.write_bytes((VENDOR / Path(source).name).read_bytes())
                else:
                    destination.write_bytes(b"synthetic product; not executable")
            elif args[:3] == ["readelf", "--wide", "--debug-dump=info"]:
                capacity = object_capacity if "runtime_object" in label else 3964
                stdout = dwarf_fixture(capacity=capacity).encode("utf-8")
            if required and code:
                raise ValueError("synthetic command failure: " + label)
            return {"exit_code": code, "argv": args}, stdout, stderr

        def fake_digest(path):
            name = Path(path).name.replace("post-", "")
            if name == "binary":
                return RESUME.BINARY_SHA
            if name == "config":
                return RESUME.CONFIG_SHA
            if name == "runtime_object":
                return "c" * 64
            return hashlib.sha256(Path(path).read_bytes()).hexdigest()

        with mock.patch.object(RESUME.platform, "system", return_value="Linux"), \
                mock.patch.object(RESUME.shutil, "which", side_effect=lambda name: "/synthetic/" + name), \
                mock.patch.object(RESUME.Commands, "run", autospec=True, side_effect=fake_command), \
                mock.patch.object(RESUME, "digest", side_effect=fake_digest), \
                mock.patch.object(RESUME.os, "getuid", return_value=1000, create=True), \
                mock.patch.object(RESUME.os, "geteuid", return_value=1000, create=True), \
                mock.patch.object(RESUME.os, "getgid", return_value=1000, create=True), \
                mock.patch.object(RESUME.os, "getegid", return_value=1000, create=True), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = RESUME.main(["--extract-only", "--repo", str(ROOT), "--history", str(self.history),
                                "--output-root", str(self.output)])
        files = list(self.output.glob("*/resume-summary.json"))
        self.assertEqual(len(files), 1)
        return code, json.loads(files[0].read_text(encoding="utf-8")), files[0].parent

    def assert_read_only_podman(self):
        for label, args in self.calls:
            if "podman" not in args:
                self.assertIn(args[0], ("readelf", "uname", "sudo"))
                continue
            self.assertEqual(args[:3], ["sudo", "-n", "podman"])
            self.assertNotIn(args[3], ("start", "exec", "run", "create", "build", "pull", "load",
                                       "rm", "rmi", "stop", "kill", "commit"), label)

    def test_extract_only_copies_actual_source_and_detached_HEAD_without_start_or_exec(self):
        code, result, output = self.run_mocked_extract()
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "EXTRACTED_FOR_REVIEW_NO_BENCHMARK")
        self.assertFalse(result["ready_for_pilot"])
        self.assertEqual(result["benchmarks"], "NOT_RUN")
        self.assertEqual(result["runtime_layout"]["byte_size"], 24008)
        self.assertEqual(result["runtime_layout"]["members"][5]["dimensions"], [3964])
        audit = result["source_extraction"]
        self.assertTrue(audit["complete"])
        self.assertTrue(audit["head_matches_pinned"])
        self.assertTrue(audit["scoped_sources_match_pinned"])
        self.assertIn("NOT_OBSERVED", audit["full_worktree_status"])
        self.assertEqual(audit["historical_driver_execution"], "A0_AUDIT_ONLY_NOT_RUN")
        driver = output / "original-source/tool/DBDS/run_PDS.py"
        self.assertEqual(audit["files"]["tool/DBDS/run_PDS.py"]["sha256"],
                         hashlib.sha256(driver.read_bytes()).hexdigest())
        self.assertTrue((output / "A0-historical-driver-audit.json").is_file())
        self.assertEqual(set(result["source_integrity_rechecks"]), set(RESUME.SOURCE_FILES))
        self.assert_read_only_podman()

    def test_symbolic_HEAD_resolves_from_preserved_packed_refs(self):
        code, result, output = self.run_mocked_extract(packed=True)
        self.assertEqual(code, 0)
        self.assertEqual(result["source_extraction"]["upstream_head"], RESUME.PINNED_COMMIT)
        self.assertIn(".git/packed-refs", result["source_extraction"]["files"])
        self.assertTrue((output / "original-source/git-metadata/HEAD").read_text().startswith("ref: "))
        self.assert_read_only_podman()

    def test_binary_and_object_layout_mismatch_blocks_without_container_execution(self):
        code, result, unused = self.run_mocked_extract(object_capacity=1990)
        self.assertNotEqual(code, 0)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("layouts differ", result["reason"])
        self.assertEqual(result["benchmarks"], "NOT_RUN")
        self.assertTrue(result["source_extraction"]["complete"])
        self.assert_read_only_podman()

    def test_missing_actual_driver_is_preserved_as_incomplete_not_inferred_from_GitHub(self):
        code, result, unused = self.run_mocked_extract(missing_source="tool/DBDS/run_PDS.py")
        self.assertNotEqual(code, 0)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(result["source_extraction"]["complete"])
        self.assertFalse(result["source_extraction"]["scoped_sources_match_pinned"])
        self.assert_read_only_podman()

    def test_unsafe_symbolic_HEAD_cannot_be_used_as_a_copy_path(self):
        code, result, unused = self.run_mocked_extract(head="ref: refs/../../outside")
        self.assertNotEqual(code, 0)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("unsafe symbolic HEAD", result["reason"])
        for label, args in self.calls:
            if "podman" in args and args[3] == "cp":
                self.assertNotIn("..", args[-2].split("/"))
        self.assert_read_only_podman()


if __name__ == "__main__":
    unittest.main(verbosity=2)
