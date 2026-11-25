#!/usr/bin/env python3
"""Experimental adapter for the pinned PERIOD driver; upstream files stay intact.

Upstream orchestration: Copyright (c) 2022 Cheng Wen, MIT License.
The complete original license is preserved in vendor/period_b6f72a7/LICENSE.
Local adaptation: cs340-period-replication experimental orchestration.

The scheduling generators, runtime, and benchmark binary are never rewritten.
This module is import safe: only main() can launch a benchmark.  See the pilot
report for the Serial prefix filtering and depth-mapping deviations.
"""
import argparse
import ast
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import traceback
import time
from typing import Callable, Optional

UPSTREAM_COMMIT = "b6f72a7b06d01ffa7114b640312873ec2578a5ea"
VENDOR = Path(__file__).resolve().parent / "vendor" / "period_b6f72a7"
PURE_MODULES = ("sched", "pds", "bp_sched", "sbp_sched", "sbp_sched_mixed_end")
RUNTIME_FILES = tuple(name + ".py" for name in PURE_MODULES) + (
    "run_PDS.py", "external_def.py", "interleaving.py", "ipc.py",
)
_modules = {}


class BudgetExhausted(RuntimeError):
    """The global logical schedule budget has been reached."""


class NoScheduleError(ValueError):
    """The official generator has no schedule for the requested constraints."""


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(name + " must be a positive integer")
    return value


def _mode(mode):
    if mode not in ("parallel", "serial"):
        raise ValueError("scheduler must be parallel or serial")
    return mode


def period_bounds(mode, depth, n):
    """Return inclusive period bounds, using the official two depth mappings."""
    _mode(mode)
    _positive(depth, "depth")
    _positive(n, "number of threads")
    return (2, depth + 1) if mode == "parallel" else (n, depth + n - 1)


def logical_depth(mode, period, n):
    _mode(mode)
    _positive(period, "period")
    _positive(n, "number of threads")
    return period - 1 if mode == "parallel" else period - n + 1


def matches_prefix(schedule, prefix):
    """A prefix fixes completed periods and a nonempty start of its final period."""
    if not prefix:
        return True
    if len(schedule) < len(prefix) or schedule[:len(prefix) - 1] != prefix[:-1]:
        return False
    tail = schedule[len(prefix) - 1]
    return tail[:len(prefix[-1])] == prefix[-1]


def _validate_prefix(prefix, n, kps, p):
    if prefix is None or prefix == []:
        return
    if not isinstance(prefix, list) or len(prefix) > p:
        raise ValueError("prefix must be a list containing at most p periods")
    counts = [0] * n
    previous = None
    for period in prefix:
        if not isinstance(period, list) or not period:
            raise ValueError("prefix periods must be nonempty lists")
        if any(isinstance(t, bool) or not isinstance(t, int) or t < 0 or t >= n for t in period):
            raise ValueError("prefix contains an invalid thread identifier")
        if len(set(period)) != 1:
            raise ValueError("prefix periods must contain one thread")
        thread = period[0]
        if thread == previous:
            raise ValueError("adjacent prefix periods must contain different threads")
        previous = thread
        for thread in period:
            counts[thread] += 1
    if any(a > b for a, b in zip(counts, kps)):
        raise ValueError("prefix consumes more key points than the slice provides")


def _manifest_entries(manifest_path):
    data = json.loads(Path(manifest_path).read_text(encoding="utf-8-sig"))
    commit = data.get("commit", data.get("source_commit", data.get("upstream_commit")))
    if commit != UPSTREAM_COMMIT:
        raise RuntimeError("source manifest does not identify the required upstream commit")
    files = data.get("files", [])
    if isinstance(files, dict):
        files = [dict(value, path=path) if isinstance(value, dict) else {"path": path, "sha256": value}
                 for path, value in files.items()]
    entries = {}
    for entry in files:
        entries[Path(entry["path"]).name] = entry
    return entries


