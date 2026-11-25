"""Recover an already completed native phase into a new accepted host view.

The failed export, HALTED marker and excluded old receipt remain untouched.
No target, benchmark build, native checkpoint or scientific record is changed.
Python 3.6+.
"""
import datetime
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
_previous = list(sys.path)
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from table2_rq1_report import collect_rounds
    from table2_scheduler_evidence import analyze_formal
finally:
    sys.path[:] = _previous

from rq1_integrity import digest, seal_tree, verify_tree
from rq1_phase import global_guard, host


REMOTE_INVENTORY = r'''
import importlib.util,json,pathlib,sys
root=pathlib.Path(sys.argv[1])
spec=importlib.util.spec_from_file_location('recovery_integrity',sys.argv[2])
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
verified=module.verify_tree(root)
files=[p for p in root.rglob('*') if p.is_file()]
print(json.dumps({'verification':verified,'manifest_sha256':module.digest(root/'SHA256SUMS'),
 'file_count':len(files),'bytes':sum(p.stat().st_size for p in files),
 'phase_result':json.loads((root/'phase-result.json').read_text()),
 'state_after':json.loads((root/'state-after.json').read_text())},sort_keys=True))
'''


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


def recorded_path(repo, value):
    value = str(value).replace("\\", "/")
    marker = "/docs/results/"
    relative = "docs/results/" + value.split(marker, 1)[1] if marker in value else value
    path = (Path(repo) / relative).resolve()
    require(Path(repo).resolve() in path.parents, "recorded evidence leaves this repository")
    return path


