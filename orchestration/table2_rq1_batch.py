#!/usr/bin/env python3
"""Run the minimum RQ1 cohort through the unchanged frozen native entry.

This outer coordinator never builds missing products or replaces an attempt.
It lives outside scripts/tests so an accepted session keeps its harness hash.
Python 3.6+; execute in the Ubuntu x86_64 root terminal.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import table2_rq1 as host
from table2_permission_stage import harness_hashes
from table2_rq1_report import write_report
from rq1_integrity import digest, seal_tree, verify_tree


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_formal_freeze(repo, frozen):
    if frozen.get("schema") == "cs340-period-rq1-twelve-formal-freeze-v1":
        from rq1_completed_freeze import verify_completed_freeze
        return verify_completed_freeze(repo, Path(repo) / frozen["freeze_path"])
    from rq1_reorder3_freeze import verify_reorder3_freeze
    return verify_reorder3_freeze(repo, Path(repo) / frozen["freeze_path"])


def preparation_plan(session):
    """Read and verify a prepared cohort without changing its frozen inputs."""
    session = Path(session).resolve()
    record = read_json(session / "session.json")
    host.require(record.get("schema") == host.SCHEMA and record.get("status") in (
        "PREPARED", "PREPARED_WITH_BLOCKED_BENCHMARKS"), "an accepted prepare session is required")
    host.require(not (session / "HALTED.json").exists(), "session has a retained global/legacy HALTED marker")
    host.require(harness_hashes(ROOT) == record["harness_hashes"], "frozen harness changed")
    host.verify_frozen_pilot(ROOT)
    protocol = read_json(session / "protocol.json")
    host.require(digest(session / "protocol.json") == record["protocol_sha256"], "session protocol changed")
    host.require(protocol.get("benchmarks") == list(host.BENCHMARKS)
                 and protocol.get("minimum_rounds") == 3
                 and protocol.get("initial_total_formal_rounds") == 24,
                 "this launcher runs only the minimum 24-round protocol")
    verification = verify_tree(session)
    receipt = read_json(session / "prepare/stage-result.json")
    host.require(receipt.get("status") in ("PREPARED", "PREPARED_WITH_BLOCKED_BENCHMARKS")
                 and receipt.get("phase_excluded") is False, "prepare phase was not accepted")
    native = session / "prepare/native-evidence"
    state = read_json(native / "state-after.json")
    host.require(state.get("protocol_sha256") == record["protocol_sha256"], "prepare protocol identity changed")
    entries = []
    for benchmark in host.BENCHMARKS:
        item = state["benchmarks"].get(benchmark, {})
        inventory_path = native / benchmark / "inventory.json"
        inventory = read_json(inventory_path) if inventory_path.is_file() else {}
        missing = [path for path, identity in sorted(inventory.items()) if identity.get("exists") is False]
        ready = "manifest" in item and "abi_proof" in item
        if ready:
            manifest = native / benchmark / "benchmark-manifest.json"
            proof = read_json(native / benchmark / "abi-proof.json")
            host.require(proof.get("status") == "PASS" and not proof.get("blockers")
                         and proof.get("benchmark") == benchmark
                         and proof.get("benchmark_manifest", {}).get("sha256") == digest(manifest),
                         "prepared ABI proof is invalid: " + benchmark)
        entries.append({"benchmark": benchmark, "planned_formal_rounds": 6,
                        "status": "READY" if ready else "BLOCKED_PREPARATION",
                        "missing_artifacts": missing, "preparation_status": item.get("status"),
                        "reason": None if ready else item.get("reason", "identity/ABI preparation did not pass")})
    return {"schema": "cs340-period-rq1-batch-plan-v1", "session": str(session),
            "planned_formal_rounds": 24, "rounds_per_mode": 3,
            "eligible_formal_rounds": sum(6 for item in entries if item["status"] == "READY"),
            "benchmarks": entries, "preparation_evidence_verification": verification}, state


def execute_plan(plan, state, phase_runner):
    """Sequence existing phases; local failures cannot select replacement runs."""
    outcomes, phases = [], []
    global_failure = None
    for entry in plan["benchmarks"]:
        benchmark = entry["benchmark"]
        outcome = dict(entry)
        if global_failure:
            outcome.update(status="NOT_RUN_GLOBAL_STOP", reason=global_failure)
            outcomes.append(outcome)
            continue
        if entry["status"] != "READY":
            outcomes.append(outcome)
            continue
        item = state.get("benchmarks", {}).get(benchmark, {})
        if item.get("formal_complete"):
            outcome.update(status="REUSED_COMPLETED", reason="retained complete cohort; no additional runs")
            outcomes.append(outcome)
            continue
        if item.get("formal_attempted") or (item.get("adaptation_attempted") and not item.get("adaptation")):
            outcome.update(status="BLOCKED_PREVIOUS_ATTEMPT", reason="a retained incomplete attempt cannot be retried automatically")
            outcomes.append(outcome)
            continue
        if benchmark != "reorder_3_bad" and not state.get("reorder3_formal_complete"):
            outcome.update(status="BLOCKED_DEPENDENCY", reason="the unchanged native entry requires the six reorder_3 rounds first")
            outcomes.append(outcome)
            continue
        required = ["reorder3"] if benchmark == "reorder_3_bad" else (
            ["formal"] if item.get("adaptation", {}).get("status") == "PASS" else ["adapt", "formal"])
        for phase in required:
            result = phase_runner(phase, None if phase == "reorder3" else benchmark)
            phases.append(result)
            if result.get("state") is not None:
                state = result["state"]
            scope = result.get("failure_scope", "global")
            if scope != "none":
                outcome.update(status="BENCHMARK_FAILED" if scope == "benchmark" else "GLOBAL_FAILURE",
                               reason=result.get("reason", "phase did not pass"), evidence=result.get("evidence"))
                if scope != "benchmark":
                    global_failure = outcome["reason"]
                break
        else:
            outcome.update(status="FORMAL_COMPLETE", reason=None)
        outcomes.append(outcome)
    return {"benchmarks": outcomes, "phases": phases, "global_failure": global_failure}


def final_status(summary, execution, integrity_ok):
    if not integrity_ok or execution.get("global_failure"):
        return "BLOCKED_GLOBAL", 2
    if summary and summary.get("minimum_complete") and summary.get("valid_formal_rounds") == 24:
        return "MINIMUM_24_PASSED", 0
    return "INCOMPLETE_MINIMUM_24", 3


def execute_remaining(plan, state, phase_runner):
    """Preserve accepted cohorts and execute only unfinished programs."""
    host.require(state.get("reorder3_formal_complete") is True and
                 state.get("benchmarks", {}).get("reorder_3_bad", {}).get("formal_complete") is True,
                 "the native checkpoint must retain the six completed reorder_3 rounds")
    outcomes = [dict(plan["benchmarks"][0], status="REUSED_FROZEN_SIX", reason="verified immutable six-round evidence; no launch")]
    phases, global_failure = [], None
    for entry in plan["benchmarks"][1:]:
        benchmark = entry["benchmark"]
        outcome = dict(entry)
        if global_failure:
            outcome.update(status="NOT_RUN_GLOBAL_STOP", reason=global_failure)
            outcomes.append(outcome)
            continue
        item = state.get("benchmarks", {}).get(benchmark, {})
        if item.get("formal_complete"):
            outcomes.append(dict(outcome, status="REUSED_COMPLETED", reason="retained accepted cohort; no new execution", missing_artifacts=[]))
            continue
        if item.get("formal_attempted") or (item.get("adaptation_attempted") and not item.get("adaptation")):
            outcomes.append(dict(outcome, status="BLOCKED_PREVIOUS_ATTEMPT", reason="retained incomplete experiment; no automatic retry"))
            continue
        if not item.get("manifest") and item.get("build_attempted"):
            outcomes.append(dict(outcome, status="BLOCKED_PREVIOUS_BUILD", reason="retained build attempt; no automatic replacement"))
            continue
        required = ([] if item.get("manifest") else ["build"])
        if item.get("adaptation", {}).get("status") != "PASS":
            required.append("adapt")
        required.append("formal")
        for phase in required:
            result = phase_runner(phase, benchmark)
            phases.append(result)
            if result.get("state") is not None:
                state = result["state"]
            scope = result.get("failure_scope", "global")
            if scope != "none":
                outcome.update(status="BENCHMARK_FAILED" if scope == "benchmark" else "GLOBAL_FAILURE",
                               reason=result.get("reason", "phase did not pass"), evidence=result.get("evidence"))
                if scope != "benchmark":
                    global_failure = outcome["reason"]
                break
            item = state.get("benchmarks", {}).get(benchmark, {})
            if phase == "build":
                if not (item.get("manifest") and item.get("abi_proof")):
                    global_failure = "build passed without a registered measured ABI proof"
                    outcome.update(status="GLOBAL_FAILURE", reason=global_failure, evidence=result.get("evidence"))
                    break
                outcome["build_evidence"] = result.get("evidence")
        else:
            outcome.update(status="FORMAL_COMPLETE", reason=None, missing_artifacts=[])
        outcomes.append(outcome)
    return {"benchmarks": outcomes, "phases": phases, "global_failure": global_failure}


def write_final_report(output, plan, execution, summary, status, error=None, completion=False):
    actual = summary.get("valid_formal_rounds", 0) if summary else None
    lines = ["# Table 2 / RQ1 batch result", "", "Final status: **%s**" % status, "",
             "Session: `%s`" % plan.get("session", "unknown"), "",
             "Minimum required: 24 valid formal rounds. Verified valid rounds: **%s / 24**." % (
                 "not available" if actual is None else actual), "",
             "| Benchmark | Status | Reason |", "| --- | --- | --- |"]
    for item in execution.get("benchmarks", plan.get("benchmarks", [])):
        reason = (item.get("reason") or "").replace("|", "\\|").replace("\n", " ")
        lines.append("| %s | %s | %s |" % (item["benchmark"], item["status"], reason))
        for path in item.get("missing_artifacts", []):
            lines.append("| | Missing at original prepare | `%s` |" % path)
    lines += ["", "Statistics and original paper comparison are generated by the unchanged report writer:", "",
              "- [Mean and SD / per-group statistics](statistics/group-statistics.csv)",
              "- [Paper vs. Ours](statistics/paper-vs-ours.md)",
              "- [Per-round results](statistics/per-round.csv)",
              "- [Detailed statistical report and limitations](statistics/report.md)",
              "- [Censored observations](statistics/censored.csv)",
              "- [Invalid attempts](statistics/anomalies.csv)", "",
              "The sample SD uses n-1. First-error means include detected valid rounds only. ND is not 10000.",
              ("Missing products use the official three-step build in new directories, with preserved toolchain/runtime identities, exclusive publication and measured ABI acceptance."
               if completion else "Missing products are not built, migrated or treated as accepted experiments."),
              "No replacement attempts or extra repetitions are selected.",
              "Only explicit formal observations enter statistics; historical A0, pilot and adaptation records remain separate.",
              "CPU affinity remains 0-31. Hardware, supervision overhead, three repetitions and the workload family limit comparison with the full paper.",
              "A benchmark-local failure preserves prior accepted rounds. An unknown, environment or integrity failure stops subsequent execution."]
    if completion:
        lines += ["", "Accepted completed cohorts are reused without target execution. Only unfinished programs are eligible for new formal rounds.", "",
                  "[Build plan and immutable six-round reference](plan.json)", "",
                  "## Comparison charts", "",
                  "[All charts and exact chart data](charts/README.md)", "",
                  "![First detected error ordinal](charts/first_error_detected_only.svg)", "",
                  "![Total schedules](charts/total_schedules.svg)", "",
                  "![Error schedules](charts/error_interleavings.svg)", "",
                  "![Bug detection rate](charts/detection_rate.svg)", "",
                  "![External runtime](charts/external_seconds.svg)", "",
                  "The first-error mean is conditional on detection; ND/censoring and sample counts must be read alongside it.",
                  "Differences from the paper are retained. Parallel final-period execution can depend on host scheduling; matching schedules do not guarantee matching outcomes.",
                  "Build directories can change DWARF and binary hashes; every new binary is treated as a new measured identity, using the same verified runtime object."]
    if error:
        lines += ["", "Stopped exception: `%s`" % error.replace("`", "'")]
    with (output / "batch-report.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def prepare_session():
    """Use the existing prepare entry and its explicitly printed new session."""
    command = [sys.executable, "-B", str(ROOT / "scripts/table2_rq1.py"), "prepare",
               "--protocol", str(ROOT / "config/table2-rq1-protocol.json")]
    reported = set()
    with subprocess.Popen(command, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True, bufsize=1) as process:
        for line in process.stdout:
            print(line, end="", flush=True)
            if line.startswith("Session: "):
                reported.add(line[len("Session: "):].strip())
        exit_code = process.wait()
    if exit_code != 0:
        return None, exit_code
    host.require(len(reported) == 1 and next(iter(reported)),
                 "prepare did not print one consistent new Session path")
    session = Path(next(iter(reported))).resolve()
    host.require(ROOT / "docs/results" in session.parents,
                 "prepare reported a Session outside this repository's results directory")
    record = read_json(session / "session.json")
    host.require(record.get("schema") == host.SCHEMA and record.get("status") in (
        "PREPARED", "PREPARED_WITH_BLOCKED_BENCHMARKS"), "new prepare session was not accepted")
    host.require(not (session / "HALTED.json").exists(), "new prepare session is halted")
    return session, 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    entry = parser.add_mutually_exclusive_group(required=True)
    entry.add_argument("--session", type=Path, help="continue one accepted prepared session")
    entry.add_argument("--prepare", action="store_true", help="prepare a fresh session, then run its accepted benchmarks")
    entry.add_argument("--complete-from", type=Path, help="freeze an accepted six-round batch, build missing programs and run only the remaining 18")
    entry.add_argument("--recover-from", type=Path, help="recover an export-only failure into a new evidence view, then execute only unfinished programs")
    args = parser.parse_args(argv)
    if sys.platform != "linux" or platform.machine() != "x86_64" or os.geteuid() != 0:
        parser.error("run in the Ubuntu x86_64 root terminal")
    frozen = None
    if args.recover_from:
        from rq1_completed_freeze import freeze_completed
        from rq1_recover_export import recover_export
        frozen = verify_formal_freeze(ROOT, freeze_completed(ROOT, args.recover_from.resolve()))
        recovery = recover_export(ROOT, args.recover_from.resolve(), frozen)
        host.require(recovery.get("valid_formal_rounds") == 18 and recovery.get("recovered_rounds") == 6,
                     "recovery must validate the six preserved reorder_5 rounds before continuation")
        session = Path(recovery["view_session"]).resolve()
    elif args.complete_from:
        from rq1_reorder3_freeze import freeze_reorder3, verify_reorder3_freeze
        frozen = freeze_reorder3(ROOT, args.complete_from.resolve())
        frozen = verify_reorder3_freeze(ROOT, ROOT / frozen["freeze_path"])
        session = (ROOT / frozen["session"]).resolve()
    elif args.prepare:
        session, exit_code = prepare_session()
        if exit_code != 0:
            return exit_code
    else:
        session = args.session.resolve()
    host.require(ROOT / "docs/results" in session.parents, "session must be inside this repository's results directory")
    # A host lock avoids two batch launchers interleaving phases in this session.
    import fcntl
    with (session / "batch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return run_batch(session, frozen) if frozen else run_batch(session)


def run_batch(session, frozen=None):
    from rq1_phase import global_guard, run_phase
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = Path(tempfile.mkdtemp(prefix="table2-rq1-batch-" + stamp + "-", dir=str(ROOT / "docs/results")))
    print("Batch evidence: " + str(output), flush=True)
    plan = {"session": str(session), "benchmarks": []}
    execution = {"benchmarks": [], "phases": [], "global_failure": None}
    summary, error, integrity_ok = None, None, False
    try:
        plan, state = preparation_plan(session)
        if frozen:
            plan.update(reuse_frozen_formal_rounds=frozen.get("formal_rounds", 6), build_missing_authorized=True,
                        freeze_path=frozen["freeze_path"])
        input_names = ["session.json", "protocol.json"]
        if (session / "recovery-provenance.json").is_file():
            provenance = read_json(session / "recovery-provenance.json")
            accepted_recovery = read_json(session / "recovery-control/recovery-result.json")
            host.require(accepted_recovery.get("status") == "PASS" and
                         accepted_recovery.get("provenance") == provenance, "recovery provenance differs from its sealed acceptance")
            plan.update(recovered_original_formal_rounds=provenance["recovered_formal_rounds"],
                        recovery_provenance=str(session / "recovery-provenance.json"))
            input_names.append("recovery-provenance.json")
        write_json(output / "plan.json", plan)
        for item in plan["benchmarks"]:
            print("%s: %s%s" % (item["benchmark"], item["status"],
                  " - " + str(item["reason"]) if item["reason"] else ""), flush=True)
            for path in item["missing_artifacts"]:
                print("  Missing: " + path, flush=True)
        if frozen:
            print("Reuse all accepted completed rounds; execute only unfinished benchmarks.", flush=True)
        else:
            print("Eligible formal rounds: %d / 24; no missing products will be built." % plan["eligible_formal_rounds"], flush=True)
        for filename in input_names:
            shutil.copyfile(str(session / filename), str(output / ("input-" + filename)))
        launcher = output / "launcher"
        launcher.mkdir()
        for path in sorted(Path(__file__).resolve().parent.glob("*.py")):
            shutil.copyfile(str(path), str(launcher / path.name))
        control = output / "preflight"
        control.mkdir()
        current = global_guard(ROOT, session, host.Commands(control), "batch-start")
        state = current["state"]
        execute = execute_remaining if frozen else execute_plan
        execution = execute(plan, state, lambda phase, benchmark: run_phase(ROOT, session, phase, benchmark))
        if execution["global_failure"]:
            raise ValueError(execution["global_failure"])
        for filename in input_names:
            host.require(digest(session / filename) == digest(output / ("input-" + filename)),
                         "batch input changed during execution: " + filename)
        for snapshot in sorted(launcher.glob("*.py")):
            host.require(digest(snapshot) == digest(Path(__file__).resolve().parent / snapshot.name),
                         "outer launcher changed during execution: " + snapshot.name)
        if frozen:
            verify_formal_freeze(ROOT, frozen)
        write_json(output / "raw-evidence-verification.json", verify_tree(session))
        integrity_ok = True
    except BaseException as exception:
        error = type(exception).__name__ + ": " + str(exception)
        execution["global_failure"] = execution.get("global_failure") or error
        write_json(output / "stopped-exception.json", {"error": error, "traceback": traceback.format_exc()})
        print(traceback.format_exc(), file=sys.stderr)
        if not (session / "HALTED.json").exists():
            write_json(session / "HALTED.json", {"phase": "batch", "evidence": str(output), "reason": error,
                                                "policy": "Global/unknown failure; no automatic continuation."})
    # Reporting is read-only with respect to previous experiments, even after a stop.
    try:
        summary = write_report(session, output / "statistics")
        verify_tree(output / "statistics")
        if frozen:
            from rq1_charts import write_charts
            write_charts(output / "statistics", output / "charts")
            verify_tree(output / "charts")
    except BaseException as exception:
        error = error or type(exception).__name__ + ": " + str(exception)
        execution["global_failure"] = execution.get("global_failure") or error
        write_json(output / "report-exception.json", {"error": str(exception), "traceback": traceback.format_exc()})
    status, exit_code = final_status(summary, execution, integrity_ok)
    if status == "BLOCKED_GLOBAL" and not (session / "HALTED.json").exists():
        write_json(session / "HALTED.json", {"phase": "batch", "evidence": str(output),
                                            "reason": execution.get("global_failure") or error,
                                            "policy": "Global/unknown failure; no automatic continuation."})
    result = {"schema": "cs340-period-rq1-batch-v1", "status": status, "session": str(session),
              "planned_formal_rounds": 24, "valid_formal_rounds": summary.get("valid_formal_rounds") if summary else None,
              "minimum_complete": bool(summary and summary.get("minimum_complete")),
              "raw_evidence_verified": integrity_ok, "execution": execution, "error": error}
    write_json(output / "batch-result.json", result)
    write_final_report(output, plan, execution, summary, status, error, completion=bool(frozen))
    seal_tree(output)
    verify_tree(output)
    print("Final status: %s\nValid formal rounds: %s / 24\nReport: %s\nEvidence: %s" % (
        status, result["valid_formal_rounds"], output / "batch-report.md", output), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
