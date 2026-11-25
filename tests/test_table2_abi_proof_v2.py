"""Runtime-DWARF proof tests; all files and inspection commands are synthetic.

The expected layout is a byte-identical copy of the user's observed 3964-entry
binary layout.  Passing these tests never certifies a live container or ELF.
"""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "scripts/vendor/period_b6f72a7"
FIXTURE = ROOT / "tests/fixtures/period_runtime_3964_layout.json"


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREFLIGHT = load_file("runtime_dwarf_proof_under_test", ROOT / "scripts/table2_scheduler_preflight.py")
PARSER_FIXTURES = load_file("legacy_proof_fixture_only", ROOT / "tests/test_table2_preflight.py")


def canonical(layout):
    return {key: value for key, value in layout.items() if key != "compilation_unit"}


class RuntimeDwarfProofTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="period-v2-synthetic-proof-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.upstream = self.base / "PERIOD"
        self.dbds = self.upstream / "tool/DBDS"
        self.dbds.mkdir(parents=True)
        for name in ("run_PDS.py", "pds.py", "sched.py", "bp_sched.py", "sbp_sched.py",
                     "sbp_sched_mixed_end.py", "external_def.py", "interleaving.py", "ipc.py"):
            shutil.copyfile(str(VENDOR / name), str(self.dbds / name))
        self.runtime_source = self.upstream / "tool/staticAnalysis/DBDS-INSTRU/llvm-mode/DBDSFunction.cpp"
        self.runtime_source.parent.mkdir(parents=True)
        shutil.copyfile(str(VENDOR / "DBDSFunction.cpp"), str(self.runtime_source))
        self.runtime_object = self.runtime_source.parent.parent / "DBDSFunction.o"
        self.runtime_object.write_bytes(b"synthetic runtime object; not an ELF or executable")
        self.target = self.base / "reorder_3_bad"
        self.target.write_bytes(b"synthetic target; must never be executed")
        self.config = self.base / "ConConfig.reorder_3_bad"
        self.config.write_bytes(b"synthetic key point config")
        self.driver = self.base / "run_scheduler_comparison.py"
        self.driver.write_text("# synthetic adapter identity only\n", encoding="utf-8")
        self.reference = self.base / "run_abi_parallel_reference.py"
        self.reference.write_text("# synthetic ABI-only reference identity only\n", encoding="utf-8")
        self.proof_path = self.base / "abi-proof.json"
        self.actual = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.dwarf = PARSER_FIXTURES.dwarf_fixture(capacity=3964)
        self.binary_dwarf = self.object_dwarf = self.dwarf
        self.calls = []
        self.git_head = PREFLIGHT.COMMIT
        self.git_dirty = ""

    def command(self, argv):
        self.calls.append(list(argv))
        if argv[:3] == ["readelf", "--wide", "--debug-dump=info"]:
            path = Path(argv[3]).resolve()
            if path == self.target.resolve():
                return self.binary_dwarf
            if path == self.runtime_object.resolve():
                return self.object_dwarf
            raise AssertionError("unexpected readelf target: " + str(path))
        if argv[0] == "git" and "rev-parse" in argv:
            return self.git_head + "\n"
        if argv[0] == "git" and "diff" in argv:
            return self.git_dirty
        raise AssertionError("unexpected inspection command (no target launch allowed): " + repr(argv))

    @contextlib.contextmanager
    def synthetic_environment(self):
        # Only synthetic input identities are substituted. Actual product checks
        # remain enabled and the command mock allows read-only git/readelf only.
        target_sha = hashlib.sha256(b"synthetic target; must never be executed").hexdigest()
        config_sha = hashlib.sha256(b"synthetic key point config").hexdigest()
        with mock.patch.object(PREFLIGHT, "command", side_effect=self.command), \
                mock.patch.object(PREFLIGHT, "BINARY_SHA256", target_sha), \
                mock.patch.object(PREFLIGHT, "CONFIG_SHA256", config_sha), \
                mock.patch.object(PREFLIGHT.platform, "system", return_value="Linux"), \
                mock.patch.object(PREFLIGHT.platform, "machine", return_value="x86_64"), \
                mock.patch.object(PREFLIGHT.sys, "byteorder", "little"), \
                mock.patch.object(PREFLIGHT.shutil, "which", return_value="/synthetic/readelf"):
            yield

    def generate(self):
        args = ["--binary", str(self.target), "--config", str(self.config),
                "--runtime-object", str(self.runtime_object), "--runtime-source", str(self.runtime_source),
                "--upstream", str(self.upstream), "--driver", str(self.driver),
                "--output", str(self.proof_path), "--abi-profile", "runtime-dwarf"]
        with self.synthetic_environment(), contextlib.redirect_stdout(io.StringIO()):
            code = PREFLIGHT.main(args)
        return code, json.loads(self.proof_path.read_text(encoding="utf-8"))

    def validate(self, proof=None):
        if proof is not None:
            self.proof_path.write_text(json.dumps(proof), encoding="utf-8")
        with self.synthetic_environment():
            return PREFLIGHT.validate_abi_proof(self.proof_path, self.target, self.dbds)

    def test_actual_fixture_and_independent_dwarf_have_identical_layout(self):
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
                         "5889aed8e923b6e177d1cc1b0213a4d8b8e052cf3f334ca8c1315822bbe71c17")
        self.assertEqual(canonical(PREFLIGHT.runtime_layout(self.dwarf)), canonical(self.actual))

    def test_generated_proof_binds_actual_layout_and_validates_without_launching_target(self):
        code, proof = self.generate()
        self.assertEqual(code, 0, proof)
        self.assertEqual(proof["schema"], "cs340-period-abi-proof-v2")
        self.assertEqual(proof["abi_profile"], "runtime-dwarf")
        self.assertEqual(proof["layout"], canonical(self.actual))
        self.assertEqual(proof["status"], "PASS")
        validated = self.validate()
        self.assertEqual(validated["layout"], canonical(self.actual))
        self.assertEqual(validated["map_size"], 24008)
        self.assertTrue(self.calls)
        self.assertTrue(all(argv[0] in ("readelf", "git") for argv in self.calls))

    def test_raw_driver_audit_is_not_a_compatible_historical_baseline(self):
        code, proof = self.generate()
        self.assertEqual(code, 0, proof)
        check = next(item for item in proof["checks"] if item["name"] == "raw_driver_abi_audit")
        self.assertEqual(check["status"], "PASS")
        audit = check["evidence"]
        self.assertEqual(audit["status"], "legacy_unverified")
        self.assertFalse(audit["compatible_with_runtime"])

    def test_profile_schema_status_and_blockers_cannot_be_waived(self):
        unused, original = self.generate()
        for field, value in (("schema", "cs340-period-abi-proof-v1"),
                             ("abi_profile", "legacy-fixed"), ("status", "BLOCKED"),
                             ("source_commit", "wrong-commit"), ("blockers", ["unchecked ABI"])):
            changed = copy.deepcopy(original)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises((ValueError, RuntimeError)):
                self.validate(changed)

    def test_legacy_layout_cannot_be_swapped_into_actual_runtime_proof(self):
        unused, proof = self.generate()
        proof["layout"] = PREFLIGHT.expected_layout()
        with self.assertRaises((ValueError, RuntimeError)):
            self.validate(proof)

    def test_tampered_layout_size_capacity_offset_and_unsigned_fields_are_rejected(self):
        unused, original = self.generate()
        changes = []
        changed = copy.deepcopy(original)
        changed["layout"]["byte_size"] = 24004
        changes.append(changed)
        for field, value in (("offset", 8146), ("dimensions", [1990]),
                             ("element_bytes", 4), ("unsigned", False)):
            changed = copy.deepcopy(original)
            changed["layout"]["members"][6][field] = value
            changes.append(changed)
        for changed in changes:
            with self.subTest(layout=changed["layout"]), self.assertRaises((ValueError, RuntimeError)):
                self.validate(changed)

    def test_binary_object_mismatch_is_rechecked_from_current_dwarf(self):
        self.generate()
        self.object_dwarf = PARSER_FIXTURES.dwarf_fixture(capacity=1990)
        with self.assertRaises((ValueError, RuntimeError)):
            self.validate()

    def test_signed_fields_and_false_offsets_in_current_dwarf_fail_closed(self):
        unused, original = self.generate()
        for changed_dwarf in (PARSER_FIXTURES.dwarf_fixture(capacity=3964, signed=True),
                              PARSER_FIXTURES.dwarf_fixture(capacity=3964, offset_overrides={"kpLoc": 8150})):
            self.binary_dwarf = changed_dwarf
            with self.subTest(dwarf=changed_dwarf[-100:]), self.assertRaises((ValueError, RuntimeError)):
                self.validate(original)

    def test_proof_check_set_is_exact_and_all_checks_must_pass(self):
        unused, original = self.generate()
        for removed in PREFLIGHT.V2_REQUIRED_CHECKS:
            changed = copy.deepcopy(original)
            changed["checks"] = [item for item in changed["checks"] if item["name"] != removed]
            with self.subTest(removed=removed), self.assertRaises((ValueError, RuntimeError)):
                self.validate(changed)
        for kind in ("duplicate", "failed", "unexpected"):
            changed = copy.deepcopy(original)
            if kind == "duplicate":
                changed["checks"].append(copy.deepcopy(changed["checks"][0]))
            elif kind == "failed":
                changed["checks"][0]["status"] = "BLOCKED"
            else:
                changed["checks"].append({"name": "waiver", "status": "PASS"})
            with self.subTest(kind=kind), self.assertRaises((ValueError, RuntimeError)):
                self.validate(changed)

    def test_current_binary_object_and_driver_hashes_are_rebound(self):
        unused, original = self.generate()
        for path in (self.target, self.runtime_object, self.driver, self.reference):
            before = path.read_bytes()
            path.write_bytes(before + b"changed")
            try:
                with self.subTest(path=str(path)), self.assertRaises((ValueError, RuntimeError)):
                    self.validate(original)
            finally:
                path.write_bytes(before)

    def test_changed_actual_source_is_not_hidden_by_recorded_head(self):
        self.generate()
        path = self.dbds / "run_PDS.py"
        raw = path.read_bytes()
        path.write_bytes(raw.replace(b"SHARE_ARRAY_SIZE = 1990", b"SHARE_ARRAY_SIZE = 3964", 1))
        with self.assertRaises((ValueError, RuntimeError)):
            self.validate()

    def test_current_observed_layout_evidence_cannot_disagree_with_proof(self):
        unused, original = self.generate()
        for key in ("binary", "runtime_object"):
            changed = copy.deepcopy(original)
            changed["observed_layouts"][key] = {}
            with self.subTest(key=key), self.assertRaises((ValueError, RuntimeError)):
                self.validate(changed)

    def test_shared_abi_layer_manifest_and_runtime_source_identity_are_not_waivers(self):
        unused, original = self.generate()
        for label in ("abi_layer_identity", "source_manifest_identity", "runtime_source_identity"):
            changed = copy.deepcopy(original)
            check = next(item for item in changed["checks"] if item["name"] == label)
            check["evidence"]["sha256"] = "0" * 64
            with self.subTest(label=label), self.assertRaises((ValueError, RuntimeError)):
                self.validate(changed)

    def test_raw_incompatible_driver_cannot_be_relabelled_compatible(self):
        unused, proof = self.generate()
        audit = next(item for item in proof["checks"] if item["name"] == "raw_driver_abi_audit")["evidence"]
        audit.update(status="compatible", compatible_with_runtime=True)
        with self.assertRaises((ValueError, RuntimeError)):
            self.validate(proof)

    def test_current_source_commit_and_clean_worktree_are_rechecked(self):
        unused, original = self.generate()
        self.git_head = "different-current-commit"
        with self.assertRaises((ValueError, RuntimeError)):
            self.validate(original)
        self.git_head = PREFLIGHT.COMMIT
        self.git_dirty = "tracked driver/runtime differences\n"
        with self.assertRaises((ValueError, RuntimeError)):
            self.validate(original)

    def test_missing_actual_raw_driver_never_certifies_historical_compatibility(self):
        (self.dbds / "run_PDS.py").unlink()
        code, proof = self.generate()
        self.assertNotEqual(code, 0)
        self.assertEqual(proof["status"], "BLOCKED")
        self.assertTrue(proof["blockers"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
