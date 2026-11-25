#!/usr/bin/env python3
"""Summarize preserved RQ1 formal rounds; never execute a target or change data.

Python 3.6+. Pilot, adaptation and legacy A0 records are excluded by purpose.
First-error means are conditional on successful detection, never on a numeric
substitution for undetected/right-censored observations.
"""
import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path
import statistics

BENCHMARKS = tuple("reorder_%d_bad" % n for n in (3, 4, 5, 10))
MODES = ("parallel", "serial")
PAPER = {
    "reorder_3_bad": {"parallel": (6, 27, 6), "serial": (10, 30, 10)},
    "reorder_4_bad": {"parallel": (9, 100, 12), "serial": (37, 384, 90)},
    "reorder_5_bad": {"parallel": (12, 225, 20), "serial": (283, 5040, 816)},
    "reorder_10_bad": {"parallel": (27, 2350, 89), "serial": (None, 10000, 0)},
}
VALID_STATES = ("COMPLETED", "BUDGET_EXHAUSTED")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mean_sd(values):
    values = [float(value) for value in values if value is not None]
    if not values:
        return {"n": 0, "mean": None, "sample_sd": None}
    return {"n": len(values), "mean": statistics.mean(values),
            "sample_sd": statistics.stdev(values) if len(values) > 1 else None}


def normalize_round(context, analysis, run_dir, protocol_hash, budget=10000):
    """Reject invalid/mismatched outcomes without losing attempted-round data."""
    reasons = list(analysis.get("exclusion_reasons") or [])
    benchmark, mode = context.get("benchmark"), context.get("mode")
    if context.get("schema") != "cs340-period-rq1-run-v1" or type(context.get("round")) is not int or context["round"] < 1:
        reasons.append("missing formal run schema or valid round identity")
    if context.get("purpose") != "formal" or context.get("role") != "unified":
        reasons.append("formal statistics require explicit formal purpose and unified driver role")
    if benchmark not in BENCHMARKS or mode not in MODES:
        reasons.append("unsupported formal benchmark/mode")
    if context.get("protocol_sha256") != protocol_hash:
        reasons.append("protocol identity differs from the frozen session")
    if analysis.get("protocol_sha256") != protocol_hash:
        reasons.append("analysis protocol identity differs from the frozen session")
    if analysis.get("benchmark") != benchmark or analysis.get("mode") != mode:
        reasons.append("analysis and run context identify different experiments")
    state = analysis.get("termination_state", "INFRASTRUCTURE_FAILURE")
    valid = (analysis.get("schema") == "cs340-period-formal-evidence-v1"
             and analysis.get("status") == "PASS" and analysis.get("validation") == "PASS"
             and analysis.get("included") is True and analysis.get("valid_research_result") is True
             and state in VALID_STATES)
    total = analysis.get("total_schedules", analysis.get("executed_schedules"))
    completed = analysis.get("completed_schedules")
    errors = analysis.get("error_interleavings")
    first = analysis.get("first_error")
    if not (type(total) is int and 0 < total <= budget and type(completed) is int and completed == total
            and analysis.get("in_flight") == 0 and type(errors) is int and 0 <= errors <= total
            and analysis.get("timeouts") == 0):
        reasons.append("invalid or unfinished execution accounting")
    if state == "BUDGET_EXHAUSTED" and total != budget:
        reasons.append("budget-exhausted outcome is not exactly the frozen schedule budget")
    if first is not None and not (type(first) is int and type(total) is int and 1 <= first <= total):
        reasons.append("first-error ordinal outside actually executed schedules")
    if (first is None) != (errors == 0):
        reasons.append("first-error result and error count disagree")
    if not valid and not reasons:
        reasons.append("formal evidence did not pass research-result acceptance")
    valid = valid and not reasons
    censor = analysis.get("censoring") or {}
    return {
        "run_dir": str(run_dir), "benchmark": benchmark, "mode": mode,
        "round": context.get("round"), "purpose": "formal", "termination_state": state,
        "included": valid, "first_error": first, "bug_detected": first is not None if valid else None,
        "right_censored": bool(valid and first is None),
        "censor_at": completed if valid and first is None else None,
        "censor_reason": censor.get("reason", "no bug in observed schedules") if valid and first is None else None,
        "total_schedules": total, "completed_schedules": completed,
        "in_flight": analysis.get("in_flight"), "retests": analysis.get("retests"),
        "physical_launches": analysis.get("physical_launches"),
        "error_interleavings": errors, "timeouts": analysis.get("timeouts"),
        "internal_seconds": analysis.get("internal_seconds"),
        "external_seconds": analysis.get("external_seconds"), "exit_code": analysis.get("exit_code"),
        "protocol_sha256": context.get("protocol_sha256"),
        "exclusion_reasons": "; ".join(str(reason) for reason in reasons),
    }


