#!/usr/bin/env python3
"""Narrow native execution of the frozen four-program RQ1 protocol.

Uses the already verified drivers, ABI, permission gate and trace observer.
No container, benchmark source, runtime or historical product is changed.
"""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
import traceback

from resume_table2_podman import Commands, require
from table2_scheduler_affinity import verify_affinity
from table2_scheduler_permissions import validate_permission_proof

BENCHMARKS = ("reorder_3_bad", "reorder_4_bad", "reorder_5_bad", "reorder_10_bad")
UPSTREAM = Path("/workdir/PERIOD")
HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


def checksums(root):
    root = Path(root)
    entries = [digest(path) + "  " + str(path.relative_to(root))
               for path in sorted(root.rglob("*")) if path.is_file() and path != root / "SHA256SUMS"]
    with (root / "SHA256SUMS").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(entries) + "\n")


def checkpoint(root, state):
    temporary = Path(root) / "state.next.json"
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    os.replace(str(temporary), str(Path(root) / "state.json"))


def rollback_promotions(state, before):
    """Revoke completion after a failed final gate, retaining attempt guards."""
    for name, item in state.get("benchmarks", {}).items():
        original = before.get("benchmarks", {}).get(name, {})
        for key in ("adaptation", "formal_complete"):
            if key in original:
                item[key] = original[key]
            else:
                item.pop(key, None)
    if "reorder3_formal_complete" in before:
        state["reorder3_formal_complete"] = before["reorder3_formal_complete"]
    else:
        state.pop("reorder3_formal_complete", None)


def validate_protocol(protocol):
    require(protocol.get("schema") == "cs340-period-rq1-protocol-v1", "unsupported protocol")
    require(protocol.get("benchmarks") == list(BENCHMARKS), "benchmark cohort changed")
    require(protocol.get("bug_depth") == 3 and protocol.get("schedule_budget") == 10000,
            "frozen depth/budget changed")
    require(protocol.get("minimum_rounds") == 3 and protocol.get("expected_cpus") == list(range(32)),
            "frozen repetition or affinity changed")
    for field in ("target_timeout_seconds", "round_timeout_seconds", "kill_after_seconds"):
        require(type(protocol.get(field)) is int and protocol[field] > 0, "invalid protocol timeout")
    require(protocol["target_timeout_seconds"] == 5 and protocol["round_timeout_seconds"] == 3600
            and protocol["kill_after_seconds"] == 20, "frozen timeout policy changed")


def environment(protocol):
    cpu = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")), "")
    release = Path("/etc/os-release").read_text()
    pretty = next((line.split("=", 1)[1].strip('"') for line in release.splitlines()
                   if line.startswith("PRETTY_NAME=")), "")
    record = {"cpu_model": cpu, "kernel": platform.release(), "container_userland": pretty,
              "python": platform.python_version(), "status": Path("/proc/self/status").read_text(),
              "cgroup": Path("/proc/self/cgroup").read_text()}
    baseline = protocol["environment_baseline"]
    for field in ("cpu_model", "kernel", "container_userland", "python"):
        require(record[field] == baseline[field], "environment differs from frozen protocol: " + field)
    return record


def live_gate(protocol, proof):
    measured = validate_permission_proof(proof)
    affinity = verify_affinity(",".join(str(cpu) for cpu in protocol["expected_cpus"]))
    active = []
    names = {"run_PDS.py", "run_abi_parallel_reference.py", "run_scheduler_comparison.py",
             "trace_period_driver.py", "table2_scheduler_permissions.py", "table2_rq1_native.py"}
    for process in Path("/proc").iterdir():
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        try:
            argv = [item.decode("utf-8", "replace") for item in (process / "cmdline").read_bytes().split(b"\0") if item]
            if argv and (Path(argv[0]).name in BENCHMARKS or
                         Path(argv[0]).name.startswith("python") and any(Path(a).name in names for a in argv[1:4])):
                active.append({"pid": int(process.name), "argv": argv})
        except (FileNotFoundError, ProcessLookupError):
            pass
    require(not active, "another PERIOD target/driver is active: " + str(active))
    ipc = Path("/proc/sysvipc/shm").read_text()
    rows = ipc.splitlines()
    require(rows, "SysV IPC state unavailable")
    for row in rows[1:]:
        values = dict(zip(rows[0].split(), row.split()))
        if int(values["key"]) == 1111:
            require(int(values["nattch"]) == 0 and int(values["size"]) == 24008,
                    "IPC1111 is attached or incompatible; no removal is performed")
    return {"identity": measured["identity"], "affinity": affinity, "ipc": ipc, "active": active}


