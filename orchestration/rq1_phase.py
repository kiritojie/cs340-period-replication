"""Outer sequencing bridge to the unchanged, session-frozen RQ1 entry point.

Only orchestration changes: native permission, ABI, process and scheduling
implementations remain the exact prepared files. Unknown failures stop globally.
Python 3.6+.
"""
import datetime
import json
from pathlib import Path
import sys
import tempfile
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
_previous_path = list(sys.path)
sys.path.insert(0, str(ROOT / "scripts"))
try:
    import table2_rq1 as host
finally:
    sys.path[:] = _previous_path

from rq1_integrity import digest, seal_tree, verify_tree


GUARD_PROBE = r'''
import json,pathlib,subprocess,sys
root=pathlib.Path(sys.argv[1]); proof=pathlib.Path(sys.argv[2])
sys.path.insert(0,str(root/'scripts'))
import table2_rq1_native as native
from table2_scheduler_preflight import verify_benchmark_manifest
protocol=json.loads((root/'protocol.json').read_text())
native.validate_protocol(protocol)
state=json.loads((root/'state.json').read_text())
native.require(state.get('protocol_sha256')==native.digest(root/'protocol.json'),'native checkpoint protocol differs')
head=subprocess.check_output(['git','-C',str(native.UPSTREAM),'rev-parse','HEAD']).decode().strip()
native.require(head==protocol['source_commit'],'upstream HEAD changed')
result={'environment':native.environment(protocol),'live':native.live_gate(protocol,proof),'state':state,'source_commit':head,'manifests':{}}
for name,item in sorted(state.get('benchmarks',{}).items()):
 if 'manifest' in item:
  result['manifests'][name]=verify_benchmark_manifest(item['manifest'],native.UPSTREAM)
print(json.dumps(result,sort_keys=True))
'''


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def global_guard(repo, session_root, commands, label):
    """Recheck frozen identities and actual native permissions without a target."""
    repo, session_root = Path(repo).resolve(), Path(session_root).resolve()
    session = read_json(session_root / "session.json")
    protocol = read_json(session_root / "protocol.json")
    host.verify_frozen_pilot(repo)
    name, prefix = host.CONTAINERS[0]
    unused, raw, unused2 = commands.run(label + "-inspect", ["podman", "inspect", name])
    record = host.one_inspect(raw.decode("utf-8"))
    cid = host.validate_container(record, name, prefix)
    host.validate_security_configuration(record)
    host.validate_session(session, record, repo, session_root)
    native = session["container_root"]
    unused, raw, unused2 = commands.run(label + "-harness", [
        "podman", "exec", cid, "python3", "-B", "-c", host.HASH_PROBE, native])
    host.require(json.loads(raw.decode("utf-8")) == session["harness_hashes"],
                 "staged harness changed")
    unused, raw, unused2 = commands.run(label + "-inputs", [
        "podman", "exec", cid, "python3", "-B", "-c", host.INPUT_HASH_PROBE, native])
    host.require(json.loads(raw.decode("utf-8")) == session["input_hashes"],
                 "staged protocol or frozen pilot changed")
    unused, raw, unused2 = commands.run(label + "-live", [
        "podman", "exec", cid, "python3", "-B", "-c", host.LIVE_PROBE])
    live = json.loads(raw.decode("utf-8"))
    host.validate_live(live)
    host.require(live["cpus"] == protocol["expected_cpus"], "actual affinity differs from frozen protocol")
    permission_dir = native + "/outer-guard-" + uuid.uuid4().hex
    proof_path = permission_dir + "/permission-proof.json"
    # The unchanged helper writes fixed-name child sidecars in proof.parent.
    # Give every invocation an exclusive directory, then export all raw files.
    commands.run(label + "-fresh-proof-directory", ["podman", "exec", cid, "python3", "-B", "-c",
        "import pathlib,sys; pathlib.Path(sys.argv[1]).mkdir()", permission_dir])
    try:
        permission_info, unused, unused2 = commands.run(label + "-real-permissions", [
            "podman", "exec", "--env", "PYTHONDONTWRITEBYTECODE=1", cid, "python3", "-B",
            native + "/scripts/table2_scheduler_permissions.py", "--output", proof_path], timeout=60, required=False)
    finally:
        export_info, unused, unused2 = commands.run(label + "-export-permissions", [
            "podman", "cp", cid + ":" + permission_dir,
            str(commands.output / (label + "-permission-evidence"))], required=False)
    host.require(permission_info["exit_code"] == 0, label + " fresh real permission acceptance failed")
    host.require(export_info["exit_code"] == 0, label + " raw permission evidence export failed")
    unused, raw, unused2 = commands.run(label + "-native-guard", [
        "podman", "exec", "--env", "PYTHONDONTWRITEBYTECODE=1", cid,
        "python3", "-B", "-c", GUARD_PROBE, native, proof_path], timeout=120)
    measured = json.loads(raw.decode("utf-8"))
    measured.update(container_id=cid, container_root=native,
                    runtime_identity=host.runtime_identity(record),
                    launch_configuration=host.launch_configuration(record))
    return measured


