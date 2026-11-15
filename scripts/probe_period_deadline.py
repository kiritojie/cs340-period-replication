#!/usr/bin/env python3
"""Bounded, standalone Linux x86_64 SCHED_DEADLINE capability probe.

No PERIOD source, affinity, cgroup, sysctl or persistent setting is modified.
Only a short-lived child changes its own scheduling policy. Defaults are
source-derived from the archived doubleFree Runtime=9710, N=2, CPUs=16;
they are NOT an observed sched_setattr trace or a benchmark acceptance test.
Compatible with Python 3.6 in the recorded Ubuntu 18.04 environment.
"""
import argparse
import ctypes
import datetime
import errno
import json
import os
import platform
import subprocess
import sys
import time


class Attr(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint32), ("sched_policy", ctypes.c_uint32),
        ("sched_flags", ctypes.c_uint64), ("sched_nice", ctypes.c_int32),
        ("sched_priority", ctypes.c_uint32), ("sched_runtime", ctypes.c_uint64),
        ("sched_deadline", ctypes.c_uint64), ("sched_period", ctypes.c_uint64),
    ]


class ReadAttr(ctypes.Structure):
    _fields_ = Attr._fields_ + [
        ("sched_util_min", ctypes.c_uint32), ("sched_util_max", ctypes.c_uint32)
    ]


def snapshot(attr):
    return {name: int(getattr(attr, name)) for name, _ in attr._fields_}


def invoke(libc, number, *args):
    ctypes.set_errno(0)
    result = int(libc.syscall(ctypes.c_long(number), *args))
    err = ctypes.get_errno() if result < 0 else 0
    return {"return": result, "errno": err,
            "errno_name": errno.errorcode.get(err, "OK"),
            "error": os.strerror(err) if err else None}


def child(args):
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    attr = Attr(ctypes.sizeof(Attr), 6, 0, 0, 0,
                args.runtime_ns, args.deadline_ns, args.period_ns)
    record = {"requested": snapshot(attr), "pid": os.getpid(),
              "euid": os.geteuid(), "affinity": sorted(os.sched_getaffinity(0))}
    with open("/proc/self/status") as status:
        record["process_status"] = [line.strip() for line in status
                                    if line.startswith(("Cap", "NoNewPrivs:",
                                                        "Seccomp:", "Cpus_allowed"))]
    record["sched_setattr"] = invoke(libc, 314, ctypes.c_int(0),
                                     ctypes.byref(attr), ctypes.c_uint(0))
    active = record["sched_setattr"]["return"] == 0
    passed = False
    if active:
        try:
            readback = ReadAttr()
            record["sched_getattr"] = invoke(libc, 315, ctypes.c_int(0),
                                             ctypes.byref(readback),
                                             ctypes.c_uint(ctypes.sizeof(readback)),
                                             ctypes.c_uint(0))
            record["readback"] = snapshot(readback)
            record["sched_getscheduler"] = os.sched_getscheduler(0)
            if record["sched_getattr"]["return"] == 0:
                keys = ("sched_policy", "sched_flags", "sched_priority", "sched_runtime",
                        "sched_deadline", "sched_period")
                passed = all(record["readback"][key] == record["requested"][key]
                             for key in keys)
                passed = passed and record["sched_getscheduler"] == 6
            before = time.monotonic()
            os.sched_yield()
            record["yield_returned"] = True
            record["yield_elapsed_seconds"] = time.monotonic() - before
        finally:
            normal = Attr()
            normal.size = ctypes.sizeof(Attr)
            record["restore_sched_other"] = invoke(libc, 314, ctypes.c_int(0),
                                                     ctypes.byref(normal),
                                                     ctypes.c_uint(0))
            passed = passed and record["restore_sched_other"]["return"] == 0
    record["status"] = "PASS_SINGLE_TASK" if passed else "FAIL"
    print(json.dumps(record, sort_keys=True))
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-ns", type=int, default=485500)
    parser.add_argument("--deadline-ns", type=int, default=9710000)
    parser.add_argument("--period-ns", type=int, default=9710000)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not (1024 <= args.runtime_ns <= args.deadline_ns <= args.period_ns <= 1000000000):
        parser.error("require 1024 <= runtime <= deadline <= period <= 1e9 ns")
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
        print(json.dumps({"status": "UNSUPPORTED_HOST", "system": platform.system(),
                          "machine": platform.machine(),
                          "reason": "Run in the recorded Linux x86_64 PERIOD container."}))
        return 77
    if args.child:
        return child(args)
    metadata = {"started_utc": datetime.datetime.utcnow().isoformat() + "Z",
                "kernel": platform.release(), "machine": platform.machine(),
                "scope": "single child; capability only; not benchmark results",
                "default_parameters_origin": "b6f72 runtime formula, archived doubleFree Runtime=9710, N=2, CPUs=16"}
    command = [sys.executable, os.path.abspath(__file__), "--child",
               "--runtime-ns", str(args.runtime_ns),
               "--deadline-ns", str(args.deadline_ns),
               "--period-ns", str(args.period_ns)]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True, timeout=5)
        metadata.update({"child_exit_code": result.returncode,
                         "child_stdout": result.stdout, "child_stderr": result.stderr})
        exit_code = result.returncode if result.returncode >= 0 else 1
    except subprocess.TimeoutExpired as exc:
        metadata.update({"status": "TIMEOUT", "timeout_seconds": 5,
                         "child_stdout": (exc.stdout or b"").decode("utf-8", "replace")
                         if isinstance(exc.stdout, bytes) else exc.stdout,
                         "child_stderr": (exc.stderr or b"").decode("utf-8", "replace")
                         if isinstance(exc.stderr, bytes) else exc.stderr})
        exit_code = 124
    print(json.dumps(metadata, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