def checked_diagnostic(stage, filename):
    """Check a selected immutable outer record without accepting partial raw data."""
    entries = {}
    for line in (stage / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([0-9a-f]{64})  (.+)$", line)
        require(match is not None, "malformed old outer checksum manifest")
        expected, name = match.groups()
        name = name.replace("\\", "/")
        require(name not in entries, "duplicate old outer checksum entry")
        entries[name] = expected
    require(filename in entries and digest(stage / filename) == entries[filename],
            "historical diagnostic was changed: " + filename)
    return entries[filename]


def _historical_identity(before, after):
    for key in ("cpu_model", "kernel", "container_userland", "python"):
        require(before["environment"][key] == after["environment"][key],
                "historical environment really changed: " + key)
    for key in ("identity", "affinity"):
        require(before["live"][key] == after["live"][key], "historical live identity changed: " + key)
    require(not before["live"]["active"] and not after["live"]["active"], "historical active target remained")
    require(before["source_commit"] == after["source_commit"] and before["manifests"] == after["manifests"],
            "historical source or product identity changed")


def inspect_failure(repo, failed_batch):
    """Read the exact failed copy and the actually successful post-run guards."""
    repo, batch = Path(repo).resolve(), Path(failed_batch).resolve()
    verify_tree(batch)
    result = read_json(batch / "batch-result.json")
    require(result.get("status") == "BLOCKED_GLOBAL", "recovery needs the recorded failed batch")
    session = recorded_path(repo, result["session"])
    record = read_json(session / "session.json")
    phases = [item for item in result["execution"]["phases"] if item.get("phase") == "formal"
              and item.get("benchmark") == "reorder_5_bad" and item.get("native_exit_code") == 0
              and item.get("export_error")]
    require(len(phases) == 1, "need one export-only failed reorder_5 phase")
    stage = recorded_path(repo, phases[0]["evidence"])
    require(stage.parent == session, "failed phase is outside its source session")
    protected = {}
    for name in ("stage-result.json", "09-native-phase.command.json", "09-native-phase.stdout.log",
                 "09-native-phase.stderr.log", "10-export-native-evidence.command.json",
                 "10-export-native-evidence.stdout.log", "10-export-native-evidence.stderr.log",
                 "08-before-native-guard.stdout.log", "18-after-native-guard.stdout.log",
                 "native-evidence/SHA256SUMS"):
        protected[name] = checked_diagnostic(stage, name)
    for metadata in sorted(stage.glob("*.command.json")):
        if metadata.name != "10-export-native-evidence.command.json":
            checked_diagnostic(stage, metadata.name)
            require(read_json(metadata).get("exit_code") == 0, "a historical guard/phase actually failed: " + metadata.name)
    receipt = read_json(stage / "stage-result.json")
    require(receipt.get("reason", "").startswith("ValueError: export-native-evidence failed;") and
            receipt.get("post_guard_error") in (None, "ValueError: native checkpoint changed after exported phase evidence"),
            "the historical stop contains an unrelated global failure")
    command = read_json(stage / "10-export-native-evidence.command.json")
    argv = command.get("argv", [])
    require(len(argv) == 4 and argv[:2] == ["podman", "cp"] and command.get("exit_code") is None
            and command.get("exception", "").startswith("command timed out"),
            "the first export failure was not the known transfer timeout")
    require(not (stage / "10-export-native-evidence.stderr.log").read_bytes(), "copy reported an additional engine error")
    cid, separator, source = argv[2].partition(":")
    native_root = record["container_root"]
    require(separator and cid == record["container_id"] and
            re.match(r"^/tmp/cs340-rq1-[0-9a-f]{32}$", native_root), "copy container/native identity is inconsistent")
    require(source == native_root + "/evidence/" + stage.name, "copy source is not the exact recorded native phase")
    require(PurePosixPath(argv[-1]).name == "native-evidence", "old export destination is inconsistent")
    native_command = read_json(stage / "09-native-phase.command.json")
    require(native_command.get("exit_code") == 0 and
            native_command["argv"][native_command["argv"].index("--output") + 1] == source,
            "successful native invocation did not produce this exact source directory")
    require("FORMAL_BENCHMARK_PASSED" in (stage / "09-native-phase.stdout.log").read_text(),
            "original native stdout does not accept the completed six rounds")
    before = read_json(stage / "08-before-native-guard.stdout.log")
    after = read_json(stage / "18-after-native-guard.stdout.log")
    _historical_identity(before, after)
    require(receipt["state"] == before["state"], "export failure did not retain the expected stale pre-run state")
    require(after["state"]["benchmarks"]["reorder_5_bad"].get("formal_complete") is True,
            "original healthy postguard did not observe completed reorder_5 rounds")
    for stem in ("06-before-real-permissions", "16-after-real-permissions"):
        name = stem + ".stdout.log"
        protected[name] = checked_diagnostic(stage, name)
        require(read_json(stage / name).get("status") == "PASS", "original real permissions did not pass")
    inspections = [host.one_inspect((stage / name).read_text()) for name in (
        "01-before-inspect.stdout.log", "11-after-inspect.stdout.log")]
    for name in ("01-before-inspect.stdout.log", "11-after-inspect.stdout.log"):
        protected[name] = checked_diagnostic(stage, name)
    require(host.runtime_identity(inspections[0]) == host.runtime_identity(inspections[1]) and
            host.launch_configuration(inspections[0]) == host.launch_configuration(inspections[1]),
            "historical container runtime/configuration changed")
    require(host.runtime_identity(inspections[0]) == record["runtime_identity"] and
            host.launch_configuration(inspections[0]) == record["launch_configuration"],
            "historical container differs from the frozen session baseline")
    return {"source_session": str(session), "failed_stage": str(stage), "failed_batch": str(batch),
            "container_id": cid, "native_root": native_root, "native_source": source,
            "original_native_manifest_sha256": protected["native-evidence/SHA256SUMS"],
            "historical_after_state": after["state"], "source_diagnostic_sha256": protected,
            "export_timeout_seconds": command.get("wall_seconds"),
            "root_cause": "native completed; podman cp hit the outer default 60-second transfer timeout"}


def _native_stage(native_root, recorded):
    prefix = native_root + "/evidence/"
    require(recorded.startswith(prefix), "measured proof is outside the recorded native root")
    parts = PurePosixPath(recorded[len(prefix):]).parts
    require(parts and all(part not in (".", "..", "") for part in parts), "unsafe measured proof path")
    return parts[0]


def _copy_accepted(repo, session, view, frozen, state):
    stages = {recorded_path(repo, value) for value in frozen["selected_phases"]}
    item = state["benchmarks"]["reorder_5_bad"]
    names = {_native_stage(state["root"], item["manifest"])}
    adaptation = item.get("adaptation", {})
    require(adaptation.get("status") == "PASS" and set(adaptation.get("runs", {})) == {"reference", "parallel", "serial"},
            "reorder_5 adaptation was not already accepted")
    adaptation_names = {_native_stage(state["root"], value) for value in adaptation["runs"].values()}
    require(len(adaptation_names) == 1, "adaptation evidence spans inconsistent phases")
    names.update(adaptation_names)
    stages.update(session / name for name in names)
    copied = []
    for stage in sorted(stages):
        require(stage.parent == session, "only verified healthy source phases may enter the recovery view")
        verify_tree(stage)
        if stage.name != "prepare":
            receipt = read_json(stage / "stage-result.json")
            require(receipt.get("phase_excluded") is False and receipt.get("status") in (
                "FORMAL_BENCHMARK_PASSED", "ADAPTATION_PASSED", "BUILD_PASSED"),
                "a copied source phase was not accepted: " + stage.name)
        print("Preserve accepted source phase: " + stage.name, flush=True)
        target = view / stage.name
        shutil.copytree(str(stage), str(target))
        verify_tree(target)
        require(digest(stage / "SHA256SUMS") == digest(target / "SHA256SUMS"), "accepted source copy changed")
        copied.append({"source": stage.relative_to(repo).as_posix(), "view": target.relative_to(repo).as_posix(),
                       "manifest_sha256": digest(target / "SHA256SUMS")})
    return copied


def _inventory(commands, cid, source, helper, label):
    unused, raw, unused2 = commands.run(label, ["podman", "exec", "--env", "PYTHONDONTWRITEBYTECODE=1",
        cid, "python3", "-B", "-c", REMOTE_INVENTORY, source, helper], timeout=180)
    value = json.loads(raw.decode("utf-8"))
    result = value["phase_result"]
    require(result.get("status") == "FORMAL_BENCHMARK_PASSED" and result.get("phase") == "formal"
            and result.get("benchmark") == "reorder_5_bad" and result.get("phase_excluded") is False,
            "native source is not a complete accepted reorder_5 phase")
    require(value["state_after"]["benchmarks"]["reorder_5_bad"].get("formal_complete") is True,
            "native source checkpoint did not complete reorder_5")
    return value


def _round_guards(run, protocol):
    """The unchanged native entry writes environment-after per round, not per phase."""
    environments = [read_json(run / name) for name in ("environment.json", "environment-after.json")]
    for key in ("cpu_model", "kernel", "container_userland", "python"):
        require(environments[0][key] == environments[1][key] == protocol["environment_baseline"][key],
                "original round environment differs from its frozen baseline: " + key)
    lives = [read_json(run / name) for name in ("live-before.json", "live-after.json")]
    require(lives[0]["identity"] == lives[1]["identity"], "original round security identity changed")
    for live in lives:
        require(not live["active"] and live["affinity"]["status"] == "PASS"
                and live["affinity"]["actual_cpus"] == protocol["expected_cpus"],
                "original round live/affinity check did not pass")


def reanalyze_recovered(view, native, state):
    """Audit raw records unchanged; no relabeling or synthesized observations."""
    item = state["benchmarks"]["reorder_5_bad"]
    manifest_stage = _native_stage(state["root"], item["manifest"])
    manifest = read_json(view / manifest_stage / "native-evidence/benchmark-manifest.json")
    expected = {(mode, number) for mode in ("parallel", "serial") for number in (1, 2, 3)}
    protocol = read_json(view / "protocol.json")
    observed = set()
    records = []
    for context_path in sorted(native.rglob("run-context.json")):
        run = context_path.parent
        context = read_json(context_path)
        key = (context.get("mode"), context.get("round"))
        require(context.get("benchmark") == "reorder_5_bad" and context.get("phase") == "formal"
                and context.get("purpose") == "formal" and context.get("role") == "unified"
                and key in expected and key not in observed, "recovered formal round identities are missing or duplicated")
        observed.add(key)
        for filename in ("stdout.log", "stderr.log", "actual-yield.jsonl", "adapter-metadata.json", "SHA256SUMS"):
            require((run / filename).is_file(), "recovered required raw file is absent: " + str(run / filename))
        _round_guards(run, protocol)
        analyzed = analyze_formal(run, context["mode"], manifest, view / "protocol.json", item["runtime_profile"])
        saved = read_json(run / "analysis.json")
        require(analyzed.get("included") is True and analyzed.get("validation") == "PASS",
                "recovered raw acceptance failed: " + str(analyzed.get("exclusion_reasons")))
        for name in ("status", "validation", "included", "termination_state", "first_error", "total_schedules",
                     "error_interleavings", "timeouts", "exit_code", "internal_seconds", "external_seconds",
                     "kps", "matrix_shape", "schedules", "error_ordinals", "actual_yield_patterns",
                     "actual_saved_error_yields", "accounting", "binary_sha256", "config_sha256", "abi_layout", "abi_layer_sha256"):
            require(json.loads(json.dumps(analyzed.get(name))) == json.loads(json.dumps(saved.get(name))),
                    "recovered analysis differs from the original result: " + run.name + ":" + name)
        records.append({"benchmark": "reorder_5_bad", "mode": key[0], "round": key[1],
                        "first_error": saved["first_error"], "total_schedules": saved["total_schedules"],
                        "error_interleavings": saved["error_interleavings"], "exit_code": saved["exit_code"],
                        "source_analysis_sha256": digest(run / "analysis.json")})
    require(observed == expected and len(records) == 6, "recovered source did not contain all six original formal rounds")
    for filename in ("live-before.json", "live-after.json"):
        live = read_json(native / filename)
        require(not live["active"] and live["affinity"]["status"] == "PASS", "native phase left an invalid live state")
    require(read_json(native / "live-before.json")["identity"] == read_json(native / "live-after.json")["identity"],
            "native phase security identity changed")
    phase_environment = read_json(native / "environment.json")
    for key in ("cpu_model", "kernel", "container_userland", "python"):
        require(phase_environment[key] == protocol["environment_baseline"][key], "native phase environment differs from frozen baseline")
    require(read_json(native / "permission-proof.json").get("status") == "PASS", "native actual permissions did not pass")
    return records


def recover_export(repo, failed_batch, frozen_record):
    """Export, fully validate and select original data; never retry an experiment."""
    from rq1_completed_freeze import verify_completed_freeze
    repo = Path(repo).resolve()
    frozen = verify_completed_freeze(repo, repo / frozen_record["freeze_path"])
    require(frozen == frozen_record and frozen.get("formal_rounds") == 12, "the original twelve-round freeze differs")
    diagnosis = inspect_failure(repo, failed_batch)
    source_session = Path(diagnosis["source_session"])
    require(source_session == recorded_path(repo, frozen["session"]), "the export failure identifies another frozen cohort")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    view = Path(tempfile.mkdtemp(prefix="table2-rq1-recovered-session-" + stamp + "-", dir=str(repo / "docs/results")))
    control = view / "recovery-control"
    control.mkdir()
    print("Recovery view: " + str(view), flush=True)
    for name in ("session.json", "protocol.json"):
        shutil.copyfile(str(source_session / name), str(view / name))
    write_json(control / "source-diagnosis.json", diagnosis)
    commands = host.Commands(control)
    stage = None
    try:
        before = global_guard(repo, view, commands, "recovery-before")
        require(before["container_id"] == diagnosis["container_id"] and before["container_root"] == diagnosis["native_root"],
                "current recovery container differs from the original successful native phase")
        require(before["state"] == diagnosis["historical_after_state"], "native checkpoint changed since the original healthy postguard")
        copied = _copy_accepted(repo, source_session, view, frozen, before["state"])
        helper = diagnosis["native_root"] + "/recovery-integrity-" + uuid.uuid4().hex + ".py"
        commands.run("unused-recovery-helper", ["podman", "exec", diagnosis["container_id"], "python3", "-B", "-c",
            "import os,sys; assert not os.path.lexists(sys.argv[1])", helper])
        helper_source = repo / "orchestration/rq1_integrity.py"
        commands.run("stage-recovery-integrity", ["podman", "cp", str(helper_source), diagnosis["container_id"] + ":" + helper])
        unused, raw, unused2 = commands.run("verify-recovery-integrity-helper", ["podman", "exec", diagnosis["container_id"],
            "python3", "-B", "-c", "import hashlib,pathlib,sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())", helper])
        require(raw.decode().strip() == digest(helper_source), "staged recovery integrity verifier differs")
        inventory = _inventory(commands, diagnosis["container_id"], diagnosis["native_source"], helper, "native-source-inventory-before")
        require(inventory["manifest_sha256"] == diagnosis["original_native_manifest_sha256"],
                "native evidence manifest differs from the original interrupted export")
        require(inventory["state_after"] == diagnosis["historical_after_state"] == before["state"],
                "native completed phase and original/current checkpoints disagree")
        stage = Path(tempfile.mkdtemp(prefix="recovered-formal5-" + stamp + "-", dir=str(view)))
        destination = stage / "native-evidence"
        require(not destination.exists(), "recovery export requires an independent empty destination")
        # This is transport time, independent of the frozen experimental limit.
        commands.run("recover-original-native-evidence", ["podman", "cp",
            diagnosis["container_id"] + ":" + diagnosis["native_source"], str(destination)], timeout=1800)
        verification = verify_tree(destination)
        require(digest(destination / "SHA256SUMS") == inventory["manifest_sha256"], "re-exported source manifest changed")
        recovered_state = read_json(destination / "state-after.json")
        require(recovered_state == inventory["state_after"], "recovered checkpoint differs from the native source")
        require(read_json(destination / "phase-result.json") == inventory["phase_result"], "recovered native receipt differs")
        records = reanalyze_recovered(view, destination, recovered_state)
        source_after = _inventory(commands, diagnosis["container_id"], diagnosis["native_source"], helper, "native-source-inventory-after")
        require(source_after == inventory, "original native evidence changed during its re-export")
        after = global_guard(repo, view, commands, "recovery-after")
        require(after["state"] == recovered_state and after["runtime_identity"] == before["runtime_identity"]
                and after["launch_configuration"] == before["launch_configuration"],
                "current recovery environment/checkpoint changed")
        receipt = {"schema": "cs340-period-rq1-host-phase-v1", "phase": "formal", "benchmark": "reorder_5_bad",
                   "status": "FORMAL_BENCHMARK_PASSED", "failure_scope": "none", "phase_excluded": False,
                   "native_exit_code": 0, "native_result": inventory["phase_result"], "state": recovered_state,
                   "evidence": str(stage), "reason": "validated re-export of the same completed original phase; no experiment execution",
                   "recovery": {"source": diagnosis["native_source"], "failed_original_stage": diagnosis["failed_stage"],
                                "native_manifest_sha256": inventory["manifest_sha256"],
                                "historical_diagnostic_sha256": diagnosis["source_diagnostic_sha256"],
                                "raw_verification": verification, "records": records,
                                "selection": "Only the failed transport receipt is superseded in this new view; original raw data is unchanged."}}
        write_json(stage / "stage-result.json", receipt)
        seal_tree(stage)
        verify_tree(stage)
        provenance = {"schema": "cs340-period-rq1-export-recovery-v1", "status": "RECOVERED_SIX_ORIGINAL_FORMAL_ROUNDS",
                      "source_session": source_session.relative_to(repo).as_posix(), "source_batch": diagnosis["failed_batch"],
                      "old_halted_marker_sha256": digest(source_session / "HALTED.json"),
                      "freeze_path": frozen["freeze_path"], "frozen_formal_rounds": 12, "recovered_formal_rounds": 6,
                      "copied_accepted_phases": copied, "recovered_stage": stage.relative_to(repo).as_posix(),
                      "native_source": diagnosis["native_source"], "native_source_manifest_sha256": inventory["manifest_sha256"],
                      "session_metadata_sha256": digest(view / "session.json"), "protocol_sha256": digest(view / "protocol.json"),
                      "old_failed_phase_included_in_view": False, "new_target_or_build_executions": 0}
        write_json(view / "recovery-provenance.json", provenance)
        rows = collect_rounds(view, digest(view / "protocol.json"), 10000)
        require(len(rows) == 18 and all(row["included"] for row in rows),
                "recovery view must select exactly eighteen accepted original rounds without duplicates")
        require(sum(row["benchmark"] == "reorder_5_bad" for row in rows) == 6, "the recovered six are missing from the selected view")
        write_json(control / "recovery-result.json", {"status": "PASS", "view_session": str(view), "formal_rounds": 18,
                                                      "native_source": diagnosis["native_source"], "provenance": provenance})
        seal_tree(control)
        verify_tree(view)
        print("Recovered and accepted original data: 18 / 24 valid formal rounds; no target or build execution.", flush=True)
        return {"view_session": str(view), "recovered_rounds": 6, "valid_formal_rounds": 18, "provenance": provenance}
    except BaseException as error:
        details = {"status": "BLOCKED_RECOVERY", "error": type(error).__name__ + ": " + str(error),
                   "traceback": traceback.format_exc(), "view_session": str(view), "source_session_unchanged": str(source_session)}
        write_json(control / "recovery-exception.json", details)
        if not (control / "recovery-result.json").exists():
            write_json(control / "recovery-result.json", details)
        if stage is not None and not (stage / "SHA256SUMS").exists():
            write_json(stage / "recovery-failed.json", details)
            seal_tree(stage)
        if not (control / "SHA256SUMS").exists():
            seal_tree(control)
        write_json(view / "HALTED.json", details)
        print("Recovery stopped; evidence preserved: " + str(view), flush=True)
        raise