def classify_native(result, native_dir):
    """Allow only positively identified per-program failures to continue."""
    native_dir = Path(native_dir)
    if result.get("phase_excluded") is True:
        return "global"
    if result.get("status") in ("FORMAL_BENCHMARK_PASSED", "ADAPTATION_PASSED", "BUILD_PASSED"):
        return "none"
    if result.get("status") != "BLOCKED":
        return "global"
    if result.get("phase") == "build":
        return "benchmark" if (result.get("failure_scope") == "benchmark" and
            result.get("build_failure_kind") in ("COMPILER_FAILURE", "BENCHMARK_ABI_FAILURE")) else "global"
    analyses = [read_json(path) for path in sorted(native_dir.rglob("analysis.json"))]
    invalid = [item for item in analyses if item.get("included") is not True]
    if any(item.get("termination_state") not in ("TARGET_TIMEOUT", "ROUND_TIMEOUT")
           for item in invalid):
        return "global"
    error = result.get("error", "")
    if (invalid and (error.startswith("ValueError: invalid formal round retained;")
                     or error.startswith("ValueError: adaptation failed:"))):
        return "benchmark"
    regression = native_dir / "A1B-regression.json"
    if error == "ValueError: A1/B adaptation regression differs" and not invalid and regression.is_file():
        comparison = read_json(regression)
        local_fields = ("threads", "kps", "matrix_shape", "schedules", "actual_yield_patterns",
                        "error_ordinals", "total_schedules", "error_interleavings", "timeouts")
        if (comparison.get("status") == "BLOCKED"
                and comparison.get("reference", {}).get("included") is True
                and comparison.get("candidate", {}).get("included") is True
                and comparison.get("reason") in tuple("A1/B mismatch in " + field for field in local_fields)):
            return "benchmark"
    return "global"


