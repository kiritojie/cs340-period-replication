"""Synthetic DWARF/proof tests: no compiler, container, or benchmark is run."""
import copy
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREFLIGHT = load_module("preflight_under_test", "table2_scheduler_preflight.py")
EVIDENCE = load_module("evidence_under_test", "table2_scheduler_evidence.py")


def dwarf_fixture(capacity=1990, compilation_unit="/src/DBDSFunction.cpp", signed=False,
                  offset_overrides=None, declaration=False, no_location=False):
    """Small GNU-readelf style DIE tree with an actual si-to-struct type link.

    Offsets come from C scalar widths and array extents, rather than the parser's
    expected_layout function.  The fixture is text, not an executable/object.
    """
    offsets = [0, 8, 12, 16, 20, 220, 220 + 2 * capacity, 220 + 4 * capacity]
    fields = ["time", "N", "M", "TestedBounds", "kpNumArray", "kp", "kpLoc", "kpOrder"]
    type_refs = [0x20, 0x30, 0x30, 0x30, 0x400, 0x500, 0x500, 0x500]
    raw_size = 220 + 6 * capacity
    struct_size = (raw_size + 7) // 8 * 8
    overrides = offset_overrides or {}
    lines = [
        " <0><b>: Abbrev Number: 1 (DW_TAG_compile_unit)",
        "    <c> DW_AT_name : (indirect string, offset: 0x0): " + compilation_unit,
    ]
    for offset, width, typename in ((0x20, 8, "unsigned long long"),
                                     (0x30, 4, "unsigned int"),
                                     (0x40, 2, "unsigned short")):
        lines.extend([
            " <1><{0:x}>: Abbrev Number: 2 (DW_TAG_base_type)".format(offset),
            "    <1> DW_AT_name : " + typename,
            "    <2> DW_AT_byte_size : (data1) " + str(width),
            "    <3> DW_AT_encoding : " + ("5 (signed)" if signed and width == 2 else "7 (unsigned)"),
        ])
    lines.extend([
        " <1><50>: Abbrev Number: 3 (DW_TAG_structure_type)",
        "    <51> DW_AT_name : Sched_Info",
        "    <52> DW_AT_byte_size : " + str(struct_size),
    ])
    for index, (field, member_offset, type_ref) in enumerate(zip(fields, offsets, type_refs)):
        lines.extend([
            " <2><{0:x}>: Abbrev Number: 4 (DW_TAG_member)".format(0x60 + index * 0x10),
            "    <1> DW_AT_name : " + field,
            "    <2> DW_AT_type : <0x{0:x}>".format(type_ref),
            "    <3> DW_AT_data_member_location : " + str(overrides.get(field, member_offset)),
        ])
    lines.extend([
        " <1><300>: Abbrev Number: 5 (DW_TAG_pointer_type)",
        "    <301> DW_AT_byte_size : 8",
        "    <302> DW_AT_type : <0x50>",
    ])
    for offset, count in ((0x400, 100), (0x500, capacity)):
        lines.extend([
            " <1><{0:x}>: Abbrev Number: 6 (DW_TAG_array_type)".format(offset),
            "    <1> DW_AT_type : <0x40>",
            " <2><{0:x}>: Abbrev Number: 7 (DW_TAG_subrange_type)".format(offset + 0x10),
            "    <2> DW_AT_lower_bound : 0",
            "    <3> DW_AT_upper_bound : " + str(count - 1),
        ])
    lines.extend([
        " <1><600>: Abbrev Number: 8 (DW_TAG_variable)",
        "    <601> DW_AT_name : si",
        "    <602> DW_AT_type : <0x300>",
    ])
    if not no_location:
        lines.append("    <603> DW_AT_location : 9 byte block: 3 0 0 0 0 0 0 0 0 (DW_OP_addr: 0)")
    if declaration:
        lines.append("    <604> DW_AT_declaration : 1")
    return "\n".join(lines) + "\n"


