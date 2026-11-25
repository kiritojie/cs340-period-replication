"""Frozen per-benchmark identities; synthetic bytes, read-only mocked inspection."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "formal_preflight_fixture", ROOT / "tests/test_table2_abi_proof_v2.py")
FIXTURES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURES)
PREFLIGHT = FIXTURES.PREFLIGHT


class FormalBenchmarkPreflightTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FIXTURES.RuntimeDwarfProofTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.manifest_path = self.fixture.base / "benchmark.json"
        self.base_command = self.fixture.command

    def select_program(self, benchmark):
        fixture = self.fixture
        directory = fixture.upstream / "evaluation/CS" / benchmark[:-4]
        directory.mkdir(parents=True, exist_ok=True)
        fixture.target = directory / benchmark
        fixture.target.write_bytes(("synthetic ELF identity: " + benchmark).encode("ascii"))
        fixture.config = directory / ("ConConfig." + benchmark)
        fixture.config.write_bytes(("synthetic config: " + benchmark).encode("ascii"))
        self.source = directory / "reorder_bad.c"
        self.source.write_text("/* pinned synthetic source */\n", encoding="utf-8")
        raw = self.source.read_bytes()
        self.source_blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
        identities = {"binary": fixture.target, "config": fixture.config,
                      "runtime_object": fixture.runtime_object, "runtime_source": fixture.runtime_source,
                      "source": self.source}
        self.manifest = {"schema": PREFLIGHT.BENCHMARK_MANIFEST_SCHEMA,
                         "benchmark": benchmark, "threads": PREFLIGHT.BENCHMARK_THREADS[benchmark],
                         "source_commit": PREFLIGHT.COMMIT}
        self.manifest.update({label: {"path": str(path.resolve()), "sha256": PREFLIGHT.sha256(path)}
                              for label, path in identities.items()})
        self.write_manifest()

    def write_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def command(self, argv):
        if argv[0] == "git" and "rev-parse" in argv and ":evaluation/CS/" in argv[-1]:
            self.fixture.calls.append(list(argv))
            return self.source_blob + "\n"
        return self.base_command(argv)

    @contextlib.contextmanager
    def environment(self):
        with mock.patch.object(self.fixture, "command", side_effect=self.command), \
                self.fixture.synthetic_environment(), \
                mock.patch.dict(PREFLIGHT.os.environ, {"Con_PATH": str(self.fixture.config.resolve())}):
            yield

    def generate(self):
        fixture = self.fixture
        args = ["--binary", str(fixture.target), "--config", str(fixture.config),
                "--runtime-object", str(fixture.runtime_object), "--runtime-source", str(fixture.runtime_source),
                "--upstream", str(fixture.upstream), "--driver", str(fixture.driver),
                "--output", str(fixture.proof_path), "--abi-profile", "runtime-dwarf",
                "--benchmark-manifest", str(self.manifest_path)]
        with self.environment(), contextlib.redirect_stdout(io.StringIO()):
            code = PREFLIGHT.main(args)
        return code, json.loads(fixture.proof_path.read_text())

    def validate(self, target=None):
        fixture = self.fixture
        with self.environment():
            return PREFLIGHT.validate_abi_proof(fixture.proof_path, target or fixture.target, fixture.dbds)

    def test_all_four_names_bind_inspected_identity_and_actual_dwarf_without_launch(self):
        for benchmark in PREFLIGHT.BENCHMARK_THREADS:
            with self.subTest(benchmark=benchmark):
                self.select_program(benchmark)
                code, proof = self.generate()
                self.assertEqual(code, 0, proof)
                self.assertEqual(proof["status"], "PASS")
                self.assertEqual(len(proof["checks"]), 25)
                checked = self.validate()
                self.assertEqual(checked["benchmark"], benchmark)
                self.assertEqual(checked["threads"], PREFLIGHT.BENCHMARK_THREADS[benchmark])
                self.assertEqual(checked["map_size"], 24008)
                self.assertTrue(all(c[0] in ("git", "readelf") for c in self.fixture.calls))
                # Each subcase has its own immutable proof/DWARF output names.
                self.fixture.proof_path = self.fixture.base / (benchmark + "-next-proof.json")
                for filename in ("binary-dwarf.txt", "runtime_object-dwarf.txt"):
                    (self.fixture.base / filename).unlink()

    def test_target_copy_is_allowed_but_wrong_name_and_config_are_not(self):
        self.select_program("reorder_4_bad")
        self.assertEqual(self.generate()[0], 0)
        work = self.fixture.base / "work"
        work.mkdir()
        copy_target = work / "reorder_4_bad"
        copy_target.write_bytes(self.fixture.target.read_bytes())
        copy_config = work / "ConConfig.reorder_4_bad"
        copy_config.write_bytes(self.fixture.config.read_bytes())
        # The fixture's readelf adapter accepts only its originally selected
        # target. Rebind that read-only fixture for the identical copied bytes.
        original_target = self.fixture.target
        original_config = self.fixture.config
        original_proof = self.fixture.proof_path
        self.fixture.target = copy_target
        self.fixture.config = copy_config
        try:
            self.assertEqual(self.validate(copy_target)["benchmark"], "reorder_4_bad")
            self.fixture.proof_path = work / "copy-proof.json"
            self.assertEqual(self.generate()[0], 0)
            self.assertEqual(self.validate(copy_target)["benchmark"], "reorder_4_bad")
        finally:
            self.fixture.target = original_target
            self.fixture.config = original_config
            self.fixture.proof_path = original_proof
        bad = work / "reorder_5_bad"
        bad.write_bytes(original_target.read_bytes())
        with self.assertRaisesRegex(ValueError, "current binary"):
            self.validate(bad)
        with self.environment(), mock.patch.dict(PREFLIGHT.os.environ, {"Con_PATH": str(bad)}):
            with self.assertRaisesRegex(ValueError, "current config"):
                PREFLIGHT.validate_abi_proof(self.fixture.proof_path, original_target, self.fixture.dbds)

    def test_manifest_commit_threads_scope_or_current_hash_cannot_be_waived(self):
        self.select_program("reorder_5_bad")
        original = copy.deepcopy(self.manifest)
        changes = [("source_commit", "changed"), ("threads", 3), ("benchmark", "reorder_20_bad")]
        for key, value in changes:
            self.manifest = copy.deepcopy(original)
            self.manifest[key] = value
            self.write_manifest()
            with self.environment(), self.subTest(key=key), self.assertRaises(ValueError):
                PREFLIGHT.verify_benchmark_manifest(self.manifest_path, self.fixture.upstream)
        self.manifest = original
        self.write_manifest()
        self.fixture.config.write_bytes(b"changed after freeze")
        with self.environment(), self.assertRaisesRegex(ValueError, "config changed"):
            PREFLIGHT.verify_benchmark_manifest(self.manifest_path, self.fixture.upstream)

    def test_pinned_source_blob_is_verified_even_if_manifest_source_hash_is_updated(self):
        self.select_program("reorder_10_bad")
        self.source.write_text("/* changed source */\n", encoding="utf-8")
        self.manifest["source"]["sha256"] = PREFLIGHT.sha256(self.source)
        self.write_manifest()
        with self.environment(), self.assertRaisesRegex(ValueError, "pinned commit"):
            PREFLIGHT.verify_benchmark_manifest(self.manifest_path, self.fixture.upstream)

    def test_proof_manifest_and_abi_cannot_change_after_preflight(self):
        self.select_program("reorder_4_bad")
        self.assertEqual(self.generate()[0], 0)
        self.manifest["threads"] = 5
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "manifest changed"):
            self.validate()
        self.manifest["threads"] = 4
        self.write_manifest()
        self.fixture.object_dwarf = FIXTURES.PARSER_FIXTURES.dwarf_fixture(capacity=1990)
        with self.assertRaises((ValueError, RuntimeError)):
            self.validate()


if __name__ == "__main__":
    unittest.main()
