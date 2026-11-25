#!/usr/bin/env python3
"""DWARF-described PERIOD shared memory; no scheduler or runtime changes.

All address-taking methods require a valid buffer/mapping owned by the caller.
They validate offsets, lengths and values before touching native memory. Merely
constructing or attaching an ABI never clears an existing SysV segment.
"""
from __future__ import print_function

import ctypes
import json
import sys
from pathlib import Path

SCALARS = (("time", ctypes.c_uint64, 8), ("N", ctypes.c_uint32, 4),
           ("M", ctypes.c_uint32, 4), ("TestedBounds", ctypes.c_uint32, 4))
ARRAY_NAMES = ("kpNumArray", "kp", "kpLoc", "kpOrder")
FIELD_NAMES = tuple(item[0] for item in SCALARS) + ARRAY_NAMES


def _integer(value, label, lower=0, upper=None):
    if type(value) is not int or value < lower or (upper is not None and value > upper):
        raise ValueError("invalid " + label + ": " + repr(value))
    return value


class MemoryABI(object):
    @classmethod
    def from_layout(cls, layout):
        if not isinstance(layout, dict) or layout.get("struct_name") != "Sched_Info":
            raise ValueError("expected an observed Sched_Info layout")
        members = layout.get("members")
        if (not isinstance(members, list) or not all(isinstance(item, dict) for item in members) or
                tuple(item.get("name") for item in members) != FIELD_NAMES):
            raise ValueError("Sched_Info fields are missing, duplicated, reordered or unknown")
        fields, canonical = [], []
        for index, member in enumerate(members):
            if member.get("unsigned") is not True:
                raise ValueError("Sched_Info field is not proven unsigned")
            offset = _integer(member.get("offset"), "field offset")
            element_bytes = _integer(member.get("element_bytes"), "field element size", 1)
            if index < len(SCALARS):
                key, ctype, width = SCALARS[index]
                if element_bytes != width or member.get("dimensions") != []:
                    raise ValueError("invalid scalar type for " + key)
                dimensions = []
            else:
                key, width = ARRAY_NAMES[index - len(SCALARS)], 2
                dimensions = member.get("dimensions")
                if (element_bytes != 2 or not isinstance(dimensions, list) or
                        len(dimensions) != 1):
                    raise ValueError("invalid uint16 array type for " + key)
                count = _integer(dimensions[0], key + " capacity", 1, 1048576)
                ctype = ctypes.c_uint16 * count
                dimensions = [count]
            fields.append((key, ctype))
            canonical.append({"name": key, "offset": offset, "element_bytes": width,
                              "unsigned": True, "dimensions": dimensions})
        capacities = [canonical[index]["dimensions"][0] for index in (5, 6, 7)]
        if len(set(capacities)) != 1:
            raise ValueError("kp/kpLoc/kpOrder capacities differ")
        structure = type("ObservedPeriodSchedInfo", (ctypes.Structure,), {"_fields_": fields})
        byte_size = _integer(layout.get("byte_size"), "struct byte size", 1)
        if ctypes.sizeof(structure) != byte_size:
            raise ValueError("ctypes struct size disagrees with observed DWARF")
        for member in canonical:
            if getattr(structure, member["name"]).offset != member["offset"]:
                raise ValueError("ctypes offset disagrees with DWARF for " + member["name"])
        instance = cls()
        instance.layout = {"struct_name": "Sched_Info", "byte_size": byte_size, "members": canonical}
        instance.map_size = instance.struct_size = byte_size
        instance.thread_capacity = canonical[4]["dimensions"][0]
        instance.point_capacity = capacities[0]
        instance.structure_type = instance.ctypes_type = structure
        instance.offsets = {member["name"]: member["offset"] for member in canonical}
        instance._fields = dict(fields)
        instance._members = {member["name"]: member for member in canonical}
        return instance

    def field_offset(self, field):
        if field not in self.offsets:
            raise ValueError("unknown shared-memory field: " + str(field))
        return self.offsets[field]

    def field_bytes(self, field):
        self.field_offset(field)
        return ctypes.sizeof(self._fields[field])

    def _address(self, address, offset=0, length=None):
        limit = (1 << (8 * ctypes.sizeof(ctypes.c_void_p))) - 1
        _integer(address, "native address", 1, limit)
        _integer(offset, "mapping offset", 0, self.map_size)
        length = self.map_size if length is None else _integer(length, "memory length")
        if offset + length > self.map_size or address > limit - self.map_size:
            raise ValueError("memory operation exceeds the validated mapping")
        return address + offset

    def clear(self, address):
        """Explicit caller-requested clear, never called implicitly by attach."""
        ctypes.memset(self._address(address), 0, self.map_size)

    def read_scalar(self, address, field):
        if field not in self._members or self._members[field]["dimensions"]:
            raise ValueError("not a scalar field: " + str(field))
        size = self.field_bytes(field)
        pointer = self._address(address, self.field_offset(field), size)
        return int(self._fields[field].from_buffer_copy(ctypes.string_at(pointer, size)).value)

    def write_scalar(self, address, field, value):
        if field not in self._members or self._members[field]["dimensions"]:
            raise ValueError("not a scalar field: " + str(field))
        size = self.field_bytes(field)
        _integer(value, field + " unsigned value", 0, (1 << (size * 8)) - 1)
        pointer = self._address(address, self.field_offset(field), size)
        encoded = self._fields[field](value)
        ctypes.memmove(pointer, ctypes.byref(encoded), size)

    def read_array(self, address, field, count=None):
        if field not in self._members or not self._members[field]["dimensions"]:
            raise ValueError("not an array field: " + str(field))
        capacity = self._members[field]["dimensions"][0]
        count = capacity if count is None else _integer(count, "array read count", 0, capacity)
        pointer = self._address(address, self.field_offset(field), count * 2)
        return list((ctypes.c_uint16 * count).from_buffer_copy(ctypes.string_at(pointer, count * 2)))

    def write_array(self, address, field, values, start=0):
        if field not in self._members or not self._members[field]["dimensions"]:
            raise ValueError("not an array field: " + str(field))
        capacity = self._members[field]["dimensions"][0]
        start = _integer(start, "array write start", 0, capacity)
        values = list(values)
        if start + len(values) > capacity:
            raise ValueError("array write exceeds field capacity")
        for value in values:
            _integer(value, "uint16 array value", 0, 65535)
        pointer = self._address(address, self.field_offset(field) + start * 2, len(values) * 2)
        encoded = (ctypes.c_uint16 * len(values))(*values)
        if values:
            ctypes.memmove(pointer, encoded, len(values) * 2)

    def write_yield_pattern(self, address, pattern, n=None, m=None):
        if not isinstance(pattern, (list, tuple)) or not pattern:
            raise ValueError("yield pattern must be a nonempty rectangular matrix")
        rows = len(pattern)
        if not isinstance(pattern[0], (list, tuple)) or not pattern[0]:
            raise ValueError("yield pattern must have nonempty rows")
        columns = len(pattern[0])
        n = rows if n is None else _integer(n, "yield thread count", 1, self.thread_capacity)
        m = columns if m is None else _integer(m, "yield width", 1)
        if rows != n or columns != m or n > self.thread_capacity or n * m > self.point_capacity:
            raise ValueError("yield shape exceeds the observed ABI or declared N/M")
        flattened = []
        for row in pattern:
            if not isinstance(row, (list, tuple)) or len(row) != m:
                raise ValueError("yield pattern is not rectangular")
            for value in row:
                _integer(value, "yield uint16 value", 0, 65535)
                flattened.append(value)
        # Validation is complete before one atomic field-sized copy. Other
        # fields, including dry-run N/M/time and feedback arrays, are untouched.
        flattened.extend([0] * (self.point_capacity - len(flattened)))
        self.write_array(address, "kp", flattened)

    def validate_dimensions(self, n, m, allow_zero=False):
        lower = 0 if allow_zero else 1
        n = _integer(n, "thread count", lower, self.thread_capacity)
        m = _integer(m, "key-point width", lower)
        if n * m > self.point_capacity:
            raise ValueError("N*M exceeds the observed point-array capacity")
        return n, m


