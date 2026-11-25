#!/usr/bin/env python3
"""Two explicit stages in the existing container: permissions, then reorder_3.

Never starts/creates a container or repeats historical extraction. Python 3.6+.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import tempfile
import traceback
import uuid

from resume_table2_podman import (
    Commands, CONTAINERS, launch_configuration, one_inspect, read_native_results,
    native_pilot_passed, require, validate_container, validate_security_configuration,
)

SCHEMA = "cs340-period-permission-stage-v1"
LIVE_PROBE = r'''
import json,os,pathlib
status=pathlib.Path('/proc/self/status').read_text()
active=[]
names={'run_PDS.py','run_abi_parallel_reference.py','run_scheduler_comparison.py','trace_period_driver.py','table2_scheduler_permissions.py'}
for process in pathlib.Path('/proc').iterdir():
    if not process.name.isdigit() or int(process.name)==os.getpid(): continue
    try:
        argv=[a.decode('utf-8','replace') for a in (process/'cmdline').read_bytes().split(bytes([0])) if a]
        if argv and (pathlib.Path(argv[0]).name=='reorder_3_bad' or (pathlib.Path(argv[0]).name.startswith('python') and any(pathlib.Path(a).name in names for a in argv[1:4]))): active.append({'pid':int(process.name),'argv':argv})
    except (FileNotFoundError,ProcessLookupError): pass
ipc=pathlib.Path('/proc/sysvipc/shm').read_text()
print(json.dumps({'uid':os.getuid(),'euid':os.geteuid(),'status':status,'cpus':sorted(os.sched_getaffinity(0)),'active':active,'ipc':ipc}))
'''
HASH_PROBE = """import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]); result={}
for directory in ('scripts','tests'):
 for path in sorted((root/directory).rglob('*')):
  if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc': result[str(path.relative_to(root))]=hashlib.sha256(path.read_bytes()).hexdigest()
