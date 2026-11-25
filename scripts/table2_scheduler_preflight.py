#!/usr/bin/env python3
"""Fail-closed, read-only ABI/provenance checks before any PERIOD target run.

This program never starts the benchmark and never builds or replaces a product.
The JSON is evidence of the checks actually performed, not a user-editable waiver.
Python 3.6+; GNU readelf is required for the linked runtime DWARF check.
"""
from __future__ import print_function

import argparse
import ast
import ctypes
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

# The legacy tests load this file by absolute importlib spec. Load the adjacent
# pure ABI module explicitly rather than assuming scripts/ is on sys.path.
ABI_LAYER_PATH = Path(__file__).resolve().with_name("period_shared_memory.py")
_abi_spec = importlib.util.spec_from_file_location("_cs340_period_shared_memory", str(ABI_LAYER_PATH))
_abi_module = importlib.util.module_from_spec(_abi_spec)
_abi_spec.loader.exec_module(_abi_module)
MemoryABI = _abi_module.MemoryABI

COMMIT = "b6f72a7b06d01ffa7114b640312873ec2578a5ea"
BINARY_SHA256 = "ed2d13809b87a00eaaba76ac0f1faf4871a489a0960993e5963dc89b4bb13db9"
CONFIG_SHA256 = "0ed49729a85b862b9a918c62f3826f3c56b89ec825ae3fe35a28f21f253d7d4d"
BENCHMARK_MANIFEST_SCHEMA = "cs340-period-rq1-benchmark-v1"
BENCHMARK_THREADS = {"reorder_3_bad": 3, "reorder_4_bad": 4,
                     "reorder_5_bad": 5, "reorder_10_bad": 10}
BENCHMARK_REQUIRED_CHECKS = ("benchmark_manifest_identity", "benchmark_contract")
EXPECTED_MEMBERS = [
    ("time", 0, 8, []), ("N", 8, 4, []), ("M", 12, 4, []),
    ("TestedBounds", 16, 4, []), ("kpNumArray", 20, 2, [100]),
    ("kp", 220, 2, [1990]), ("kpLoc", 4200, 2, [1990]),
    ("kpOrder", 8180, 2, [1990]),
]
V2_REQUIRED_CHECKS = (
    "linux_x86_64", "driver_host_ctypes", "binary_identity", "config_identity", "runtime_object_identity",
    "runtime_source_identity", "driver_identity", "reference_driver_identity", "abi_layer_identity", "source_manifest_identity",
    "frozen_binary", "frozen_config", "upstream_head", "upstream_runtime_clean", "pinned_source_files",
    "runtime_source_path", "runtime_object_path", "reference_driver_path", "readelf_available", "binary_dwarf_abi",
    "runtime_object_dwarf_abi", "common_runtime_layout", "raw_driver_abi_audit",
)
VENDOR_MANIFEST = Path(__file__).resolve().parent / "vendor/period_b6f72a7/SOURCE_MANIFEST.json"
PINNED_PATHS = tuple("tool/DBDS/" + name + ".py" for name in (
    "run_PDS", "external_def", "interleaving", "ipc", "sched", "pds", "bp_sched", "sbp_sched", "sbp_sched_mixed_end")) + (
        "tool/staticAnalysis/DBDS-INSTRU/llvm-mode/DBDSFunction.cpp",)


def sha256(path):
    digest = hashlib.sha256()
    with open(str(path), "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def command(argv):
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               universal_newlines=True)
    try:
        stdout, stderr = process.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise ValueError("read-only inspection command timed out: " + repr(argv))
    if process.returncode:
        raise ValueError("command failed ({0}): {1}\n{2}".format(
            process.returncode, repr(argv), stderr.strip()))
    return stdout


def integer(value):
    # readelf versions may prepend a DW_FORM, e.g. '(data1) 8'.
    value = re.sub(r"^\([^)]*\)\s*", "", value).strip()
    if re.match(r"^(?:0x[0-9a-fA-F]+|[0-9]+)$", value):
        return int(value, 16 if value.startswith("0x") else 10)
    raise ValueError("unsupported DWARF integer/location: " + value)


def name(value):
    if "):" in value:
        return value.split("):", 1)[1].strip()
    return re.sub(r"^\([^)]*\)\s*", "", value).strip()


def reference(value):
    matched = re.search(r"<0x([0-9a-fA-F]+)>", value)
    if not matched:
        raise ValueError("unsupported DWARF type reference: " + value)
    return int(matched.group(1), 16)


def parse_dies(text):
    dies, stack, current = {}, [], None
    for line in text.splitlines():
        matched = re.match(r"\s*<(\d+)><([0-9a-fA-F]+)>: Abbrev Number: (\d+)(?: \((DW_TAG_\w+)\))?", line)
        if matched:
            depth, offset, abbrev, tag = matched.groups()
            depth, offset = int(depth), int(offset, 16)
            while stack and stack[-1][0] >= depth:
                stack.pop()
            if abbrev == "0":
                current = None
                continue
            current = {"offset": offset, "tag": tag, "attributes": {},
                       "children": [], "parent": stack[-1][1] if stack else None}
            dies[offset] = current
            if stack:
                dies[stack[-1][1]]["children"].append(offset)
            stack.append((depth, offset))
            continue
        matched = re.match(r"\s*<[0-9a-fA-F]+>\s+(DW_AT_\w+)\s*:\s*(.*)$", line)
        if matched and current is not None:
            current["attributes"][matched.group(1)] = matched.group(2)
    if not dies:
        raise ValueError("no parseable DWARF DIEs (stripped or unsupported readelf output)")
    return dies


def unwrap(dies, offset, allow_pointer=False):
    seen = set()
    while True:
        if offset in seen or offset not in dies:
            raise ValueError("missing or cyclic DWARF type")
        seen.add(offset)
        die = dies[offset]
        wrappers = {"DW_TAG_typedef", "DW_TAG_const_type", "DW_TAG_volatile_type",
                    "DW_TAG_restrict_type"}
        if allow_pointer:
            wrappers.add("DW_TAG_pointer_type")
        if die["tag"] not in wrappers:
            return die
        offset = reference(die["attributes"]["DW_AT_type"])


