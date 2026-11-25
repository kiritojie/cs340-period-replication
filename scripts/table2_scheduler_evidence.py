#!/usr/bin/env python3
"""Validate preserved PERIOD logs; legacy pilot and frozen formal profiles."""
from __future__ import print_function

import argparse
import ast
import hashlib
import importlib.util
import itertools
import json
import re
import sys
import traceback
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TEST = re.compile(r"^\s*test (\d+)(?: for prefix .*?)?:\s*(\[\[.*\]\])\s*$")
ERROR_FILE = re.compile(r"^\d{6}_(\d{7})_assertion-failed$")
EXPECTED_ERROR_ORDINALS = [6, 7, 19, 20, 24, 25]
KPS = [2, 2, 1]
FORMAL_BENCHMARKS = {"reorder_3_bad": 3, "reorder_4_bad": 4,
                     "reorder_5_bad": 5, "reorder_10_bad": 10}
FORMAL_SCHEMA = "cs340-period-formal-evidence-v1"
FORMAL_TEST = re.compile(r"^\s*test (\d+)(?: for prefix (\[.*\]))?:\s*(\[\[.*\]\])\s*$")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def yield_pattern(schedule):
    # Mirrors pinned bp_sched.py:get_yield_pattern, with driver's zero-padding.
    result = [[0] * count for count in KPS]
    indices = [0] * len(KPS)
    for period in schedule:
        for thread in period:
            indices[thread] += 1
        for thread in range(len(KPS)):
            if indices[thread] < len(result[thread]):
                result[thread][indices[thread]] += 1
    for row in result:
        row.extend([0] * (2 - len(row)))
    return result


def valid_schedule(value, mode):
    require(isinstance(value, list) and value, "schedule is not a nonempty list")
    totals = [0, 0, 0]
    for period in value:
        require(isinstance(period, list) and period, "empty or invalid period")
        for thread in period:
            require(type(thread) is int and 0 <= thread < 3, "invalid thread ID")
            totals[thread] += 1
    require(totals == KPS, "schedule does not contain exactly [2,2,1] key points")
    if mode == "serial":
        require(3 <= len(value) <= 5, "serial period count outside depth-3 window")
        require(all(len(set(period)) == 1 for period in value), "serial period mixes threads")
        require(all(left[0] != right[0] for left, right in zip(value, value[1:])),
                "serial adjacent periods repeat a thread")
    else:
        require(2 <= len(value) <= 4, "parallel period count outside depth-3 window")
        require(all(len(set(period)) == 1 for period in value[:-1]),
                "parallel non-final period mixes threads")
        require(all(left[0] != right[0] for left, right in zip(value[:-2], value[1:-1])),
                "parallel adjacent controlled periods repeat a thread")
        require(value[-2][0] not in value[-1], "parallel final period repeats the preceding thread")


def one_value(matches, label):
    require(len(matches) == 1, "missing or repeated " + label)
    return int(matches[0])


def actual_yield_trace(run, schedules):
    path = run / "actual-yield.jsonl"
    require(path.is_file(), "missing actual memmove_pattern_list observation trace")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    starts = [record for record in records if record.get("event") == "trace_start"]
    summaries = [record for record in records if record.get("event") == "trace_summary"]
    writes = [record for record in records if record.get("event") == "yield_write"]
    require(len(starts) == 1 and len(summaries) == 1, "incomplete or duplicated observation trace")
    require(starts[0].get("schema") == "cs340-period-yield-trace-v1", "unsupported observation trace schema")
    require(isinstance(starts[0].get("expected_source"), str) and bool(starts[0]["expected_source"]),
            "observation trace lacks its official source namespace")
    require(re.match(r"^[0-9a-f]{64}$", starts[0].get("expected_source_sha256", "")) is not None and
            re.match(r"^[0-9a-f]{64}$", starts[0].get("driver_sha256", "")) is not None,
            "observation trace lacks source/entry-driver identity hashes")
    require(records[0].get("event") == "trace_start" and records[-1].get("event") == "trace_summary",
            "observation trace has invalid event order")
    require(all(record.get("event") in ("trace_start", "yield_write", "trace_summary") for record in records),
            "observation trace records an error or unsupported event")
    require(summaries[0].get("driver_exit_code") == 0 and summaries[0].get("yield_writes") == len(writes),
            "observer/driver did not complete successfully")
    require(summaries[0].get("pending_writes") == 0 and summaries[0].get("observation_error") is None,
            "observer reports unfinished writes or an observation failure")
    require(len(writes) == len(schedules), "actual yield-write count differs from executed schedules")
    patterns = []
    for ordinal, (record, schedule) in enumerate(zip(writes, schedules), 1):
        require(record.get("ordinal") == ordinal and record.get("schedule") == schedule,
                "actual write ordinal/schedule differs from stdout")
        require(record.get("period") == len(schedule), "actual write period differs from printed schedule")
        require(record.get("source_file") == starts[0].get("expected_source"),
                "actual write came from a different driver source namespace")
        pattern = record.get("yield_pattern")
        require(isinstance(pattern, list) and len(pattern) == 3 and
                all(isinstance(row, list) and len(row) == 2 and
                    all(type(value) is int and 0 <= value <= 65535 for value in row) for row in pattern),
                "actual yield matrix is not a padded uint16 3x2 matrix")
        require(pattern == yield_pattern(schedule), "actual yield matrix differs from official conversion")
        patterns.append(pattern)
    return {"actual_yield_patterns": patterns,
            "trace_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "observed_source": starts[0]["expected_source"],
            "observed_source_sha256": starts[0]["expected_source_sha256"],
            "observation": "Actual padded PatternList arguments observed at every call to memmove_pattern_list; "
                           "read-only Python profiling adds timing overhead."}