def artifact(path):
    path = Path(path)
    require(path.is_file(), "missing existing artifact: " + str(path))
    return {"path": str(path), "sha256": digest(path)}


def inspect_manifest(benchmark, protocol):
    require(benchmark in BENCHMARKS, "unsupported benchmark")
    count = int(benchmark.split("_")[1])
    directory = UPSTREAM / "evaluation/CS" / ("reorder_" + str(count))
    source = directory / (benchmark + ".c")
    require(source.is_file(), "expected pinned benchmark source missing: " + str(source))
    manifest = {"schema": "cs340-period-rq1-benchmark-v1", "benchmark": benchmark,
                "threads": count, "source_commit": protocol["source_commit"], "product_origin": "existing",
                "binary": artifact(directory / benchmark),
                "config": artifact(directory / ("ConConfig." + benchmark)),
                "source": artifact(source),
                "runtime_object": artifact(UPSTREAM / "tool/staticAnalysis/DBDS-INSTRU/DBDSFunction.o"),
                "runtime_source": artifact(UPSTREAM / "tool/staticAnalysis/DBDS-INSTRU/llvm-mode/DBDSFunction.cpp")}
    locations = [line for line in Path(manifest["config"]["path"]).read_text().splitlines() if line.strip()]
    manifest["configuration_line_count"] = len(locations)
    manifest["static_keypoint_locations"] = locations
    manifest["static_keypoint_location_count"] = len(locations)
    return manifest


def observed_profile(run, manifest):
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", (Path(run) / "stdout.log").read_text())
    def one(pattern):
        values = re.findall(pattern, text, re.M)
        require(len(values) == 1, "runtime profile missing/repeated: " + pattern)
        return values[0]
    threads = int(one(r"^ThreadNum:\s*(\d+)\s*$"))
    width = int(one(r"^MaxKpNum:\s*(\d+)\s*$"))
    kps = [int(value) for value in one(r"^kpNumArray:\s*([0-9 ]+)\s*$").split()]
    require(threads == manifest["threads"] and len(kps) == threads and width > 0
            and all(0 <= value <= width for value in kps) and sum(kps) > 0,
            "runtime dimensions do not match verified benchmark")
    return {"schema": "cs340-period-rq1-runtime-profile-v1", "benchmark": manifest["benchmark"],
            "threads": threads, "matrix_width": width, "kps": kps,
            "binary_sha256": manifest["binary"]["sha256"], "config_sha256": manifest["config"]["sha256"]}


def same_profile(left, right):
    return all(left.get(key) == right.get(key) for key in (
        "benchmark", "threads", "matrix_width", "kps", "binary_sha256", "config_sha256"))


def invalid_analysis(error, state="INFRASTRUCTURE_FAILURE", previous=None):
    result = dict(previous or {})
    result.update(schema="cs340-period-formal-evidence-v1", status="BLOCKED", validation="FAIL",
                  included=False, valid_research_result=False, termination_state=state,
                  reason=type(error).__name__ + ": " + str(error), traceback=traceback.format_exc())
    return result