def type_layout(dies, offset):
    die = unwrap(dies, offset)
    attrs = die["attributes"]
    if die["tag"] == "DW_TAG_array_type":
        dimensions = []
        for child_offset in die["children"]:
            child = dies[child_offset]
            if child["tag"] != "DW_TAG_subrange_type":
                continue
            bounds = child["attributes"]
            lower = integer(bounds.get("DW_AT_lower_bound", "0"))
            if lower != 0:
                raise ValueError("nonzero array lower bound")
            if "DW_AT_count" in bounds:
                dimensions.append(integer(bounds["DW_AT_count"]))
            else:
                dimensions.append(integer(bounds["DW_AT_upper_bound"]) + 1)
        if not dimensions:
            raise ValueError("array has no constant dimensions")
        element = type_layout(dies, reference(attrs["DW_AT_type"]))
        if element["dimensions"]:
            raise ValueError("unexpected nested array type")
        element["dimensions"] = dimensions
        return element
    if die["tag"] != "DW_TAG_base_type":
        raise ValueError("unsupported field type: " + str(die["tag"]))
    encoding = attrs.get("DW_AT_encoding", "")
    # DW_ATE_unsigned = 7. A width match alone is not enough.
    if not re.match(r"(?:\([^)]*\)\s*)?7\b", encoding) or "unsigned" not in encoding:
        raise ValueError("field is not proven unsigned: " + encoding)
    return {"element_bytes": integer(attrs["DW_AT_byte_size"]),
            "unsigned": True, "dimensions": []}


def runtime_layout(dwarf_text):
    dies = parse_dies(dwarf_text)
    layouts = []
    for die in dies.values():
        attrs = die["attributes"]
        if die["tag"] != "DW_TAG_variable" or name(attrs.get("DW_AT_name", "")) != "si":
            continue
        if "DW_AT_location" not in attrs or "DW_AT_declaration" in attrs:
            continue
        ancestor = die
        while ancestor["parent"] is not None:
            ancestor = dies[ancestor["parent"]]
        unit = name(ancestor["attributes"].get("DW_AT_name", ""))
        if not unit.replace("\\", "/").endswith("DBDSFunction.cpp"):
            continue
        pointer = unwrap(dies, reference(attrs["DW_AT_type"]))
        if pointer["tag"] != "DW_TAG_pointer_type":
            raise ValueError("runtime si is not a pointer")
        structure = unwrap(dies, reference(pointer["attributes"]["DW_AT_type"]))
        sattrs = structure["attributes"]
        if structure["tag"] != "DW_TAG_structure_type" or name(sattrs.get("DW_AT_name", "")) != "Sched_Info":
            raise ValueError("runtime si does not point to Sched_Info")
        members = []
        for member_offset in structure["children"]:
            member = dies[member_offset]
            if member["tag"] != "DW_TAG_member":
                continue
            mattrs = member["attributes"]
            layout = type_layout(dies, reference(mattrs["DW_AT_type"]))
            layout.update({"name": name(mattrs["DW_AT_name"]),
                           "offset": integer(mattrs["DW_AT_data_member_location"])})
            members.append(layout)
        layouts.append({"struct_name": "Sched_Info", "compilation_unit": unit,
                        "byte_size": integer(sattrs["DW_AT_byte_size"]), "members": members})
    if not layouts:
        raise ValueError("DWARF does not prove the defined runtime si in DBDSFunction.cpp")
    first = dict(layouts[0])
    canonical = {key: value for key, value in first.items() if key != "compilation_unit"}
    for layout in layouts[1:]:
        if {key: value for key, value in layout.items() if key != "compilation_unit"} != canonical:
            raise ValueError("conflicting runtime Sched_Info definitions")
    return first


def expected_layout():
    return {"struct_name": "Sched_Info", "byte_size": 12160,
            "members": [{"name": key, "offset": offset, "element_bytes": width,
                         "unsigned": True, "dimensions": dims}
                        for key, offset, width, dims in EXPECTED_MEMBERS]}


def source_constants(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    result = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Num):
            for target in statement.targets:
                if isinstance(target, ast.Name) and target.id in ("SHARE_THREAD_NUM", "SHARE_ARRAY_SIZE"):
                    result[target.id] = statement.value.n
    return result


def _static_expression(node, constants):
    if isinstance(node, ast.Num) and type(node.n) is int:
        return node.n
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id]
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
        left, right = _static_expression(node.left, constants), _static_expression(node.right, constants)
        return left + right if isinstance(node.op, ast.Add) else left - right if isinstance(node.op, ast.Sub) else left * right
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sizeof" and len(node.args) == 1:
        widths = {"c_ulonglong": 8, "c_uint64": 8, "c_uint": 4, "c_uint32": 4, "c_uint16": 2}
        if isinstance(node.args[0], ast.Name) and node.args[0].id in widths:
            return widths[node.args[0].id]
    raise ValueError("unsupported static ABI expression: " + ast.dump(node))