def analyze(run_path, mode, baseline="historical"):
    require(baseline in ("historical", "abi-corrected"), "unsupported baseline kind")
    run = Path(run_path).resolve()
    require((run / "exit-code.txt").read_text().strip() == "0", "driver/outer timeout exit code is not 0")
    raw = (run / "stdout.log").read_bytes()
    text = ANSI.sub("", raw.decode("utf-8", errors="strict"))
    stderr = (run / "stderr.log").read_text(encoding="utf-8")
    require(not re.search(r"Unknown Exception|Traceback|\(retest\)", text + stderr),
            "exception or retest present; manual investigation is required")
    require(text.count("End Testing!") == 1, "incomplete/concatenated run")
    require(one_value(re.findall(r"^ThreadNum:\s*(\d+)\s*$", text, re.M), "ThreadNum") == 3,
            "worker thread count changed")
    kp_lines = re.findall(r"^kpNumArray:\s*([0-9 ]+)\s*$", text, re.M)
    require(len(kp_lines) == 1 and [int(item) for item in kp_lines[0].split()] == KPS,
            "dry-run key-point counts changed")
    schedules, errors = [], []
    for line in text.splitlines():
        match = TEST.match(line)
        if match:
            ordinal = int(match.group(1))
            require(ordinal == len(schedules) + 1, "schedule ordinal is not contiguous")
            schedule = ast.literal_eval(match.group(2))
            valid_schedule(schedule, mode)
            schedules.append(schedule)
        if re.match(r"^\s*\[Error Found\]:", line):
            require(bool(schedules), "error marker before any schedule")
            errors.append(len(schedules))
    total = one_value(re.findall(r"^Round\s+\d+\s+(\d+)\s*$", text, re.M), "total Round")
    error_count = one_value(re.findall(r"^Total Error Interleavings:\s*(\d+)\s*$", text, re.M), "error count")
    timeouts = one_value(re.findall(r"^Total Timeouts Interleavings:\s*(\d+)\s*$", text, re.M), "timeout count")
    require(total == len(schedules) and 0 < total <= 10000, "executed schedules/footer/budget disagree")
    require(len(set(json.dumps(value) for value in schedules)) == total, "duplicate schedules")
    require(error_count == len(errors) == len(set(errors)), "error markers/footer disagree")
    require(timeouts == 0, "target timeouts prevent pilot acceptance")
    artifacts = list((run / "work").glob("out_reorder_3_bad_*"))
    require(len(artifacts) == 1 and artifacts[0].is_dir(), "need exactly one untouched raw output directory")
    require(all((artifacts[0] / dirname).is_dir() for dirname in ("Errors", "Timeouts", "DiffResult")),
            "raw output is missing an Errors/Timeouts/DiffResult directory")
    saved = {}
    for path in sorted((artifacts[0] / "Errors").glob("*")):
        require(path.is_file(), "unexpected directory in Errors")
        match = ERROR_FILE.match(path.name)
        require(match is not None, "unexpected error type/name: " + path.name)
        ordinal = int(match.group(1))
        require(ordinal in errors and ordinal not in saved, "error file ordinal missing or duplicated")
        record = path.read_text(encoding="utf-8")
        lines = record.splitlines()
        require(bool(lines), "empty error file")
        pattern = ast.literal_eval(lines[0])
        require(pattern == yield_pattern(schedules[ordinal - 1]), "saved yield disagrees with schedule")
        require("assert" in "\n".join(lines[1:]).lower(), "missing assertion evidence")
        saved[ordinal] = pattern
    require(sorted(saved) == errors, "full raw error records were not preserved")
    for dirname in ("Timeouts", "DiffResult"):
        require(not any((artifacts[0] / dirname).glob("*")), dirname + " is not empty")
    if mode in ("reference", "parallel") and baseline == "historical":
        require(total == 27 and errors == EXPECTED_ERROR_ORDINALS,
                "Parallel regression differs from archived 27/6/first6 path")
    elif mode == "serial":
        flattened = [tuple(thread for period in value for thread in period) for value in schedules]
        expected = set(itertools.permutations((0, 0, 1, 1, 2)))
        require(len(flattened) == len(set(flattened)) and set(flattened) == expected,
                "Serial fixed [2,2,1] enumeration loses/repeats legal event orders")
        require(error_count > 0, "Serial did not detect the benchmark assertion")
    result = {"mode": mode, "total_schedules": total, "first_error": errors[0] if errors else None,
            "error_ordinals": errors, "error_interleavings": error_count, "timeouts": timeouts,
            "stdout_sha256": hashlib.sha256(raw).hexdigest(), "schedules": schedules,
            "derived_yield_patterns": [yield_pattern(value) for value in schedules],
            "actual_saved_error_yields": saved}
    result.update(actual_yield_trace(run, schedules))
    result["baseline_kind"] = baseline
    if mode in ("reference", "parallel"):
        result["historical_comparison"] = {
            "reference_only": {"first_error": 6, "total_schedules": 27,
                               "error_interleavings": 6, "error_ordinals": EXPECTED_ERROR_ORDINALS},
            "matches": total == 27 and errors == EXPECTED_ERROR_ORDINALS,
            "note": "A corrected ABI result is a separate measurement; historical agreement is not a filtering rule."}
    if baseline == "abi-corrected":
        metadata = json.loads((run / "adapter-metadata.json").read_text(encoding="utf-8"))
        require(metadata.get("status") == "COMPLETED" and metadata.get("exit_code") == 0,
                "ABI-corrected driver did not complete uncensored exploration")
        require(metadata.get("scheduler") == ("serial" if mode == "serial" else "parallel") and
                metadata.get("depth") == 3 and metadata.get("target_timeout_seconds") == 5,
                "ABI-corrected driver configuration differs from pilot")
        require(metadata.get("abi_proof", {}).get("status") == "PASS",
                "missing validated ABI proof in driver metadata")
        layout = metadata.get("abi_layout")
        layer_hash = metadata.get("abi_layer_sha256")
        require(isinstance(layout, dict) and isinstance(layer_hash, str) and
                re.match(r"^[0-9a-f]{64}$", layer_hash), "missing concrete common ABI layer identity")
        spec = importlib.util.spec_from_file_location("period_evidence_memory_abi", Path(__file__).with_name("period_shared_memory.py"))
        memory_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(memory_module)
        concrete_abi = memory_module.MemoryABI.from_layout(layout)
        require(layout == concrete_abi.layout and metadata["abi_proof"].get("abi_profile") == "runtime-dwarf"
                and metadata["abi_proof"].get("layout") == concrete_abi.layout,
                "driver metadata ABI is not bound to its measured runtime proof")
        if mode == "reference":
            require(metadata.get("role") == "abi-only-parallel-reference" and metadata.get("budget") == 10000,
                    "corrected reference must be labeled separately from unmodified historical driver")
        result["abi_layout"] = layout
        result["abi_layer_sha256"] = layer_hash
        result["driver_role"] = metadata.get("role", "unified-comparison")
    if mode != "reference":
        metadata = json.loads((run / "adapter-metadata.json").read_text(encoding="utf-8"))
        require(metadata.get("status") == "COMPLETED" and metadata.get("exit_code") == 0,
                "adapter did not report complete, uncensored exploration")
        require(metadata.get("scheduler") == mode and metadata.get("depth") == 3 and
                metadata.get("target_timeout_seconds") == 5, "adapter configuration differs from pilot")
        accounting = metadata.get("accounting", {})
        require(accounting.get("limit") == 10000 and accounting.get("executed") == total and
                accounting.get("completed") == total and accounting.get("in_flight") == 0 and
                accounting.get("retests") == 0 and accounting.get("retests_completed") == 0 and
                accounting.get("physical_launches") == total and accounting.get("budget_hit") is False,
                "adapter accounting does not reconcile with actual writes and stdout")
        require(metadata.get("upstream_statistics", {}).get("rounds") == total,
                "adapter's final rounds differs from executed schedules")
        result["adapter_accounting"] = accounting
    return result


