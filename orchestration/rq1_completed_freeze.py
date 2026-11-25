"""Freeze the twelve accepted reorder_3/4 rounds with scoped raw verification.

An unrelated, incomplete reorder_5 export remains preserved and unaccepted.
Only the original passed phases and their measured input proofs are frozen.
Python 3.6+; no container, build or target execution is performed here.
"""
import csv
import datetime
import json
from pathlib import Path, PurePosixPath
import sys

ROOT = Path(__file__).resolve().parents[1]
_previous = list(sys.path)
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from table2_rq1_report import collect_rounds, summarize, write_csv
    from table2_scheduler_evidence import analyze_formal
finally:
    sys.path[:] = _previous

from rq1_integrity import digest, seal_tree, verify_tree
from rq1_reorder3_freeze import _equal, _path, _recorded_session, _relative, read_json, require

SCHEMA = "cs340-period-rq1-twelve-formal-freeze-v1"
DEFAULT_OUTPUT = "docs/frozen/table2-rq1-twelve-formal-20261124"
BENCHMARKS = ("reorder_3_bad", "reorder_4_bad")
METRICS = ("benchmark", "mode", "round", "included", "first_error", "total_schedules",
           "completed_schedules", "physical_launches", "error_interleavings", "timeouts",
           "internal_seconds", "external_seconds", "exit_code", "termination_state",
           "context_sha256", "analysis_sha256")


def _native_evidence(session, native_root, recorded):
    prefix = str(native_root).rstrip("/") + "/evidence/"
    value = str(recorded).replace("\\", "/")
    require(value.startswith(prefix), "recorded input proof is outside its original native session")
    relative = PurePosixPath(value[len(prefix):])
    require(relative.parts and not relative.is_absolute() and
            all(part not in ("", ".", "..") for part in relative.parts), "unsafe native evidence path")
    result = session / relative.parts[0] / "native-evidence"
    for part in relative.parts[1:]:
        result = result / part
    require(result.exists(), "required original measured input evidence is missing: " + str(result))
    return result


def _stage(session, local):
    relative = local.resolve().relative_to(session)
    require(relative.parts, "missing original phase directory")
    return session / relative.parts[0]