def audit_driver_source(path, runtime_layout=None):
    """Audit the actual file, never infer a historical ABI from GitHub alone.

    A recognized but mismatching old driver is legacy_unverified. This report
    does not certify that driver for execution; corrected arms use MemoryABI.
    """
    path = Path(path)
    result = {"path": str(path.resolve()), "status": "unverifiable", "compatible_with_runtime": None}
    try:
        result["source_sha256"] = sha256(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = source_constants(path)
        if set(constants) != {"SHARE_THREAD_NUM", "SHARE_ARRAY_SIZE"} or any(type(value) is not int or value <= 0 for value in constants.values()):
            raise ValueError("missing or invalid driver capacity constants")
        result["constants"] = constants
        functions = {statement.name: statement for statement in tree.body if isinstance(statement, ast.FunctionDef)}
        for required in ("setup_share_memroy", "get_info_from_share_memory", "memmove_pattern_list"):
            if required not in functions:
                raise ValueError("unrecognized raw driver function " + required)
        values = dict(constants, ADDR=0)
        setup = functions["setup_share_memroy"]
        map_sizes = []
        for node in ast.walk(setup):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, (ast.Tuple, ast.List)) and isinstance(node.value, (ast.Tuple, ast.List)):
                    for key, value in zip(target.elts, node.value.elts):
                        if isinstance(key, ast.Name) and key.id == "MAP_SIZE":
                            map_sizes.append(_static_expression(value, values))
                elif isinstance(target, ast.Name) and target.id == "MAP_SIZE":
                    map_sizes.append(_static_expression(node.value, values))
        if len(map_sizes) != 1:
            raise ValueError("cannot prove one raw driver MAP_SIZE expression")
        field_map = {"P": ("time", 8, []), "A": ("N", 4, []), "B": ("M", 4, []),
                     "T": ("TestedBounds", 4, []), "kpNumArray": ("kpNumArray", 2, [constants["SHARE_THREAD_NUM"]]),
                     "kpYieldArray": ("kp", 2, [constants["SHARE_ARRAY_SIZE"]]),
                     "kpLocArray": ("kpLoc", 2, [constants["SHARE_ARRAY_SIZE"]]),
                     "kpOrderArray": ("kpOrder", 2, [constants["SHARE_ARRAY_SIZE"]])}
        fields, expressions = {}, []
        for node in ast.walk(functions["get_info_from_share_memory"]):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "memmove"):
                continue
            if len(node.args) != 3:
                raise ValueError("unrecognized raw reader memmove")
            destination = node.args[0]
            if not (isinstance(destination, ast.Call) and isinstance(destination.func, ast.Name) and
                    destination.func.id == "byref" and len(destination.args) == 1 and
                    isinstance(destination.args[0], ast.Name) and destination.args[0].id in field_map):
                raise ValueError("unknown raw reader destination")
            key, width, dimensions = field_map[destination.args[0].id]
            offset, length = _static_expression(node.args[1], values), _static_expression(node.args[2], values)
            if key in fields or length != width * (dimensions[0] if dimensions else 1):
                raise ValueError("raw reader copy width/count is inconsistent")
            fields[key] = {"name": key, "offset": offset, "element_bytes": width,
                           "unsigned": True, "dimensions": dimensions}
            expressions.append({"field": key, "offset_ast": ast.dump(node.args[1]), "length_ast": ast.dump(node.args[2])})
        if set(fields) != set(item[0] for item in EXPECTED_MEMBERS):
            raise ValueError("raw reader does not expose all eight fields")
        # Confirm all four receiving buffers are uint16 arrays with the same
        # declared dimensions, rather than trusting the explanatory comments.
        found_arrays = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            constructor = node.value.func
            if not (isinstance(constructor, ast.BinOp) and isinstance(constructor.op, ast.Mult) and
                    isinstance(constructor.left, ast.Name) and constructor.left.id == "c_uint16"):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in field_map and field_map[target.id][2]:
                    found_arrays[target.id] = _static_expression(constructor.right, values)
        if found_arrays != {key: item[2][0] for key, item in field_map.items() if item[2]}:
            raise ValueError("raw driver array element types/dimensions are unverified")
        scalar_types = {"P": ("c_ulonglong", "c_uint64"), "A": ("c_uint", "c_uint32"),
                        "B": ("c_uint", "c_uint32"), "T": ("c_uint", "c_uint32")}
        declared_scalars = {}
        for node in tree.body:
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and
                    isinstance(node.value.func, ast.Name)):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in scalar_types:
                        declared_scalars[target.id] = node.value.func.id
        if set(declared_scalars) != set(scalar_types) or any(declared_scalars[key] not in allowed for key, allowed in scalar_types.items()):
            raise ValueError("raw driver scalar receiving types are unverified")
        writer = functions["memmove_pattern_list"]
        calls = [node for node in ast.walk(writer) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "memmove"]
        if len(calls) != 1 or _static_expression(calls[0].args[0], values) != fields["kp"]["offset"]:
            raise ValueError("raw yield writer offset is unverified")
        wanted_length = ast.dump(ast.parse("sizeof(c_uint16) * len(tmp)", mode="eval").body)
        if ast.dump(calls[0].args[2]) != wanted_length:
            raise ValueError("raw yield writer copy element width is unverified")
        wanted_array = ast.dump(ast.parse("(c_uint16 * len(tmp))(*tmp)", mode="eval").body)
        if not any(isinstance(node, ast.Assign) and ast.dump(node.value) == wanted_array for node in ast.walk(writer)):
            raise ValueError("raw yield writer uint16 buffer is unverified")
        scalar_by_offset = {value["offset"]: value for value in fields.values() if not value["dimensions"]}
        scalar_writes = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "memmove"):
                continue
            if node is calls[0] or not any(isinstance(item, ast.Name) and item.id == "ADDR" for item in ast.walk(node.args[0])):
                continue
            offset = _static_expression(node.args[0], values)
            length = _static_expression(node.args[2], values)
            if offset not in scalar_by_offset or length != scalar_by_offset[offset]["element_bytes"]:
                raise ValueError("raw direct scalar write has an unknown offset/width")
            encoded = node.args[1]
            if not (isinstance(encoded, ast.Call) and isinstance(encoded.func, ast.Name) and encoded.func.id == "byref" and
                    len(encoded.args) == 1 and isinstance(encoded.args[0], ast.Call) and
                    isinstance(encoded.args[0].func, ast.Name)):
                raise ValueError("raw direct scalar write has an unverified value type")
            declared = encoded.args[0].func.id
            widths = {"c_ulonglong": 8, "c_uint64": 8, "c_uint": 4, "c_uint32": 4}
            if widths.get(declared) != length:
                raise ValueError("raw direct scalar write type does not match its width")
            scalar_writes.append({"field": scalar_by_offset[offset]["name"], "offset_ast": ast.dump(node.args[0]),
                                  "length_ast": ast.dump(node.args[2]), "value_type": declared})
        layout = {"struct_name": "Sched_Info", "byte_size": map_sizes[0],
                  "members": [fields[key] for key, _, _, _ in EXPECTED_MEMBERS]}
        # The legacy driver's map may omit C tail padding. The raw expressions
        # are reported literally; they are not silently rounded or repaired.
        result.update({"layout": layout, "offset_expressions": expressions, "scalar_writes": scalar_writes,
                       "typed_receivers": {"scalars": declared_scalars,
                                           "arrays": {key: {"ctype": "c_uint16", "count": count}
                                                      for key, count in found_arrays.items()}},
                       "map_size": map_sizes[0], "status": "legacy_unverified"})
        if runtime_layout is not None:
            observed = MemoryABI.from_layout(runtime_layout).layout
            result["compatible_with_runtime"] = layout == observed
            if result["compatible_with_runtime"]:
                result["status"] = "compatible"
            else:
                result["reason"] = "actual raw driver types/offsets/capacities differ from runtime DWARF"
        else:
            result["reason"] = "runtime layout was not provided; execution compatibility is unverified"
    except Exception as error:
        result["status"] = "unverifiable"
        result["compatible_with_runtime"] = None
        result["reason"] = str(error)
    return result