def segment_metadata(key, shmid, path="/proc/sysvipc/shm"):
    rows = Path(path).read_text(encoding="ascii").splitlines()
    if not rows:
        raise ValueError("cannot inspect the existing SysV shared-memory segment")
    columns = rows[0].split()
    for row in rows[1:]:
        record = dict(zip(columns, row.split()))
        if int(record["key"]) == key and int(record["shmid"]) == shmid:
            return {"size": int(record["size"]), "nattch": int(record["nattch"])}
    raise ValueError("SysV shared-memory identity was not found")


def setup_share_memory(libc, abi, key=1111):
    """Attach the exact observed layout, with no memset, ipcrm or resizing."""
    _integer(key, "SysV IPC key", 1, 2147483647)
    if not isinstance(abi, MemoryABI):
        raise ValueError("a validated MemoryABI is required")
    libc.shmget.argtypes = [ctypes.c_int, ctypes.c_size_t, ctypes.c_int]
    libc.shmget.restype = ctypes.c_int
    libc.shmat.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    libc.shmat.restype = ctypes.c_void_p
    created = True
    shmid = libc.shmget(key, abi.map_size, 512 | 1024 | 0o666)
    if shmid < 0:
        created = False
        shmid = libc.shmget(key, abi.map_size, 0o666)
    if shmid < 0:
        raise OSError(ctypes.get_errno(), "shmget failed; no segment was cleared or removed")
    metadata = segment_metadata(key, shmid)
    if metadata["size"] != abi.map_size or metadata["nattch"] != 0:
        raise ValueError("existing shared memory is attached or has a different ABI size")
    result = libc.shmat(shmid, None, 0)
    address = result.value if isinstance(result, ctypes.c_void_p) else result
    if address in (None, 0, -1, ctypes.c_void_p(-1).value):
        raise OSError(ctypes.get_errno(), "shmat failed")
    return abi._address(address)


def abi_from_proof(proof_path, target_path, dbds_dir):
    # Late import avoids an import cycle in proof generation and has no native
    # side effects. Validation repeats current file/DWARF/source bindings.
    from table2_scheduler_preflight import validate_abi_proof
    result = validate_abi_proof(proof_path, target_path, dbds_dir)
    if "layout" not in result:
        raise ValueError("runtime-dwarf ABI proof v2 is required")
    return MemoryABI.from_layout(result["layout"])