def checksum_errors(run_dir):
    root = Path(run_dir).resolve()
    try:
        entries = {}
        for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
            expected, relative = line.split("  ", 1)
            path = (root / relative).resolve()
            if root not in path.parents or relative in entries or digest(path) != expected:
                raise ValueError("invalid path, duplicate entry or checksum mismatch: " + relative)
            entries[relative] = expected
        if not {"run-context.json", "analysis.json"}.issubset(entries):
            raise ValueError("run context/analysis are absent from the checksum manifest")
    except (OSError, ValueError) as error:
        return ["raw round checksum verification failed: " + str(error)]
    return []


def collect_rounds(session, protocol_hash, budget=10000):
    records = []
    for path in sorted(Path(session).rglob("run-context.json")):
        context = json.loads(path.read_text(encoding="utf-8"))
        # An explicit purpose prevents prior pilot/adaptation data entering formal means.
        if context.get("phase") != "formal":
            continue
        analysis_path = path.with_name("analysis.json")
        try:
            analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            analysis = {"termination_state": "INFRASTRUCTURE_FAILURE",
                        "exclusion_reasons": ["missing/unreadable analysis: " + str(error)]}
        analysis["exclusion_reasons"] = list(analysis.get("exclusion_reasons") or []) + checksum_errors(path.parent)
        for parent in path.parents:
            receipt = parent / "stage-result.json"
            if receipt.is_file():
                try:
                    phase = json.loads(receipt.read_text(encoding="utf-8"))
                    if phase.get("phase_excluded") is True:
                        analysis["exclusion_reasons"].append("phase excluded by realtime environment/configuration gate: " + str(receipt))
                except (OSError, ValueError) as error:
                    analysis["exclusion_reasons"].append("unreadable phase receipt: " + str(error))
            if parent.resolve() == Path(session).resolve():
                break
        row = normalize_round(context, analysis, path.parent, protocol_hash, budget)
        row["context_sha256"] = digest(path)
        row["analysis_sha256"] = digest(analysis_path) if analysis_path.is_file() else None
        records.append(row)
    duplicates = collections.Counter((row["benchmark"], row["mode"], row["round"]) for row in records)
    for row in records:
        if duplicates[(row["benchmark"], row["mode"], row["round"])] > 1:
            row["included"], row["bug_detected"], row["right_censored"], row["censor_at"] = False, None, False, None
            row["censor_reason"] = None
            row["exclusion_reasons"] += "; duplicate formal round: no replacement policy was frozen"
    return records


