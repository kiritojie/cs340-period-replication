"""Execute ABI-adapted IPC helpers against guarded local buffers, never SysV IPC."""
import ast
import ctypes
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "scripts/vendor/period_b6f72a7"
FIXTURE = ROOT / "tests/fixtures/period_runtime_3964_layout.json"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def ast_module(nodes):
    tree = ast.Module(body=nodes, type_ignores=[])
    return ast.fix_missing_locations(tree)


class AbiAdaptedDriverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = load("period_shared_memory_driver_test", ROOT / "scripts/period_shared_memory.py")
        cls.driver = load("comparison_abi_driver_test", ROOT / "scripts/run_scheduler_comparison.py")
        cls.original = (VENDOR / "run_PDS.py").read_text(encoding="utf-8")
        cls.adapted = cls.driver.prepare_abi_source(cls.original)
        cls.tree = ast.parse(cls.adapted)
        cls.observed = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def setUp(self):
        self.abi = self.shared.MemoryABI.from_layout(self.observed)
        self.buffer = (ctypes.c_ubyte * (24008 + 128))()
        ctypes.memset(ctypes.addressof(self.buffer), 0xA5, ctypes.sizeof(self.buffer))
        self.address = ctypes.addressof(self.buffer) + 64
        self.abi.clear(self.address)
        self.namespace = dict(vars(ctypes))
        self.namespace.update({"_comparison_abi": self.abi, "ADDR": self.address})
        wanted = {"PeriodABIError", "_abi_checked", "setup_share_memroy",
                  "get_info_from_share_memory", "memmove_pattern_list"}
        definitions = [node for node in self.tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in wanted]
        self.assertEqual({node.name for node in definitions}, wanted)
        exec(compile(ast_module(definitions), "<real-adapted-ipc-helpers>", "exec"), self.namespace)
        arrays = {"kpNumArray", "kpYieldArray", "kpLocArray", "kpOrderArray"}
        assignments = [node for node in self.tree.body if isinstance(node, ast.Assign) and
                       len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in arrays]
        self.assertEqual(len(assignments), 4)
        exec(compile(ast_module(assignments), "<real-adapted-receiving-arrays>", "exec"), self.namespace)

    def assert_guards(self):
        raw = bytes(self.buffer)
        self.assertEqual(raw[:64], b"\xA5" * 64)
        self.assertEqual(raw[-64:], b"\xA5" * 64)

    def test_actual_adapted_array_constructors_have_runtime_capacity(self):
        self.assertEqual(len(self.namespace["kpNumArray"]), 100)
        for local in ("kpYieldArray", "kpLocArray", "kpOrderArray"):
            self.assertEqual(len(self.namespace[local]), 3964)
            self.assertEqual(ctypes.sizeof(self.namespace[local]), 7928)

    def test_actual_helper_reads_all_fields_including_beyond_legacy_1990(self):
        for field, value in (("time", 9876543210123), ("N", 3), ("M", 2), ("TestedBounds", 4)):
            self.abi.write_scalar(self.address, field, value)
        expected = {}
        for index, field in enumerate(("kpNumArray", "kp", "kpLoc", "kpOrder"), 1):
            count = 100 if field == "kpNumArray" else 3964
            values = [(index * 1000 + position) % 65536 for position in range(count)]
            self.abi.write_array(self.address, field, values)
            expected[field] = values
        p, a, b, t = ctypes.c_uint64(), ctypes.c_uint32(), ctypes.c_uint32(), ctypes.c_uint32()
        self.namespace["get_info_from_share_memory"](p, a, b, t,
            self.namespace["kpNumArray"], self.namespace["kpYieldArray"],
            self.namespace["kpLocArray"], self.namespace["kpOrderArray"])
        self.assertEqual((p.value, a.value, b.value, t.value), (9876543210123, 3, 2, 4))
        for local, field in (("kpNumArray", "kpNumArray"), ("kpYieldArray", "kp"),
                             ("kpLocArray", "kpLoc"), ("kpOrderArray", "kpOrder")):
            self.assertEqual(list(self.namespace[local]), expected[field])
        self.assert_guards()

    def test_old_receiving_array_is_fatal_instead_of_partial_read_or_swallowed_exception(self):
        old = (ctypes.c_uint16 * 1990)()
        with self.assertRaises(self.namespace["PeriodABIError"]):
            self.namespace["get_info_from_share_memory"](kpLocArray=old)
        self.assert_guards()

    def test_runtime_dimension_growth_cannot_enter_feedback_with_an_oversized_slice(self):
        for n, m in ((101, 1), (100, 40), (1, 3965)):
            with self.subTest(n=n, m=m):
                self.abi.write_scalar(self.address, "N", n)
                self.abi.write_scalar(self.address, "M", m)
                a, b = ctypes.c_uint32(), ctypes.c_uint32()
                receiving = (ctypes.c_uint16 * 3964)()
                with self.assertRaises(self.namespace["PeriodABIError"]):
                    self.namespace["get_info_from_share_memory"](A=a, B=b, kpLocArray=receiving)
                self.assertEqual(list(receiving), [0] * 3964,
                                 "invalid header must stop before copying feedback arrays")
                self.assert_guards()

    def test_zero_runtime_header_is_preserved_for_upstream_diagnostic(self):
        self.abi.write_scalar(self.address, "N", 0)
        self.abi.write_scalar(self.address, "M", 0)
        a, b = ctypes.c_uint32(9), ctypes.c_uint32(9)
        self.namespace["get_info_from_share_memory"](A=a, B=b)
        self.assertEqual((a.value, b.value), (0, 0))
        self.assert_guards()

    def test_actual_pattern_writer_uses_common_layer_and_clears_tail_only(self):
        self.abi.write_scalar(self.address, "N", 3)
        self.abi.write_scalar(self.address, "M", 2)
        self.abi.write_array(self.address, "kpLoc", [55] * 3964)
        self.abi.write_array(self.address, "kpOrder", [66] * 3964)
        self.abi.write_array(self.address, "kp", [77] * 3964)
        self.namespace["memmove_pattern_list"]([[0, 2], [2, 0], [1, 0]])
        self.assertEqual(self.abi.read_array(self.address, "kp"), [0, 2, 2, 0, 1, 0] + [0] * 3958)
        self.assertEqual(self.abi.read_array(self.address, "kpLoc"), [55] * 3964)
        self.assertEqual(self.abi.read_array(self.address, "kpOrder"), [66] * 3964)
        self.assertEqual((self.abi.read_scalar(self.address, "N"), self.abi.read_scalar(self.address, "M")), (3, 2))
        self.assert_guards()

    def test_invalid_pattern_escapes_original_exception_handler_without_writing(self):
        before = bytes(self.buffer)
        caught_fatal = False
        try:
            try:
                self.namespace["memmove_pattern_list"]([[0, 65536]])
            except Exception:
                self.fail("the original broad Exception handler could hide an ABI error")
        except self.namespace["PeriodABIError"]:
            caught_fatal = True
        self.assertTrue(caught_fatal)
        self.assertEqual(bytes(self.buffer), before)

    def test_actual_setup_passes_the_proven_abi_without_clearing(self):
        sentinel = object()
        setup = mock.Mock(return_value=self.address)
        self.namespace["_comparison_setup_share_memory"] = setup
        self.namespace["CDLL"] = mock.Mock(return_value=sentinel)
        # Keep both possible ctypes spellings observable; no libc is loaded.
        self.namespace["cdll"] = types.SimpleNamespace(LoadLibrary=mock.Mock(return_value=sentinel))
        before = bytes(self.buffer)
        self.assertEqual(self.namespace["setup_share_memroy"](), self.address)
        setup.assert_called_once_with(sentinel, self.abi)
        self.assertEqual(bytes(self.buffer), before)

    def test_all_scalar_write_sites_execute_through_field_names(self):
        calls = [node for node in ast.walk(self.tree) if isinstance(node, ast.Call) and
                 isinstance(node.func, ast.Name) and node.func.id == "_abi_checked" and node.args and
                 isinstance(node.args[0], ast.Attribute) and node.args[0].attr == "write_scalar"]
        self.assertEqual(len(calls), 11)
        self.namespace.update({"Period": 7, "threadNum": 3, "KPNum": 2, "maxYieldNum": 8,
                               "N": 3, "M": 2, "iterPeriod": 5})
        for call in calls:
            with self.subTest(call=ast.dump(call)):
                self.abi.clear(self.address)
                field = ast.literal_eval(call.args[2])
                expected = eval(compile(ast.Expression(call.args[3]), "<scalar-input>", "eval"), self.namespace)
                exec(compile(ast_module([ast.Expr(value=call)]), "<actual-scalar-write-site>", "exec"), self.namespace)
                self.assertEqual(self.abi.read_scalar(self.address, field), expected)
                self.assert_guards()

    def test_serial_uses_real_final_period_index_even_with_different_logical_depth(self):
        prepared = self.driver.prepare_driver_source(self.adapted, "serial")
        tree = ast.parse(prepared)
        call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call) and
                    isinstance(node.func, ast.Name) and node.func.id == "_abi_checked" and
                    len(node.args) == 4 and isinstance(node.args[0], ast.Attribute) and
                    node.args[0].attr == "write_scalar" and ast.literal_eval(node.args[2]) == "TestedBounds" and
                    isinstance(node.args[3], ast.BinOp) and isinstance(node.args[3].left, ast.Name) and
                    node.args[3].left.id == "iterPeriod")
        self.namespace.update(iterPeriod=5, N_after_DryRun=3)
        exec(compile(ast_module([ast.Expr(value=call)]), "<actual-serial-period-write>", "exec"), self.namespace)
        self.assertEqual(self.abi.read_scalar(self.address, "TestedBounds"), 4)
        self.assertEqual(self.driver.logical_depth("serial", 5, 3), 3)

    def test_abi_only_source_preserves_official_generators_and_error_classification(self):
        original_tree = ast.parse(self.original)
        def generators(tree):
            return [ast.dump(node) for node in ast.walk(tree) if isinstance(node, ast.Call) and
                    isinstance(node.func, ast.Name) and node.func.id == "SBPMESched"]
        self.assertEqual(generators(self.tree), generators(original_tree))
        for name in ("record_error_message", "record_timeout_message"):
            original = next(node for node in original_tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
            corrected = next(node for node in self.tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
            self.assertEqual(ast.dump(corrected), ast.dump(original))
        forbidden = {"memmove", "memset", "shmget", "shmat"}
        calls = {node.func.id for node in ast.walk(self.tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertFalse(forbidden & calls)
        for mode in ("parallel", "serial"):
            compile(self.driver.prepare_driver_source(self.adapted, mode), "<abi-and-controller>", "exec")

    def test_reference_distinguishes_normal_final_exit_from_early_abort_without_target(self):
        before = list(sys.path)
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            reference = load("abi_reference_exit_test", ROOT / "scripts/run_abi_parallel_reference.py")
        finally:
            sys.path[:] = before
        filename = "<abi-reference-no-target>"
        final_line = reference._normal_exit_line(self.adapted)
        final = ast.parse(self.adapted).body[-1]
        try:
            exec(compile(ast_module([final]), filename, "exec"), {"exit": sys.exit})
        except SystemExit as error:
            self.assertTrue(reference._exit_reached(error, filename, final_line))
            self.assertFalse(reference._exit_reached(error, "<other-source>", final_line))
        else:
            self.fail("normal reference footer did not retain its original exit")
        try:
            exec(compile("raise SystemExit(0)", filename, "exec"), {})
        except SystemExit as error:
            self.assertFalse(reference._exit_reached(error, filename, final_line),
                             "a silent early exit must not become a passed reference run")


if __name__ == "__main__":
    unittest.main(verbosity=2)