def verify_official_files(dbds_dir, names=RUNTIME_FILES, manifest_path=None):
    """Verify bytes, not just git HEAD; never trust an unverified external module."""
    directory = Path(dbds_dir).resolve()
    entries = _manifest_entries(manifest_path or VENDOR / "SOURCE_MANIFEST.json")
    verified = {}
    for name in names:
        if name not in entries:
            raise RuntimeError("source manifest is missing " + name)
        path = directory / name
        raw = path.read_bytes()
        entry = entries[name]
        sha256 = hashlib.sha256(raw).hexdigest()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
        expected_sha = entry.get("sha256")
        expected_blob = entry.get("git_blob_sha", entry.get("git_blob_sha1", entry.get("blob_sha", entry.get("git_blob"))))
        if not expected_sha and not expected_blob:
            raise RuntimeError("manifest has no supported digest for " + name)
        if expected_sha and sha256 != expected_sha:
            raise RuntimeError("SHA-256 mismatch for " + str(path))
        if expected_blob and blob != expected_blob:
            raise RuntimeError("git blob mismatch for " + str(path))
        verified[name] = {"path": str(path), "sha256": sha256, "git_blob_sha": blob}
    return verified


def load_official_modules(dbds_dir, manifest_path=None):
    """Load the five verified, dependency-free generators, including local sched.py."""
    directory = Path(dbds_dir).resolve()
    verify_official_files(directory, tuple(n + ".py" for n in PURE_MODULES), manifest_path)
    loaded = {}
    # Upstream imports its own 'sched', whose name also exists in the stdlib.
    # All five names are installed explicitly from verified paths in dependency order.
    for name in PURE_MODULES:
        spec = importlib.util.spec_from_file_location(name, directory / (name + ".py"))
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load official module " + name)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        loaded[name] = module
    _modules.clear()
    _modules.update(loaded)
    globals()["SBPSched"] = loaded["sbp_sched"].SBPSched
    globals()["SBPMESched"] = loaded["sbp_sched_mixed_end"].SBPMESched
    return loaded


class _Scheduler:
    def __init__(self, inner, prefix, candidate_callback=None, filter_prefix=False):
        self.inner = inner
        self.prefix = [part.copy() for part in (prefix or [])]
        self.candidate_callback = candidate_callback
        self.filter_prefix = filter_prefix
        self.current = None

    def __iter__(self):
        return self

    def __next__(self):
        while True:
            candidate = next(self.inner)
            if self.candidate_callback:
                self.candidate_callback()
            if self.filter_prefix and not matches_prefix(candidate, self.prefix):
                continue
            if not matches_prefix(candidate, self.prefix):
                raise RuntimeError("official Parallel generator violated its fixed prefix")
            self.current = [part.copy() for part in candidate]
            return candidate

    def get_schedule(self):
        return self.inner.get_schedule() if self.current is None else [part.copy() for part in self.current]

    def get_yield_pattern(self):
        return self.inner.get_yield_pattern()

    def get_prefix(self):
        return self.inner.get_prefix()


def make_scheduler(mode, n, kps, p, prefix=None, candidate_callback=None):
    """Construct an unchanged official generator with explicit prefix semantics.

    Serial prefix jobs enumerate the full official Serial set, then select its
    valid prefix subset.  This is complete for that subset, but can generate
    rejected candidates and cost more time than a native fixed-prefix generator.
    """
    _mode(mode)
    _positive(n, "number of threads")
    _positive(p, "period")
    if not kps or any(isinstance(k, bool) or not isinstance(k, int) or k < 0 for k in kps):
        raise ValueError("kps must be a nonempty nonnegative integer list")
    # Sched._init_helper uses max(n, len(kps)); retain that upstream behavior.
    effective_n = max(n, len(kps))
    padded = list(kps)
    padded.extend([padded[-1]] * (effective_n - len(padded)))
    _validate_prefix(prefix, effective_n, padded, p)
    if not _modules:
        raise RuntimeError("call load_official_modules() before make_scheduler()")
    try:
        if mode == "parallel":
            cls = _modules["sbp_sched_mixed_end"].SBPMESched
            inner = cls(n, kps, p, prefix, fix_prefix=True) if prefix else cls(n, kps, p)
        else:
            inner = _modules["sbp_sched"].SBPSched(n, kps, p)
    except ValueError as error:
        raise NoScheduleError(str(error)) from error
    return _Scheduler(inner, prefix, candidate_callback, mode == "serial" and bool(prefix))