def _formal_object(value):
    if isinstance(value, dict):
        return value
    return json.loads(Path(value).read_text(encoding="utf-8"))


def _formal_protocol(value):
    protocol = _formal_object(value) if value is not None else {}
    depth = protocol.get("bug_depth", protocol.get("depth", 3))
    budget = protocol.get("schedule_budget", protocol.get("budget", 10000))
    target_timeout = protocol.get("target_timeout_seconds", 5)
    require(type(depth) is int and depth == 3, "formal CS.reorder depth must be 3")
    require(type(budget) is int and budget == 10000, "formal schedule budget must be 10000")
    require(type(target_timeout) in (int, float) and target_timeout > 0,
            "formal target timeout is invalid")
    return dict(protocol, bug_depth=depth, schedule_budget=budget,
                target_timeout_seconds=target_timeout)


def _formal_profile(value):
    profile = _formal_object(value)
    benchmark = profile.get("benchmark")
    require(benchmark in FORMAL_BENCHMARKS, "unsupported formal benchmark")
    require(profile.get("threads") == FORMAL_BENCHMARKS[benchmark],
            "frozen worker-thread identity differs from benchmark")
    for role in ("binary", "config"):
        identity = profile.get(role, {})
        require(isinstance(identity, dict) and re.match(r"^[0-9a-f]{64}$", identity.get("sha256", "")),
                "missing frozen " + role + " identity")
    require(profile.get("source_commit") == "b6f72a7b06d01ffa7114b640312873ec2578a5ea",
            "formal source commit is not pinned")
    return profile


