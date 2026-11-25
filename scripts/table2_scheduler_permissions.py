#!/usr/bin/env python3
"""Root-compatible launch and measured permission gate for the reorder_3 pilot.

Python 3.6+. This module does not change credentials, capabilities, container
configuration, affinity, or the PERIOD runtime. Probes use disposable children.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import select
import signal
import subprocess
import sys
import time
import traceback

SCHEMA = "cs340-period-permissions-v1"
SYS_NICE = 1 << 23
SIGKILL = getattr(signal, "SIGKILL", 9)
CAP_FIELDS = ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
STATUS_FIELDS = ("Uid", "Gid") + CAP_FIELDS + ("NoNewPrivs", "Seccomp", "Seccomp_filters")
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _euid(value=None):
    return os.geteuid() if value is None else value


def privilege_command(argv, euid=None):
    """A privileged command needs no credential transition when already root."""
    command = list(argv)
    if not command:
        raise ValueError("empty privileged command")
    return command if _euid(euid) == 0 else ["sudo", "-n"] + command


def prepare_process_launch(argv, kwargs, euid=None):
    """Normalize the pinned driver's sudo argv only at the process boundary.

    Root's leading sudo environment assignments become the child's explicit
    environment. No shell is introduced. Nonroot preserves sudo's assignment
    semantics and requires noninteractive authentication.
    """
    options = dict(kwargs)
    if isinstance(argv, (str, bytes)) or not argv or argv[0] != "sudo":
        return argv, options
    if options.get("shell"):
        raise ValueError("sudo normalization requires an argv sequence without shell=True")
    command = list(argv[1:])
    if command[:1] == ["-n"]:
        command.pop(0)
    if not command or command[0].startswith("-"):
        raise ValueError("unsupported sudo options in pinned driver launch")
    if _euid(euid) != 0:
        return ["sudo", "-n"] + command, options
    assignments = {}
    while command and ENV_ASSIGNMENT.match(command[0]):
        name, value = command.pop(0).split("=", 1)
        assignments[name] = value
    if not command or command[0].startswith("-"):
        raise ValueError("sudo launch has no executable after environment assignments")
    if assignments:
        environment = dict(os.environ if options.get("env") is None else options["env"])
        environment.update(assignments)
        options["env"] = environment
    return command, options


def normalize_official_command(argv, euid=None):
    """Normalize a command without environment assignments (e.g. sudo kill)."""
    command, options = prepare_process_launch(argv, {}, euid=euid)
    if options.get("env") is not None:
        raise ValueError("use prepare_process_launch for environment-bearing commands")
    return command


def kill_process_group(pgid, signum):
    """Only use sudo for a nonroot driver unable to signal its elevated group."""
    if pgid <= 1 or pgid == os.getpgrp():
        raise RuntimeError("refusing to signal the supervisor's process group")
    try:
        os.killpg(pgid, signum)
    except ProcessLookupError:
        return False
    except PermissionError:
        if os.geteuid() == 0:
            raise
        subprocess.check_call(privilege_command(
            ["kill", "-" + str(int(signum)), "--", "-" + str(pgid)]))
    return True


def cleanup_owned_process(process, own_group=True):
    """Kill the owned group even after its leader exits; reap with a bound.

    Every supervised target must be launched in a group/session of its own,
    whose PGID equals its original PID. Never resolve PGID from an exited PID.
    """
    if own_group:
        signaled = kill_process_group(process.pid, SIGKILL)
    else:
        signaled = process.poll() is None
        if signaled:
            try:
                process.kill()
            except PermissionError:
                if os.geteuid() == 0:
                    raise
                subprocess.check_call(privilege_command(["kill", "-KILL", str(process.pid)]))
    streams = (getattr(process, "stdout", None), getattr(process, "stderr", None))
    cached = process.__dict__.get("_cs340_cleanup_output")
    closed = [stream is None or getattr(stream, "closed", False) is True for stream in streams]
    if cached is not None or all(closed):
        # CPython 3.6's POSIX communicate() tries to register closed PIPEs in
        # its selector. A completed drain must never be repeated in finally.
        process.wait(timeout=2)
        output = cached if cached is not None else (None, None)
    elif any(closed):
        # Do not re-register even one closed pipe. Drain only the remaining
        # open pipes, using the same bound as communicate()/wait().
        output = _drain_open_pipes(process, streams, closed)
    else:
        output = process.communicate(timeout=2)
    process.__dict__["_cs340_cleanup_output"] = output
    return {"group_signaled": signaled, "returncode": process.returncode,
            "output": output}


def _drain_open_pipes(process, streams, closed):
    deadline = time.monotonic() + 2
    pending = {stream: index for index, stream in enumerate(streams) if not closed[index]}
    chunks = [[], []]
    while pending:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, 2)
        ready, _, _ = select.select(list(pending), [], [], remaining)
        for stream in ready:
            chunk = os.read(stream.fileno(), 65536)
            if chunk:
                chunks[pending[stream]].append(chunk)
            else:
                del pending[stream]
                stream.close()
    process.wait(timeout=max(0.001, deadline - time.monotonic()))
    result = []
    for index, stream in enumerate(streams):
        if closed[index]:
            result.append(None)
        else:
            data = b"".join(chunks[index])
            result.append(data.decode(stream.encoding or "utf-8", stream.errors or "replace")
                          if getattr(stream, "encoding", None) else data)
    return tuple(result)


def _exception_record(error):
    return {"error": type(error).__name__ + ": " + str(error),
            "traceback": ("".join(traceback.format_exception(type(error), error, error.__traceback__))
                          if error.__traceback__ is not None else
                          "".join(traceback.format_stack()[:-1]) +
                          "".join(traceback.format_exception_only(type(error), error)))}


def _record_cleanup_error(record, error):
    record.setdefault("probe_status", record.get("status", "BLOCKED"))
    record.setdefault("cleanup_errors", []).append(_exception_record(error))
    record["status"] = "BLOCKED"


def permission_policy():
    return {"mode": "root-direct" if os.geteuid() == 0 else "nonroot-sudo-n",
            "sudo_environment": "leading assignments merged into child env only for root",
            "process_groups": "one owned group per launch; bounded group SIGKILL cleanup",
            "official_difference": "sudo credential wrapper removed only for root; scheduler/runtime unchanged"}


def identity():
    fields = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in STATUS_FIELDS:
            fields[key] = value.strip()
    return {"uid": os.getuid(), "euid": os.geteuid(), "gid": os.getgid(),
            "egid": os.getegid(), "status_fields": fields,
            "capabilities": {name: int(fields[name], 16) for name in CAP_FIELDS},
            "effective_capabilities": ["SYS_NICE"] if int(fields["CapEff"], 16) == SYS_NICE else [],
            "no_new_privileges": int(fields["NoNewPrivs"])}


def identity_errors(record):
    errors = []
    if record["uid"] != 0 or record["euid"] != 0:
        errors.append("the historical root container must have real/effective UID 0")
    for name in ("CapPrm", "CapEff", "CapBnd"):
        if record["capabilities"][name] != SYS_NICE:
            errors.append(name + " must contain exactly SYS_NICE")
    for name in ("CapInh", "CapAmb"):
        if record["capabilities"][name] & ~SYS_NICE:
            errors.append(name + " contains an unauthorized capability")
    if record["no_new_privileges"] != 1:
        errors.append("NoNewPrivs must remain 1")
    return errors


def helper_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def supervisor_hash():
    return hashlib.sha256(Path(__file__).with_name("run_scheduler_comparison.py").read_bytes()).hexdigest()


def validate_permission_proof(path):
    proof = json.loads(Path(path).read_text())
    if proof.get("schema") != SCHEMA or proof.get("status") != "PASS":
        raise RuntimeError("a passing measured permission proof is required")
    if proof.get("helper_sha256") != helper_hash():
        raise RuntimeError("permission helper changed after measured acceptance")
    if proof.get("supervisor_sha256") != supervisor_hash():
        raise RuntimeError("process supervisor changed after measured acceptance")
    current = identity()
    if identity_errors(current) or current != proof.get("identity"):
        raise RuntimeError("UID/capabilities/security state changed after permission acceptance")
    if proof.get("policy") != permission_policy():
        raise RuntimeError("launch policy changed after permission acceptance")
    for name in ("process_control", "sched_deadline"):
        record = proof.get("probes", {}).get(name, {})
        if record.get("status") != "PASS" or record.get("exit_code") != 0:
            raise RuntimeError("missing actual permission probe: " + name)
    control = proof["probes"]["process_control"]
    if not control.get("environment_preserved") or control.get("euid") != 0:
        raise RuntimeError("direct launch identity/environment was not measured")
    expected_controls = ("term", "timeout_kill", "descendant_cleanup", "exited_leader_cleanup",
                         "outer_watchdog_supervisor_cleanup")
    if any(control.get(name, {}).get("passed") is not True for name in expected_controls):
        raise RuntimeError("incomplete measured process control acceptance")
    if (control["term"].get("returncode") != -signal.SIGTERM
            or control["timeout_kill"].get("returncode") != -SIGKILL
            or not control["timeout_kill"].get("timeout_observed")
            or not control["descendant_cleanup"].get("no_remaining_processes")
            or control["outer_watchdog_supervisor_cleanup"].get("timeout_exit_code") != 124
            or not control["outer_watchdog_supervisor_cleanup"].get("cleanup_completed")
            or control["outer_watchdog_supervisor_cleanup"].get("descendant_reaped") is not True
            or control["outer_watchdog_supervisor_cleanup"].get("subreaper_restored") is not True):
        raise RuntimeError("process control readback is incomplete")
    deadline = proof["probes"]["sched_deadline"]
    if (deadline.get("euid") != 0 or deadline.get("identity") != proof["identity"]
            or deadline.get("sched_setattr", {}).get("return") != 0
            or deadline.get("sched_getattr", {}).get("return") != 0
            or deadline.get("sched_getscheduler") != 6 or not deadline.get("yield_returned")
            or deadline.get("restore", {}).get("return") != 0 or deadline.get("restored_scheduler") != 0):
        raise RuntimeError("actual SCHED_DEADLINE acceptance/readback/restore is incomplete")
    requested, readback = deadline.get("requested", {}), deadline.get("readback", {})
    keys = ("policy", "flags", "priority", "runtime", "deadline", "period")
    if requested.get("policy") != 6 or any(key not in requested or requested[key] != readback.get(key) for key in keys):
        raise RuntimeError("SCHED_DEADLINE kernel readback does not match request")
    return proof


def _popen(command, **kwargs):
    argv, options = prepare_process_launch(command, kwargs)
    return subprocess.Popen(argv, **options)


def _read_line(stream, timeout=2):
    deadline = time.monotonic() + timeout
    data = b""
    while b"\n" not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([stream], [], [], remaining)[0]:
            raise RuntimeError("permission helper readiness timed out")
        chunk = os.read(stream.fileno(), 1)
        if not chunk:
            raise RuntimeError("permission helper exited before readiness")
        data += chunk
        if len(data) > 4096:
            raise RuntimeError("permission helper readiness exceeds bound")
    return data.decode("utf-8").strip()


def _waitpid(pid, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        reaped, status = os.waitpid(pid, os.WNOHANG)
        if reaped:
            return reaped, status
        time.sleep(0.01)
    raise RuntimeError("permission helper descendant reaping timed out")


def _process_control_child():
    """Real TERM, timed-out group KILL, and adopted-descendant reaping."""
    libc = ctypes.CDLL(None, use_errno=True)
    previous = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(previous), 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_GET_CHILD_SUBREAPER failed")
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_CHILD_SUBREAPER failed")
    record = {"status": "BLOCKED", "euid": os.geteuid(),
              "environment_preserved": os.environ.get("CS340_PERMISSION_PROBE") == "1"}
    processes = []
    extra_groups = []
    def interrupted(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        graceful = _popen(["sudo", sys.executable, "-u", "-c",
                           "import time; print('ready', flush=True); time.sleep(30)"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, start_new_session=True)
        processes.append(graceful)
        if _read_line(graceful.stdout) != "ready":
            raise RuntimeError("TERM helper failed to become ready")
        os.killpg(graceful.pid, signal.SIGTERM)
        graceful.communicate(timeout=2)
        record["term"] = {"pid": graceful.pid, "returncode": graceful.returncode,
                          "passed": graceful.returncode == -signal.SIGTERM}
        program = ("import os,signal,time,json; "
                   "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                   "child=os.fork(); "
                   "print(json.dumps({'leader':os.getpid(),'descendant':child}),flush=True) if child else None; "
                   "time.sleep(30)")
        forced = _popen(["sudo", sys.executable, "-u", "-c", program],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        universal_newlines=True, start_new_session=True)
        processes.append(forced)
        pids = json.loads(_read_line(forced.stdout))
        os.killpg(forced.pid, signal.SIGTERM)
        timed_out = False
        try:
            forced.communicate(timeout=0.15)
        except subprocess.TimeoutExpired:
            timed_out = True
        cleanup = cleanup_owned_process(forced)
        descendant, descendant_status = _waitpid(pids["descendant"])
        gone = all(not Path("/proc/" + str(pid)).exists() for pid in (forced.pid, descendant))
        record["timeout_kill"] = {"pid": forced.pid, "timeout_observed": timed_out,
                                  "returncode": forced.returncode,
                                  "group_signaled": cleanup["group_signaled"],
                                  "passed": timed_out and forced.returncode == -SIGKILL}
        record["descendant_cleanup"] = {"pid": descendant, "wait_status": descendant_status,
                                        "signal": os.WTERMSIG(descendant_status) if os.WIFSIGNALED(descendant_status) else None,
                                        "no_remaining_processes": gone,
                                        "passed": gone and os.WIFSIGNALED(descendant_status)
                                        and os.WTERMSIG(descendant_status) == SIGKILL}
        # A group can outlive its leader: exercise that cleanup path separately.
        exited_program = ("import os,signal,time,json; child=os.fork(); "
                          "(signal.signal(signal.SIGTERM,signal.SIG_IGN),time.sleep(30)) if child==0 "
                          "else print(json.dumps({'descendant':child}),flush=True)")
        exited = _popen(["sudo", sys.executable, "-u", "-c", exited_program],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        universal_newlines=True, start_new_session=True)
        processes.append(exited)
        orphan = json.loads(_read_line(exited.stdout))["descendant"]
        exited.wait(timeout=2)
        cleanup_owned_process(exited)
        adopted, adopted_status = _waitpid(orphan)
        record["exited_leader_cleanup"] = {
            "leader_returncode": exited.returncode, "descendant": adopted,
            "passed": exited.returncode == 0 and os.WIFSIGNALED(adopted_status)
            and os.WTERMSIG(adopted_status) == SIGKILL
            and not Path("/proc/" + str(adopted)).exists()}
        watchdog = _popen(["sudo", "timeout", "--signal=TERM", "--kill-after=2s", "0.7s",
                           sys.executable, str(Path(__file__).resolve()), "--child", "supervised_controller"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, start_new_session=True)
        processes.append(watchdog)
        launch_event = json.loads(_read_line(watchdog.stdout))
        extra_groups.append(launch_event["leader"])
        watchdog_stdout, watchdog_stderr = watchdog.communicate(timeout=5)
        observed = json.loads(watchdog_stdout)
        observed.update({"timeout_exit_code": watchdog.returncode, "stderr": watchdog_stderr,
                         "passed": watchdog.returncode == 124 and observed["cleanup_completed"]
                         and observed["signal"] == signal.SIGTERM
                         and observed["leader_returncode"] == -SIGKILL
                         and observed.get("descendant_reaped") is True
                         and observed.get("subreaper_restored") is True
                         and not Path("/proc/" + str(observed["descendant"])).exists()})
        record["outer_watchdog_supervisor_cleanup"] = observed
        passed = record["environment_preserved"] and all(record[key]["passed"] for key in (
            "term", "timeout_kill", "descendant_cleanup", "exited_leader_cleanup",
            "outer_watchdog_supervisor_cleanup"))
        record["status"] = "PASS" if passed else "BLOCKED"
        return record
    except BaseException as error:
        record.update(_exception_record(error))
        record["status"] = "BLOCKED"
        return record
    finally:
        cleanup_errors = []
        for process in processes:
            try:
                cleanup_owned_process(process)
            except BaseException as error:
                cleanup_errors.append(_exception_record(error))
        for group in extra_groups:
            try:
                kill_process_group(group, SIGKILL)
            except BaseException as error:
                cleanup_errors.append(_exception_record(error))
        # Reap any descendants in a failed probe as well; all are owned helpers.
        reap_deadline = time.monotonic() + 2
        while True:
            try:
                if os.waitpid(-1, os.WNOHANG)[0] == 0:
                    if time.monotonic() >= reap_deadline:
                        cleanup_errors.append(_exception_record(RuntimeError(
                            "owned probe descendants did not exit within cleanup bound")))
                        break
                    time.sleep(0.01)
            except ChildProcessError:
                break
            except BaseException as error:
                cleanup_errors.append(_exception_record(error))
                break
        try:
            if libc.prctl(36, previous.value, 0, 0, 0) != 0:
                cleanup_errors.append(_exception_record(OSError(
                    ctypes.get_errno(), "probe subreaper restoration failed")))
        except BaseException as error:
            cleanup_errors.append(_exception_record(error))
        if cleanup_errors:
            record.setdefault("probe_status", record.get("status", "BLOCKED"))
            record.setdefault("cleanup_errors", []).extend(cleanup_errors)
            record["status"] = "BLOCKED"


def _supervised_controller_child():
    # Exercise the very same class used by A1/B/C, including the outer watchdog
    # sending TERM to a controller whose targets own separate process groups.
    from run_scheduler_comparison import ProcessSupervisor
    supervisor = ProcessSupervisor(subprocess.Popen)
    supervisor.enable_subreaper()
    record = {"signal": None, "cleanup_completed": False, "subreaper_before": supervisor.subreaper_before}
    process = None
    def interrupted(signum, frame):
        if supervisor.defer_signal(signum):
            return
        record["signal"] = signum
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        program = ("import os,signal,time,json; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                   "child=os.fork(); print(json.dumps({'descendant':child}),flush=True) if child else None; "
                   "time.sleep(30)")
        process = supervisor(["sudo", "CS340_PERMISSION_PROBE=1", sys.executable, "-u", "-c", program],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        record.update(json.loads(_read_line(process.stdout)))
        record["leader"] = process.pid
        print(json.dumps({"event": "launched", "leader": process.pid,
                          "descendant": record["descendant"]}), flush=True)
        process.communicate(timeout=20)
    except KeyboardInterrupt:
        pass
    except BaseException as error:
        record.update(_exception_record(error))
    finally:
        try:
            supervisor.cleanup()
            record["cleanup_completed"] = True
        except BaseException as error:
            _record_cleanup_error(record, error)
        record["leader_returncode"] = process.returncode if process is not None else None
        record["reaped_descendants"] = supervisor.reaped_descendants
        record["descendant_reaped"] = (
            any(item["pid"] == record.get("descendant") and os.WIFSIGNALED(item["wait_status"])
                and os.WTERMSIG(item["wait_status"]) == SIGKILL for item in supervisor.reaped_descendants)
            and not Path("/proc/" + str(record.get("descendant"))).exists())
        try:
            restored = ctypes.c_int()
            libc = ctypes.CDLL(None, use_errno=True)
            record["subreaper_restored"] = (
                libc.prctl(37, ctypes.byref(restored), 0, 0, 0) == 0
                and restored.value == record["subreaper_before"])
        except BaseException as error:
            _record_cleanup_error(record, error)
    record["status"] = ("PASS" if record["signal"] == signal.SIGTERM
                        and record["cleanup_completed"] and not record.get("error")
                        and not record.get("cleanup_errors") else "BLOCKED")
    return record


class _Attr(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("policy", ctypes.c_uint32),
                ("flags", ctypes.c_uint64), ("nice", ctypes.c_int32),
                ("priority", ctypes.c_uint32), ("runtime", ctypes.c_uint64),
                ("deadline", ctypes.c_uint64), ("period", ctypes.c_uint64)]


def _attrs(attr):
    return {name: int(getattr(attr, name)) for name, _ in attr._fields_}


def _deadline_child():
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    requested = _Attr(ctypes.sizeof(_Attr), 6, 0, 0, 0, 10000000, 20000000, 20000000)
    record = {"euid": os.geteuid(), "requested": _attrs(requested),
              "affinity": sorted(os.sched_getaffinity(0)), "identity": identity()}
    def invoke(number, *args):
        ctypes.set_errno(0)
        value = int(libc.syscall(ctypes.c_long(number), *args))
        error = ctypes.get_errno() if value < 0 else 0
        return {"return": value, "errno": error, "error": os.strerror(error) if error else None}
    original = _Attr()
    record["before"] = invoke(315, ctypes.c_int(0), ctypes.byref(original),
                              ctypes.c_uint(ctypes.sizeof(original)), ctypes.c_uint(0))
    record["original"] = _attrs(original)
    if record["before"]["return"] != 0 or original.policy != 0:
        record["status"] = "BLOCKED"
        return record
    record["sched_setattr"] = invoke(314, ctypes.c_int(0), ctypes.byref(requested), ctypes.c_uint(0))
    passed = False
    if record["sched_setattr"]["return"] == 0:
        try:
            readback = _Attr()
            record["sched_getattr"] = invoke(315, ctypes.c_int(0), ctypes.byref(readback),
                                              ctypes.c_uint(ctypes.sizeof(readback)), ctypes.c_uint(0))
            record["readback"] = _attrs(readback)
            record["sched_getscheduler"] = os.sched_getscheduler(0)
            passed = (record["sched_getattr"]["return"] == 0 and record["sched_getscheduler"] == 6
                      and all(getattr(readback, key) == getattr(requested, key)
                              for key in ("policy", "flags", "priority", "runtime", "deadline", "period")))
            os.sched_yield()
            record["yield_returned"] = True
        except BaseException as error:
            record.update(_exception_record(error))
            passed = False
        finally:
            try:
                original.size = ctypes.sizeof(_Attr)
                record["restore"] = invoke(314, ctypes.c_int(0), ctypes.byref(original), ctypes.c_uint(0))
                record["restored_scheduler"] = os.sched_getscheduler(0)
                passed = passed and record["restore"]["return"] == 0 and record["restored_scheduler"] == 0
            except BaseException as error:
                _record_cleanup_error(record, error)
                passed = False
    record["status"] = "PASS" if passed else "BLOCKED"
    return record


def _text_output(value):
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else (value or "")


def _save_probe_record(directory, name, record):
    if directory is None:
        return
    directory = Path(directory)
    for suffix, content in (("stdout.log", record.get("stdout", "")),
                            ("stderr.log", record.get("stderr", "")),
                            ("result.json", json.dumps(record, indent=2, sort_keys=True) + "\n")):
        with (directory / ("permission-" + name + "." + suffix)).open("x", encoding="utf-8") as stream:
            stream.write(content)


def _run_probe(name, evidence_dir=None):
    command = ["sudo", "CS340_PERMISSION_PROBE=1", sys.executable,
               str(Path(__file__).resolve()), "--child", name]
    process = None
    record = {"status": "BLOCKED"}
    try:
        process = _popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         universal_newlines=True, start_new_session=True)
        stdout, stderr = process.communicate(timeout=10)
        # Store the actual child outcome before any finally cleanup. Keep it
        # separately even when failed cleanup makes overall acceptance BLOCKED.
        record.update({"stdout": stdout, "stderr": stderr,
                       "exit_code": process.returncode, "child_exit_code": process.returncode})
        try:
            child_result = json.loads(stdout)
            if not isinstance(child_result, dict):
                raise ValueError("permission child result is not a JSON object")
            record.update(child_result)
            # A child JSON cannot override observed transport data.
            record.update({"stdout": stdout, "stderr": stderr,
                           "exit_code": process.returncode, "child_exit_code": process.returncode})
        except ValueError as error:
            record.update(_exception_record(error))
            record["status"] = "BLOCKED"
        if process.returncode != 0:
            record["status"] = "BLOCKED"
    except subprocess.TimeoutExpired as error:
        record.update(_exception_record(error))
        record.update({"status": "BLOCKED", "exit_code": 124,
                       "stdout": _text_output(error.output),
                       "stderr": _text_output(getattr(error, "stderr", None))})
        # TERM enters the helper's finally before any KILL fallback. Its targets
        # have separate groups, so killing only the probe PID group is inadequate.
        try:
            kill_process_group(process.pid, signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=2)
            record.update({"stdout": stdout, "stderr": stderr, "child_exit_code": process.returncode})
        except BaseException as cleanup_error:
            _record_cleanup_error(record, cleanup_error)
    except BaseException as error:
        record.update(_exception_record(error))
        record.update({"status": "BLOCKED", "exit_code": 2})
    finally:
        if process is not None:
            try:
                cleanup = cleanup_owned_process(process)
                record.setdefault("child_exit_code", process.returncode)
                if not record.get("stdout") and cleanup["output"][0] is not None:
                    record["stdout"] = _text_output(cleanup["output"][0])
                if not record.get("stderr") and cleanup["output"][1] is not None:
                    record["stderr"] = _text_output(cleanup["output"][1])
            except BaseException as error:
                _record_cleanup_error(record, error)
        try:
            _save_probe_record(evidence_dir, name, record)
        except BaseException as error:
            _record_cleanup_error(record, error)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate-proof", type=Path)
    parser.add_argument("--child", choices=("process_control", "sched_deadline", "supervised_controller"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    result = {"schema": SCHEMA, "status": "BLOCKED"}
    try:
        if sys.platform != "linux" or platform.machine().lower() not in ("x86_64", "amd64"):
            raise RuntimeError("permission acceptance requires the historical Linux x86_64 container")
        if args.validate_proof:
            result = validate_permission_proof(args.validate_proof)
        elif args.child:
            handlers = {"process_control": _process_control_child, "sched_deadline": _deadline_child,
                        "supervised_controller": _supervised_controller_child}
            result = handlers[args.child]()
        else:
            result.update({"identity": identity(), "helper_sha256": helper_hash(),
                           "supervisor_sha256": supervisor_hash(), "policy": permission_policy(),
                           "started_at_epoch": time.time(), "probes": {}})
            result["errors"] = identity_errors(result["identity"])
            # Measure both capabilities regardless of static identity gate outcome.
            for name in ("process_control", "sched_deadline"):
                try:
                    result["probes"][name] = _run_probe(name, args.output.parent if args.output else None)
                except BaseException as error:
                    result["probes"][name] = dict(_exception_record(error), status="BLOCKED", exit_code=2)
            if not result["errors"] and all(item["status"] == "PASS" for item in result["probes"].values()):
                result["status"] = "PASS"
    except BaseException as error:
        result.update(_exception_record(error))
        result.update({"schema": SCHEMA, "status": "BLOCKED"})
    _emit_tracebacks(result)
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
    print(serialized, end="")
    return 0 if result.get("status") == "PASS" else 2


def _emit_tracebacks(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "traceback" and isinstance(item, str) and item:
                print(item, file=sys.stderr, end="" if item.endswith("\n") else "\n")
            elif isinstance(item, (dict, list)):
                _emit_tracebacks(item)
    elif isinstance(value, list):
        for item in value:
            _emit_tracebacks(item)


if __name__ == "__main__":
    raise SystemExit(main())