def run_one(output, benchmark, mode, purpose, number, state, protocol, proof):
    from table2_scheduler_evidence import analyze_formal
    directory = Path(output) / ("%s-%02d-%s" % (purpose, number, mode))
    directory.mkdir()
    context = {"schema": "cs340-period-rq1-run-v1", "benchmark": benchmark, "mode": mode,
               "role": "reference" if mode == "reference" else "unified", "phase": purpose,
               "purpose": purpose, "round": number, "protocol_sha256": state["protocol_sha256"],
               "outer_timeout": False}
    manifest = json.loads(Path(state["benchmarks"][benchmark]["manifest"]).read_text())
    analysis = None
    try:
        write_json(directory / "environment.json", environment(protocol))
        write_json(directory / "live-before.json", live_gate(protocol, proof))
        from table2_scheduler_preflight import verify_benchmark_manifest
        verify_benchmark_manifest(state["benchmarks"][benchmark]["manifest"], UPSTREAM)
        work = directory / "work"
        work.mkdir()
        target, config = work / benchmark, work / ("ConConfig." + benchmark)
        shutil.copy2(manifest["binary"]["path"], str(target))
        shutil.copy2(manifest["config"]["path"], str(config))
        require(digest(target) == manifest["binary"]["sha256"] and digest(config) == manifest["config"]["sha256"],
                "copied inputs changed")
        (directory / "input.sha256").write_text(digest(target) + "  work/" + target.name + "\n" +
                                                digest(config) + "  work/" + config.name + "\n")
        driver = HERE / ("run_abi_parallel_reference.py" if mode == "reference" else "run_scheduler_comparison.py")
        command = ["timeout", "--signal=TERM", "--kill-after=" + str(protocol["kill_after_seconds"]) + "s",
                   str(protocol["round_timeout_seconds"]) + "s", sys.executable, "-u", str(HERE / "trace_period_driver.py"),
                   "--trace", str(directory / "actual-yield.jsonl"), "--expected-source", str(UPSTREAM / "tool/DBDS/run_PDS.py"),
                   "--", str(driver)]
        if mode != "reference":
            command += ["--scheduler", mode]
        command += ["--period-root", str(UPSTREAM), "--depth", str(protocol["bug_depth"]),
                    "--budget", str(protocol["schedule_budget"]), "--target-timeout", str(protocol["target_timeout_seconds"]),
                    "--abi-proof", state["benchmarks"][benchmark]["abi_proof"], "--permission-proof", str(proof),
                    "--emit-adapted-source", str(directory / "adapted-source.py"),
                    "--metadata", str(directory / "adapter-metadata.json"), "--", "./" + benchmark]
        write_json(directory / "command.json", {"argv": command, "cwd": str(work), "Con_PATH": str(config)})
        env = dict(os.environ, Con_PATH=str(config))
        (directory / "started-at.txt").write_text(datetime.datetime.utcnow().isoformat() + "Z\n")
        before = time.monotonic()
        with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
            completed = subprocess.run(command, cwd=str(work), env=env, stdout=stdout, stderr=stderr,
                                       timeout=protocol["round_timeout_seconds"] + protocol["kill_after_seconds"] + 30)
        elapsed = time.monotonic() - before
        (directory / "finished-at.txt").write_text(datetime.datetime.utcnow().isoformat() + "Z\n")
        (directory / "exit-code.txt").write_text(str(completed.returncode) + "\n")
        (directory / "walltime.txt").write_text("external_wall_ns=" + str(int(elapsed * 1000000000)) + "\n")
        stderr_text = (directory / "stderr.log").read_text(errors="replace")
        context["outer_timeout"] = completed.returncode == 124 or (
            completed.returncode == 137 and "timeout: sending signal" in stderr_text)
        write_json(directory / "run-context.json", context)
        analysis = analyze_formal(directory, mode, manifest, Path(state["root"]) / "protocol.json",
                                  state["benchmarks"][benchmark].get("runtime_profile"))
        require(digest(target) == manifest["binary"]["sha256"] and digest(config) == manifest["config"]["sha256"],
                "run inputs changed")
        verify_benchmark_manifest(state["benchmarks"][benchmark]["manifest"], UPSTREAM)
        write_json(directory / "live-after.json", live_gate(protocol, proof))
        write_json(directory / "environment-after.json", environment(protocol))
        if analysis.get("included"):
            profile = observed_profile(directory, manifest)
            existing = state["benchmarks"][benchmark].get("runtime_profile")
            require(existing is None or same_profile(existing, profile), "runtime KPS/profile changed from accepted reference")
            if existing is None:
                require(purpose == "adaptation" and mode == "reference", "runtime profile needs an accepted A1 reference")
                state["benchmarks"][benchmark]["runtime_profile"] = profile
                write_json(directory / "runtime-profile.json", profile)
    except subprocess.TimeoutExpired as error:
        context["outer_timeout"] = True
        if not (directory / "run-context.json").exists():
            write_json(directory / "run-context.json", context)
        (directory / "exit-code.txt").write_text("124\n")
        (directory / "walltime.txt").write_text("external_wall_ns=" + str(int((time.monotonic() - before) * 1000000000)) + "\n")
        try:
            partial = analyze_formal(directory, mode, manifest, Path(state["root"]) / "protocol.json",
                                     state["benchmarks"][benchmark].get("runtime_profile"))
        except BaseException:
            partial = analysis
        analysis = invalid_analysis(error, "ROUND_TIMEOUT", previous=partial)
    except BaseException as error:
        analysis = invalid_analysis(error, previous=analysis)
        if not (directory / "run-context.json").exists():
            write_json(directory / "run-context.json", context)
    analysis.setdefault("benchmark", benchmark)
    analysis.setdefault("mode", mode)
    analysis.setdefault("protocol_sha256", state["protocol_sha256"])
    write_json(directory / "analysis.json", analysis)
    checksums(directory)
    return directory, analysis