def formal_yield_pattern(schedule, kps, width):
    """Independent dynamic conversion; no factorial event-order enumeration."""
    require(type(width) is int and width >= max(kps), "invalid observed matrix width")
    rows = [[] for _ in kps]
    previous = [0] * len(kps)
    for period, events in enumerate(schedule):
        for thread in events:
            rows[thread].append(period - previous[thread])
            previous[thread] = period
    for row in rows:
        row.extend([0] * (width - len(row)))
    return rows


def valid_formal_schedule(value, mode, kps, depth=3, prefix=None):
    n = len(kps)
    require(mode in ("reference", "parallel", "serial"), "unsupported scheduler mode")
    require(isinstance(value, list) and value, "schedule is not a nonempty list")
    totals = [0] * n
    for period in value:
        require(isinstance(period, list) and period, "empty or invalid period")
        for thread in period:
            require(type(thread) is int and 0 <= thread < n, "invalid thread ID")
            totals[thread] += 1
    require(totals == kps, "schedule KP counts differ from the observed fixed runtime slice")
    if mode == "serial":
        require(n <= len(value) <= n + depth - 1, "serial period count outside depth window")
        require(all(len(set(period)) == 1 for period in value), "serial period mixes threads")
        require(all(a[0] != b[0] for a, b in zip(value, value[1:])),
                "serial adjacent periods repeat a thread")
    else:
        require(2 <= len(value) <= depth + 1, "parallel period count outside depth window")
        require(all(len(set(period)) == 1 for period in value[:-1]),
                "parallel controlled period mixes threads")
        require(all(a[0] != b[0] for a, b in zip(value[:-2], value[1:-1])),
                "parallel adjacent controlled periods repeat a thread")
        require(value[-2][0] not in value[-1], "parallel final period repeats preceding thread")
        controlled = {thread for period in value[:-1] for thread in period}
        require(len(controlled.intersection(value[-1])) <= 1,
                "parallel final period resumes more than one controlled thread")
    if prefix:
        require(isinstance(prefix, list) and all(isinstance(p, list) and p for p in prefix),
                "invalid observed prefix")
        require(len(value) >= len(prefix) and value[:len(prefix) - 1] == prefix[:-1]
                and value[len(prefix) - 1][:len(prefix[-1])] == prefix[-1],
                "schedule violates its observed fixed prefix")


def _formal_metadata(metadata, profile, protocol, mode):
    require(metadata.get("scheduler") == ("serial" if mode == "serial" else "parallel"),
            "metadata scheduler differs from requested mode")
    require(metadata.get("depth") == protocol["bug_depth"] and
            metadata.get("budget") == protocol["schedule_budget"] and
            metadata.get("target_timeout_seconds") == protocol["target_timeout_seconds"],
            "driver configuration differs from frozen protocol")
    require(metadata.get("exit_code") == 0 and not metadata.get("cleanup_errors"),
            "driver did not exit cleanly")
    proof = metadata.get("abi_proof", {})
    require(metadata.get("abi_validation") == "PASS" and proof.get("status") == "PASS"
            and proof.get("abi_profile") == "runtime-dwarf", "missing measured runtime ABI proof")
    require(proof.get("binary_sha256") == profile["binary"]["sha256"],
            "runtime proof binary differs from frozen benchmark")
    require(proof.get("identities", {}).get("config", {}).get("sha256") == profile["config"]["sha256"],
            "runtime proof configuration differs from frozen benchmark")
    require(proof.get("source_commit") == profile["source_commit"], "runtime source commit differs")
    spec = importlib.util.spec_from_file_location("period_formal_memory_abi", Path(__file__).with_name("period_shared_memory.py"))
    memory_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(memory_module)
    layout = memory_module.MemoryABI.from_layout(metadata.get("abi_layout")).layout
    require(layout == proof.get("layout"), "metadata layout differs from measured ABI")
    layer_hash = metadata.get("abi_layer_sha256")
    require(isinstance(layer_hash, str) and re.match(r"^[0-9a-f]{64}$", layer_hash),
            "ABI layer identity missing")
    require(layer_hash == proof.get("abi_layer_sha256"), "ABI layer proof identity differs")
    require(metadata.get("permission_proof", {}).get("status") == "PASS",
            "missing successful permission acceptance")
    if mode == "reference":
        require(metadata.get("role") == "abi-only-parallel-reference", "invalid A1 reference role")
    return layout, layer_hash