class Budget:
    """Global logical schedule accounting; physical retests are separate."""
    def __init__(self, limit=0):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("budget must be a nonnegative integer; zero means unlimited")
        self.limit = limit
        self.generated = self.executed = self.completed = self.retests = self.retests_completed = 0
        self.budget_hit = False
        self._active = {}
        self._sequence = 0

    @property
    def started(self):
        return self.executed

    def note_generated(self):
        self.generated += 1

    def can_start(self, retest=False):
        return bool(self.executed) if retest else self.limit == 0 or self.executed < self.limit

    def before_start(self, retest=False):
        if retest and not self.executed:
            raise RuntimeError("a retest needs a previously started logical schedule")
        if not self.can_start(retest):
            self.budget_hit = True
            raise BudgetExhausted("global logical schedule budget exhausted")

    def start(self, process_id=None, retest=False):
        self.before_start(retest)
        self._sequence += 1
        key = process_id if process_id is not None else ("attempt", self._sequence)
        if key in self._active:
            raise RuntimeError("process already active")
        self._active[key] = bool(retest)
        if retest:
            self.retests += 1
        else:
            self.executed += 1
        return key

    def complete(self, process_id=None, retest=False):
        key = process_id
        if key is None:
            key = next((k for k, r in self._active.items() if r == bool(retest)), None)
        if key not in self._active:
            raise RuntimeError("cannot complete an unstarted or already completed process")
        if self._active[key] != bool(retest):
            raise RuntimeError("completion has the wrong retest classification")
        del self._active[key]
        if retest:
            self.retests_completed += 1
        else:
            self.completed += 1

    def snapshot(self):
        return {"limit": self.limit, "generated": self.generated, "executed": self.executed,
                "completed": self.completed, "retests": self.retests,
                "retests_completed": self.retests_completed,
                "physical_launches": self.executed + self.retests,
                "in_flight": len(self._active), "budget_hit": self.budget_hit}


def _replace_once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError("pinned driver adaptation anchor changed: " + repr(old[:100]))
    return source.replace(old, new, 1)