def prepare(root, output, protocol, commands, state):
    unused, unused2, test_log = commands.run("linux-unittests", [sys.executable, "-B", "-m", "unittest",
        "discover", "-s", str(root / "tests"), "-v"], timeout=180)
    require(re.search(rb"Ran [1-9][0-9]* tests?", test_log) is not None, "no Linux tests discovered")
    require(b"skipped=" not in test_log, "Linux regression checks were skipped; inspect the test log")
    commands.run("upstream-head", ["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"])
    head = subprocess.check_output(["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"]).decode().strip()
    require(head == protocol["source_commit"], "upstream commit changed")
    for tool in ("clang", "gcc", "readelf", "python3"):
        commands.run("toolchain-" + tool, [tool, "--version"])
    for benchmark in BENCHMARKS:
        folder = Path(output) / benchmark
        folder.mkdir()
        try:
            count = int(benchmark.split("_")[1])
            base = UPSTREAM / "evaluation/CS" / ("reorder_" + str(count))
            inventory = {}
            for path in (base / benchmark, base / ("ConConfig." + benchmark), base / (benchmark + ".c")):
                inventory[str(path)] = {"exists": path.is_file(), "sha256": digest(path) if path.is_file() else None,
                                        "bytes": path.stat().st_size if path.is_file() else None}
            write_json(folder / "inventory.json", inventory)
            for original, filename in ((base / ("ConConfig." + benchmark), "ConConfig.original"),
                                       (base / (benchmark + ".c"), "benchmark-source.c")):
                if original.is_file():
                    shutil.copy2(str(original), str(folder / filename))
                    require(digest(original) == digest(folder / filename), "review snapshot copy changed")
            manifest = inspect_manifest(benchmark, protocol)
            manifest_path = folder / "benchmark-manifest.json"
            write_json(manifest_path, manifest)
            proof_path = folder / "abi-proof.json"
            commands.run("abi-" + benchmark, [sys.executable, str(HERE / "table2_scheduler_preflight.py"),
                "--binary", manifest["binary"]["path"], "--config", manifest["config"]["path"],
                "--runtime-object", manifest["runtime_object"]["path"], "--runtime-source", manifest["runtime_source"]["path"],
                "--upstream", str(UPSTREAM), "--driver", str(HERE / "run_scheduler_comparison.py"),
                "--reference-driver", str(HERE / "run_abi_parallel_reference.py"), "--abi-profile", "runtime-dwarf",
                "--benchmark-manifest", str(manifest_path), "--output", str(proof_path)], timeout=120)
            unused, libraries, unused2 = commands.run("linked-libraries-" + benchmark, ["ldd", manifest["binary"]["path"]])
            require(b"not found" not in libraries, "unresolved benchmark shared libraries")
            state["benchmarks"][benchmark] = {"status": "IDENTITY_ABI_VERIFIED_RUNTIME_PROFILE_PENDING",
                "manifest": str(manifest_path), "abi_proof": str(proof_path)}
        except BaseException as error:
            state["benchmarks"][benchmark] = invalid_analysis(error)
    cache = json.loads((root / "pilot-cache.json").read_text())
    manifest3 = state["benchmarks"].get("reorder_3_bad", {})
    if "manifest" in manifest3:
        current = json.loads(Path(manifest3["manifest"]).read_text())
        require(all(current[key]["sha256"] == cache["artifacts"][key] for key in ("binary", "config", "runtime_object", "runtime_source")),
                "existing reorder_3 pilot identities differ from this session")
        manifest3["runtime_profile"] = cache["runtime_profile"]
        manifest3["adaptation"] = {"status": "PASS", "source": "verified_frozen_reorder_3_pilot", "cache": cache}
        manifest3["status"] = "ADAPTATION_VERIFIED_FROM_FROZEN_PILOT"
    require("manifest" in state["benchmarks"].get("reorder_3_bad", {}), "reorder_3 artifacts failed preparation")
    state["status"] = "PREPARED" if all("manifest" in item for item in state["benchmarks"].values()) else "PREPARED_WITH_BLOCKED_BENCHMARKS"