def verify_pinned_sources(upstream, manifest_path):
    upstream, manifest_path = Path(upstream).resolve(), Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("commit", manifest.get("source_commit")) != COMMIT:
        raise ValueError("source manifest is not pinned to the image commit")
    entries = {entry.get("upstream_path", entry.get("path")): entry for entry in manifest.get("files", [])}
    verified = {}
    for relative in PINNED_PATHS:
        if relative not in entries:
            raise ValueError("source manifest lacks " + relative)
        entry, path = entries[relative], upstream / relative
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
        expected_blob = entry.get("git_blob_sha1", entry.get("git_blob_sha", entry.get("blob_sha")))
        if not entry.get("sha256") or not expected_blob or digest != entry["sha256"] or blob != expected_blob:
            raise ValueError("actual upstream source hash is not approved: " + relative)
        verified[relative] = {"path": str(path), "sha256": digest, "git_blob_sha1": blob}
    return verified


def verify_benchmark_manifest(manifest_path, upstream, target=None, config=None):
    """Bind a named benchmark to inspected products and pinned source bytes.

    This is an identity contract, not a KPS/ABI waiver. KPS must still be
    observed from the actual driver run, and both actual DWARF layouts are
    checked by the unchanged runtime-dwarf proof below.
    """
    manifest_path, upstream = Path(manifest_path).resolve(), Path(upstream).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    benchmark = manifest.get("benchmark")
    if manifest.get("schema") != BENCHMARK_MANIFEST_SCHEMA or benchmark not in BENCHMARK_THREADS:
        raise ValueError("unsupported frozen benchmark manifest or program")
    if (manifest.get("source_commit") != COMMIT or type(manifest.get("threads")) is not int
            or manifest["threads"] != BENCHMARK_THREADS[benchmark]):
        raise ValueError("benchmark manifest commit/thread identity is inconsistent")
    directory = upstream / "evaluation/CS" / benchmark[:-4]
    expected = {
        "binary": directory / benchmark,
        "config": directory / ("ConConfig." + benchmark),
        "runtime_object": upstream / "tool/staticAnalysis/DBDS-INSTRU/DBDSFunction.o",
        "runtime_source": upstream / "tool/staticAnalysis/DBDS-INSTRU/llvm-mode/DBDSFunction.cpp",
    }
    origin = manifest.get("product_origin", "existing")
    if origin not in ("existing", "isolated_build"):
        raise ValueError("unsupported benchmark product origin")
    identities = {}
    for label in ("binary", "config", "runtime_object", "runtime_source", "source"):
        entry = manifest.get(label)
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("benchmark manifest lacks " + label + " identity")
        path = Path(entry["path"])
        if not path.is_absolute() or not re.match(r"^[0-9a-f]{64}$", entry.get("sha256", "")):
            raise ValueError("benchmark " + label + " needs an absolute path and SHA-256")
        path = path.resolve()
        if label in expected and not (origin == "isolated_build" and label in ("binary", "config")):
            if path != expected[label].resolve():
                raise ValueError("benchmark " + label + " path does not match the selected checkout")
        if label in ("binary", "config") and path.name != expected[label].name:
            raise ValueError("benchmark " + label + " basename is inconsistent")
        if label == "source":
            try:
                relative_source = path.relative_to(directory.resolve())
            except ValueError:
                raise ValueError("benchmark source lies outside its pinned program directory")
            if path.suffix not in (".c", ".cpp") or not relative_source.parts:
                raise ValueError("benchmark source must identify an actual C/C++ source file")
        current = sha256(path)
        if current != entry["sha256"]:
            raise ValueError("benchmark " + label + " changed after identity freeze")
        identities[label] = {"path": str(path), "sha256": current}
    if origin == "isolated_build":
        build = manifest.get("build_record")
        if not isinstance(build, dict) or not isinstance(build.get("path"), str):
            raise ValueError("isolated build requires a frozen build record")
        build_path = Path(build["path"])
        if not build_path.is_absolute() or sha256(build_path) != build.get("sha256"):
            raise ValueError("isolated build record identity changed")
        identities["build_record"] = {"path": str(build_path.resolve()), "sha256": build["sha256"]}
    source_path = Path(identities["source"]["path"])
    relative = str(source_path.relative_to(upstream)).replace("\\", "/")
    raw = source_path.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
    expected_blob = command(["git", "-C", str(upstream), "rev-parse", COMMIT + ":" + relative]).strip()
    if blob != expected_blob:
        raise ValueError("benchmark source bytes differ from the pinned commit")
    if command(["git", "-C", str(upstream), "diff", "HEAD", "--", relative]).strip():
        raise ValueError("benchmark source worktree is dirty")
    for label, actual in (("binary", target), ("config", config)):
        if actual is not None:
            actual = Path(actual).resolve()
            if actual.name != expected[label].name or sha256(actual) != identities[label]["sha256"]:
                raise ValueError("current " + label + " does not match the frozen benchmark")
    return {"schema": BENCHMARK_MANIFEST_SCHEMA, "benchmark": benchmark,
            "threads": manifest["threads"], "source_commit": COMMIT,
            "product_origin": origin, "identities": identities,
            "source_git_blob_sha1": blob}


