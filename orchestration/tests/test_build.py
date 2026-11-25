"""Necessary product-preservation and failure-scope checks; no real build."""
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("rq1_build_under_test", ROOT / "orchestration/rq1_build.py")
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class BuildPreservationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rq1-build-synthetic-", dir=str(ROOT))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_exclusive_publication_preserves_existing_binary_and_config(self):
        produced = self.root / "new-product"
        produced.write_bytes(b"new compiled bytes")
        existing = self.root / "reorder_4_bad"
        existing.write_bytes(b"existing historical bytes")
        with self.assertRaises(FileExistsError):
            BUILD.exclusive_publish(produced, existing)
        self.assertEqual(existing.read_bytes(), b"existing historical bytes")
        destination = self.root / "ConConfig.reorder_4_bad"
        BUILD.exclusive_publish(produced, destination)
        self.assertEqual(destination.read_bytes(), produced.read_bytes())
        with self.assertRaises(FileExistsError):
            BUILD.exclusive_publish(produced, destination)

    def test_static_thread_defaults_are_checked_without_inventing_runtime_kps(self):
        source = self.root / "reorder_5_bad.c"
        source.write_text('static int iSet = 4;\nstatic int iCheck = 1;\n')
        self.assertEqual(BUILD.source_threads(source, 5), {"iSet": 4, "iCheck": 1})
        with self.assertRaisesRegex(ValueError, "selected benchmark"):
            BUILD.source_threads(source, 3)
        source.write_text('static int iSet = 4;\nstatic int iSet = 4;\nstatic int iCheck = 1;\n')
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            BUILD.source_threads(source, 5)

    def test_unknown_tool_and_watchdog_failures_are_not_program_local(self):
        for code in (None, 124, 125, 126, 127, 137, -9):
            command = types.SimpleNamespace(run=lambda *args, **kwargs: ({"exit_code": code}, b"", b""))
            with self.subTest(exit_code=code), self.assertRaises(ValueError) as caught:
                BUILD.build_command(command, "compile", ["clang", "source.c"])
            self.assertNotIsInstance(caught.exception, BUILD.BenchmarkBuildFailure)
        ordinary = types.SimpleNamespace(run=lambda *args, **kwargs: ({"exit_code": 1}, b"", b"syntax error"))
        with self.assertRaises(BUILD.BenchmarkBuildFailure) as caught:
            BUILD.build_command(ordinary, "compile", ["clang", "source.c"])
        self.assertEqual(caught.exception.kind, "COMPILER_FAILURE")

    def test_failed_compile_keeps_durable_attempt_and_completed_reorder3(self):
        upstream = self.root / "PERIOD"
        directory = upstream / "evaluation/CS/reorder_4"
        directory.mkdir(parents=True)
        source = directory / "reorder_4_bad.c"
        source.write_text("static int iSet = 3;\nstatic int iCheck = 1;\n")
        output = self.root / "build-evidence"
        output.mkdir()
        state = {"reorder3_formal_complete": True, "benchmarks": {
            "reorder_3_bad": {"formal_complete": True, "retained_identity": "historical"},
            "reorder_4_bad": {"status": "BLOCKED"}}}
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

        def require(condition, reason):
            if not condition:
                raise ValueError(reason)

        def write_json(path, value):
            with Path(path).open("x") as stream:
                json.dump(value, stream)

        def checkpoint(root, current):
            (root / "state.json").write_text(json.dumps(current))

        native = types.SimpleNamespace(UPSTREAM=upstream, require=require,
            write_json=write_json, checkpoint=checkpoint,
            digest=lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest())

        def failed_compile(label, argv, **kwargs):
            saved = json.loads((self.root / "state.json").read_text())
            self.assertTrue(saved["benchmarks"]["reorder_4_bad"]["build_attempted"])
            self.assertTrue(saved["reorder3_formal_complete"])
            return {"exit_code": 1}, b"", b"synthetic compile error"

        with mock.patch.object(BUILD, "verify_source", return_value={
                "path": str(source), "sha256": source_hash, "git_blob_sha1": "synthetic"}):
            with self.assertRaises(BUILD.BenchmarkBuildFailure):
                BUILD.build_one(self.root, output, "reorder_4_bad", native, state, {},
                                types.SimpleNamespace(run=failed_compile))
        self.assertEqual(state["benchmarks"]["reorder_3_bad"], {
            "formal_complete": True, "retained_identity": "historical"})
        self.assertNotIn("manifest", state["benchmarks"]["reorder_4_bad"])
        self.assertEqual(native.digest(source), source_hash)
        self.assertFalse((directory / "reorder_4_bad").exists())


if __name__ == "__main__":
    unittest.main()