def _formal_classification(exit_code, metadata, context, observed_timeouts):
    if context.get("outer_timeout") or exit_code == 124:
        return "ROUND_TIMEOUT"
    if context.get("infrastructure_failure") or metadata.get("cleanup_errors"):
        return "INFRASTRUCTURE_FAILURE"
    if observed_timeouts:
        return "TARGET_TIMEOUT"
    if metadata.get("status") in ("FAILED", "INTERRUPTED"):
        if metadata.get("abi_validation") != "PASS" or metadata.get("permission_proof", {}).get("status") != "PASS":
            return "INFRASTRUCTURE_FAILURE"
        return "DRIVER_EXCEPTION"
    if exit_code != 0 or not metadata:
        return "INFRASTRUCTURE_FAILURE"
    return metadata.get("status") if metadata.get("status") in ("COMPLETED", "BUDGET_EXHAUSTED") else "DRIVER_EXCEPTION"


def analyze_formal(run_path, mode, benchmark_manifest, protocol=None, runtime_profile=None):
    """Audit one preserved run. Failure records remain visible and excluded.

    No paper value is an acceptance predicate. A valid 10000-schedule budget
    termination is included; no detection is represented by null plus a censor
    record, never by an invented first-error ordinal.
    """
    run = Path(run_path).resolve()
    result = {"schema": FORMAL_SCHEMA, "mode": mode, "status": "BLOCKED", "validation": "FAIL",
              "included": False, "valid_research_result": False,
              "termination_state": "INFRASTRUCTURE_FAILURE", "first_error": None,
              "bug_detected": None, "first_error_censored": False,
              "censoring": {"right_censored": False, "censor_at": None, "reason": "INVALID_RUN"},
              "exclusion_reasons": [], "run_directory": str(run)}
    metadata, context, exit_code = {}, {}, None
    try:
        if (run / "adapter-metadata.json").is_file():
            metadata = _formal_object(run / "adapter-metadata.json")
        if (run / "run-context.json").is_file():
            context = _formal_object(run / "run-context.json")
        exit_code = int((run / "exit-code.txt").read_text().strip())
        result["exit_code"] = exit_code
        accounting = metadata.get("accounting", {})
        for output, field in (("total_schedules", "executed"), ("executed_schedules", "executed"),
                              ("completed_schedules", "completed"), ("in_flight", "in_flight"),
                              ("retests", "retests"), ("physical_launches", "physical_launches")):
            result[output] = accounting.get(field)
        raw = (run / "stdout.log").read_bytes()
        text = ANSI.sub("", raw.decode("utf-8", errors="strict"))
        stderr = (run / "stderr.log").read_text(encoding="utf-8")
        timeout_values = re.findall(r"^Total Timeouts Interleavings:\s*(\d+)\s*$", text, re.M)
        observed_timeouts = int(timeout_values[-1]) if timeout_values else int(bool(re.search(r"\[Timeout ", text)))
        result["timeouts"] = observed_timeouts
        result["termination_state"] = _formal_classification(exit_code, metadata, context, observed_timeouts)
        profile = _formal_profile(benchmark_manifest)
        if not isinstance(benchmark_manifest, dict):
            result["benchmark_manifest_sha256"] = hashlib.sha256(Path(benchmark_manifest).read_bytes()).hexdigest()
        protocol_hash = (hashlib.sha256(Path(protocol).read_bytes()).hexdigest()
                         if protocol is not None and not isinstance(protocol, dict) else None)
        protocol = _formal_protocol(protocol)
        benchmark, n = profile["benchmark"], profile["threads"]
        result.update(benchmark=benchmark, threads=n, budget=protocol["schedule_budget"], depth=protocol["bug_depth"],
                      binary_sha256=profile["binary"]["sha256"], config_sha256=profile["config"]["sha256"],
                      source_commit=profile["source_commit"])
        if context:
            require(context.get("benchmark") == benchmark and context.get("mode") == mode,
                    "run context differs from benchmark/mode")
            if protocol_hash is not None:
                require(context.get("protocol_sha256") == protocol_hash,
                        "run context belongs to a different frozen protocol")
            result["phase"] = context.get("phase")
            result["round"] = context.get("round")
            result["protocol_sha256"] = context.get("protocol_sha256")
            if context.get("phase") == "formal":
                require(runtime_profile is not None, "formal statistics require the accepted adaptation runtime profile")
        for role, filename in (("binary", benchmark), ("config", "ConConfig." + benchmark)):
            path = run / "work" / filename
            require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == profile[role]["sha256"],
                    "preserved " + role + " does not match frozen identity")
        require(one_value(re.findall(r"^ThreadNum:\s*(\d+)\s*$", text, re.M), "ThreadNum") == n,
                "observed worker thread count differs from benchmark")
        kp_lines = re.findall(r"^kpNumArray:\s*([0-9 ]+)\s*$", text, re.M)
        require(len(kp_lines) == 1, "missing or repeated runtime KPS")
        kps = [int(value) for value in kp_lines[0].split()]
        require(len(kps) == n and all(value > 0 for value in kps), "runtime KPS has unexpected thread dimensions")
        width = one_value(re.findall(r"^MaxKpNum:\s*(\d+)\s*$", text, re.M), "MaxKpNum")
        require(width >= max(kps), "runtime matrix width does not contain KPS")
        if profile.get("kps") is not None:
            require(kps == profile["kps"], "runtime KPS differs from frozen adaptation observation")
        if profile.get("max_kp_num") is not None:
            require(width == profile["max_kp_num"], "runtime matrix width changed")
        if runtime_profile is not None:
            observed_profile = _formal_object(runtime_profile)
            require(observed_profile.get("benchmark") == benchmark and observed_profile.get("threads") == n
                    and observed_profile.get("kps") == kps and observed_profile.get("matrix_width") == width,
                    "runtime dimensions differ from accepted adaptation profile")
            require(observed_profile.get("binary_sha256") == profile["binary"]["sha256"] and
                    observed_profile.get("config_sha256") == profile["config"]["sha256"],
                    "accepted runtime profile belongs to different frozen inputs")
        result.update(kps=kps, matrix_shape=[n, width], matrix_width=width)
        schedules, errors, prefixes = [], [], []
        for line in text.splitlines():
            match = FORMAL_TEST.match(line)
            if match:
                ordinal = int(match.group(1))
                require(ordinal == len(schedules) + 1, "schedule ordinal is not contiguous")
                schedule = ast.literal_eval(match.group(3))
                prefix = ast.literal_eval(match.group(2)) if match.group(2) else []
                valid_formal_schedule(schedule, mode, kps, protocol["bug_depth"], prefix)
                schedules.append(schedule)
                prefixes.append(prefix)
            if re.match(r"^\s*\[Error Found\]:", line):
                require(bool(schedules), "error marker before schedule")
                errors.append(len(schedules))
        result.update(printed_schedule_count=len(schedules), schedules=schedules, error_ordinals=errors,
                      observed_first_error=errors[0] if errors else None, observed_bug_detected=bool(errors),
                      prefix_jobs=sum(bool(prefix) for prefix in prefixes))
        require(len({json.dumps(value) for value in schedules}) == len(schedules), "duplicate logical schedules")
        records = [json.loads(line) for line in (run / "actual-yield.jsonl").read_text().splitlines() if line.strip()]
        starts = [item for item in records if item.get("event") == "trace_start"]
        summaries = [item for item in records if item.get("event") == "trace_summary"]
        writes = [item for item in records if item.get("event") == "yield_write"]
        result["actual_yield_writes"] = len(writes)
        require(len(starts) == 1 and starts[0].get("schema") == "cs340-period-yield-trace-v1",
                "missing actual trace identity header")
        require(records[0].get("event") == "trace_start" and
                all(item.get("event") in ("trace_start", "yield_write", "trace_summary") for item in records),
                "trace has invalid event ordering/type")
        require(starts[0].get("expected_source_sha256") == metadata.get("original_source_sha256"),
                "actual trace source identity differs from driver metadata")
        role = "reference" if mode == "reference" else "driver"
        identity = metadata.get("abi_proof", {}).get("identities", {}).get(role, {})
        require(starts[0].get("driver_sha256") == identity.get("sha256") and
                re.match(r"^[0-9a-f]{64}$", starts[0].get("driver_sha256", "")),
                "trace entry-driver identity differs from ABI proof")
        require(len(writes) == len(schedules), "actual yield count differs from printed schedules")
        patterns = []
        for ordinal, (item, schedule) in enumerate(zip(writes, schedules), 1):
            require(item.get("ordinal") == ordinal and item.get("schedule") == schedule and
                    item.get("period") == len(schedule), "trace schedule/ordinal/period differs from stdout")
            require(item.get("source_file") == starts[0].get("expected_source"), "trace source namespace changed")
            pattern = item.get("yield_pattern")
            require(isinstance(pattern, list) and len(pattern) == n and
                    all(isinstance(row, list) and len(row) == width and
                        all(type(value) is int and 0 <= value <= 65535 for value in row) for row in pattern),
                    "actual yield matrix differs from observed runtime dimensions")
            require(pattern == formal_yield_pattern(schedule, kps, width), "actual yield matrix conversion mismatch")
            patterns.append(pattern)
        result.update(actual_yield_patterns=patterns, observed_source=starts[0].get("expected_source"),
                      observed_source_sha256=starts[0].get("expected_source_sha256"),
                      stdout_sha256=hashlib.sha256(raw).hexdigest(),
                      trace_sha256=hashlib.sha256((run / "actual-yield.jsonl").read_bytes()).hexdigest())
        require(result["termination_state"] in ("COMPLETED", "BUDGET_EXHAUSTED"),
                "run terminated as " + result["termination_state"])
        require(not re.search(r"Unknown Exception|Traceback|\(retest\)", text + stderr),
                "driver exception or unvalidated dynamic-KP retest; manual review required")
        require(text.count("End Testing!") == 1, "normal result footer missing or repeated")
        require(len(summaries) == 1 and records[-1].get("event") == "trace_summary" and
                summaries[0].get("driver_exit_code") == 0 and summaries[0].get("pending_writes") == 0 and
                summaries[0].get("observation_error") is None and summaries[0].get("yield_writes") == len(writes),
                "incomplete trace or unfinished/failed write")
        total = one_value(re.findall(r"^Round\s+\d+\s+(\d+)\s*$", text, re.M), "Round footer")
        error_count = one_value(re.findall(r"^Total Error Interleavings:\s*(\d+)\s*$", text, re.M), "error footer")
        timeouts = one_value(timeout_values, "timeout footer")
        require(timeouts == 0, "target timeout excludes this round from core statistics")
        require(0 < total == len(schedules) <= protocol["schedule_budget"], "schedule/footer/budget mismatch")
        require(error_count == len(errors) == len(set(errors)), "error/footer mismatch")
        if mode == "reference":
            require(metadata.get("status") == "COMPLETED", "A1 reference did not complete")
            counts = {"executed": total, "completed": total, "in_flight": 0, "retests": 0,
                      "retests_completed": 0, "physical_launches": total, "budget_hit": False}
        else:
            counts = accounting
            require(all(type(counts.get(key)) is int for key in
                        ("limit", "executed", "completed", "in_flight", "retests", "retests_completed",
                         "physical_launches", "generated")), "logical accounting counters must be integers")
            require(counts.get("limit") == protocol["schedule_budget"] and counts.get("executed") == total and
                    counts.get("completed") == total and counts.get("in_flight") == 0 and
                    counts.get("retests") == 0 and counts.get("retests_completed") == 0 and
                    counts.get("physical_launches") == total,
                    "executed/completed/physical/retest counts do not reconcile")
            require(type(counts.get("generated")) is int and counts["generated"] >= total,
                    "generated candidates cannot be fewer than actual logical launches")
        require(metadata.get("upstream_statistics", {}).get("rounds") == total, "driver rounds mismatch")
        require(metadata.get("upstream_statistics", {}).get("total_errors_interleavings") == [error_count]
                and metadata.get("upstream_statistics", {}).get("total_timeouts_interleavings") == [0],
                "driver error/timeout statistics differ from preserved raw footer")
        if metadata.get("status") == "BUDGET_EXHAUSTED":
            require(total == protocol["schedule_budget"] and counts.get("budget_hit") is True,
                    "budget termination was not exactly the completed execution boundary")
            require(counts["generated"] > total, "budget-hit candidate is not accounted before rejected launch")
        else:
            require(counts.get("budget_hit") is False, "completed status conflicts with budget flag")
        layout, layer_hash = _formal_metadata(metadata, profile, protocol, mode)
        artifacts = list((run / "work").glob("out_" + benchmark + "_*"))
        require(len(artifacts) == 1 and artifacts[0].is_dir(), "need exactly one raw output directory")
        require(all((artifacts[0] / name).is_dir() for name in ("Errors", "Timeouts", "DiffResult")),
                "raw output directories missing")
        saved = {}
        for path in sorted((artifacts[0] / "Errors").glob("*")):
            match = ERROR_FILE.match(path.name)
            require(path.is_file() and match is not None, "unexpected raw error artifact")
            ordinal = int(match.group(1))
            require(ordinal in errors and ordinal not in saved, "saved error ordinal missing/duplicated")
            lines = path.read_text(encoding="utf-8").splitlines()
            require(lines and ast.literal_eval(lines[0]) == patterns[ordinal - 1], "saved error yield mismatch")
            require("assert" in "\n".join(lines[1:]).lower(), "saved error has no assertion")
            saved[ordinal] = patterns[ordinal - 1]
        require(sorted(saved) == errors, "raw error records not complete")
        require(not any((artifacts[0] / "Timeouts").iterdir()) and not any((artifacts[0] / "DiffResult").iterdir()),
                "unvalidated timeout/different-output artifacts present")
        launches = metadata.get("process_launches_including_preparation", [])
        target_launches = [item for item in launches if item.get("executed_argv") and
                           Path(item["executed_argv"][0]).name == benchmark]
        require(len(target_launches) == total + 2,
                "target-launch ledger must equal two preparations plus logical launches; unexpected extra run")
        internal = re.findall(r"^Time\s+\S+\s+(\d+):(\d+):([0-9.]+)\s*$", text, re.M)
        require(len(internal) == 1, "missing internal total time")
        hours, minutes, seconds = internal[0]
        wall = re.findall(r"^external_wall_ns=(\d+)\s*$", (run / "walltime.txt").read_text(), re.M)
        require(len(wall) == 1, "missing external wall interval")
        detected = bool(errors)
        result.update(status="PASS", validation="PASS", included=True, valid_research_result=True,
                      termination_state=metadata["status"], total_schedules=total, executed_schedules=total,
                      completed_schedules=counts["completed"], in_flight=0, retests=counts["retests"],
                      physical_launches=counts["physical_launches"], preparation_launches=len(target_launches) - total,
                      error_interleavings=error_count, timeouts=0, first_error=errors[0] if errors else None,
                      bug_detected=detected, first_error_censored=not detected,
                      censoring={"right_censored": not detected, "censor_at": total if not detected else None,
                                 "reason": None if detected else ("BUDGET_REACHED" if metadata["status"] == "BUDGET_EXHAUSTED"
                                                                  else "SEARCH_SPACE_COMPLETED_WITHOUT_BUG")},
                      internal_seconds=int(hours) * 3600 + int(minutes) * 60 + float(seconds),
                      external_seconds=int(wall[0]) / 1000000000.0,
                      actual_saved_error_yields=saved, abi_layout=layout, abi_layer_sha256=layer_hash,
                      accounting=counts)
    except Exception as error:
        result["exclusion_reasons"].append(type(error).__name__ + ": " + str(error))
        result["exception_traceback"] = traceback.format_exc()
        if result["termination_state"] in ("COMPLETED", "BUDGET_EXHAUSTED"):
            result["termination_state"] = "INFRASTRUCTURE_FAILURE"
    return result