def validate_abi_proof(proof_path, target_path, dbds_dir):
    """Revalidate a proof against current files; never trust a JSON PASS alone.

    The target may be an untouched copy in a new run directory. readelf is run
    again on that copy and on the recorded object before the driver may Popen.
    """
    if platform.system() != "Linux" or platform.machine() != "x86_64" or sys.byteorder != "little":
        raise ValueError("execution requires little-endian x86_64 Linux")
    if [ctypes.sizeof(kind) for kind in (ctypes.c_uint16, ctypes.c_uint, ctypes.c_ulonglong, ctypes.c_void_p)] != [2, 4, 8, 8]:
        raise ValueError("current Python ctypes ABI differs from the driver")
    proof = json.loads(Path(proof_path).read_text(encoding="utf-8"))
    if proof.get("schema") == "cs340-period-abi-proof-v2":
        return _validate_runtime_dwarf_proof(proof, target_path, dbds_dir)
    if proof.get("schema") != "cs340-period-abi-proof-v1" or proof.get("status") != "PASS":
        raise ValueError("missing or failed ABI proof")
    if proof.get("source_commit") != COMMIT or proof.get("expected") != expected_layout():
        raise ValueError("ABI proof has a different commit or driver layout")
    if proof.get("blockers"):
        raise ValueError("ABI proof retains blockers")
    checks = {}
    for check in proof.get("checks", []):
        label = check.get("name")
        if label in checks or check.get("status") != "PASS":
            raise ValueError("duplicate or failing ABI proof check")
        checks[label] = check
    required = ("linux_x86_64", "driver_host_ctypes", "binary_identity", "config_identity", "runtime_object_identity",
                "runtime_source_identity", "driver_identity", "frozen_binary", "frozen_config",
                "upstream_head", "upstream_runtime_clean", "official_driver_constants",
                "runtime_source_path", "runtime_object_path", "readelf_available",
                "binary_dwarf_abi", "runtime_object_dwarf_abi")
    if set(checks) != set(required):
        raise ValueError("ABI proof check set is incomplete or unexpected")
    target = Path(target_path).resolve()
    digest = sha256(target)
    if digest != BINARY_SHA256 or checks["binary_identity"]["evidence"]["sha256"] != digest:
        raise ValueError("ABI proof is not bound to the selected target binary")
    object_evidence = checks["runtime_object_identity"]["evidence"]
    runtime_object = Path(object_evidence["path"]).resolve()
    dbds_dir = Path(dbds_dir).resolve()
    if runtime_object != dbds_dir.parent / "staticAnalysis/DBDS-INSTRU/DBDSFunction.o":
        raise ValueError("ABI proof runtime object is outside the selected PERIOD checkout")
    if sha256(runtime_object) != object_evidence["sha256"]:
        raise ValueError("runtime object changed after ABI preflight")
    driver_evidence = checks["driver_identity"]["evidence"]
    if sha256(driver_evidence["path"]) != driver_evidence["sha256"]:
        raise ValueError("comparison driver changed after ABI preflight")
    if source_constants(dbds_dir / "run_PDS.py") != {"SHARE_THREAD_NUM": 100, "SHARE_ARRAY_SIZE": 1990}:
        raise ValueError("official driver ABI constants changed")
    observed = {}
    for label, path in (("binary", target), ("runtime_object", runtime_object)):
        layout = runtime_layout(command(["readelf", "--wide", "--debug-dump=info", str(path)]))
        comparable = {key: value for key, value in layout.items() if key != "compilation_unit"}
        if comparable != expected_layout():
            raise ValueError("current " + label + " DWARF is incompatible with the driver")
        if proof.get("observed_layouts", {}).get(label) != layout:
            raise ValueError("current " + label + " DWARF differs from the proof")
        if checks[label + "_dwarf_abi"]["evidence"]["layout"] != layout:
            raise ValueError("ABI proof contains inconsistent layout evidence")
        observed[label] = layout
    return {"status": "PASS", "binary_sha256": digest,
            "runtime_object_sha256": object_evidence["sha256"], "layouts": observed}


def _proof_checks(proof, required):
    if proof.get("status") != "PASS" or proof.get("blockers"):
        raise ValueError("missing or failed runtime-dwarf proof")
    checks = {}
    for row in proof.get("checks", []):
        if row.get("status") != "PASS" or row.get("name") in checks:
            raise ValueError("failing or duplicate proof check")
        checks[row.get("name")] = row
    if set(checks) != set(required):
        raise ValueError("runtime-dwarf proof check set is incomplete or unexpected")
    return checks


