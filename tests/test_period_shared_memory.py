"""ABI transport tests on local guarded buffers; no native IPC or target runs.

The fixture is the unchanged observed executable layout from
docs/results/table2-rootful-resume-20261124T220134-l76oqi5n/
binary-observed-layout.json, SHA-256
5889aed8e923b6e177d1cc1b0213a4d8b8e052cf3f334ca8c1315822bbe71c17.
It lives in tests/fixtures so the container's isolated test harness can use it.
"""
import copy
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/period_runtime_3964_layout.json"
FAILURE = (ValueError, TypeError, KeyError, OverflowError)
OFFSETS = {"time": 0, "N": 8, "M": 12, "TestedBounds": 16,
           "kpNumArray": 20, "kp": 220, "kpLoc": 8148, "kpOrder": 16076}


def load_abi():
    path = ROOT / "scripts/period_shared_memory.py"
    spec = importlib.util.spec_from_file_location("period_shared_memory_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ObservedLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_abi()
        cls.observed = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_is_actual_failure_evidence_bytes(self):
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
                         "5889aed8e923b6e177d1cc1b0213a4d8b8e052cf3f334ca8c1315822bbe71c17")

    def test_all_actual_offsets_capacities_and_size_match_ctypes(self):
        original = copy.deepcopy(self.observed)
        abi = self.module.MemoryABI.from_layout(self.observed)
        self.assertEqual(self.observed, original, "constructing ABI must not rewrite evidence")
        self.assertEqual(abi.map_size, 24008)
        self.assertEqual(ctypes.sizeof(abi.structure_type), 24008)
        self.assertEqual((abi.thread_capacity, abi.point_capacity), (100, 3964))
        types = dict(abi.structure_type._fields_)
        for name, offset in OFFSETS.items():
            with self.subTest(field=name):
                self.assertEqual(abi.field_offset(name), offset)
                self.assertEqual(getattr(abi.structure_type, name).offset, offset)
                if name in ("kp", "kpLoc", "kpOrder", "kpNumArray"):
                    count = 100 if name == "kpNumArray" else 3964
                    self.assertEqual(types[name]._length_, count)
                    self.assertEqual(ctypes.sizeof(types[name]._type_), 2)
                    self.assertEqual(abi.field_bytes(name), count * 2)
                else:
                    width = 8 if name == "time" else 4
                    self.assertEqual(ctypes.sizeof(types[name]), width)
                    self.assertEqual(abi.field_bytes(name), width)

    def test_wrong_field_size_sign_offset_name_order_or_missing_field_is_rejected(self):
        changes = []
        value = copy.deepcopy(self.observed); value["byte_size"] = 24004; changes.append(value)
        value = copy.deepcopy(self.observed); value["members"][5]["element_bytes"] = 4; changes.append(value)
        value = copy.deepcopy(self.observed); value["members"][6]["unsigned"] = False; changes.append(value)
        value = copy.deepcopy(self.observed); value["members"][6]["offset"] = 4200; changes.append(value)
        value = copy.deepcopy(self.observed); value["members"][7]["name"] = "unknown"; changes.append(value)
        value = copy.deepcopy(self.observed); value["members"].reverse(); changes.append(value)
        value = copy.deepcopy(self.observed); value["members"].pop(); changes.append(value)
        for layout in changes:
            with self.subTest(layout=layout), self.assertRaises(FAILURE):
                self.module.MemoryABI.from_layout(layout)

    def test_point_capacities_must_be_equal_and_dimensions_must_be_constant(self):
        changes = []
        for dimensions in ([], [3963], [3964, 1], [0], [-1], [True], ["3964"]):
            value = copy.deepcopy(self.observed)
            value["members"][6]["dimensions"] = dimensions
            changes.append(value)
        value = copy.deepcopy(self.observed); value["members"][4]["dimensions"] = [99]; changes.append(value)
        for layout in changes:
            with self.subTest(layout=layout), self.assertRaises(FAILURE):
                self.module.MemoryABI.from_layout(layout)


class GuardedMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_abi()
        cls.layout = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def setUp(self):
        self.abi = self.module.MemoryABI.from_layout(self.layout)
        self.guard = 64
        self.buffer = (ctypes.c_ubyte * (24008 + 2 * self.guard))()
        ctypes.memset(ctypes.addressof(self.buffer), 0xA5, ctypes.sizeof(self.buffer))
        self.address = ctypes.addressof(self.buffer) + self.guard
        ctypes.memset(self.address, 0xCC, 24008)
        self.assertEqual(self.address % ctypes.alignment(self.abi.structure_type), 0)

    def bytes(self):
        return ctypes.string_at(self.address, 24008)

    def assert_guards(self):
        raw = bytes(self.buffer)
        self.assertEqual(raw[:self.guard], b"\xA5" * self.guard)
        self.assertEqual(raw[-self.guard:], b"\xA5" * self.guard)

    def assert_atomic_failure(self, callback):
        before = bytes(self.buffer)
        with self.assertRaises(FAILURE):
            callback()
        self.assertEqual(bytes(self.buffer), before)
        self.assert_guards()

    def test_clear_covers_struct_including_padding_and_preserves_canaries(self):
        self.abi.clear(self.address)
        self.assertEqual(self.bytes(), b"\0" * 24008)
        self.assert_guards()

    def test_scalar_read_write_uses_actual_offsets_and_unsigned_widths(self):
        values = {"time": 2 ** 64 - 1, "N": 3, "M": 2, "TestedBounds": 2 ** 32 - 1}
        for name, value in values.items():
            self.abi.write_scalar(self.address, name, value)
            self.assertEqual(self.abi.read_scalar(self.address, name), value)
            fmt = "<Q" if name == "time" else "<I"
            self.assertEqual(struct.unpack_from(fmt, self.bytes(), OFFSETS[name])[0], value)
        self.assert_guards()

    def test_scalar_overflow_negative_bool_and_fraction_never_partly_write(self):
        for name, bits in (("time", 64), ("N", 32), ("M", 32), ("TestedBounds", 32)):
            for value in (-1, 2 ** bits, True, 1.5, "1"):
                with self.subTest(field=name, value=value):
                    self.assert_atomic_failure(lambda: self.abi.write_scalar(self.address, name, value))

    def test_each_array_first_and_final_elements_use_actual_field_bounds(self):
        for name, count in (("kpNumArray", 100), ("kp", 3964), ("kpLoc", 3964), ("kpOrder", 3964)):
            with self.subTest(field=name):
                self.abi.clear(self.address)
                self.abi.write_array(self.address, name, [17], start=0)
                self.abi.write_array(self.address, name, [65535], start=count - 1)
                values = self.abi.read_array(self.address, name)
                self.assertEqual(len(values), count)
                self.assertEqual(values[0], 17)
                self.assertEqual(values[-1], 65535)
                self.assertEqual(values[1:-1], [0] * (count - 2))
                self.assertEqual(struct.unpack_from("<H", self.bytes(), OFFSETS[name])[0], 17)
                self.assertEqual(struct.unpack_from("<H", self.bytes(), OFFSETS[name] + 2 * (count - 1))[0], 65535)
                self.assert_guards()

    def test_array_bounds_values_and_wrong_field_kind_fail_without_writes(self):
        for name, count in (("kpNumArray", 100), ("kp", 3964), ("kpLoc", 3964), ("kpOrder", 3964)):
            cases = (([1], -1), ([1], count), ([1, 2], count - 1), ([0] * (count + 1), 0),
                     ([1, -1], 0), ([1, 65536], 0), ([True], 0), ([1.5], 0), ([1], True))
            for values, start in cases:
                with self.subTest(field=name, start=start, length=len(values)):
                    self.assert_atomic_failure(lambda: self.abi.write_array(self.address, name, values, start=start))
            for count_value in (-1, count + 1, True, 0.5):
                with self.subTest(field=name, count=count_value), self.assertRaises(FAILURE):
                    self.abi.read_array(self.address, name, count=count_value)
        for callback in (lambda: self.abi.write_scalar(self.address, "kp", 1),
                         lambda: self.abi.write_array(self.address, "N", [1]),
                         lambda: self.abi.write_scalar(self.address, "unknown", 1),
                         lambda: self.abi.write_array(self.address, "unknown", [1])):
            self.assert_atomic_failure(callback)

    def test_invalid_address_is_rejected_before_any_ctypes_access(self):
        for address in (0, -1, True, None):
            with self.subTest(address=address):
                for callback in (lambda: self.abi.clear(address),
                                 lambda: self.abi.read_scalar(address, "N"),
                                 lambda: self.abi.write_scalar(address, "N", 1),
                                 lambda: self.abi.read_array(address, "kp"),
                                 lambda: self.abi.write_array(address, "kp", [1])):
                    with self.assertRaises(FAILURE):
                        callback()
        self.assert_guards()

    def test_yield_write_clears_entire_unused_kp_tail_and_nothing_else(self):
        before = self.bytes()
        pattern = [[0, 2], [2, 0], [1, 0]]
        self.abi.write_yield_pattern(self.address, pattern, n=3, m=2)
        actual = self.bytes()
        expected_kp = struct.pack("<6H", 0, 2, 2, 0, 1, 0) + b"\0" * (2 * (3964 - 6))
        self.assertEqual(actual[220:8148], expected_kp)
        self.assertEqual(actual[:220], before[:220])
        self.assertEqual(actual[8148:], before[8148:])
        self.assert_guards()

    def test_yield_shape_values_and_total_capacity_are_checked_atomically(self):
        cases = [([], 0, 0), ([[0]], 101, 1), ([[0, 0]], 1, 3965),
                 ([[0] * 40 for unused in range(100)], 100, 40),
                 ([[0, 0], [0]], 2, 2), ([[0, 0]], 2, 2),
                 ([[0, 65536]], 1, 2), ([[0, -1]], 1, 2), ([[0, True]], 1, 2),
                 ([[0]], True, 1), ([[0]], 1, True)]
        for pattern, n, m in cases:
            with self.subTest(n=n, m=m):
                self.assert_atomic_failure(lambda: self.abi.write_yield_pattern(self.address, pattern, n=n, m=m))

    def test_large_valid_pattern_exceeds_legacy_capacity_but_fits_actual_buffer(self):
        pattern = [[(thread + point) % 65536 for point in range(39)] for thread in range(100)]
        self.abi.write_yield_pattern(self.address, pattern, n=100, m=39)
        flattened = [value for row in pattern for value in row]
        values = self.abi.read_array(self.address, "kp")
        self.assertEqual(values[:3900], flattened)
        self.assertEqual(values[3900:], [0] * 64)
        self.assert_guards()

    def test_runtime_dimensions_validate_total_capacity_and_only_explicit_zero_state(self):
        self.assertEqual(self.abi.validate_dimensions(3, 2), (3, 2))
        self.assertEqual(self.abi.validate_dimensions(100, 39), (100, 39))
        self.assertEqual(self.abi.validate_dimensions(0, 0, allow_zero=True), (0, 0))
        for n, m in ((101, 1), (100, 40), (1, 3965), (True, 1), (1, True), (-1, 1), (1, -1), (0, 1)):
            with self.subTest(n=n, m=m), self.assertRaises(FAILURE):
                self.abi.validate_dimensions(n, m)
        self.assert_guards()


class SharedMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_abi()
        cls.layout = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def setUp(self):
        self.abi = self.module.MemoryABI.from_layout(self.layout)
        self.buffer = (ctypes.c_ubyte * 24008)()
        ctypes.memset(ctypes.addressof(self.buffer), 0xCC, 24008)
        self.address = ctypes.addressof(self.buffer)

    class FakeCall:
        def __init__(self, values):
            self.values = list(values)
            self.calls = []

        def __call__(self, *args):
            self.calls.append(args)
            return self.values.pop(0)

    def libc(self, ids=None, attached=None):
        return types.SimpleNamespace(shmget=self.FakeCall([7] if ids is None else ids),
                                     shmat=self.FakeCall([self.address] if attached is None else attached))

    def test_allocate_exact_observed_struct_and_attach_without_implicit_clear(self):
        libc = self.libc()
        before = bytes(self.buffer)
        with mock.patch.object(self.module, "segment_metadata", return_value={"size": 24008, "nattch": 0}) as metadata:
            address = self.module.setup_share_memory(libc, self.abi)
        self.assertEqual(address, self.address)
        self.assertEqual(libc.shmget.calls, [(1111, 24008, 512 | 1024 | 0o666)])
        self.assertEqual(libc.shmat.calls, [(7, None, 0)])
        metadata.assert_called_once_with(1111, 7)
        self.assertEqual(bytes(self.buffer), before)

    def test_existing_exact_unused_segment_is_not_removed_resized_or_cleared(self):
        libc = self.libc(ids=[-1, 7])
        before = bytes(self.buffer)
        with mock.patch.object(self.module, "segment_metadata", return_value={"size": 24008, "nattch": 0}):
            self.assertEqual(self.module.setup_share_memory(libc, self.abi), self.address)
        self.assertEqual(libc.shmget.calls, [(1111, 24008, 512 | 1024 | 0o666), (1111, 24008, 0o666)])
        self.assertEqual(bytes(self.buffer), before)
        self.assertFalse(hasattr(libc, "shmctl"))

    def test_size_mismatch_or_any_other_attacher_blocks_before_shmat(self):
        for ids in ([7], [-1, 7]):
            for metadata in ({"size": 12160, "nattch": 0}, {"size": 24008, "nattch": 1}):
                with self.subTest(ids=ids, metadata=metadata):
                    libc = self.libc(ids=ids)
                    with mock.patch.object(self.module, "segment_metadata", return_value=metadata):
                        with self.assertRaises(FAILURE):
                            self.module.setup_share_memory(libc, self.abi)
                    self.assertEqual(libc.shmat.calls, [])
                    self.assertEqual(bytes(self.buffer), b"\xCC" * 24008)

    def test_shmget_and_shmat_failures_raise_without_native_dereference(self):
        libc = self.libc(ids=[-1, -1])
        with self.assertRaises(OSError):
            self.module.setup_share_memory(libc, self.abi)
        self.assertEqual(libc.shmat.calls, [])
        for address in (None, 0, -1, ctypes.c_void_p(-1).value):
            with self.subTest(address=address):
                libc = self.libc(attached=[address])
                with mock.patch.object(self.module, "segment_metadata", return_value={"size": 24008, "nattch": 0}):
                    with self.assertRaises(OSError):
                        self.module.setup_share_memory(libc, self.abi)
        self.assertEqual(bytes(self.buffer), b"\xCC" * 24008)


if __name__ == "__main__":
    unittest.main(verbosity=2)