def run_phase(repo, session_root, phase, benchmark=None):
    """Run one existing native phase and retain raw evidence on every outcome."""
    repo, session_root = Path(repo).resolve(), Path(session_root).resolve()
    host.require(phase in ("reorder3", "build", "adapt", "formal"), "unsupported batch phase")
    host.require((phase == "reorder3" and benchmark is None)
                 or (phase in ("build", "adapt", "formal") and benchmark in host.BENCHMARKS[1:]),
                 "inconsistent phase/benchmark")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = Path(tempfile.mkdtemp(prefix="batch-" + phase + "-" + stamp + "-", dir=str(session_root)))
    commands = host.Commands(output)
    receipt = {"schema": "cs340-period-rq1-host-phase-v1", "phase": phase,
               "benchmark": benchmark, "status": "BLOCKED", "failure_scope": "global",
               "phase_excluded": False, "evidence": str(output), "state": {},
               "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "orchestrator": "external batch bridge; unchanged frozen native phase"}
    invoked, native_output, cid = False, None, None
    measured, exported_state = None, None
    try:
        verify_tree(session_root)
        before = global_guard(repo, session_root, commands, "before")
        receipt["state"] = before["state"]
        native, cid = before["container_root"], before["container_id"]
        protocol = read_json(session_root / "protocol.json")
        native_output = native + "/evidence/" + output.name
        entry = native + "/scripts/table2_rq1_native.py"
        if phase == "build":
            worker = repo / "orchestration/rq1_build.py"
            entry = native + "/" + output.name + "-build.py"
            commands.run("unused-build-worker-path", ["podman", "exec", cid, "python3", "-B", "-c",
                "import os,sys; assert not os.path.lexists(sys.argv[1])", entry])
            commands.run("copy-official-build-worker", ["podman", "cp", str(worker), cid + ":" + entry])
            unused, raw, unused2 = commands.run("verify-build-worker", ["podman", "exec", cid, "python3", "-B", "-c",
                "import hashlib,pathlib,sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())", entry])
            host.require(raw.decode().strip() == digest(worker), "staged build worker changed")
            (output / "build-worker.py").write_bytes(worker.read_bytes())
        argv = ["podman", "exec", "--env", "PYTHONDONTWRITEBYTECODE=1", cid,
                "python3", "-B", entry, "--root", native, "--output", native_output]
        if phase != "build":
            argv += ["--phase", phase]
        if benchmark:
            argv += ["--benchmark", benchmark]
        invoked = True
        info, unused, unused2 = commands.run("native-phase", argv,
            timeout=3000 if phase == "build" else host.phase_timeout(phase, protocol), required=False)
        receipt["native_exit_code"] = info["exit_code"]
        host.require(info["exit_code"] in (0, 2),
                     "native process failed or watchdog expired; no automatic retry")
    except BaseException as error:
        receipt.update(reason=type(error).__name__ + ": " + str(error), traceback=traceback.format_exc())
    finally:
        if invoked:
            try:
                commands.run("export-native-evidence", [
                    "podman", "cp", cid + ":" + native_output, str(output / "native-evidence")], timeout=1800)
                verify_tree(output / "native-evidence")
                measured = read_json(output / "native-evidence/phase-result.json")
                receipt["native_result"] = measured
                exported_state = read_json(output / "native-evidence/state-after.json")
                receipt["state"] = exported_state
                receipt["phase_excluded"] = measured.get("phase_excluded", False)
                if "reason" not in receipt:
                    host.require(measured.get("phase") == phase and measured.get("benchmark") == benchmark,
                                 "native receipt identifies a different phase or benchmark")
                    host.require((receipt["native_exit_code"] == 0) == (measured.get("status") != "BLOCKED"),
                                 "native status and exit code disagree")
                    if receipt["native_exit_code"] == 0:
                        expected = ("BUILD_PASSED" if phase == "build" else
                                    "ADAPTATION_PASSED" if phase == "adapt" else "FORMAL_BENCHMARK_PASSED")
                        host.require(measured.get("status") == expected, "unexpected native phase completion status")
                    receipt["failure_scope"] = classify_native(measured, output / "native-evidence")
                    receipt["status"] = measured["status"]
                    if receipt["failure_scope"] != "none":
                        receipt["reason"] = measured.get("error", "unclassified native phase failure")
            except BaseException as error:
                receipt.update(status="BLOCKED", failure_scope="global", phase_excluded=True,
                    export_error=type(error).__name__ + ": " + str(error), export_traceback=traceback.format_exc())
                receipt.setdefault("reason", receipt["export_error"])
            try:
                after = global_guard(repo, session_root, commands, "after")
                if "before" in locals():
                    host.require(after["runtime_identity"] == before["runtime_identity"]
                                 and after["launch_configuration"] == before["launch_configuration"],
                                 "container runtime or configuration changed during phase")
                if exported_state is not None:
                    host.require(after["state"] == exported_state,
                                 "native checkpoint changed after exported phase evidence")
                receipt["state"] = after["state"]
            except BaseException as error:
                receipt.update(status="BLOCKED", failure_scope="global", phase_excluded=True,
                    post_guard_error=type(error).__name__ + ": " + str(error),
                    post_guard_traceback=traceback.format_exc())
                receipt.setdefault("reason", receipt["post_guard_error"])
        # A native exit 2 can retain earlier individually accepted rounds.
        # Exclude the whole phase only when its final native gate says so or
        # a host post-gate cannot establish that the environment stayed valid.
        if invoked and receipt.get("native_exit_code") not in (0, 2):
            receipt["phase_excluded"] = True
        receipt.setdefault("reason", "")
        receipt["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        host.write_json(output / "stage-result.json", receipt)
        seal_tree(output)
    return receipt