print(json.dumps(result))
"""


def harness_hashes(repo):
    result = {}
    for directory in ("scripts", "tests"):
        for path in sorted((Path(repo) / directory).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                result[str(path.relative_to(repo)).replace("\\", "/")] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def runtime_identity(record):
    state = record.get("State", {})
    require(state.get("Running") is True and state.get("Status") == "running",
            "selected historical container must already be running; no automatic start")
    require(type(state.get("Pid")) is int and state["Pid"] > 0 and state.get("StartedAt"),
            "running container PID/start-time identity unavailable")
    return {"pid": state["Pid"], "started_at": state["StartedAt"]}


def validate_live(live, previous=None):
    require(live.get("uid") == 0 and live.get("euid") == 0, "container must execute as root")
    require(live.get("cpus") and not live.get("active"), "empty affinity or active PERIOD process")
    if previous is not None:
        require(live["cpus"] == previous["cpus"], "affinity changed since permission acceptance")
    rows = live["ipc"].splitlines()
    require(rows, "SysV IPC state unavailable")
    for row in rows[1:]:
        fields = dict(zip(rows[0].split(), row.split()))
        if int(fields["key"]) == 1111:
            require(int(fields["nattch"]) == 0 and int(fields["size"]) == 24008,
                    "IPC1111 attached or incompatible; no IPC removal is performed")


def validate_session(session, record, repo):
    require(session.get("schema") == SCHEMA and session.get("status") == "PERMISSIONS_PASSED",
            "pilot requires this entry's passing permissions session")
    require(session["container_id"] == record.get("Id", record.get("ID")), "container changed")
    require(session["runtime_identity"] == runtime_identity(record), "container restarted; rerun permissions")
    require(session["launch_configuration"] == launch_configuration(record), "container configuration changed")
    require(session["harness_hashes"] == harness_hashes(repo), "harness changed; rerun permissions")
    require(re.match(r"^/tmp/cs340-permission-stage-[0-9a-f]{32}$", session.get("container_root", "")),
            "unexpected recorded container work directory")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--permissions-only", action="store_true", help="default; no benchmark")
    mode.add_argument("--pilot", action="store_true", help="explicitly run A1/B then C after a passing session")
    parser.add_argument("--session", type=Path, help="session directory printed by permissions stage")
    args = parser.parse_args(argv)
    if sys.platform != "linux" or platform.machine() != "x86_64" or os.geteuid() != 0:
        parser.error("run from the Ubuntu x86_64 root terminal")
    if bool(args.session) != args.pilot:
        parser.error("--session is required only with --pilot")
    repo = Path(__file__).resolve().parents[1]
    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    if args.pilot:
        session_root = args.session.resolve()
        require(session_root.is_dir(), "session directory missing")
        session = json.loads((session_root / "stage-session.json").read_text())
        output = Path(tempfile.mkdtemp(prefix="pilot-" + stamp + "-", dir=str(session_root)))
    else:
        output = Path(tempfile.mkdtemp(prefix="table2-permission-stage-" + stamp + "-", dir=str(repo / "docs/results")))
        session_root, session = output, {"schema": SCHEMA}
    commands = Commands(output)
    result = {"schema": SCHEMA, "stage": "pilot" if args.pilot else "permissions", "status": "BLOCKED",
              "started_at": datetime.datetime.utcnow().isoformat() + "Z"}
    cid, native, export_root, copied = None, None, None, False
    print("Session: " + str(session_root), flush=True)
    print("Evidence: " + str(output), flush=True)
    try:
        require(shutil.which("podman"), "rootful Podman unavailable")
        name, prefix = CONTAINERS[0]
        unused, raw, unused2 = commands.run("inspect-existing-container", ["podman", "inspect", name])
        record = one_inspect(raw.decode("utf-8"))
        cid = validate_container(record, name, prefix)
        runtime = runtime_identity(record)
        validate_security_configuration(record)
        if args.pilot:
            validate_session(session, record, repo)
        unused, raw, unused2 = commands.run("live-environment", ["podman", "exec", cid, "python3", "-c", LIVE_PROBE])
        live = json.loads(raw.decode("utf-8"))
        validate_live(live, session.get("live") if args.pilot else None)
        result["live"] = live
        if not args.pilot:
            native = "/tmp/cs340-permission-stage-" + uuid.uuid4().hex
            check = "import os,sys; p=sys.argv[1]; assert not os.path.lexists(p),p"
            commands.run("unused-work-directory", ["podman", "exec", cid, "python3", "-c", check, native])
            stage = output / "harness"
            stage.mkdir()
            for directory in ("scripts", "tests"):
                shutil.copytree(str(repo / directory), str(stage / directory), ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            commands.run("copy-current-harness", ["podman", "cp", str(stage), cid + ":" + native])
            copied = True
            export_root = native + "/evidence"
            commands.run("create-new-evidence", ["podman", "exec", cid, "mkdir", native + "/evidence"])
            unused, raw, unused2 = commands.run("verify-copied-harness", ["podman", "exec", cid, "python3", "-c", HASH_PROBE, native])
            require(json.loads(raw.decode("utf-8")) == harness_hashes(repo), "copied harness differs from current files")
            commands.run("linux-cleanup-regressions", ["podman", "exec", "--env", "PYTHONDONTWRITEBYTECODE=1", cid,
                "python3", "-B", "-m", "unittest", "discover", "-s", native + "/tests", "-p", "test_table2_cleanup.py", "-v"], timeout=120)
            info, unused, unused2 = commands.run("real-permission-acceptance", ["podman", "exec", "--env", "PYTHONDONTWRITEBYTECODE=1", cid,
                "python3", native + "/scripts/table2_scheduler_permissions.py", "--output", native + "/evidence/permission-proof.json"], timeout=60, required=False)
            require(info["exit_code"] == 0, "real permission acceptance failed; raw evidence will be exported")
            commands.run("validate-measured-permissions", ["podman", "exec", cid, "python3", native + "/scripts/table2_scheduler_permissions.py",
                "--validate-proof", native + "/evidence/permission-proof.json"])
            result["status"] = "PERMISSIONS_PASSED"
            session.update(result, container_id=cid, runtime_identity=runtime, launch_configuration=launch_configuration(record),
                           harness_hashes=harness_hashes(repo), container_root=native)
        else:
            native = session["container_root"]
            copied = True
            export_root = native + "/" + output.name
            unused, raw, unused2 = commands.run("recheck-container-harness", ["podman", "exec", cid, "python3", "-c", HASH_PROBE, native])
            require(json.loads(raw.decode("utf-8")) == session["harness_hashes"], "container harness changed; rerun permissions")
            proof = native + "/evidence/permission-proof.json"
            commands.run("validate-current-permissions", ["podman", "exec", cid, "python3", native + "/scripts/table2_scheduler_permissions.py", "--validate-proof", proof])
            commands.run("linux-bash-syntax", ["podman", "exec", cid, "/bin/bash", "-n", native + "/scripts/table2_scheduler_pilot.sh"])
            info, unused, unused2 = commands.run("gated-reorder3-pilot", ["podman", "exec", "--env", "PYTHONDONTWRITEBYTECODE=1", cid, "/bin/bash",
                native + "/scripts/table2_scheduler_pilot.sh", "--execute", "--upstream", "/workdir/PERIOD", "--expected-cpus",
                ",".join(str(cpu) for cpu in live["cpus"]), "--output-root", export_root, "--permission-proof", proof], timeout=2400, required=False)
            require(info["exit_code"] == 0, "gated pilot failed; see fresh native evidence")
            result["status"] = "VERIFY_NATIVE_RESULTS"
        unused, raw, unused2 = commands.run("live-environment-after", ["podman", "exec", cid, "python3", "-c", LIVE_PROBE])
        validate_live(json.loads(raw.decode("utf-8")), live)
        unused, raw, unused2 = commands.run("inspect-container-after", ["podman", "inspect", cid])
        after = one_inspect(raw.decode("utf-8"))
        require(runtime_identity(after) == runtime and launch_configuration(after) == launch_configuration(record),
                "container runtime/configuration changed during stage")
    except BaseException as error:
        result.update(status="BLOCKED", error=type(error).__name__ + ": " + str(error), traceback=traceback.format_exc())
        print(result["traceback"], file=sys.stderr)
    finally:
        if copied:
            try:
                commands.run("export-native-evidence", ["podman", "cp", cid + ":" + export_root, str(output / "native-evidence")])
                if args.pilot and result["status"] == "VERIFY_NATIVE_RESULTS":
                    observed = read_native_results(output)
                    result["native_results"] = observed
                    result["status"] = "PILOT_PASSED" if native_pilot_passed(observed) else "BLOCKED"
            except BaseException as error:
                result.update(status="BLOCKED", export_error=str(error), export_traceback=traceback.format_exc())
        if not args.pilot:
            result["finished_at"] = datetime.datetime.utcnow().isoformat() + "Z"
            session.update(result)
            with (output / "stage-session.json").open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(session, indent=2) + "\n")
        result["finished_at"] = datetime.datetime.utcnow().isoformat() + "Z"
        with (output / "stage-result.json").open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, indent=2) + "\n")
        entries = [hashlib.sha256(path.read_bytes()).hexdigest() + "  " + str(path.relative_to(output)).replace("\\", "/")
                   for path in sorted(output.rglob("*")) if path.is_file() and path != output / "SHA256SUMS"]
        with (output / "SHA256SUMS").open("x", encoding="utf-8") as stream:
            stream.write("\n".join(entries) + "\n")
        print("Final status: " + result["status"] + "\nSession: " + str(session_root) + "\nEvidence: " + str(output), flush=True)
    return 0 if result["status"] in ("PERMISSIONS_PASSED", "PILOT_PASSED") else 2


if __name__ == "__main__":
    sys.exit(main())
