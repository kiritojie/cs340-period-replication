#!/usr/bin/env python3
"""Explicit, staged RQ1 preparation and runs in the existing rootful container.

Preparation inspects artifacts/ABI and permissions, never launches a benchmark.
All target execution is delegated to the existing verified drivers.
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
    Commands, CONTAINERS, launch_configuration, one_inspect, require,
    validate_container, validate_security_configuration,
)
from table2_permission_stage import HASH_PROBE, harness_hashes, runtime_identity, validate_live

SCHEMA = "cs340-period-rq1-session-v1"
BENCHMARKS = ("reorder_3_bad", "reorder_4_bad", "reorder_5_bad", "reorder_10_bad")
FREEZE = "docs/frozen/table2-rq1-reorder3-pilot-20261124/FREEZE.json"
LIVE_PROBE = r'''
import json,os,pathlib
active=[]
targets={'reorder_3_bad','reorder_4_bad','reorder_5_bad','reorder_10_bad'}
drivers={'run_PDS.py','run_abi_parallel_reference.py','run_scheduler_comparison.py','trace_period_driver.py','table2_scheduler_permissions.py','table2_rq1_native.py'}
for p in pathlib.Path('/proc').iterdir():
 if not p.name.isdigit() or int(p.name)==os.getpid(): continue
 try:
  argv=[a.decode('utf-8','replace') for a in (p/'cmdline').read_bytes().split(bytes([0])) if a]
  if argv and (pathlib.Path(argv[0]).name in targets or pathlib.Path(argv[0]).name.startswith('python') and any(pathlib.Path(a).name in drivers for a in argv[1:4])): active.append({'pid':int(p.name),'argv':argv})
 except (FileNotFoundError,ProcessLookupError): pass
print(json.dumps({'uid':os.getuid(),'euid':os.geteuid(),'status':pathlib.Path('/proc/self/status').read_text(),'cpus':sorted(os.sched_getaffinity(0)),'active':active,'ipc':pathlib.Path('/proc/sysvipc/shm').read_text()}))
'''
INPUT_HASH_PROBE = """import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]); print(json.dumps({name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ('protocol.json','frozen-pilot.json','pilot-cache.json')}))
"""


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


def checksums(root):
    root = Path(root)
    entries = [digest(path) + "  " + str(path.relative_to(root)).replace("\\", "/")
               for path in sorted(root.rglob("*")) if path.is_file() and path != root / "SHA256SUMS"]
    with (root / "SHA256SUMS").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(entries) + "\n")


def verify_frozen_pilot(repo):
    repo = Path(repo).resolve()
    frozen = json.loads((repo / FREEZE).read_text())
    require(frozen.get("schema") == "cs340-period-rq1-frozen-pilot-v1", "unsupported pilot freeze")
    for name, expected in frozen["protected_modules"].items():
        require(digest(repo / "scripts" / name) == expected, "verified core module changed: " + name)
    for relative, expected in frozen["immutable_evidence_manifests"].items():
        manifest = (repo / relative).resolve()
        require(repo in manifest.parents and digest(manifest) == expected, "frozen pilot manifest changed")
        for line in manifest.read_text().splitlines():
            checksum, name = line.split("  ", 1)
            path = (manifest.parent / name).resolve()
            require(manifest.parent in path.parents and path.is_file() and digest(path) == checksum,
                    "frozen pilot evidence changed: " + name)
    pilot = repo / frozen["pilot"]
    folders = list((pilot / "native-evidence").glob("table2-scheduler-pilot-*"))
    require(len(folders) == 1, "frozen native pilot is ambiguous")
    native = folders[0]
    require(json.loads((native / "A1B-regression.json").read_text()).get("status") == "PASS"
            and json.loads((native / "C-validation.json").read_text()).get("status") == "PASS", "frozen pilot failed")
    proof = json.loads((native / "abi-proof.json").read_text())
    require(proof.get("status") == "PASS" and proof.get("source_commit") == frozen["source_commit"], "frozen ABI proof invalid")
    checks = {item["name"]: item for item in proof["checks"]}
    artifacts = {key: checks[key + "_identity"]["evidence"]["sha256"]
                 for key in ("binary", "config", "runtime_object", "runtime_source")}
    text = (native / "A1-abi-corrected-parallel/stdout.log").read_text()
    def one(pattern):
        found = re.findall(pattern, text, re.M)
        require(len(found) == 1, "verified pilot runtime profile is ambiguous")
        return found[0]
    profile = {"schema": "cs340-period-rq1-runtime-profile-v1", "benchmark": "reorder_3_bad",
               "threads": int(one(r"^ThreadNum:\s*(\d+)\s*$")),
               "matrix_width": int(one(r"^MaxKpNum:\s*(\d+)\s*$")),
               "kps": [int(value) for value in one(r"^kpNumArray:\s*([0-9 ]+)\s*$").split()],
               "binary_sha256": artifacts["binary"], "config_sha256": artifacts["config"]}
    return frozen, {"schema": "cs340-period-rq1-pilot-cache-v1", "status": "PASS", "pilot": frozen["pilot"],
                    "source_commit": frozen["source_commit"], "artifacts": artifacts,
                    "runtime_profile": profile, "core_hashes": frozen["protected_modules"]}


def validate_session(session, record, repo, root):
    require(not (root / "HALTED.json").exists(), "an earlier failed phase halted this cohort; inspect evidence before a new session")
    require(session.get("schema") == SCHEMA and session.get("status") in ("PREPARED", "PREPARED_WITH_BLOCKED_BENCHMARKS"),
            "need an accepted prepare session")
    require(session["container_id"] == record.get("Id", record.get("ID")), "container identity changed")
    require(session["runtime_identity"] == runtime_identity(record), "container restarted; create a separate session")
    require(session["launch_configuration"] == launch_configuration(record), "container configuration changed")
    require(session["harness_hashes"] == harness_hashes(repo), "harness changed; frozen cohort cannot continue")
    require(digest(root / "protocol.json") == session["protocol_sha256"], "session protocol changed")
    require(re.match(r"^/tmp/cs340-rq1-[0-9a-f]{32}$", session.get("container_root", "")), "unsafe recorded native path")


def phase_timeout(phase, protocol):
    runs = 0 if phase == "prepare" else 3 if phase == "adapt" else 2 * protocol["minimum_rounds"]
    return 600 + runs * (protocol["round_timeout_seconds"] + protocol["kill_after_seconds"] + 120)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "reorder3", "adapt", "formal"))
    parser.add_argument("--protocol", type=Path, default=Path("config/table2-rq1-protocol.json"))
    parser.add_argument("--session", type=Path)
    parser.add_argument("--benchmark", choices=BENCHMARKS)
    args = parser.parse_args(argv)
    if sys.platform != "linux" or platform.machine() != "x86_64" or os.geteuid() != 0:
        parser.error("run in the Ubuntu x86_64 root terminal")
    if (args.phase == "prepare") == bool(args.session):
        parser.error("--session is required only after prepare")
    if (args.phase in ("adapt", "formal")) != bool(args.benchmark):
        parser.error("--benchmark is required only for adapt/formal")
    if args.benchmark == "reorder_3_bad":
        parser.error("use reorder3 phase for the verified three-thread cohort")
    repo = Path(__file__).resolve().parents[1]
    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    if args.phase == "prepare":
        session_root = Path(tempfile.mkdtemp(prefix="table2-rq1-session-" + stamp + "-", dir=str(repo / "docs/results")))
        output = session_root / "prepare"
        output.mkdir()
        session = {"schema": SCHEMA, "status": "BLOCKED"}
    else:
        session_root = args.session.resolve()
        session = json.loads((session_root / "session.json").read_text())
        output = Path(tempfile.mkdtemp(prefix=args.phase + "-" + stamp + "-", dir=str(session_root)))
    commands = Commands(output)
    result = {"schema": "cs340-period-rq1-host-phase-v1", "phase": args.phase, "benchmark": args.benchmark,
              "status": "BLOCKED", "phase_excluded": False, "started_at": datetime.datetime.utcnow().isoformat() + "Z"}
    cid, native, exported, invoked = None, None, False, False
    print("Session: " + str(session_root), flush=True)
    print("Evidence: " + str(output), flush=True)
    try:
        require(shutil.which("podman"), "rootful Podman unavailable")
        frozen, cache = verify_frozen_pilot(repo)
        name, prefix = CONTAINERS[0]
        unused, raw, unused2 = commands.run("inspect-existing-container", ["podman", "inspect", name])
        record = one_inspect(raw.decode())
        cid = validate_container(record, name, prefix)
        runtime = runtime_identity(record)
        validate_security_configuration(record)
        if args.phase == "prepare":
            protocol_path = args.protocol.resolve()
            protocol = json.loads(protocol_path.read_text())
            require(protocol.get("schema") == "cs340-period-rq1-protocol-v1" and protocol.get("source_commit") == frozen["source_commit"],
                    "unsupported/unpinned protocol")
            shutil.copyfile(str(protocol_path), str(session_root / "protocol.json"))
            native = "/tmp/cs340-rq1-" + uuid.uuid4().hex
            stage = output / "harness"
            stage.mkdir()
            for directory in ("scripts", "tests"):
                shutil.copytree(str(repo / directory), str(stage / directory), ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            shutil.copyfile(str(protocol_path), str(stage / "protocol.json"))
            shutil.copyfile(str(repo / FREEZE), str(stage / "frozen-pilot.json"))
            write_json(stage / "pilot-cache.json", cache)
            session.update(container_id=cid, runtime_identity=runtime, launch_configuration=launch_configuration(record),
                           harness_hashes=harness_hashes(repo), protocol_sha256=digest(protocol_path), container_root=native,
                           input_hashes={path.name: digest(path) for path in (stage / "protocol.json", stage / "frozen-pilot.json", stage / "pilot-cache.json")})
            commands.run("unused-native-directory", ["podman", "exec", cid, "python3", "-c",
                "import os,sys; assert not os.path.lexists(sys.argv[1])", native])
            commands.run("copy-frozen-harness", ["podman", "cp", str(stage), cid + ":" + native])
            exported = True
        else:
            validate_session(session, record, repo, session_root)
            native = session["container_root"]
            protocol = json.loads((session_root / "protocol.json").read_text())
            exported = True
        unused, raw, unused2 = commands.run("current-harness-hashes", ["podman", "exec", cid, "python3", "-c", HASH_PROBE, native])
        require(json.loads(raw.decode()) == session["harness_hashes"], "staged harness changed")
        unused, raw, unused2 = commands.run("current-input-hashes", ["podman", "exec", cid, "python3", "-c", INPUT_HASH_PROBE, native])
        require(json.loads(raw.decode()) == session["input_hashes"], "staged protocol or freeze changed")
        unused, raw, unused2 = commands.run("live-before", ["podman", "exec", cid, "python3", "-c", LIVE_PROBE])
        live = json.loads(raw.decode())
        validate_live(live)
        require(live["cpus"] == protocol["expected_cpus"], "actual affinity differs from frozen 0-31")
        native_output = native + "/evidence/" + ("prepare" if args.phase == "prepare" else output.name)
        command = ["podman", "exec", "--env", "PYTHONDONTWRITEBYTECODE=1", cid, "python3", "-B",
                   native + "/scripts/table2_rq1_native.py", "--root", native, "--output", native_output, "--phase", args.phase]
        if args.benchmark:
            command += ["--benchmark", args.benchmark]
        invoked = True
        info, unused, unused2 = commands.run("native-phase", command, timeout=phase_timeout(args.phase, protocol), required=False)
        require(info["exit_code"] == 0, "native phase stopped; preserve and inspect raw evidence, no automatic retry")
        unused, raw, unused2 = commands.run("live-after", ["podman", "exec", cid, "python3", "-c", LIVE_PROBE])
        validate_live(json.loads(raw.decode()), live)
        unused, raw, unused2 = commands.run("inspect-after", ["podman", "inspect", cid])
        after = one_inspect(raw.decode())
        require(runtime_identity(after) == runtime and launch_configuration(after) == launch_configuration(record),
                "container runtime/configuration changed during phase")
        result["status"] = "VERIFY_NATIVE_RESULTS"
    except BaseException as error:
        result.update(status="BLOCKED", error=type(error).__name__ + ": " + str(error), traceback=traceback.format_exc())
        result["phase_excluded"] = invoked and "info" in locals() and info.get("exit_code") in (None, 0)
        print(result["traceback"], file=sys.stderr)
    finally:
        if exported and invoked:
            try:
                commands.run("export-phase-only", ["podman", "cp", cid + ":" + native_output, str(output / "native-evidence")])
                measured = json.loads((output / "native-evidence/phase-result.json").read_text())
                result["native_result"] = measured
                result["phase_excluded"] = result["phase_excluded"] or measured.get("phase_excluded", False)
                if result["status"] == "VERIFY_NATIVE_RESULTS":
                    result["status"] = measured["status"]
            except BaseException as error:
                result.update(status="BLOCKED", phase_excluded=True, export_error=str(error), export_traceback=traceback.format_exc())
        if args.phase == "prepare":
            session["status"] = result["status"]
            write_json(session_root / "session.json", session)
        result["finished_at"] = datetime.datetime.utcnow().isoformat() + "Z"
        write_json(output / "stage-result.json", result)
        if result["status"] == "BLOCKED" and not (session_root / "HALTED.json").exists():
            write_json(session_root / "HALTED.json", {"phase": args.phase, "evidence": str(output),
                       "reason": result.get("error", result.get("export_error", "native failure")),
                       "policy": "No silent retry, replacement or continuation after a failed phase."})
        checksums(output)
        print("Final status: " + result["status"] + "\nSession: " + str(session_root) + "\nEvidence: " + str(output), flush=True)
    return 0 if result["status"] != "BLOCKED" else 2


if __name__ == "__main__":
    sys.exit(main())