def _validate_runtime_dwarf_proof(proof, target_path, dbds_dir):
    if proof.get("abi_profile") != "runtime-dwarf" or proof.get("source_commit") != COMMIT:
        raise ValueError("incorrect runtime-dwarf profile or source commit")
    formal = "benchmark_manifest" in proof
    required = V2_REQUIRED_CHECKS + (BENCHMARK_REQUIRED_CHECKS if formal else ())
    checks = _proof_checks(proof, required)
    abi = MemoryABI.from_layout(proof.get("layout"))
    if proof.get("map_size") != abi.map_size:
        raise ValueError("proof mapping size differs from observed ctypes layout")
    target, dbds_dir = Path(target_path).resolve(), Path(dbds_dir).resolve()
    upstream = dbds_dir.parent.parent
    contract = None
    if formal:
        binding = proof["benchmark_manifest"]
        if not isinstance(binding, dict) or binding != checks["benchmark_manifest_identity"]["evidence"]:
            raise ValueError("benchmark manifest proof identity is inconsistent")
        manifest_path = Path(binding.get("path", "")).resolve()
        if sha256(manifest_path) != binding.get("sha256"):
            raise ValueError("benchmark manifest changed after preflight")
        current_config = os.environ.get("Con_PATH")
        if not current_config:
            raise ValueError("manifest-bound execution requires actual Con_PATH")
        contract = verify_benchmark_manifest(manifest_path, upstream, target, current_config)
        if (contract != checks["benchmark_contract"]["evidence"] or proof.get("benchmark") != contract["benchmark"]
                or proof.get("threads") != contract["threads"]):
            raise ValueError("benchmark contract changed after preflight")
    digest = sha256(target)
    expected_binary = contract["identities"]["binary"]["sha256"] if contract else BINARY_SHA256
    expected_config = contract["identities"]["config"]["sha256"] if contract else CONFIG_SHA256
    if digest != expected_binary or checks["binary_identity"]["evidence"]["sha256"] != digest:
        raise ValueError("runtime-dwarf proof is not bound to the frozen target")
    expected_paths = {
        "runtime_object": upstream / "tool/staticAnalysis/DBDS-INSTRU/DBDSFunction.o",
        "runtime_source": upstream / "tool/staticAnalysis/DBDS-INSTRU/llvm-mode/DBDSFunction.cpp",
        "abi_layer": ABI_LAYER_PATH,
        "reference_driver": Path(checks["driver_identity"]["evidence"]["path"]).resolve().with_name("run_abi_parallel_reference.py"),
    }
    identities = {}
    for label in ("config", "runtime_object", "runtime_source", "driver", "reference_driver", "abi_layer", "source_manifest"):
        evidence = checks[label + "_identity"]["evidence"]
        path = Path(evidence["path"]).resolve()
        if label in expected_paths and path != expected_paths[label].resolve():
            raise ValueError(label + " path does not match the selected checkout/shared layer")
        current = sha256(path)
        if current != evidence["sha256"]:
            raise ValueError(label + " hash changed after preflight")
        identities[label] = {"path": str(path), "sha256": current}
    if identities["config"]["sha256"] != expected_config:
        raise ValueError("config is not the frozen benchmark configuration")
    if contract:
        if Path(identities["config"]["path"]).name != Path(contract["identities"]["config"]["path"]).name:
            raise ValueError("proof config basename does not match the frozen benchmark manifest")
        for label in ("runtime_object", "runtime_source"):
            if identities[label] != contract["identities"][label]:
                raise ValueError("proof " + label + " does not match the frozen benchmark manifest")
    if proof.get("abi_layer_sha256") != identities["abi_layer"]["sha256"]:
        raise ValueError("proof ABI layer hash is internally inconsistent")
    if (proof.get("shared_abi_layer_sha256") != identities["abi_layer"]["sha256"] or
            proof.get("reference_driver_sha256") != identities["reference_driver"]["sha256"]):
        raise ValueError("proof shared-layer/reference entry identity is inconsistent")
    if command(["git", "-C", str(upstream), "rev-parse", "HEAD"]).strip() != COMMIT:
        raise ValueError("upstream HEAD changed")
    if command(["git", "-C", str(upstream), "diff", "HEAD", "--", "tool/DBDS",
                "tool/staticAnalysis/DBDS-INSTRU/llvm-mode/DBDSFunction.cpp"]).strip():
        raise ValueError("upstream driver/support/runtime worktree changed")
    verified_sources = verify_pinned_sources(upstream, identities["source_manifest"]["path"])
    if checks["pinned_source_files"]["evidence"] != verified_sources:
        raise ValueError("pinned source evidence changed")
    observed = {}
    for label, path in (("binary", target), ("runtime_object", expected_paths["runtime_object"])):
        layout = runtime_layout(command(["readelf", "--wide", "--debug-dump=info", str(path)]))
        if MemoryABI.from_layout(layout).layout != abi.layout:
            raise ValueError("current " + label + " runtime DWARF differs from the corrected ABI")
        if proof.get("observed_layouts", {}).get(label) != layout:
            raise ValueError("current " + label + " DWARF differs from recorded evidence")
        if checks[label + "_dwarf_abi"]["evidence"]["layout"] != layout:
            raise ValueError("runtime DWARF proof contains conflicting field evidence")
        observed[label] = layout
    common = checks["common_runtime_layout"]["evidence"]
    if common.get("layout") != abi.layout or common.get("map_size") != abi.map_size:
        raise ValueError("common runtime ABI check is inconsistent")
    raw_audit = audit_driver_source(dbds_dir / "run_PDS.py", abi.layout)
    if raw_audit.get("status") == "unverifiable":
        raise ValueError("actual raw driver ABI cannot be statically audited")
    if checks["raw_driver_abi_audit"]["evidence"] != raw_audit or proof.get("raw_driver_abi") != raw_audit:
        raise ValueError("actual raw driver source audit changed")
    identities["reference"] = dict(identities["reference_driver"])
    result = {"schema": "cs340-period-abi-proof-v2", "status": "PASS", "abi_profile": "runtime-dwarf",
            "source_commit": COMMIT, "layout": abi.layout, "map_size": abi.map_size,
            "abi_layer_sha256": identities["abi_layer"]["sha256"], "binary_sha256": digest,
            "shared_abi_layer_sha256": identities["abi_layer"]["sha256"],
            "reference_driver_sha256": identities["reference_driver"]["sha256"],
            "reference_identity": identities["reference_driver"],
            "runtime_object_sha256": identities["runtime_object"]["sha256"],
            "driver_sha256": identities["driver"]["sha256"], "identities": identities,
            "verified_sources": verified_sources, "layouts": observed, "raw_driver_abi": raw_audit}
    if contract:
        result.update({"benchmark_manifest": dict(proof["benchmark_manifest"]),
                       "benchmark": contract["benchmark"], "threads": contract["threads"],
                       "benchmark_contract": contract})
    return result


