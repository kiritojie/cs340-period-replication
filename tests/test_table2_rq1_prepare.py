"""Prepare regressions for physical source paths and independent benchmarks.

All artifacts and external command responses here are synthetic. These checks
do not substitute for the native source identity, ABI or permission gates.
"""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_native():
    spec = importlib.util.spec_from_file_location(
        "rq1_prepare_native_under_test", ROOT / "scripts/table2_rq1_native.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


previous_path = list(sys.path)
sys.path.insert(0, str(ROOT / "scripts"))
try:
    if sys.platform == "win32":
        with mock.patch.dict(sys.modules, {"fcntl": types.ModuleType("fcntl")}):
            NATIVE = load_native()
    else:
        NATIVE = load_native()
finally:
    sys.path[:] = previous_path


class PrepareArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rq1-prepare-synthetic-", dir=str(ROOT))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.upstream = self.root / "PERIOD"
        self.benchmark = self.upstream / "evaluation/CS/reorder_3"
        self.benchmark.mkdir(parents=True)
        self.source = self.benchmark / "reorder_3_bad.c"
        self.source.write_text("/* synthetic tracked source */\nint main(void) { return 0; }\n")
        (self.benchmark / "reorder_3_bad").write_bytes(b"synthetic benchmark binary")
        (self.benchmark / "ConConfig.reorder_3_bad").write_text(
            "reorder_bad.c:71\nreorder_bad.c:72\nreorder_bad.c:78\n")
        runtime = self.upstream / "tool/staticAnalysis/DBDS-INSTRU"
        (runtime / "llvm-mode").mkdir(parents=True)
        (runtime / "DBDSFunction.o").write_bytes(b"synthetic runtime object")
        (runtime / "llvm-mode/DBDSFunction.cpp").write_text("/* synthetic runtime */\n")
        protocol = ROOT / "config/table2-rq1-protocol.json"
        if not protocol.is_file():
            protocol = ROOT / "protocol.json"
        self.protocol = json.loads(protocol.read_text())
        patcher = mock.patch.object(NATIVE, "UPSTREAM", self.upstream)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_physical_source_is_distinct_from_config_location_labels(self):
        manifest = NATIVE.inspect_manifest("reorder_3_bad", self.protocol)
        self.assertEqual(manifest["source"]["path"], str(self.source))
        self.assertEqual(manifest["source"]["sha256"], NATIVE.digest(self.source))
        self.assertEqual(manifest["static_keypoint_locations"], [
            "reorder_bad.c:71", "reorder_bad.c:72", "reorder_bad.c:78"])
        self.assertEqual(manifest["source_commit"], self.protocol["source_commit"])

        # A file named after the debug labels cannot replace the tracked source.
        self.source.rename(self.benchmark / "reorder_bad.c")
        with self.assertRaisesRegex(ValueError, "reorder_3_bad.c"):
            NATIVE.inspect_manifest("reorder_3_bad", self.protocol)

    def test_missing_other_benchmarks_preserve_reorder3_prepare_and_abi_gate(self):
        manifest = NATIVE.inspect_manifest("reorder_3_bad", self.protocol)
        cache = {"artifacts": {key: manifest[key]["sha256"] for key in (
            "binary", "config", "runtime_object", "runtime_source")},
            "runtime_profile": {"benchmark": "reorder_3_bad", "threads": 3,
                                "matrix_width": 2, "kps": [2, 2, 1]}}
        (self.root / "pilot-cache.json").write_text(json.dumps(cache))
        output = self.root / "prepare"
        output.mkdir()
        state = {"benchmarks": {}}
        commands = mock.Mock()

        def external_command(label, argv, **kwargs):
            if label == "linux-unittests":
                return 0, b"", b"Ran 1 test in 0.001s\n\nOK\n"
            if label.startswith("abi-"):
                proof = Path(argv[argv.index("--output") + 1])
                proof.write_text('{"synthetic_external_response": true}\n')
            return 0, b"", b""

        commands.run.side_effect = external_command
        original_source_hash = NATIVE.digest(self.source)
        with mock.patch.object(NATIVE.subprocess, "check_output", return_value=(
                self.protocol["source_commit"] + "\n").encode("ascii")):
            NATIVE.prepare(self.root, output, self.protocol, commands, state)

        self.assertEqual(state["status"], "PREPARED_WITH_BLOCKED_BENCHMARKS")
        item = state["benchmarks"]["reorder_3_bad"]
        self.assertEqual(item["status"], "ADAPTATION_VERIFIED_FROM_FROZEN_PILOT")
        self.assertEqual(item["runtime_profile"], cache["runtime_profile"])
        self.assertTrue(Path(item["abi_proof"]).is_file())
        snapshot = output / "reorder_3_bad/benchmark-source.c"
        self.assertEqual(NATIVE.digest(snapshot), original_source_hash)
        self.assertEqual(NATIVE.digest(self.source), original_source_hash)
        inventory = json.loads((output / "reorder_3_bad/inventory.json").read_text())
        self.assertTrue(inventory[str(self.source)]["exists"])
        self.assertNotIn(str(self.benchmark / "reorder_bad.c"), inventory)

        calls = {call[0][0]: call[0][1] for call in commands.run.call_args_list}
        abi = calls["abi-reorder_3_bad"]
        self.assertEqual(abi[abi.index("--benchmark-manifest") + 1], item["manifest"])
        self.assertEqual(abi[abi.index("--abi-profile") + 1], "runtime-dwarf")
        for benchmark in ("reorder_4_bad", "reorder_5_bad", "reorder_10_bad"):
            blocked = state["benchmarks"][benchmark]
            self.assertEqual(blocked["status"], "BLOCKED")
            self.assertIn(benchmark + ".c", blocked["reason"])
            self.assertNotIn("manifest", blocked)
            self.assertNotIn("abi-" + benchmark, calls)


if __name__ == "__main__":
    unittest.main()