def compare_formal(reference_dir, candidate_dir, benchmark_manifest, protocol=None, runtime_profile=None):
    reference = analyze_formal(reference_dir, "reference", benchmark_manifest, protocol, runtime_profile)
    candidate = analyze_formal(candidate_dir, "parallel", benchmark_manifest, protocol, runtime_profile)
    result = {"schema": FORMAL_SCHEMA, "status": "BLOCKED", "reference": reference, "candidate": candidate}
    try:
        require(reference["included"] and candidate["included"], "A1/B contains an invalid run")
        for key in ("threads", "kps", "matrix_shape", "schedules", "actual_yield_patterns", "error_ordinals",
                    "total_schedules", "error_interleavings", "timeouts", "observed_source_sha256",
                    "abi_layout", "abi_layer_sha256"):
            require(reference[key] == candidate[key], "A1/B mismatch in " + key)
        result["status"] = "PASS"
    except Exception as error:
        result["reason"] = str(error)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action")
    comparison = sub.add_parser("compare")
    comparison.add_argument("--reference-dir", required=True)
    comparison.add_argument("--candidate-dir", required=True)
    comparison.add_argument("--output", required=True)
    comparison.add_argument("--baseline", choices=("historical", "abi-corrected"), default="historical")
    inspection = sub.add_parser("analyze")
    inspection.add_argument("--run-dir", required=True)
    inspection.add_argument("--mode", choices=("reference", "parallel", "serial"), required=True)
    inspection.add_argument("--output", required=True)
    inspection.add_argument("--baseline", choices=("historical", "abi-corrected"), default="historical")
    formal_inspection = sub.add_parser("formal-analyze")
    formal_inspection.add_argument("--run-dir", required=True)
    formal_inspection.add_argument("--mode", choices=("reference", "parallel", "serial"), required=True)
    formal_comparison = sub.add_parser("formal-compare")
    formal_comparison.add_argument("--reference-dir", required=True)
    formal_comparison.add_argument("--candidate-dir", required=True)
    for command in (formal_inspection, formal_comparison):
        command.add_argument("--benchmark-manifest", required=True)
        command.add_argument("--protocol", required=True)
        command.add_argument("--runtime-profile")
        command.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if not args.action:
        parser.error("choose compare or analyze")
    destination = Path(args.output)
    if destination.exists():
        parser.error("refusing to overwrite " + str(destination))
    result = {"schema": "cs340-period-pilot-evidence-v1", "status": "BLOCKED"}
    try:
        if args.action == "formal-analyze":
            result = analyze_formal(args.run_dir, args.mode, args.benchmark_manifest, args.protocol, args.runtime_profile)
        elif args.action == "formal-compare":
            result = compare_formal(args.reference_dir, args.candidate_dir, args.benchmark_manifest, args.protocol, args.runtime_profile)
        elif args.action == "compare":
            reference = analyze(args.reference_dir, "reference", args.baseline)
            candidate = analyze(args.candidate_dir, "parallel", args.baseline)
            for field in ("schedules", "derived_yield_patterns", "actual_yield_patterns", "observed_source",
                          "observed_source_sha256", "error_ordinals", "actual_saved_error_yields",
                          "total_schedules", "error_interleavings", "timeouts"):
                require(reference[field] == candidate[field], "A/B mismatch in " + field)
            if args.baseline == "abi-corrected":
                for field in ("abi_layout", "abi_layer_sha256"):
                    require(reference[field] == candidate[field], "corrected A1/B common ABI mismatch in " + field)
                result["unmodified_historical_driver"] = "A0: audit only; not executed by this ABI-corrected comparison"
            result.update({"reference": reference, "candidate": candidate})
        else:
            result["run"] = analyze(args.run_dir, args.mode, args.baseline)
        if args.action not in ("formal-analyze", "formal-compare"):
            result["status"] = "PASS"
    except Exception as exc:
        result["reason"] = str(exc)
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("{0}: {1}".format(result["status"], destination))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