def summarize(records, minimum_rounds=3):
    groups = []
    for benchmark in BENCHMARKS:
        for mode in MODES:
            attempts = [row for row in records if row["benchmark"] == benchmark and row["mode"] == mode]
            accepted = [row for row in attempts if row["included"]]
            detected = [row for row in accepted if row["bug_detected"]]
            group = {"benchmark": benchmark, "mode": mode, "planned_minimum": minimum_rounds,
                     "attempted": len(attempts), "valid": len(accepted), "invalid": len(attempts) - len(accepted),
                     "detected": len(detected), "undetected": len(accepted) - len(detected),
                     "budget_exhausted": sum(row["termination_state"] == "BUDGET_EXHAUSTED" for row in accepted),
                     "detection_rate": len(detected) / float(len(accepted)) if accepted else None,
                     "status": "NOT_RUN" if not attempts else "MINIMUM_COMPLETE" if len(accepted) >= minimum_rounds else "INCOMPLETE"}
            for field, rows in (("first_error_detected_only", detected), ("total_schedules", accepted),
                                ("error_interleavings", accepted), ("internal_seconds", accepted),
                                ("external_seconds", accepted)):
                source = "first_error" if field == "first_error_detected_only" else field
                stats = mean_sd([row[source] for row in rows])
                for name, value in stats.items():
                    group[field + "_" + name] = value
            first, total, errors = PAPER[benchmark][mode]
            group.update(paper_first_error=first, paper_total_schedules=total,
                         paper_error_interleavings=errors,
                         paper_budget_censored=benchmark == "reorder_10_bad" and mode == "serial")
            groups.append(group)
    return groups


def write_csv(path, rows, fields):
    with Path(path).open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def display(mean, sd, count):
    if mean is None:
        return "NOT_RUN"
    return "%.5g +/- %s (n=%d)" % (mean, "undefined" if sd is None else "%.5g" % sd, count)


