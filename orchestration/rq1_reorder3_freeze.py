"""Freeze six accepted reorder_3 formal rounds without copying or rerunning them.

The frozen evidence index uses repository-relative paths, so the same record
works from Windows and the Ubuntu mount. Future other-benchmark rounds may be
added to the session; existing six rounds and their source evidence stay fixed.
Python 3.6+.
"""
import csv
import datetime
import json
import math
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
_previous = list(sys.path)
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from table2_rq1_report import collect_rounds, summarize
    from table2_scheduler_evidence import analyze_formal
finally:
    sys.path[:] = _previous

from rq1_integrity import digest, seal_tree, verify_tree

SCHEMA = "cs340-period-rq1-reorder3-formal-freeze-v1"
DEFAULT_OUTPUT = "docs/frozen/table2-rq1-reorder3-formal-20261124"
METRICS = ("benchmark", "mode", "round", "included", "first_error", "total_schedules",
           "completed_schedules", "physical_launches", "error_interleavings", "timeouts",
           "internal_seconds", "external_seconds", "exit_code", "termination_state")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _path(repo, relative):
    result = (repo / relative).resolve()
    require(repo in result.parents, "frozen evidence path leaves the repository: " + str(relative))
    return result


def _recorded_session(repo, raw):
    value = str(raw).replace("\\", "/")
    marker = "/docs/results/"
    if marker in value:
        return _path(repo, "docs/results/" + value.split(marker, 1)[1])
    return _path(repo, value)


def _relative(repo, path):
    path = Path(path).resolve()
    require(repo in path.parents, "evidence is outside repository: " + str(path))
    return path.relative_to(repo).as_posix()


def _equal(actual, expected, label):
    if isinstance(actual, (dict, list)) and isinstance(expected, (dict, list)):
        # JSON evidence persists integer mapping keys as strings.
        actual = json.loads(json.dumps(actual))
        expected = json.loads(json.dumps(expected))
    if type(actual) is float or type(expected) is float:
        require(type(actual) in (int, float) and type(expected) in (int, float)
                and math.isfinite(actual) and math.isfinite(expected)
                and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12),
                "frozen statistic differs: " + label)
    else:
        require(actual == expected, "frozen statistic differs: " + label)


def audit_six(repo, batch, session=None):
    """Re-audit original bytes with the existing formal acceptance functions."""
    repo, batch = Path(repo).resolve(), Path(batch).resolve()
    batch_record = read_json(batch / "batch-result.json")
    session = Path(session).resolve() if session else _recorded_session(repo, batch_record["session"])
    raw = {"batch": verify_tree(batch), "session": verify_tree(session)}
    original = read_json(session / "session.json")
    protocol_path = session / "protocol.json"
    protocol = read_json(protocol_path)
    protocol_hash = digest(protocol_path)
    require(protocol_hash == original["protocol_sha256"], "session protocol identity differs")
    require(protocol.get("minimum_rounds") == 3 and protocol.get("schedule_budget") == 10000
            and protocol.get("bug_depth") == 3, "frozen formal protocol differs")
    collected = collect_rounds(session, protocol_hash, 10000)
    records = [row for row in collected if row["benchmark"] == "reorder_3_bad"]
    expected = {(mode, number) for mode in ("parallel", "serial") for number in (1, 2, 3)}
    require(len(records) == 6 and {(row["mode"], row["round"]) for row in records} == expected,
            "need exactly the six independent reorder_3 formal rounds")
    for row in records:
        require(row["included"] is True and row["exit_code"] == 0 and row["timeouts"] == 0,
                "reorder_3 formal round is not valid: " + row["run_dir"])
        run = Path(row["run_dir"])
        context = read_json(run / "run-context.json")
        require(context.get("phase") == "formal" and context.get("purpose") == "formal"
                and context.get("role") == "unified", "round is not an explicit unified formal result")
        native = run.parent
        phase_state = read_json(native / "state-after.json")
        item = phase_state["benchmarks"]["reorder_3_bad"]
        require(phase_state.get("reorder3_formal_complete") is True and item.get("formal_complete") is True,
                "native completion checkpoint does not accept the six-round cohort")
        manifest = read_json(session / "prepare/native-evidence/reorder_3_bad/benchmark-manifest.json")
        replay = analyze_formal(run, row["mode"], manifest, protocol_path, item["runtime_profile"])
        require(replay.get("included") is True and replay.get("validation") == "PASS",
                "raw formal reanalysis failed: " + str(replay.get("exclusion_reasons")))
        saved = read_json(run / "analysis.json")
        for key in ("first_error", "total_schedules", "error_interleavings", "timeouts", "exit_code",
                    "internal_seconds", "external_seconds", "kps", "matrix_shape", "schedules",
                    "error_ordinals", "actual_yield_patterns", "actual_saved_error_yields", "accounting",
                    "binary_sha256", "config_sha256", "abi_layout", "abi_layer_sha256"):
            _equal(replay.get(key), saved.get(key), "%s:%s" % (run.name, key))
    groups = [group for group in summarize(records, 3) if group["benchmark"] == "reorder_3_bad"]
    previous = read_json(batch / "statistics/summary.json")
    require(previous.get("formal_attempts") == 6 and previous.get("valid_formal_rounds") == 6
            and previous.get("invalid_attempts") == 0, "original batch did not report six valid formal rounds")
    previous_groups = {(group["benchmark"], group["mode"]): group for group in previous["groups"]}
    for group in groups:
        saved_group = previous_groups[(group["benchmark"], group["mode"])]
        for key, value in group.items():
            _equal(value, saved_group.get(key), group["mode"] + ":" + key)
    with (batch / "statistics/per-round.csv").open(encoding="utf-8", newline="") as stream:
        saved_rows = list(csv.DictReader(stream))
    require(len(saved_rows) == 6, "original per-round table does not contain six rows")
    keyed = {(row["benchmark"], row["mode"], int(row["round"])): row for row in saved_rows}
    require(len(keyed) == 6, "original per-round table repeats a round")
    for row in records:
        saved_row = keyed[(row["benchmark"], row["mode"], row["round"])]
        for name in METRICS:
            value = row[name]
            raw_value = saved_row.get(name, "")
            if type(value) is bool:
                _equal(str(value), raw_value, row["mode"] + ":" + name)
            elif type(value) in (int, float):
                _equal(value, float(raw_value), row["mode"] + ":" + name)
            elif value is None:
                require(raw_value == "", "null result became a numeric value")
            else:
                _equal(value, raw_value, row["mode"] + ":" + name)
    return {"session": session, "session_record": original, "protocol": protocol,
            "protocol_sha256": protocol_hash, "records": records, "groups": groups,
            "raw_verification": raw}