def audit_completed(repo, batch):
    """Use the existing formal validator, scoped to the twelve accepted rounds."""
    repo, batch = Path(repo).resolve(), Path(batch).resolve()
    batch_record = read_json(batch / "batch-result.json")
    session = _recorded_session(repo, batch_record["session"])
    original = read_json(session / "session.json")
    protocol_path = session / "protocol.json"
    protocol, protocol_hash = read_json(protocol_path), digest(protocol_path)
    require(protocol_hash == original["protocol_sha256"], "completed session protocol changed")
    require(protocol.get("minimum_rounds") == 3 and protocol.get("schedule_budget") == 10000
            and protocol.get("bug_depth") == 3, "completed formal protocol differs")
    previous = read_json(batch / "statistics/summary.json")
    require(previous.get("valid_formal_rounds") == 12 and batch_record.get("valid_formal_rounds") == 12,
            "the source batch must record the twelve already accepted rounds")
    with (batch / "statistics/per-round.csv").open(encoding="utf-8", newline="") as stream:
        reported = [row for row in csv.DictReader(stream) if row["benchmark"] in BENCHMARKS]
    expected = {(name, mode, number) for name in BENCHMARKS
                for mode in ("parallel", "serial") for number in (1, 2, 3)}
    keys = [(row["benchmark"], row["mode"], int(row["round"])) for row in reported]
    require(len(keys) == 12 and set(keys) == expected and all(row["included"] == "True" for row in reported),
            "need exactly twelve accepted reorder_3/4 formal round identities")
    formal_stages = sorted({_recorded_session(repo, row["run_dir"]).parents[1] for row in reported})
    require(all(session in phase.parents for phase in formal_stages), "a completed phase belongs to another session")
    verified = {_relative(repo, batch): verify_tree(batch)}
    roots = {batch, session / "prepare"}
    records = []
    for phase in formal_stages:
        verified[_relative(repo, phase)] = verify_tree(phase)
        roots.add(phase)
        receipt = read_json(phase / "stage-result.json")
        require(receipt.get("status") == "FORMAL_BENCHMARK_PASSED"
                and receipt.get("failure_scope") == "none" and receipt.get("phase_excluded") is False,
                "the original formal phase was not accepted: " + str(phase))
        selected = collect_rounds(phase, protocol_hash, 10000)
        require(selected and all(row["benchmark"] in BENCHMARKS for row in selected),
                "completed phase contains unexpected formal programs")
        state = read_json(phase / "native-evidence/state-after.json")
        require(state.get("root") == original["container_root"] and state.get("protocol_sha256") == protocol_hash,
                "completed phase belongs to another native session/protocol")
        for row in selected:
            name, run = row["benchmark"], Path(row["run_dir"])
            require(row["included"] is True and row["exit_code"] == 0 and row["timeouts"] == 0,
                    "a completed formal round failed acceptance")
            item = state["benchmarks"][name]
            require(item.get("formal_complete") is True and item.get("adaptation", {}).get("status") == "PASS",
                    "native completion/adaptation checkpoint did not accept the formal cohort")
            if name == "reorder_3_bad":
                require(state.get("reorder3_formal_complete") is True, "missing reorder_3 completion checkpoint")
            manifest_path = _native_evidence(session, state["root"], item["manifest"])
            proof_path = _native_evidence(session, state["root"], item["abi_proof"])
            proof = read_json(proof_path)
            require(proof.get("status") == "PASS" and not proof.get("blockers")
                    and proof.get("benchmark_manifest", {}).get("sha256") == digest(manifest_path),
                    "completed round measured ABI proof is not bound to its original input manifest")
            manifest = read_json(manifest_path)
            roots.add(_stage(session, manifest_path))
            for recorded in item.get("adaptation", {}).get("runs", {}).values():
                roots.add(_stage(session, _native_evidence(session, state["root"], recorded)))
            replay = analyze_formal(run, row["mode"], manifest, protocol_path, item["runtime_profile"])
            require(replay.get("included") is True and replay.get("validation") == "PASS",
                    "completed raw round failed reanalysis: " + str(replay.get("exclusion_reasons")))
            saved = read_json(run / "analysis.json")
            for field in ("first_error", "total_schedules", "error_interleavings", "timeouts", "exit_code",
                          "internal_seconds", "external_seconds", "kps", "matrix_shape", "schedules",
                          "error_ordinals", "actual_yield_patterns", "actual_saved_error_yields", "accounting",
                          "binary_sha256", "config_sha256", "abi_layout", "abi_layer_sha256"):
                _equal(replay.get(field), saved.get(field), name + ":" + run.name + ":" + field)
            records.append(row)
    require(len(records) == 12 and {(row["benchmark"], row["mode"], row["round"]) for row in records} == expected,
            "completed evidence has duplicate or missing formal rounds")
    for directory in sorted(roots):
        key = _relative(repo, directory)
        if key not in verified:
            verified[key] = verify_tree(directory)
    keyed = {(row["benchmark"], row["mode"], int(row["round"])): row for row in reported}
    for row in records:
        saved = keyed[(row["benchmark"], row["mode"], row["round"])]
        for name in METRICS:
            value = row[name]
            raw = saved.get(name, "")
            if type(value) in (int, float):
                _equal(value, float(raw), row["benchmark"] + ":" + name)
            elif type(value) is bool:
                _equal(str(value), raw, row["benchmark"] + ":" + name)
            elif value is None:
                require(raw == "", "null completed result became a numeric substitute")
            else:
                _equal(value, raw, row["benchmark"] + ":" + name)
    groups = [group for group in summarize(records, 3) if group["benchmark"] in BENCHMARKS]
    saved_groups = {(group["benchmark"], group["mode"]): group for group in previous["groups"]}
    for group in groups:
        for field, value in group.items():
            _equal(value, saved_groups[(group["benchmark"], group["mode"])].get(field),
                   group["benchmark"] + ":" + group["mode"] + ":" + field)
    return {"session": session, "session_record": original, "protocol": protocol,
            "protocol_sha256": protocol_hash, "records": records, "groups": groups,
            "roots": sorted(roots), "raw_verification": verified}