def prepare_abi_source(source):
    """Correct only the pinned driver's IPC contract using a proven MemoryABI.

    The source still uses the official generators, period/depth mapping,
    feedback, error classification, statistics, and budget.  In particular this
    is not a substitution of the number 1990: every raw IPC read/write and every
    receiving ctypes array is replaced by the same checked ABI implementation.
    The runtime-populated dry-run segment is attached without clearing it.
    """
    source = _replace_once(source, "SHARE_THREAD_NUM = 100", "SHARE_THREAD_NUM = _comparison_abi.thread_capacity")
    source = _replace_once(source, "SHARE_ARRAY_SIZE = 1990", "SHARE_ARRAY_SIZE = _comparison_abi.point_capacity")
    start = source.index("def setup_share_memroy():")
    end = source.index("# create subprocess according to the value of check_STDOUT and check_STDERR")
    helpers = '''class PeriodABIError(BaseException):
    """Fatal IPC contract error; the historical generic handler must not hide it."""

def _abi_checked(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except Exception as error:
        raise PeriodABIError("shared-memory ABI operation failed: " + str(error)) from error

def setup_share_memroy():
    return _abi_checked(_comparison_setup_share_memory, CDLL("libc.so.6", use_errno=True), _comparison_abi)

def get_info_from_share_memory(P=None, A=None, B=None, T=None, kpNumArray=None, kpYieldArray=None, kpLocArray=None, kpOrderArray=None):
    for destination, field in ((P, "time"), (A, "N"), (B, "M"), (T, "TestedBounds")):
        if destination is not None:
            destination.value = _abi_checked(_comparison_abi.read_scalar, ADDR, field)
    if A is not None and B is not None:
        _abi_checked(_comparison_abi.validate_dimensions, A.value, B.value, allow_zero=True)
    for destination, field in ((kpNumArray, "kpNumArray"), (kpYieldArray, "kp"), (kpLocArray, "kpLoc"), (kpOrderArray, "kpOrder")):
        if destination is not None:
            values = _abi_checked(_comparison_abi.read_array, ADDR, field)
            if len(destination) != len(values):
                raise PeriodABIError("receiving ctypes array does not match proven field " + field)
            for index, value in enumerate(values):
                destination[index] = value

def memmove_pattern_list(PatternList):
    _abi_checked(_comparison_abi.write_yield_pattern, ADDR, PatternList)

'''
    source = source[:start] + helpers + source[end:]
    for local, field in (("kpNumArray", "kpNumArray"), ("kpYieldArray", "kp"), ("kpLocArray", "kpLoc"), ("kpOrderArray", "kpOrder")):
        capacity = "SHARE_THREAD_NUM" if field == "kpNumArray" else "SHARE_ARRAY_SIZE"
        source = _replace_once(source, local + " = (c_uint16*" + capacity + ")(0)",
                               local + " = dict(_comparison_abi.structure_type._fields_)[" + repr(field) + "]()")
    scalar_writes = (
        ("memmove(ADDR + sizeof(c_ulonglong) + sizeof(c_uint)*2, byref(c_uint(0)), sizeof(c_uint))", "TestedBounds", "0"),
        ("memmove(ADDR, byref(c_ulonglong(int(Period*10))), sizeof(c_ulonglong))", "time", "int(Period*10)"),
        ("memmove(ADDR, byref(c_ulonglong(int(Period*100))), sizeof(c_ulonglong))", "time", "int(Period*100)"),
        ("memmove(ADDR, byref(c_ulonglong(int(Period*1.5))), sizeof(c_ulonglong))", "time", "int(Period*1.5)"),
        ("memmove(ADDR + sizeof(c_ulonglong), byref(c_uint(threadNum)), sizeof(c_uint))", "N", "threadNum"),
        ("memmove(ADDR + sizeof(c_ulonglong) + sizeof(c_uint), byref(c_uint(KPNum)), sizeof(c_uint))", "M", "KPNum"),
        ("memmove(ADDR + sizeof(c_ulonglong) + sizeof(c_uint)*2, byref(c_uint(maxYieldNum)), sizeof(c_uint))", "TestedBounds", "maxYieldNum"),
        ("memmove(ADDR + sizeof(c_ulonglong) + sizeof(c_uint)*2, byref(c_uint(N-1)), sizeof(c_uint))", "TestedBounds", "N-1"),
        ("memmove(ADDR + sizeof(c_ulonglong) + sizeof(c_uint)*2, byref(c_uint(iterPeriod-1)), sizeof(c_uint))", "TestedBounds", "iterPeriod-1"),
        ("memmove(ADDR + sizeof(c_ulonglong), byref(c_uint(N)), sizeof(c_uint))", "N", "N"),
        ("memmove(ADDR + sizeof(c_ulonglong) + sizeof(c_uint), byref(c_uint(M)), sizeof(c_uint))", "M", "M"),
    )
    for old, field, value in scalar_writes:
        source = _replace_once(source, old, "_abi_checked(_comparison_abi.write_scalar, ADDR, " + repr(field) + ", " + value + ")")
    source = _replace_once(source, "if N > SHARE_THREAD_NUM or M * (N + zero_in_KP) > SHARE_ARRAY_SIZE:",
                           "if N + zero_in_KP > SHARE_THREAD_NUM or M * (N + zero_in_KP) > SHARE_ARRAY_SIZE:")
    source = "# IPC ABI-only adaptation; original PERIOD commit " + UPSTREAM_COMMIT + "\n" + source
    tree = ast.parse(source)
    forbidden = {"memmove", "memset", "shmget", "shmat"}
    remaining = sorted({node.func.id for node in ast.walk(tree)
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in forbidden})
    if remaining:
        raise RuntimeError("unadapted direct IPC operation: " + repr(remaining))
    compile(source, "<PERIOD-ABI-only-adapted>", "exec")
    return source


def runtime_abi_from_result(proof_result):
    """Require the new measured runtime proof, rather than accepting v1/1990."""
    if proof_result.get("status") != "PASS" or proof_result.get("abi_profile") != "runtime-dwarf" or "layout" not in proof_result:
        raise ValueError("execution requires the measured runtime-dwarf ABI proof (v2)")
    from period_shared_memory import MemoryABI
    abi = MemoryABI.from_layout(proof_result["layout"])
    if (abi.thread_capacity, abi.point_capacity, abi.map_size) != (100, 3964, 24008):
        raise ValueError("runtime proof does not match the selected 100-thread/3964-point profile")
    return abi