def write_report(session, output, protocol_path=None):
    session, output = Path(session).resolve(), Path(output).resolve()
    protocol_path = Path(protocol_path).resolve() if protocol_path else session / "protocol.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if protocol.get("schedule_budget") != 10000 or type(protocol.get("minimum_rounds")) is not int or protocol["minimum_rounds"] < 3:
        raise ValueError("report requires frozen schedule budget 10000 and at least three formal rounds per group")
    protocol_hash = digest(protocol_path)
    records = collect_rounds(session, protocol_hash, protocol.get("schedule_budget", 10000))
    groups = summarize(records, protocol.get("minimum_rounds", 3))
    output.mkdir(parents=True, exist_ok=False)
    fields = list(records[0]) if records else ["run_dir", "benchmark", "mode", "round", "purpose", "termination_state",
        "included", "first_error", "bug_detected", "right_censored", "censor_at", "total_schedules",
        "completed_schedules", "error_interleavings", "timeouts", "internal_seconds", "external_seconds", "exit_code",
        "exclusion_reasons"]
    write_csv(output / "per-round.csv", records, fields)
    write_csv(output / "group-statistics.csv", groups, list(groups[0]))
    comparison_fields = ["benchmark", "mode", "planned_minimum", "attempted", "valid", "detected", "detection_rate",
        "undetected", "budget_exhausted", "paper_first_error", "paper_total_schedules", "paper_error_interleavings",
        "paper_budget_censored", "first_error_detected_only_mean", "first_error_detected_only_sample_sd",
        "first_error_detected_only_n", "total_schedules_mean", "total_schedules_sample_sd",
        "error_interleavings_mean", "error_interleavings_sample_sd", "status"]
    write_csv(output / "paper-vs-ours.csv", groups, comparison_fields)
    invalid = [row for row in records if not row["included"]]
    write_csv(output / "anomalies.csv", invalid, fields)
    censored = [row for row in records if row["included"] and row["right_censored"]]
    write_csv(output / "censored.csv", censored, fields)
    summary = {"schema": "cs340-period-rq1-report-v1", "session": str(session), "protocol_sha256": protocol_hash,
               "formal_attempts": len(records), "valid_formal_rounds": sum(row["included"] for row in records),
               "invalid_attempts": len(invalid), "censored_valid_rounds": len(censored), "groups": groups,
               "minimum_complete": all(group["status"] == "MINIMUM_COMPLETE" for group in groups),
               "first_error_statistics": "conditional on valid detected runs only; ND never replaced by budget",
               "detection_rate_denominator": "valid formal runs; planned/attempted/invalid reported separately"}
    with (output / "summary.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    lines = ["# Table 2 / RQ1 formal results", "", "Only explicit formal rounds are included. Pilot, adaptation and legacy A0 are separate.", "",
        "| Benchmark | Mode | Planned / attempted / valid | Detection rate | First ordinal, detected only | Total schedules | Error schedules |",
        "| --- | --- | --- | --- | --- | --- | --- |"]
    for group in groups:
        def metric(name):
            if name == "first_error_detected_only" and group["valid"] and not group["detected"]:
                return "ND (0/%d detected; censored)" % group["valid"]
            if not group["valid"] and group["attempted"]:
                return "NO_VALID_RUNS"
            return display(group[name + "_mean"], group[name + "_sample_sd"], group[name + "_n"])
        rate = "NOT_RUN" if group["detection_rate"] is None else "%d/%d (%.1f%%)" % (group["detected"], group["valid"], 100 * group["detection_rate"])
        lines.append("| %s | %s | %d / %d / %d | %s | %s | %s | %s |" % (
            group["benchmark"], group["mode"], group["planned_minimum"], group["attempted"], group["valid"], rate,
            metric("first_error_detected_only"), metric("total_schedules"), metric("error_interleavings")))
    lines += ["", "Mean +/- sample standard deviation uses only validated formal rounds. SD is undefined for n=1.",
        "First-error means use detected runs only and must be read with detection rate and censoring; they are not unconditional means.",
        "Budget exhaustion at exactly the frozen count is a valid result. ND is not the numeric value 10000.",
        "Invalid, timed-out, unfinished or duplicate attempts remain in anomalies.csv and are not silently replaced or counted as no-bug runs.",
        "", "Paper comparison is in paper-vs-ours.csv. Source: PERIOD ICSE 2022, Table 2 (PDF page 9), https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf.",
        "The paper's reorder_10 Serial result is ND / budget 10000 / 0 errors; no comparable paper runtime is supplied.",
        "", "Limitations: at least three rounds per group are the local minimum, below the paper's ten; one workload family does not reproduce all Table 2.",
        "CPU affinity is frozen at 0-31; historical 0-7 and legacy ABI data must not be pooled. Profiling/supervision and hardware affect elapsed time.",
        "Yield-write observations are not complete worker execution-order traces. Error schedules are not distinct bugs."]
    with (output / "report.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    comparison = ["# Paper vs. Ours", "", "Triples mean first-error ordinal / total schedules / error schedules. Ours uses mean +/- sample SD; the first-error mean is conditional on detection.", "",
        "| Benchmark | Mode | Paper triple | Ours first ordinal | Ours total | Ours errors | Detected / valid | Censored |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for group in groups:
        first = "ND" if group["paper_first_error"] is None else str(group["paper_first_error"])
        total = str(group["paper_total_schedules"]) + (" (budget)" if group["paper_budget_censored"] else "")
        def observed(name):
            if not group["valid"]:
                return "NOT_RUN" if not group["attempted"] else "NO_VALID_RUNS"
            if name == "first_error_detected_only" and not group["detected"]:
                return "ND"
            return display(group[name + "_mean"], group[name + "_sample_sd"], group[name + "_n"])
        comparison.append("| %s | %s | %s / %s / %s | %s | %s | %s | %d / %d | %d |" % (
            group["benchmark"], group["mode"], first, total, group["paper_error_interleavings"],
            observed("first_error_detected_only"), observed("total_schedules"), observed("error_interleavings"),
            group["detected"], group["valid"], group["undetected"]))
    comparison += ["", "No observed results have been inserted to force agreement with the paper. Legacy A0, adaptation and pilot data are not pooled.",
        "Paper source: PERIOD ICSE 2022 Table 2, https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf."]
    with (output / "paper-vs-ours.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(comparison) + "\n")
    entries = [digest(path) + "  " + path.name for path in sorted(output.iterdir()) if path.is_file()]
    with (output / "SHA256SUMS").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(entries) + "\n")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="new directory; existing output is never overwritten")
    parser.add_argument("--protocol", type=Path)
    args = parser.parse_args(argv)
    summary = write_report(args.session, args.output, args.protocol)
    print("Report: " + str(args.output.resolve()))
    print("Valid formal rounds: %d; invalid attempts: %d" % (summary["valid_formal_rounds"], summary["invalid_attempts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