def freeze_completed(repo, batch, output=None):
    repo, batch = Path(repo).resolve(), Path(batch).resolve()
    output = Path(output).resolve() if output else repo / DEFAULT_OUTPUT
    if output.exists():
        existing = verify_completed_freeze(repo, output / "FREEZE.json")
        require(existing["batch"] == _relative(repo, batch), "existing completed freeze identifies another batch")
        return existing
    audited = audit_completed(repo, batch)
    trusted = {}
    for directory in audited["roots"]:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                trusted[_relative(repo, path)] = digest(path)
    session = audited["session"]
    for filename in ("session.json", "protocol.json"):
        trusted[_relative(repo, session / filename)] = digest(session / filename)
    rows = [dict(row, run_dir=_relative(repo, row["run_dir"])) for row in audited["records"]]
    original = audited["session_record"]
    record = {"schema": SCHEMA, "status": "TWELVE_FORMAL_ROUNDS_FROZEN", "formal_rounds": 12,
              "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "batch": _relative(repo, batch), "session": _relative(repo, session),
              "freeze_path": _relative(repo, output / "FREEZE.json"),
              "protocol_sha256": audited["protocol_sha256"], "source_commit": audited["protocol"]["source_commit"],
              "container_id": original["container_id"], "runtime_identity": original["runtime_identity"],
              "launch_configuration": original["launch_configuration"], "harness_hashes": original["harness_hashes"],
              "records": rows, "groups": audited["groups"], "trusted_file_digests": trusted,
              "selected_phases": [_relative(repo, path) for path in audited["roots"] if path != batch],
              "raw_verification": audited["raw_verification"],
              "scope": "Original accepted reorder_3/4 only; failed reorder_5 export is preserved and excluded.",
              "reuse_policy": "No reexecution or replacement of the twelve accepted formal rounds."}
    output.mkdir(parents=True)
    with (output / "FREEZE.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    write_csv(output / "per-round.csv", rows, list(rows[0]))
    write_csv(output / "group-statistics.csv", audited["groups"], list(audited["groups"][0]))
    with (output / "README.md").open("x", encoding="utf-8") as stream:
        stream.write("# Frozen twelve accepted RQ1 formal rounds\n\n"
                     "The original reorder_3 and reorder_4 evidence is indexed by repository-relative hashes in FREEZE.json. "
                     "The twelve-row table and four group summaries were recalculated by the unchanged report/acceptance functions. "
                     "The incomplete reorder_5 export remains preserved outside this accepted-data freeze. "
                     "Its recovery must pass its own full evidence and environment acceptance before inclusion.\n")
    seal_tree(output)
    verify_completed_freeze(repo, output / "FREEZE.json")
    return record


def verify_completed_freeze(repo, freeze_path):
    repo = Path(repo).resolve()
    freeze_path = Path(freeze_path)
    freeze_path = freeze_path.resolve() if freeze_path.is_absolute() else (repo / freeze_path).resolve()
    verify_tree(freeze_path.parent)
    record = read_json(freeze_path)
    require(record.get("schema") == SCHEMA and record.get("status") == "TWELVE_FORMAL_ROUNDS_FROZEN"
            and record.get("formal_rounds") == 12, "unsupported completed formal freeze")
    for relative, expected in record["trusted_file_digests"].items():
        path = _path(repo, relative)
        require(path.is_file() and digest(path) == expected, "frozen accepted evidence changed: " + relative)
    audited = audit_completed(repo, _path(repo, record["batch"]))
    require(_relative(repo, audited["session"]) == record["session"] and
            audited["protocol_sha256"] == record["protocol_sha256"], "completed freeze session/protocol changed")
    actual = {(row["benchmark"], row["mode"], row["round"]): row for row in audited["records"]}
    require(len(record["records"]) == 12, "completed freeze lost its twelve identities")
    for row in record["records"]:
        current = actual[(row["benchmark"], row["mode"], row["round"])]
        require(_relative(repo, current["run_dir"]) == row["run_dir"], "completed formal path changed")
        for field in METRICS:
            _equal(current[field], row[field], row["benchmark"] + ":" + field)
    return record
