#!/usr/bin/env python3
"""Observe completed PERIOD yield-matrix writes without changing driver code.

Both experimental arms must use this observer. It adds Python profiling and
JSONL I/O overhead, so traced wall times are diagnostic only. It never edits a
frame, globals dictionary, scheduling function, benchmark, or shared-memory ABI.
Python 3.6+; no third-party packages are required by the observer itself.
"""
from __future__ import print_function

import argparse
import dis
import hashlib
import json
import runpy
import sys
import traceback
from pathlib import Path


class ObservationFailure(BaseException):
    """Abort through upstream's ordinary Exception handlers on observation loss."""


def _digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _copy(value):
    # Snapshot now: the scheduler may reuse and mutate these lists later.
    return json.loads(json.dumps(value, separators=(",", ":")))


def _positive_integer(value, label):
    if type(value) is not int or value < 1:
        raise ValueError(label + " is not a positive integer")
    return value


def _matrix(value):
    if not isinstance(value, list) or not value:
        raise ValueError("PatternList is not a nonempty matrix")
    for row in value:
        if not isinstance(row, list) or not row:
            raise ValueError("PatternList contains an empty/non-list row")
        if any(type(item) is not int or not 0 <= item <= 65535 for item in row):
            raise ValueError("PatternList contains a non-uint16 value")
    return value


class YieldObserver(object):
    def __init__(self, stream, expected_source):
        self.stream = stream
        self.expected_source = Path(expected_source).resolve()
        self.pending = {}
        self.yield_writes = 0
        self.ignored_initialization_writes = 0
        self.ignored_replay_writes = 0
        self.error = None

    def emit(self, event):
        self.stream.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        self.stream.flush()

    def _is_writer(self, frame):
        if frame.f_code.co_name != "memmove_pattern_list":
            return False
        source = frame.f_globals.get("__file__")
        if source is None or Path(source).resolve() != self.expected_source:
            return False
        function = frame.f_globals.get("memmove_pattern_list")
        return getattr(function, "__code__", None) is frame.f_code

    def _non_exploration_phase(self, frame, caller):
        """Recognize only the pinned driver's known pre-exploration writes.

        run_PDS.py:437 writes pattern_list for TaskReproduce; :480 and :525
        write ZeroPattern before DBDS_stage is initialized at :558. Do not
        classify an incomplete positive-round context as initialization.
        """
        namespace = frame.f_globals
        if caller.f_locals is not namespace:
            return None
        if type(namespace.get("rounds")) is not int or namespace["rounds"] != 0:
            return None
        if any(label in namespace for label in ("DBDS_stage", "iterPeriod", "inter")):
            return None
        task = namespace.get("TaskReproduce")
        if type(task) is not int:
            return None
        pattern = frame.f_locals.get("PatternList")
        if task == 0 and "ZeroPattern" in namespace and pattern is namespace["ZeroPattern"]:
            return "initialization"
        if task == 1 and "pattern_list" in namespace and pattern is namespace["pattern_list"]:
            return "replay"
        return None

    def profile(self, frame, event, argument):
        if event not in ("call", "return"):
            return
        try:
            if not self._is_writer(frame):
                return
            key = id(frame)
            if event == "call":
                if key in self.pending:
                    raise ValueError("writer frame was already pending")
                caller = frame.f_back
                if caller is None or caller.f_globals is not frame.f_globals:
                    raise ValueError("yield writer caller is outside its driver namespace")
                phase = self._non_exploration_phase(frame, caller)
                if phase is not None:
                    self.pending[key] = {"ignored_phase": phase}
                    return
                values = caller.f_locals

                def lookup(label):
                    return values[label] if label in values else frame.f_globals[label]

                record = {
                    "event": "yield_write",
                    "ordinal": _positive_integer(lookup("rounds"), "rounds"),
                    "period": _positive_integer(lookup("iterPeriod"), "iterPeriod"),
                    "schedule": _copy(lookup("inter")),
                    "yield_pattern": _copy(_matrix(frame.f_locals["PatternList"])),
                    "source_file": str(self.expected_source),
                    "code_filename": frame.f_code.co_filename,
                }
                self.pending[key] = record
                return
            if key not in self.pending:
                raise ValueError("writer returned without an observed call")
            record = self.pending.pop(key)
            # A profile 'return' also occurs when an exception unwinds a frame.
            # Only normal RETURN_* instructions prove this writer completed.
            instruction = frame.f_code.co_code[frame.f_lasti] if frame.f_lasti >= 0 else -1
            if instruction < 0 or dis.opname[instruction] not in ("RETURN_VALUE", "RETURN_CONST"):
                raise ValueError("yield writer did not return normally")
            if "ignored_phase" in record:
                if record["ignored_phase"] == "initialization":
                    self.ignored_initialization_writes += 1
                else:
                    self.ignored_replay_writes += 1
                return
            self.emit(record)
            self.yield_writes += 1
        except BaseException as error:
            self.error = type(error).__name__ + ": " + str(error)
            try:
                self.emit({"event": "trace_error", "reason": self.error})
            finally:
                raise ObservationFailure(self.error)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--expected-source", type=Path, required=True,
                        help="exact unchanged official tool/DBDS/run_PDS.py path")
    parser.add_argument("driver_and_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.driver_and_args
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("provide DRIVER_PATH and its arguments after --")
    driver = Path(command[0]).resolve()
    expected = args.expected_source.resolve()
    if not driver.is_file() or not expected.is_file():
        parser.error("driver and expected official source must both exist")
    if args.trace.exists():
        parser.error("refusing to overwrite trace: " + str(args.trace))
    if sys.getprofile() is not None:
        parser.error("another profiler is already active")
    old_argv, old_path = sys.argv, list(sys.path)
    code = 0
    # 'x' prevents an accidental race from truncating an existing trace.
    with args.trace.open("x", encoding="utf-8") as stream:
        observer = YieldObserver(stream, expected)
        observer.emit({"event": "trace_start", "schema": "cs340-period-yield-trace-v1",
                       "driver_path": str(driver), "driver_sha256": _digest(driver),
                       "expected_source": str(expected), "expected_source_sha256": _digest(expected),
                       "driver_argv": [str(driver)] + command[1:],
                       "observation": "sys.setprofile at normal memmove_pattern_list return"})
        try:
            sys.argv = [str(driver)] + command[1:]
            # Match direct `python DRIVER.py ...` import resolution.
            sys.path.insert(0, str(driver.parent))
            sys.setprofile(observer.profile)
            runpy.run_path(str(driver), run_name="__main__")
        except SystemExit as error:
            if error.code is None:
                code = 0
            elif isinstance(error.code, int):
                code = error.code
            else:
                print(error.code, file=sys.stderr)
                code = 1
        except KeyboardInterrupt:
            code = 130
            traceback.print_exc()
        except BaseException:
            code = 2
            traceback.print_exc()
        finally:
            sys.setprofile(None)
            sys.argv, sys.path[:] = old_argv, old_path
            if observer.error is not None or observer.pending:
                code = 2
            observer.emit({"event": "trace_summary", "yield_writes": observer.yield_writes,
                           "driver_exit_code": code, "pending_writes": len(observer.pending),
                           "observation_error": observer.error,
                           "ignored_initialization_writes": observer.ignored_initialization_writes,
                           "ignored_replay_writes": observer.ignored_replay_writes})
    return code


if __name__ == "__main__":
    sys.exit(main())