def execute_phase(output, args, state, protocol, proof):
    from table2_scheduler_evidence import compare_formal
    benchmark = args.benchmark
    if args.phase == "reorder3":
        benchmark = "reorder_3_bad"
    else:
        require(state.get("reorder3_formal_complete") is True, "complete the six reorder_3 formal runs first")
    require(benchmark in BENCHMARKS and "manifest" in state["benchmarks"].get(benchmark, {}),
            "benchmark artifacts/ABI are not verified; inspect preparation evidence")
    item = state["benchmarks"][benchmark]
    require(not item.get("formal_complete"), "formal cohort already completed; no implicit extra rounds")
    if args.phase == "adapt":
        require(benchmark != "reorder_3_bad", "reorder_3 uses its frozen verified pilot")
        require(not item.get("adaptation"), "adaptation already recorded; no implicit replacement")
        require(not item.get("adaptation_attempted"), "earlier adaptation attempt retained; no silent retry")
        item["adaptation_attempted"] = True
        checkpoint(state["root"], state)
        runs = {}
        for mode in ("reference", "parallel", "serial"):
            directory, analysis = run_one(output, benchmark, mode, "adaptation", 1, state, protocol, proof)
            require(analysis.get("included") is True, "adaptation failed: " + str(directory))
            runs[mode] = str(directory)
            if mode == "parallel":
                manifest = json.loads(Path(item["manifest"]).read_text())
                regression = compare_formal(runs["reference"], directory, manifest,
                                            Path(state["root"]) / "protocol.json", item.get("runtime_profile"))
                write_json(Path(output) / "A1B-regression.json", regression)
                require(regression.get("status") == "PASS", "A1/B adaptation regression differs")
        item["adaptation"] = {"status": "PASS", "runs": runs}
        return "ADAPTATION_PASSED"
    require(item.get("adaptation", {}).get("status") == "PASS" and item.get("runtime_profile"),
            "formal runs require accepted per-benchmark adaptation and observed KPS")
    # One independent work directory and driver per mode/round; no concurrency.
    item.setdefault("formal_attempted", False)
    require(not item["formal_attempted"], "an earlier formal attempt exists; no silent retry/replacement")
    item["formal_attempted"] = True
    checkpoint(state["root"], state)
    for number in range(1, protocol["minimum_rounds"] + 1):
        for mode in ("parallel", "serial"):
            directory, analysis = run_one(output, benchmark, mode, "formal", number, state, protocol, proof)
            require(analysis.get("included") is True, "invalid formal round retained; phase stopped: " + str(directory))
    item["formal_complete"] = True
    if benchmark == "reorder_3_bad":
        state["reorder3_formal_complete"] = True
    return "FORMAL_BENCHMARK_PASSED"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=("prepare", "reorder3", "adapt", "formal"), required=True)
    parser.add_argument("--benchmark", choices=BENCHMARKS)
    args = parser.parse_args(argv)
    root, output = args.root.resolve(), args.output.resolve()
    require(re.match(r"^/tmp/cs340-rq1-[0-9a-f]{32}$", str(root)), "unexpected native session path")
    require(root in output.parents and not output.exists(), "need a fresh evidence directory inside this session")
    output.mkdir(parents=True)
    result = {"schema": "cs340-period-rq1-phase-v1", "status": "BLOCKED", "phase_excluded": False, "phase": args.phase,
              "benchmark": args.benchmark, "started_at": datetime.datetime.utcnow().isoformat() + "Z"}
    state_path = root / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"benchmarks": {}}
    state["root"] = str(root)
    write_json(output / "state-before.json", state)
    before_state = json.loads(json.dumps(state))
    phase_work_returned = False
    try:
        require(sys.platform == "linux" and platform.machine() == "x86_64" and os.geteuid() == 0,
                "requires original Linux x86_64 root container")
        protocol_path = root / "protocol.json"
        protocol = json.loads(protocol_path.read_text())
        validate_protocol(protocol)
        require(state.get("protocol_sha256", digest(protocol_path)) == digest(protocol_path), "protocol changed")
        state["protocol_sha256"] = digest(protocol_path)
        os.environ["ROOT_DIR"] = str(UPSTREAM)
        os.environ["PATH"] = str(UPSTREAM / "clang+llvm/bin") + ":" + os.environ["PATH"]
        os.environ["LD_LIBRARY_PATH"] = str(UPSTREAM / "clang+llvm/lib") + ":" + os.environ.get("LD_LIBRARY_PATH", "")
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        with open("/tmp/cs340-period-ipc1111.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            commands = Commands(output)
            write_json(output / "environment.json", environment(protocol))
            proof = output / "permission-proof.json"
            commands.run("real-permissions", [sys.executable, str(HERE / "table2_scheduler_permissions.py"), "--output", str(proof)], timeout=60)
            write_json(output / "live-before.json", live_gate(protocol, proof))
            if args.phase == "prepare":
                require(not state_path.exists(), "session already prepared")
                prepare(root, output, protocol, commands, state)
                result["status"] = state["status"]
            else:
                require(state.get("status", "").startswith("PREPARED"), "session not prepared")
                result["status"] = execute_phase(output, args, state, protocol, proof)
            phase_work_returned = True
            write_json(output / "live-after.json", live_gate(protocol, proof))
    except BaseException as error:
        # Never promote a phase whose final live gate failed. Attempt markers
        # remain durable so an interrupted/failed cohort cannot be silently rerun.
        rollback_promotions(state, before_state)
        result.update(status="BLOCKED", phase_excluded=phase_work_returned,
                      error=type(error).__name__ + ": " + str(error), traceback=traceback.format_exc())
        print(result["traceback"], file=sys.stderr)
    finally:
        result["finished_at"] = datetime.datetime.utcnow().isoformat() + "Z"
        write_json(output / "state-after.json", state)
        # This session-local checkpoint is mutable; all before/after snapshots
        # and raw measurements are immutable in their unique evidence folders.
        checkpoint(root, state)
        write_json(output / "phase-result.json", result)
        checksums(output)
        print("Final status: " + result["status"] + "\nEvidence: " + str(output), flush=True)
    return 0 if result["status"] != "BLOCKED" else 2


if __name__ == "__main__":
    sys.exit(main())