def freeze_reorder3(repo, batch, output=None):
    repo, batch = Path(repo).resolve(), Path(batch).resolve()
    output = Path(output).resolve() if output else repo / DEFAULT_OUTPUT
    if output.exists():
        existing = verify_reorder3_freeze(repo, output / "FREEZE.json")
        require(existing["batch"] == _relative(repo, batch), "an existing freeze identifies another batch")
        return existing
    audited = audit_six(repo, batch)
    session = audited["session"]
    evidence = {}
    roots = [batch, session / "prepare"] + sorted({Path(row["run_dir"]).parents[1] for row in audited["records"]})
    for directory in roots:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                evidence[_relative(repo, path)] = digest(path)
    for filename in ("session.json", "protocol.json"):
        evidence[_relative(repo, session / filename)] = digest(session / filename)
    records = []
    for row in audited["records"]:
        item = dict(row)
        item["run_dir"] = _relative(repo, row["run_dir"])
        records.append(item)
    original = audited["session_record"]
    record = {"schema": SCHEMA, "status": "SIX_FORMAL_ROUNDS_FROZEN",
              "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "freeze_path": _relative(repo, output / "FREEZE.json"),
              "batch": _relative(repo, batch), "session": _relative(repo, session),
              "formal_rounds": 6, "protocol_sha256": audited["protocol_sha256"],
              "source_commit": audited["protocol"]["source_commit"],
              "container_id": original["container_id"], "runtime_identity": original["runtime_identity"],
              "launch_configuration": original["launch_configuration"], "harness_hashes": original["harness_hashes"],
              "records": records, "groups": audited["groups"], "immutable_evidence": evidence,
              "raw_verification": audited["raw_verification"],
              "reuse_policy": "Reuse these exact six rounds; no replacement or additional reorder_3 formal execution."}
    output.mkdir(parents=True)
    shutil.copytree(str(batch / "statistics"), str(output / "statistics"))
    with (output / "FREEZE.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(record, indent=2, sort_keys=True) + "\n")
    with (output / "README.md").open("x", encoding="utf-8") as stream:
        stream.write("# Frozen reorder_3 formal results\n\n"
                     "Six accepted unified-driver formal rounds are indexed by exact repository-relative file hashes in FREEZE.json. "
                     "The original evidence remains in its existing results directories; statistics/ is a byte-preserved snapshot. "
                     "Later other-benchmark results may be added to the same session without replacing these six rounds.\n")
    seal_tree(output)
    verify_reorder3_freeze(repo, output / "FREEZE.json")
    return record


def verify_reorder3_freeze(repo, freeze_path):
    repo = Path(repo).resolve()
    freeze_path = Path(freeze_path)
    if not freeze_path.is_absolute():
        freeze_path = repo / freeze_path
    freeze_path = freeze_path.resolve()
    verify_tree(freeze_path.parent)
    record = read_json(freeze_path)
    require(record.get("schema") == SCHEMA and record.get("status") == "SIX_FORMAL_ROUNDS_FROZEN"
            and record.get("formal_rounds") == 6, "unsupported reorder_3 formal freeze")
    for relative, expected in record["immutable_evidence"].items():
        path = _path(repo, relative)
        require(path.is_file() and digest(path) == expected, "frozen formal evidence changed: " + relative)
    audited = audit_six(repo, _path(repo, record["batch"]), _path(repo, record["session"]))
    require(audited["protocol_sha256"] == record["protocol_sha256"], "frozen protocol differs")
    actual_rows = {(row["mode"], row["round"]): row for row in audited["records"]}
    require(len(record["records"]) == 6, "freeze is missing its six round identities")
    for row in record["records"]:
        actual = actual_rows[(row["mode"], row["round"])]
        require(_relative(repo, actual["run_dir"]) == row["run_dir"], "formal round path changed")
        for name in METRICS + ("context_sha256", "analysis_sha256"):
            _equal(actual.get(name), row.get(name), row["mode"] + ":" + name)
    return record