class DwarfParserTests(unittest.TestCase):
    def test_unsigned_16_bit_1990_layout_is_parsed_exactly(self):
        parsed = PREFLIGHT.runtime_layout(dwarf_fixture())
        self.assertEqual(parsed.pop("compilation_unit"), "/src/DBDSFunction.cpp")
        self.assertEqual(parsed, PREFLIGHT.expected_layout())
        self.assertEqual(parsed["byte_size"], 12160)

    def test_3964_capacity_is_visible_and_does_not_equal_driver_layout(self):
        parsed = PREFLIGHT.runtime_layout(dwarf_fixture(capacity=3964))
        parsed.pop("compilation_unit")
        self.assertEqual(parsed["byte_size"], 24008)
        self.assertEqual(parsed["members"][5]["dimensions"], [3964])
        self.assertNotEqual(parsed, PREFLIGHT.expected_layout())

    def test_si_must_be_defined_in_actual_runtime_compilation_unit(self):
        for kwargs in ({"compilation_unit": "/src/reorder_3_bad.c"},
                       {"declaration": True}, {"no_location": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                PREFLIGHT.runtime_layout(dwarf_fixture(**kwargs))

    def test_unreferenced_matching_struct_is_not_sufficient_proof(self):
        fixture = dwarf_fixture().replace("<602> DW_AT_type : <0x300>",
                                          "<602> DW_AT_type : <0x30>")
        with self.assertRaises(ValueError):
            PREFLIGHT.runtime_layout(fixture)

    def test_signed_field_and_nonconstant_offset_fail_closed(self):
        with self.assertRaises(ValueError):
            PREFLIGHT.runtime_layout(dwarf_fixture(signed=True))
        with self.assertRaises(ValueError):
            PREFLIGHT.runtime_layout(dwarf_fixture(offset_overrides={"kp": "(exprloc) DW_OP_plus_uconst: 220"}))

    def test_missing_member_type_and_nonzero_array_lower_bound_fail_closed(self):
        missing_type = dwarf_fixture().replace("<2> DW_AT_type : <0x500>", "<2> DW_AT_unknown : 0")
        with self.assertRaises((ValueError, KeyError)):
            PREFLIGHT.runtime_layout(missing_type)
        nonzero_lower = dwarf_fixture().replace("DW_AT_lower_bound : 0", "DW_AT_lower_bound : 1", 1)
        with self.assertRaises(ValueError):
            PREFLIGHT.runtime_layout(nonzero_lower)

    def test_unparseable_and_cyclic_types_fail_closed(self):
        with self.assertRaises(ValueError):
            PREFLIGHT.runtime_layout("no debug info available\n")
        dies = {1: {"tag": "DW_TAG_typedef", "attributes": {"DW_AT_type": "<0x1>"}}}
        with self.assertRaises(ValueError):
            PREFLIGHT.unwrap(dies, 1)

    def test_typedefs_resolve_to_the_referenced_structure_and_scalar(self):
        fixture = dwarf_fixture().replace("<1> DW_AT_type : <0x40>",
                                          "<1> DW_AT_type : <0x700>")
        fixture = fixture.replace("<302> DW_AT_type : <0x50>",
                                  "<302> DW_AT_type : <0x710>")
        fixture += (
            " <1><700>: Abbrev Number: 9 (DW_TAG_typedef)\n"
            "    <701> DW_AT_name : uint16_t\n"
            "    <702> DW_AT_type : <0x40>\n"
            " <1><710>: Abbrev Number: 9 (DW_TAG_typedef)\n"
            "    <711> DW_AT_name : sched_info\n"
            "    <712> DW_AT_type : <0x50>\n"
        )
        parsed = PREFLIGHT.runtime_layout(fixture)
        parsed.pop("compilation_unit")
        self.assertEqual(parsed, PREFLIGHT.expected_layout())

    def test_conflicting_defined_runtime_compilation_units_are_rejected(self):
        second = dwarf_fixture(capacity=3964, compilation_unit="/other/DBDSFunction.cpp")
        second = re.sub(r"<(\d+)><([0-9a-f]+)>",
                        lambda match: "<{0}><{1:x}>".format(match.group(1), int(match.group(2), 16) + 0x1000),
                        second)
        second = re.sub(r"<0x([0-9a-f]+)>",
                        lambda match: "<0x{0:x}>".format(int(match.group(1), 16) + 0x1000), second)
        with self.assertRaises(ValueError):
            PREFLIGHT.runtime_layout(dwarf_fixture() + second)


class AbiProofValidationTests(unittest.TestCase):
    REQUIRED_CHECKS = (
        "linux_x86_64", "driver_host_ctypes", "binary_identity", "config_identity", "runtime_object_identity",
        "runtime_source_identity", "driver_identity", "frozen_binary", "frozen_config",
        "upstream_head", "upstream_runtime_clean", "official_driver_constants",
        "runtime_source_path", "runtime_object_path", "readelf_available",
        "binary_dwarf_abi", "runtime_object_dwarf_abi",
    )

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="period-synthetic-proof-")
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        self.dbds = base / "PERIOD" / "tool" / "DBDS"
        self.dbds.mkdir(parents=True)
        (self.dbds / "run_PDS.py").write_text("SHARE_THREAD_NUM = 100\nSHARE_ARRAY_SIZE = 1990\n", encoding="utf-8")
        self.target = base / "reorder_3_bad"
        self.target.write_bytes(b"synthetic fixture: never an executable")
        self.runtime_object = self.dbds.parent / "staticAnalysis" / "DBDS-INSTRU" / "DBDSFunction.o"
        self.runtime_object.parent.mkdir(parents=True)
        self.runtime_object.write_bytes(b"synthetic object: no ELF")
        self.driver = base / "run_scheduler_comparison.py"
        self.driver.write_text("# synthetic driver identity only\n", encoding="utf-8")
        self.proof_path = base / "proof.json"
        self.dwarf = dwarf_fixture()
        self.layout = PREFLIGHT.runtime_layout(self.dwarf)
        checks = [{"name": name, "status": "PASS", "evidence": True}
                  for name in self.REQUIRED_CHECKS]
        by_name = {item["name"]: item for item in checks}
        by_name["binary_identity"]["evidence"] = {"path": str(self.target), "sha256": PREFLIGHT.BINARY_SHA256}
        by_name["runtime_object_identity"]["evidence"] = {"path": str(self.runtime_object), "sha256": "object-fixture-sha256"}
        by_name["driver_identity"]["evidence"] = {"path": str(self.driver), "sha256": "driver-fixture-sha256"}
        for key in ("binary_dwarf_abi", "runtime_object_dwarf_abi"):
            by_name[key]["evidence"] = {"layout": self.layout}
        self.proof = {
            "schema": "cs340-period-abi-proof-v1", "status": "PASS",
            "source_commit": PREFLIGHT.COMMIT, "expected": PREFLIGHT.expected_layout(),
            "checks": checks, "blockers": [],
            "observed_layouts": {"binary": self.layout, "runtime_object": self.layout},
        }

    def validate(self, proof=None, dwarf=None, target_hash=None, object_hash=None,
                 driver_hash=None, host_system="Linux", host_machine="x86_64",
                 host_byteorder="little"):
        self.proof_path.write_text(json.dumps(self.proof if proof is None else proof), encoding="utf-8")

        def fake_sha256(path):
            if Path(path).resolve() == self.target.resolve():
                return target_hash or PREFLIGHT.BINARY_SHA256
            if Path(path).resolve() == self.runtime_object.resolve():
                return object_hash or "object-fixture-sha256"
            if Path(path).resolve() == self.driver.resolve():
                return driver_hash or "driver-fixture-sha256"
            raise AssertionError("unexpected hash request: " + str(path))

        def fake_readelf(argv):
            self.assertEqual(argv[:3], ["readelf", "--wide", "--debug-dump=info"])
            return self.dwarf if dwarf is None else dwarf

        # This is a synthetic, platform-independent proof unit test.  These
        # mocks do not certify the execution host or allow any target launch.
        with mock.patch.object(PREFLIGHT, "sha256", side_effect=fake_sha256), \
                mock.patch.object(PREFLIGHT, "command", side_effect=fake_readelf), \
                mock.patch.object(PREFLIGHT.platform, "system", return_value=host_system), \
                mock.patch.object(PREFLIGHT.platform, "machine", return_value=host_machine), \
                mock.patch.object(PREFLIGHT.sys, "byteorder", host_byteorder):
            return PREFLIGHT.validate_abi_proof(self.proof_path, self.target, self.dbds)

    def test_consistent_synthetic_proof_is_accepted_without_launching_anything(self):
        self.assertEqual(self.validate()["status"], "PASS")

    def test_current_host_and_interpreter_abi_are_checked_even_with_a_pass_proof(self):
        for kwargs in ({"host_system": "Windows"}, {"host_machine": "aarch64"},
                       {"host_byteorder": "big"}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, "little-endian x86_64 Linux"):
                self.validate(**kwargs)
        with mock.patch.object(PREFLIGHT.ctypes, "sizeof", return_value=4), \
                self.assertRaisesRegex(ValueError, "current Python ctypes ABI"):
            self.validate()

    def test_every_required_check_must_be_present(self):
        for removed in self.REQUIRED_CHECKS:
            proof = copy.deepcopy(self.proof)
            proof["checks"] = [row for row in proof["checks"] if row["name"] != removed]
            with self.subTest(removed=removed), self.assertRaises(ValueError):
                self.validate(proof)

    def test_duplicate_failed_and_unexpected_checks_are_rejected(self):
        duplicate = copy.deepcopy(self.proof)
        duplicate["checks"].append(copy.deepcopy(duplicate["checks"][0]))
        failed = copy.deepcopy(self.proof)
        failed["checks"][0]["status"] = "BLOCKED"
        unexpected = copy.deepcopy(self.proof)
        unexpected["checks"].append({"name": "waiver", "status": "PASS"})
        for proof in (duplicate, failed, unexpected):
            with self.subTest(checks=proof["checks"]), self.assertRaises(ValueError):
                self.validate(proof)

    def test_status_commit_expected_layout_and_blockers_cannot_be_waived(self):
        for field, value in (("status", "BLOCKED"), ("schema", "unknown"),
                             ("source_commit", "different"), ("expected", {}),
                             ("blockers", ["actual ABI was not checked"])):
            proof = copy.deepcopy(self.proof)
            proof[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(proof)

    def test_target_and_object_hashes_are_rebound_to_current_files(self):
        with self.assertRaises(ValueError):
            self.validate(target_hash="changed binary")
        with self.assertRaises(ValueError):
            self.validate(object_hash="changed object")
        with self.assertRaisesRegex(ValueError, "driver changed"):
            self.validate(driver_hash="changed driver")

    def test_object_path_must_be_the_selected_checkout_link_object(self):
        proof = copy.deepcopy(self.proof)
        next(row for row in proof["checks"] if row["name"] == "runtime_object_identity")["evidence"]["path"] = str(self.dbds / "DBDSFunction.o")
        with self.assertRaises(ValueError):
            self.validate(proof)

    def test_actual_incompatible_capacity_type_or_offset_blocks_even_a_pass_json(self):
        for dwarf in (dwarf_fixture(capacity=3964), dwarf_fixture(signed=True),
                      dwarf_fixture(offset_overrides={"kpLoc": 4202})):
            with self.subTest(dwarf=dwarf[-200:]), self.assertRaises(ValueError):
                self.validate(dwarf=dwarf)

    def test_stale_or_internally_conflicting_layout_evidence_is_rejected(self):
        proof = copy.deepcopy(self.proof)
        proof["observed_layouts"]["binary"] = {}
        with self.assertRaises(ValueError):
            self.validate(proof)
        proof = copy.deepcopy(self.proof)
        next(row for row in proof["checks"] if row["name"] == "runtime_object_dwarf_abi")["evidence"]["layout"] = {}
        with self.assertRaises(ValueError):
            self.validate(proof)


class EvidenceEncodingTests(unittest.TestCase):
    def test_known_schedule_has_expected_yield_matrix(self):
        self.assertEqual(EVIDENCE.yield_pattern([[0], [2], [0, 1, 1]]),
                         [[0, 2], [2, 0], [1, 0]])

    def test_valid_serial_and_parallel_schedule_examples(self):
        EVIDENCE.valid_schedule([[0, 0], [1, 1], [2]], "serial")
        EVIDENCE.valid_schedule([[0], [2], [0, 1, 1]], "parallel")

    def test_invalid_thread_counts_ids_and_serial_mixing_are_rejected(self):
        for schedule in ([[0], [2], [0, 1]], [[True, 0], [1, 1], [2]],
                         [[0, 1], [0, 1], [2]], [[0], [0], [1, 1, 2]]):
            with self.subTest(schedule=schedule), self.assertRaises(ValueError):
                EVIDENCE.valid_schedule(schedule, "serial")

    def test_parallel_adjacent_period_and_final_period_constraints(self):
        for schedule in ([[0], [0], [1, 1, 2]],
                         [[0], [1], [0, 1, 2]]):
            with self.subTest(schedule=schedule), self.assertRaises(ValueError):
                EVIDENCE.valid_schedule(schedule, "parallel")


if __name__ == "__main__":
    unittest.main(verbosity=2)