def _create_runtime_dwarf_proof(args, output):
    proof = {"schema": "cs340-period-abi-proof-v2", "abi_profile": "runtime-dwarf", "status": "BLOCKED",
             "source_commit": COMMIT, "checks": [], "blockers": [], "observed_layouts": {}}

    def require(condition, reason, value=True):
        if not condition:
            raise ValueError(reason)
        return value

    def check(label, callback):
        try:
            result = callback()
            proof["checks"].append({"name": label, "status": "PASS", "evidence": result})
            return result
        except Exception as error:
            proof["checks"].append({"name": label, "status": "BLOCKED", "reason": str(error)})
            proof["blockers"].append(label + ": " + str(error))
            return None

    check("linux_x86_64", lambda: require(platform.system() == "Linux" and platform.machine() == "x86_64",
          "runtime-dwarf execution requires x86_64 Linux", platform.platform()))
    host = {"uint16_bytes": ctypes.sizeof(ctypes.c_uint16), "uint_bytes": ctypes.sizeof(ctypes.c_uint),
            "ulonglong_bytes": ctypes.sizeof(ctypes.c_ulonglong), "pointer_bytes": ctypes.sizeof(ctypes.c_void_p),
            "byteorder": sys.byteorder}
    check("driver_host_ctypes", lambda: require(host == {"uint16_bytes": 2, "uint_bytes": 4,
          "ulonglong_bytes": 8, "pointer_bytes": 8, "byteorder": "little"}, "incompatible host ctypes ABI", host))
    manifest = Path(args.source_manifest).resolve()
    upstream = Path(args.upstream).resolve()
    benchmark_manifest = getattr(args, "benchmark_manifest", None)
    contract = None
    if benchmark_manifest:
        benchmark_manifest = Path(benchmark_manifest).resolve()
        binding = check("benchmark_manifest_identity", lambda: {
            "path": str(benchmark_manifest), "sha256": sha256(benchmark_manifest)})
        proof["benchmark_manifest"] = binding
        contract = check("benchmark_contract", lambda: verify_benchmark_manifest(
            benchmark_manifest, upstream, args.binary, args.config))
        if contract:
            proof.update({"benchmark": contract["benchmark"], "threads": contract["threads"]})
    paths = {label: Path(getattr(args, label)).resolve()
             for label in ("binary", "config", "runtime_object", "runtime_source", "driver")}
    paths.update({"abi_layer": ABI_LAYER_PATH, "source_manifest": manifest})
    paths["reference_driver"] = (Path(args.reference_driver).resolve() if args.reference_driver else
                                 paths["driver"].with_name("run_abi_parallel_reference.py"))
    for label, path in paths.items():
        check(label + "_identity", lambda path=path: {"path": str(path), "sha256": sha256(path)})
    binary_sha = contract["identities"]["binary"]["sha256"] if contract else BINARY_SHA256
    config_sha = contract["identities"]["config"]["sha256"] if contract else CONFIG_SHA256
    check("frozen_binary", lambda: require(sha256(args.binary) == binary_sha,
          "binary is not the frozen, unchanged benchmark product", binary_sha))
    check("frozen_config", lambda: require(sha256(args.config) == config_sha,
          "config is not the frozen benchmark configuration", config_sha))
    check("upstream_head", lambda: require(command(["git", "-C", str(upstream), "rev-parse", "HEAD"]).strip() == COMMIT,
          "upstream HEAD is not the pinned image commit", COMMIT))
    check("upstream_runtime_clean", lambda: require(not command(["git", "-C", str(upstream), "diff", "HEAD", "--",
          "tool/DBDS", "tool/staticAnalysis/DBDS-INSTRU/llvm-mode/DBDSFunction.cpp"]).strip(),
          "upstream tracked driver/support/runtime files are dirty"))
    check("pinned_source_files", lambda: verify_pinned_sources(upstream, manifest))
    check("runtime_source_path", lambda: require(paths["runtime_source"] ==
          upstream / "tool/staticAnalysis/DBDS-INSTRU/llvm-mode/DBDSFunction.cpp", "incorrect runtime source path"))
    check("runtime_object_path", lambda: require(paths["runtime_object"] ==
          upstream / "tool/staticAnalysis/DBDS-INSTRU/DBDSFunction.o", "incorrect existing runtime object path"))
    check("reference_driver_path", lambda: require(paths["reference_driver"] ==
          paths["driver"].with_name("run_abi_parallel_reference.py"), "reference entry must be alongside the bound unified driver"))
    check("readelf_available", lambda: require(shutil.which("readelf") is not None, "GNU readelf unavailable"))
    for label in ("binary", "runtime_object"):
        def extract(label=label):
            text = command(["readelf", "--wide", "--debug-dump=info", str(paths[label])])
            destination = output.parent / (label + "-dwarf.txt")
            if destination.exists():
                raise ValueError("refusing to replace existing DWARF evidence")
            destination.write_text(text, encoding="utf-8")
            layout = runtime_layout(text)
            proof["observed_layouts"][label] = layout
            MemoryABI.from_layout(layout)
            return {"layout": layout, "dwarf_path": str(destination), "dwarf_sha256": sha256(destination)}
        check(label + "_dwarf_abi", extract)

    def common_layout():
        binary = MemoryABI.from_layout(proof["observed_layouts"]["binary"])
        object_abi = MemoryABI.from_layout(proof["observed_layouts"]["runtime_object"])
        require(binary.layout == object_abi.layout, "binary and existing runtime object DWARF layouts disagree")
        proof.update({"layout": binary.layout, "map_size": binary.map_size})
        return {"layout": binary.layout, "map_size": binary.map_size}

    check("common_runtime_layout", common_layout)

    def raw_audit():
        audit = audit_driver_source(upstream / "tool/DBDS/run_PDS.py", proof.get("layout"))
        proof["raw_driver_abi"] = audit
        require(audit["status"] != "unverifiable", "actual raw driver source ABI is not statically verified: " + audit.get("reason", ""))
        return audit

    check("raw_driver_abi_audit", raw_audit)
    proof["abi_layer_sha256"] = sha256(ABI_LAYER_PATH)
    proof["shared_abi_layer_sha256"] = proof["abi_layer_sha256"]
    proof["reference_driver_sha256"] = (sha256(paths["reference_driver"]) if paths["reference_driver"].is_file() else None)
    proof["note"] = ("PASS certifies the shared corrected MemoryABI against actual executable/object DWARF and pinned sources. "
                     "The raw legacy driver is separately audited; legacy_unverified is never permission to run it. "
                     "No binary/runtime/core algorithm is rebuilt, changed or executed by this preflight.")
    required = V2_REQUIRED_CHECKS + (BENCHMARK_REQUIRED_CHECKS if benchmark_manifest else ())
    if not proof["blockers"] and {row["name"] for row in proof["checks"]} == set(required):
        proof["status"] = "PASS"
    output.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("{0}: {1}".format(proof["status"], output))
    return 0 if proof["status"] == "PASS" else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("binary", "config", "runtime-object", "runtime-source", "upstream", "driver", "output"):
        parser.add_argument("--" + flag, required=True)
    parser.add_argument("--abi-profile", choices=("legacy-1990", "runtime-dwarf"), default="legacy-1990")
    parser.add_argument("--source-manifest", default=str(VENDOR_MANIFEST))
    parser.add_argument("--reference-driver", default=None)
    parser.add_argument("--benchmark-manifest", default=None,
                        help="frozen inspected identities for an allowlisted RQ1 benchmark")
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        parser.error("refusing to overwrite existing proof: " + str(output))
    if args.abi_profile == "runtime-dwarf":
        return _create_runtime_dwarf_proof(args, output)
    if args.benchmark_manifest:
        parser.error("--benchmark-manifest requires --abi-profile runtime-dwarf")
    proof = {"schema": "cs340-period-abi-proof-v1", "status": "BLOCKED",
             "source_commit": COMMIT, "expected": expected_layout(), "checks": [], "blockers": []}

    def check(label, callback):
        try:
            value = callback()
            proof["checks"].append({"name": label, "status": "PASS", "evidence": value})
            return value
        except Exception as exc:
            proof["checks"].append({"name": label, "status": "BLOCKED", "reason": str(exc)})
            proof["blockers"].append(label + ": " + str(exc))
            return None

    def require(condition, message, value=True):
        if not condition:
            raise ValueError(message)
        return value

    check("linux_x86_64", lambda: require(platform.system() == "Linux" and platform.machine() == "x86_64",
          "must run inside the existing x86_64 Linux container", platform.platform()))
    host_layout = {"uint16_bytes": ctypes.sizeof(ctypes.c_uint16), "uint_bytes": ctypes.sizeof(ctypes.c_uint),
                   "ulonglong_bytes": ctypes.sizeof(ctypes.c_ulonglong), "pointer_bytes": ctypes.sizeof(ctypes.c_void_p),
                   "byteorder": sys.byteorder}
    check("driver_host_ctypes", lambda: require(host_layout == {"uint16_bytes": 2, "uint_bytes": 4,
          "ulonglong_bytes": 8, "pointer_bytes": 8, "byteorder": "little"},
          "host Python ctypes ABI does not match the frozen x86_64 driver", host_layout))
    for label in ("binary", "config", "runtime_object", "runtime_source", "driver"):
        path = Path(getattr(args, label)).resolve()
        check(label + "_identity", lambda p=path, l=label: require(p.is_file(), str(p) + " missing",
              {"path": str(p), "sha256": sha256(p) if p.is_file() else None}))
    check("frozen_binary", lambda: require(sha256(args.binary) == BINARY_SHA256,
          "binary differs from the archived Table 2 reorder_3 product", BINARY_SHA256))
    check("frozen_config", lambda: require(sha256(args.config) == CONFIG_SHA256,
          "ConConfig differs from the archived build", CONFIG_SHA256))
    upstream = Path(args.upstream).resolve()
    check("upstream_head", lambda: require(command(["git", "-C", str(upstream), "rev-parse", "HEAD"]).strip() == COMMIT,
          "upstream checkout is not the fixed image commit", COMMIT))
    check("upstream_runtime_clean", lambda: require(not command(["git", "-C", str(upstream), "diff", "HEAD", "--",
          "tool/DBDS", "tool/staticAnalysis/DBDS-INSTRU/llvm-mode/DBDSFunction.cpp"]).strip(),
          "upstream driver/support/runtime tracked files differ from the pinned commit"))
    check("official_driver_constants", lambda: require(source_constants(upstream / "tool/DBDS/run_PDS.py") ==
          {"SHARE_THREAD_NUM": 100, "SHARE_ARRAY_SIZE": 1990}, "unexpected official driver constants",
          {"SHARE_THREAD_NUM": 100, "SHARE_ARRAY_SIZE": 1990}))
    check("runtime_source_path", lambda: require(Path(args.runtime_source).resolve() ==
          upstream / "tool/staticAnalysis/DBDS-INSTRU/llvm-mode/DBDSFunction.cpp",
          "runtime-source must identify the fixed checkout's DBDSFunction.cpp"))
    check("runtime_object_path", lambda: require(Path(args.runtime_object).resolve() ==
          upstream / "tool/staticAnalysis/DBDS-INSTRU/DBDSFunction.o",
          "runtime-object must be the existing DBDSFunction.o in the fixed checkout"))
    check("readelf_available", lambda: require(shutil.which("readelf") is not None, "GNU readelf unavailable"))
    actual_layouts = {}
    for label, path in (("binary", args.binary), ("runtime_object", args.runtime_object)):
        def extract(label=label, path=path):
            dwarf = command(["readelf", "--wide", "--debug-dump=info", str(Path(path).resolve())])
            destination = output.parent / (label + "-dwarf.txt")
            if destination.exists():
                raise ValueError("refusing to overwrite DWARF evidence")
            destination.write_text(dwarf, encoding="utf-8")
            layout = runtime_layout(dwarf)
            actual_layouts[label] = layout
            comparable = {key: value for key, value in layout.items() if key != "compilation_unit"}
            require(comparable == expected_layout(),
                    "linked/object Sched_Info is incompatible with 16-bit, 1990-entry driver: " + json.dumps(layout))
            return {"layout": layout, "dwarf_path": str(destination), "dwarf_sha256": sha256(destination)}
        check(label + "_dwarf_abi", extract)
    proof["observed_layouts"] = actual_layouts
    proof["note"] = ("Source hashes establish identity only. PASS requires actual runtime si DWARF in both "
                     "the executable and object to match all expected offsets/types/array dimensions. "
                     "This check does not establish original build/link provenance or launch a benchmark.")
    if not proof["blockers"]:
        proof["status"] = "PASS"
    output.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("{0}: {1}".format(proof["status"], output))
    return 0 if proof["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