def verify_harness_identity(proof_result, role, path):
    """Bind the actually imported harness bytes to the revalidated v2 proof."""
    identity = proof_result.get("identities", {}).get(role)
    actual = Path(path).resolve()
    if not isinstance(identity, dict) or "path" not in identity or "sha256" not in identity:
        raise ValueError("runtime ABI proof does not bind the " + role + " harness")
    digest = hashlib.sha256(actual.read_bytes()).hexdigest()
    if Path(identity["path"]).resolve() != actual or identity["sha256"] != digest:
        raise ValueError("current " + role + " harness differs from the runtime ABI proof")
    return digest


def prepare_driver_source(source, mode):
    """Adapt only the pinned driver's orchestration, with checked exact anchors."""
    _mode(mode)
    source = _replace_once(source, "period_limit = bugDepth + 1\n\nfor iterPeriod in range(2, period_limit+1):",
                           "first_period, period_limit = period_bounds(COMPARISON_MODE, bugDepth, N_after_DryRun)\n\nfor iterPeriod in range(first_period, period_limit+1):")
    source = source.replace("iterPeriod == 2", "iterPeriod == first_period")
    source = _replace_once(source, "DBDS_stage == 1 and iterPeriod-1 >= 4", "DBDS_stage == 1 and logical_depth(COMPARISON_MODE, iterPeriod, N_after_DryRun) >= 4")
    source = _replace_once(source, 'print("Targeting bugs that bug depth =", iterPeriod-1,', 'print("Targeting bugs that bug depth =", logical_depth(COMPARISON_MODE, iterPeriod, N_after_DryRun),')
    replacements = [
        ("SBPMESched(N_after_DryRun + zero_in_KP, MList, iterPeriod)", "_comparison_scheduler(N_after_DryRun + zero_in_KP, MList, iterPeriod)"),
        ("SBPMESched(N + zero_num(useful_kp_num_list, [0]*SHARE_THREAD_NUM, N), useful_kp_num_list, iterPeriod)", "_comparison_scheduler(N + zero_num(useful_kp_num_list, [0]*SHARE_THREAD_NUM, N), useful_kp_num_list, iterPeriod)"),
        ("SBPMESched(N, useful_kp_num_list, iterPeriod)", "_comparison_scheduler(N, useful_kp_num_list, iterPeriod)"),
        ("SBPMESched(tempL[2], tmpMList, iterPeriod, prefix, fix_prefix=True)", "_comparison_scheduler(tempL[2], tmpMList, iterPeriod, prefix)"),
    ]
    for old, new in replacements:
        source = _replace_once(source, old, new)
    # The four generator construction handlers may handle an impossible slice,
    # but must never hide malformed prefixes, ABI errors, or implementation bugs.
    if source.count("except:") != 4:
        raise RuntimeError("unexpected generic generator handler count")
    source = source.replace("except:", "except NoScheduleError:")
    source = _replace_once(source, "                rounds = rounds + 1", "                _comparison_budget.before_start()\n                rounds = rounds + 1")
    source = _replace_once(source,
        "                if runs_limit != 0 and rounds > runs_limit:\n                    reach_runs_limit = 1\n                    break",
        "                # Global budget is enforced before counting, printing, or launching.")
    source = _replace_once(source, "\n                process = create_DBDS_subprocess(check_STDOUT, check_STDERR)",
        "\n                process = _comparison_launch(create_DBDS_subprocess, check_STDOUT, check_STDERR, retest=False)")
    source = _replace_once(source, "\n                        process = create_DBDS_subprocess(check_STDOUT, check_STDERR)",
        "\n                        process = _comparison_launch(create_DBDS_subprocess, check_STDOUT, check_STDERR, retest=True)")
    source = _replace_once(source, '                    subprocess.check_call(["sudo", "kill", str(process.pid)])', "                    _comparison_timeout_cleanup(process)")
    source = _replace_once(source, '                    print("\\033[34m\\tUnknown Exception" + "\\033[0m")\n                    print(e)\n                    pass', "                    raise RuntimeError('target execution or feedback failed') from e")
    # Catch the budget once outside every period/stage/prefix loop. The normal
    # upstream footer is retained, including its unmodified error classification.
    start = source.index("for iterPeriod in range(first_period, period_limit+1):")
    end = source.index('print("\\033[4;36mEnd Testing!')
    body = source[start:end]
    wrapped = "try:\n" + "".join("    " + line if line.strip() else line for line in body.splitlines(keepends=True))
    wrapped += "except BudgetExhausted:\n    print('COMPARISON_BUDGET_EXHAUSTED')\n\nrounds = _comparison_budget.executed\n"
    source = source[:start] + wrapped + source[end:]
    ending = source.rstrip()
    if not ending.endswith("exit()"):
        raise RuntimeError("pinned driver normal-exit anchor changed")
    source = ending[:-len("exit()")] + "_comparison_finished = True\n"
    source = "# Experimental orchestration adapter; upstream commit " + UPSTREAM_COMMIT + "\nCOMPARISON_MODE = " + repr(mode) + "\n" + source
    compile(source, "<PERIOD-comparison-adapted>", "exec")
    return source


class _Process:
    def __init__(self, process, budget, retest):
        self.process, self.budget, self.retest = process, budget, retest
        self.finished = False

    def __getattr__(self, name):
        return getattr(self.process, name)

    def communicate(self, *args, **kwargs):
        result = self.process.communicate(*args, **kwargs)
        self._complete()
        return result

    def _complete(self):
        if not self.finished:
            self.budget.complete(self.process.pid, self.retest)
            self.finished = True

    def cleanup(self):
        from table2_scheduler_permissions import cleanup_owned_process
        cleanup_owned_process(self.process, own_group=True)
        self._complete()


class ProcessSupervisor:
    """Apply one permission/lifecycle policy to every official driver launch.

    The verified source and finalized command lists retain their original indices.
    Only Popen's argv/environment and ownership of child process groups change.
    This also observes preparation children, outside the logical schedule budget.
    """
    def __init__(self, popen):
        self.popen = popen
        self.processes = []
        self.launches = []
        self.subreaper_before = None
        self.reaped_descendants = []
        self.launching = False
        self.pending_signal = None

    def defer_signal(self, signum):
        # A TERM handler must not unwind Popen before the newly created private
        # group is registered for cleanup. The child inherits no blocked mask.
        if self.launching:
            self.pending_signal = signum
            return True
        return False

    def enable_subreaper(self):
        """Adopt target descendants so a non-reaping container PID 1 is safe."""
        if self.subreaper_before is not None:
            return
        libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        if libc.prctl(37, ctypes.byref(previous), 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "PR_GET_CHILD_SUBREAPER failed")
        if libc.prctl(36, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "PR_SET_CHILD_SUBREAPER failed")
        self.subreaper_before = previous.value

    def __call__(self, *args, **kwargs):
        from table2_scheduler_permissions import prepare_process_launch
        if args:
            original = args[0]
        else:
            original = kwargs.pop("args")
        command, options = prepare_process_launch(original, kwargs)
        if options.get("preexec_fn") is os.setpgrp:
            own_group = True
        elif options.get("preexec_fn") is None:
            # Preparation and dry-run children also need a private process group
            # so an outer timeout can clean up all their descendants.
            options["start_new_session"] = True
            own_group = True
        else:
            raise ValueError("unverified driver child process-group setup")
        self.launching = True
        try:
            process = self.popen(command, *args[1:], **options)
            self.processes.append((process, own_group))
            self.launches.append({"pid": process.pid, "original_argv": list(original),
                                  "executed_argv": list(command), "own_process_group": own_group})
        finally:
            self.launching = False
        if self.pending_signal is not None:
            signum, self.pending_signal = self.pending_signal, None
            signal.getsignal(signum)(signum, None)
        return process

    def cleanup(self):
        from table2_scheduler_permissions import cleanup_owned_process
        errors = []
        for process, own_group in self.processes:
            try:
                # A reaped leader can still have living descendants in its group.
                cleanup_owned_process(process, own_group=own_group)
            except BaseException as error:
                errors.append(traceback.format_exc())
        if self.subreaper_before is not None:
            deadline = time.monotonic() + 2
            while True:
                try:
                    pid, status = os.waitpid(-1, os.WNOHANG)
                except ChildProcessError:
                    break
                if pid:
                    self.reaped_descendants.append({"pid": pid, "wait_status": status})
                elif time.monotonic() >= deadline:
                    errors.append("owned descendants did not exit within cleanup bound")
                    break
                else:
                    time.sleep(0.01)
            libc = ctypes.CDLL(None, use_errno=True)
            if libc.prctl(36, self.subreaper_before, 0, 0, 0) != 0:
                errors.append("PR_SET_CHILD_SUBREAPER restore failed")
            self.subreaper_before = None
        if errors:
            raise RuntimeError("; ".join(errors))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scheduler", choices=("serial", "parallel"), required=True)
    parser.add_argument("--period-root", type=Path, default=Path(os.environ.get("PERIOD_ROOT", "/workdir/PERIOD")))
    parser.add_argument("--manifest", type=Path, default=VENDOR / "SOURCE_MANIFEST.json")
    parser.add_argument("--depth", type=int, default=3)
    parser.add_argument("--budget", type=int, default=10000)
    parser.add_argument("--target-timeout", type=int, default=5)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--abi-proof", type=Path)
    parser.add_argument("--permission-proof", type=Path)
    parser.add_argument("--emit-adapted-source", type=Path)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("target", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    _positive(args.depth, "depth")
    _positive(args.target_timeout, "target timeout")
    budget = Budget(args.budget)
    directory = args.period_root.resolve() / "tool" / "DBDS"
    verified = verify_official_files(directory, manifest_path=args.manifest)
    raw = (directory / "run_PDS.py").read_bytes()
    abi_source = prepare_abi_source(raw.decode("utf-8"))
    adapted = prepare_driver_source(abi_source, args.scheduler)
    if args.emit_adapted_source:
        with args.emit_adapted_source.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(adapted)
    metadata = {"schema_version": 2, "role": "unified-scheduler-comparison", "abi_profile": "runtime-dwarf",
                "abi_validation": "NOT_EXECUTED", "upstream_commit": UPSTREAM_COMMIT,
                "scheduler": args.scheduler, "depth": args.depth,
                "budget": args.budget,
                "original_source_sha256": hashlib.sha256(raw).hexdigest(),
                "abi_only_source_sha256": hashlib.sha256(abi_source.encode("utf-8")).hexdigest(),
                "adapted_source_sha256": hashlib.sha256(adapted.encode("utf-8")).hexdigest(),
                "verified_sources": verified, "status": "CHECK_ONLY" if args.check_only else "STARTING",
                "serial_prefix_policy": "full official Serial enumeration filtered by complete prefix",
                "target_timeout_seconds": args.target_timeout}
    processes = []
    namespace = {}
    return_code = 0
    old_argv, old_path, original_popen = sys.argv, list(sys.path), subprocess.Popen
    supervisor = ProcessSupervisor(original_popen)
    previous_sigterm = None
    try:
        if args.check_only:
            print(json.dumps(metadata, sort_keys=True))
            return 0
        if sys.platform != "linux":
            raise RuntimeError("benchmark execution requires the verified Linux environment")
        target = args.target[1:] if args.target[:1] == ["--"] else args.target
        if not target:
            raise ValueError("provide the existing instrumented target after --")
        if args.abi_proof is None:
            raise ValueError("--abi-proof is required before any target execution")
        if args.permission_proof is None:
            raise ValueError("--permission-proof is required before any target execution")
        from table2_scheduler_permissions import validate_permission_proof, permission_policy
        metadata["permission_proof"] = validate_permission_proof(args.permission_proof)
        metadata["permission_policy"] = permission_policy()
        from table2_scheduler_preflight import validate_abi_proof
        metadata["abi_proof"] = validate_abi_proof(args.abi_proof, Path(target[0]).resolve(), directory)
        abi = runtime_abi_from_result(metadata["abi_proof"])
        import period_shared_memory
        setup_share_memory = period_shared_memory.setup_share_memory
        verify_harness_identity(metadata["abi_proof"], "driver", __file__)
        layer_hash = verify_harness_identity(metadata["abi_proof"], "abi_layer", period_shared_memory.__file__)
        metadata["abi_validation"] = "PASS"
        metadata["abi_layout"] = abi.layout
        metadata["abi_layer_sha256"] = layer_hash

        def interrupted(signum, frame):
            if supervisor.defer_signal(signum):
                return
            raise InterruptedError("comparison interrupted by signal " + str(signum))

        previous_sigterm = signal.signal(signal.SIGTERM, interrupted)
        load_official_modules(directory, args.manifest)
        sys.path.insert(0, str(directory))
        sys.argv = [str(directory / "run_PDS.py"), "-y", "-d", str(args.depth),
                    "-f", str(args.budget), "-t", str(args.target_timeout)] + target
        # Upstream rejects -f 0, whereas this adapter documents 0 as unlimited.
        if args.budget == 0:
            del sys.argv[4:6]
        metadata["upstream_argv"] = sys.argv[:]

        def launch(factory, *factory_args, retest=False):
            budget.before_start(retest)
            process = factory(*factory_args)
            budget.start(process.pid, retest)
            proxy = _Process(process, budget, retest)
            processes.append(proxy)
            return proxy

        def scheduler(n, kps, p, prefix=None):
            return make_scheduler(args.scheduler, n, kps, p, prefix, budget.note_generated)

        namespace.update({"__name__": "__main__", "__file__": str(directory / "run_PDS.py"),
                          "period_bounds": period_bounds, "logical_depth": logical_depth,
                          "NoScheduleError": NoScheduleError, "BudgetExhausted": BudgetExhausted,
                          "_comparison_budget": budget, "_comparison_scheduler": scheduler,
                          "_comparison_abi": abi, "_comparison_setup_share_memory": setup_share_memory,
                          "_comparison_launch": launch, "_comparison_timeout_cleanup": lambda p: p.cleanup()})
        supervisor.enable_subreaper()
        subprocess.Popen = supervisor
        exec(compile(adapted, str(directory / "run_PDS.py") + " [comparison]", "exec"), namespace)
        if not namespace.get("_comparison_finished"):
            raise RuntimeError("upstream driver exited before its result footer")
        metadata["status"] = "BUDGET_EXHAUSTED" if budget.budget_hit else "COMPLETED"
    except BaseException as error:
        interrupted_error = isinstance(error, InterruptedError) or isinstance(error.__cause__, InterruptedError)
        return_code = 130 if isinstance(error, KeyboardInterrupt) else 143 if interrupted_error else 2
        metadata["status"] = "INTERRUPTED" if return_code in (130, 143) else "FAILED"
        metadata["exception"] = type(error).__name__ + ": " + str(error)
        metadata["exception_traceback"] = traceback.format_exc()
        traceback.print_exc()
    finally:
        subprocess.Popen = original_popen
        for process in processes:
            if not process.finished:
                try:
                    process.cleanup()
                except BaseException as error:
                    return_code = 2
                    metadata["status"] = "FAILED"
                    metadata.setdefault("cleanup_errors", []).append({
                        "error": str(error), "traceback": traceback.format_exc()})
        try:
            supervisor.cleanup()
        except BaseException as error:
            return_code = 2
            metadata["status"] = "FAILED"
            metadata.setdefault("cleanup_errors", []).append({
                "error": str(error), "traceback": traceback.format_exc()})
        metadata["process_launches_including_preparation"] = supervisor.launches
        metadata["reaped_descendants"] = supervisor.reaped_descendants
        sys.argv, sys.path[:] = old_argv, old_path
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
        metadata["accounting"] = budget.snapshot()
        metadata["upstream_statistics"] = {key: namespace.get(key) for key in (
            "rounds", "total_errors_interleavings", "total_timeouts_interleavings", "statusL")}
        metadata["exit_code"] = return_code
        print("COMPARISON_SUMMARY " + json.dumps(metadata, sort_keys=True))
        if args.metadata:
            args.metadata.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
