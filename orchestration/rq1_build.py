#!/usr/bin/env python3
"""Build one missing reorder program with the fixed official toolchain.

This worker is staged outside the frozen harness. It imports its validated
guards and preflight instead of changing the runtime, ABI or scheduling code.
Python 3.6+; native Linux execution only.
"""
import argparse
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import sys
import traceback

BENCHMARKS = ("reorder_4_bad", "reorder_5_bad", "reorder_10_bad")


class BenchmarkBuildFailure(ValueError):
    """An ordinary compiler/analysis/ABI failure with intact global guards."""

    def __init__(self, message, kind="COMPILER_FAILURE"):
        ValueError.__init__(self, message)
        self.kind = kind


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def source_threads(source, expected):
    text = Path(source).read_text(encoding="utf-8")
    values = {}
    for name in ("iSet", "iCheck"):
        matches = re.findall(r"^\s*static\s+int\s+" + name + r"\s*=\s*(\d+)\s*;", text, re.M)
        if len(matches) != 1:
            raise ValueError("fixed source has ambiguous thread defaults: " + name)
        values[name] = int(matches[0])
    if values["iSet"] + values["iCheck"] != expected:
        raise ValueError("source thread defaults differ from the selected benchmark")
    return values


def verify_source(native, source, protocol, commands):
    source = Path(source)
    relative = source.relative_to(native.UPSTREAM).as_posix()
    raw = source.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
    unused, head, unused2 = commands.run("upstream-head", ["git", "-C", str(native.UPSTREAM), "rev-parse", "HEAD"])
    native.require(head.decode().strip() == protocol["source_commit"], "upstream HEAD changed")
    unused, expected, unused2 = commands.run("benchmark-source-blob", ["git", "-C", str(native.UPSTREAM),
        "rev-parse", protocol["source_commit"] + ":" + relative])
    native.require(expected.decode().strip() == blob, "benchmark source differs from the fixed Git blob")
    unused, diff, unused2 = commands.run("benchmark-source-clean", ["git", "-C", str(native.UPSTREAM),
        "diff", "HEAD", "--", relative])
    native.require(not diff.strip(), "benchmark source worktree is dirty")
    return {"path": str(source), "sha256": native.digest(source), "git_blob_sha1": blob}


def protected_paths(native):
    upstream = native.UPSTREAM
    instrumentation = upstream / "tool/staticAnalysis/DBDS-INSTRU"
    paths = [upstream / "evaluation/CS" / ("reorder_" + str(n)) / ("reorder_%d_bad.c" % n)
             for n in (3, 4, 5, 10)]
    paths += [upstream / "evaluation/CS/reorder_3/reorder_3_bad",
              upstream / "evaluation/CS/reorder_3/ConConfig.reorder_3_bad",
              instrumentation / "DBDSFunction.o", instrumentation / "llvm-mode/DBDSFunction.cpp",
              instrumentation / "dbds-clang-fast", instrumentation / "dbds-clang-fast++",
              instrumentation / "dbds-llvm-pass.so", upstream / "tool/staticAnalysis/staticAnalysis.sh"]
    paths += [upstream / "clang+llvm/bin" / name for name in ("clang", "clang++", "opt")]
    paths += sorted((upstream / "tool/DBDS").glob("*.py"))
    for n in (4, 5, 10):
        directory = upstream / "evaluation/CS" / ("reorder_" + str(n))
        paths += [path for path in (directory / ("reorder_%d_bad" % n),
                                    directory / ("ConConfig.reorder_%d_bad" % n)) if path.is_file()]
    return paths


def fixed_tool_scripts(native, protocol, commands, output):
    """Pin and preserve the official analysis scripts actually used by the build."""
    unused, tree, unused2 = commands.run("fixed-analysis-script-tree", ["git", "-C", str(native.UPSTREAM),
        "ls-tree", "-r", protocol["source_commit"], "--", "tool/staticAnalysis"])
    tracked = {}
    for line in tree.decode("utf-8").splitlines():
        header, relative = line.split("\t", 1)
        if Path(relative).suffix in (".py", ".sh"):
            tracked[relative] = header.split()
    pending = ["tool/staticAnalysis/staticAnalysis.sh"]
    paths, inspected = [], set()
    snapshot = output / "official-analysis-scripts"
    while pending:
        relative = pending.pop()
        if relative in inspected:
            continue
        native.require(relative in tracked, "required official analysis script is untracked: " + relative)
        mode, kind, expected = tracked[relative]
        native.require(kind == "blob" and mode in ("100644", "100755"), "unsupported official script entry")
        path = native.UPSTREAM / relative
        raw = path.read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
        native.require(actual == expected, "official analysis script differs from fixed commit: " + relative)
        destination = snapshot / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(raw)
        paths.append(path)
        inspected.add(relative)
        text = "\n".join(line for line in raw.decode("utf-8").splitlines()
                         if not line.lstrip().startswith("#"))
        # Follow explicit script dependencies and local Python imports. Do not
        # require unrelated optional programs merely because Git tracks them.
        referenced = set(re.findall(r"tool/staticAnalysis/[A-Za-z0-9_./-]+\.(?:py|sh)", text))
        for name in re.findall(r"[A-Za-z0-9_.-]+\.(?:py|sh)", text):
            siblings = [entry for entry in tracked if Path(entry).name == name]
            if len(siblings) == 1:
                referenced.add(siblings[0])
        if path.suffix == ".py":
            for name in re.findall(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.M):
                sibling = (Path(relative).parent / (name + ".py")).as_posix()
                if sibling in tracked:
                    referenced.add(sibling)
        pending.extend(sorted(referenced - inspected))
    native.require(native.UPSTREAM / "tool/staticAnalysis/staticAnalysis.sh" in paths,
                   "fixed official staticAnalysis script is missing")
    return paths


def protected_hashes(native, paths):
    result = {}
    for path in paths:
        native.require(path.is_file(), "required fixed build input missing: " + str(path))
        result[str(path)] = native.digest(path)
    return result


def exclusive_publish(source, destination):
    """Copy a new product without replacing an existing or dangling link."""
    source, destination = Path(source), Path(destination)
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing)
    os.chmod(str(destination), stat.S_IMODE(source.stat().st_mode))


def build_command(commands, label, argv):
    # timeout's established TERM/KILL options work in the existing old image.
    # Its own process group also contains subprocesses spawned by staticAnalysis.
    command = ["timeout", "--signal=TERM", "--kill-after=20s", "600s"] + argv
    info, stdout, stderr = commands.run(label, command, timeout=650, required=False)
    code = info["exit_code"]
    if code is None or code in (124, 125, 126, 127, 137) or code < 0:
        raise ValueError("build tool/watchdog infrastructure failure: " + label + " (exit " + str(code) + ")")
    if code != 0:
        raise BenchmarkBuildFailure("official build step failed: " + label + " (exit " + str(code) + ")")
    return info


def build_one(root, output, benchmark, native, state, protocol, commands):
    native.require(benchmark in BENCHMARKS, "only the three missing programs may be built")
    native.require(state.get("reorder3_formal_complete") is True
                   and state["benchmarks"]["reorder_3_bad"].get("formal_complete") is True,
                   "the accepted six reorder_3 formal rounds are required first")
    previous = state["benchmarks"].get(benchmark, {})
    native.require(not previous.get("build_attempted") and "manifest" not in previous,
                   "an earlier build/product record exists; no automatic rebuild")
    directory = native.UPSTREAM / "evaluation/CS" / benchmark[:-4]
    source = directory / (benchmark + ".c")
    binary, config = directory / benchmark, directory / ("ConConfig." + benchmark)
    native.require(not os.path.lexists(str(binary)) and not os.path.lexists(str(config)),
                   "existing/partial canonical products must not be overwritten")
    source_identity = verify_source(native, source, protocol, commands)
    threads = source_threads(source, int(benchmark.split("_")[1]))
    native.write_json(output / "source-identity.json", dict(source_identity, thread_defaults=threads))
    state["benchmarks"][benchmark] = dict(previous, build_attempted=True)
    native.checkpoint(root, state)
    work = output / "build-work"
    work.mkdir()
    shutil.copy2(str(source), str(work / source.name))
    native.require(native.digest(work / source.name) == source_identity["sha256"], "copied build source changed")
    for name in ("build.sh", "cleanDIR.sh"):
        if (directory / name).is_file():
            shutil.copy2(str(directory / name), str(output / ("official-" + name)))
    instrumentation = native.UPSTREAM / "tool/staticAnalysis/DBDS-INSTRU"
    saved_cwd = Path.cwd()
    try:
        os.chdir(str(work))
        build_command(commands, "compile-llvm", [str(native.UPSTREAM / "clang+llvm/bin/clang"),
            "-g", "-emit-llvm", "-c", "./" + source.name, "-o", benchmark + ".bc"])
        build_command(commands, "official-static-analysis", [
            str(native.UPSTREAM / "tool/staticAnalysis/staticAnalysis.sh"), benchmark])
        os.environ["Con_PATH"] = str(work / config.name)
        build_command(commands, "official-instrument-and-link", [str(instrumentation / "dbds-clang-fast++"),
            "-g", "./" + benchmark + ".bc", "-o", benchmark, "-lpthread", "-ldl"])
    finally:
        os.chdir(str(saved_cwd))
    native.require(native.digest(work / source.name) == source_identity["sha256"], "build modified its source copy")
    built_binary, built_config = work / benchmark, work / config.name
    if not built_binary.is_file() or not built_config.is_file():
        raise BenchmarkBuildFailure("official build did not produce both binary and ConConfig")
    lines = [line for line in built_config.read_text().splitlines() if line.strip()]
    if not lines or any(re.match(r"^.+:[0-9]+$", line) is None for line in lines):
        raise BenchmarkBuildFailure("generated keypoint configuration is empty or malformed")
    native.write_json(output / "keypoint-configuration.json", {
        "locations": lines, "static_location_count": len(lines), "thread_defaults": threads,
        "runtime_kps": "pending actual A1/B/C adaptation; static locations are not per-thread KPS"})
    # The caller verifies every protected input before permitting publication.
    before = read_json(output / "protected-before.json")
    native.require(protected_hashes(native, [Path(path) for path in before]) == before,
                   "fixed source/runtime/toolchain/reorder_3 changed during build")
    published = []
    for original, destination in ((built_binary, binary), (built_config, config)):
        exclusive_publish(original, destination)
        native.require(native.digest(original) == native.digest(destination), "published product copy changed")
        published.append(native.artifact(destination))
        native.write_json(output / ("published-%d.json" % len(published)), published[-1])
    record = {"schema": "cs340-period-rq1-isolated-build-v1", "benchmark": benchmark,
              "source_commit": protocol["source_commit"], "source": source_identity,
              "thread_defaults": threads, "build_directory": str(work), "published_products": published,
              "runtime_object": native.artifact(instrumentation / "DBDSFunction.o"),
              "protected_inputs": before,
              "environment": {name: os.environ.get(name) for name in (
                  "ROOT_DIR", "PATH", "LD_LIBRARY_PATH", "AFL_PATH", "AFL_CC", "AFL_CXX", "Con_PATH")},
              "commands": [read_json(path) for path in sorted(output.glob("*.command.json"))],
              "method": "official clang/staticAnalysis/dbds-clang-fast++ sequence in a fresh directory; no make or cleanDIR"}
    record_path = output / "build-record.json"
    native.write_json(record_path, record)
    manifest = native.inspect_manifest(benchmark, protocol)
    manifest.update(product_origin="isolated_build", build_record=native.artifact(record_path))
    manifest_path, proof_path = output / "benchmark-manifest.json", output / "abi-proof.json"
    native.write_json(manifest_path, manifest)
    info, unused, unused2 = commands.run("new-product-abi", [sys.executable,
        str(native.HERE / "table2_scheduler_preflight.py"), "--binary", str(binary), "--config", str(config),
        "--runtime-object", manifest["runtime_object"]["path"], "--runtime-source", manifest["runtime_source"]["path"],
        "--upstream", str(native.UPSTREAM), "--driver", str(native.HERE / "run_scheduler_comparison.py"),
        "--reference-driver", str(native.HERE / "run_abi_parallel_reference.py"), "--abi-profile", "runtime-dwarf",
        "--benchmark-manifest", str(manifest_path), "--output", str(proof_path)], timeout=120, required=False)
    if info["exit_code"] is None:
        raise ValueError("ABI preflight infrastructure failed")
    if info["exit_code"] != 0:
        proof = read_json(proof_path)
        blocked = {item.get("name") for item in proof.get("checks", []) if item.get("status") != "PASS"}
        if blocked and blocked.issubset({"binary_dwarf_abi", "common_runtime_layout"}):
            raise BenchmarkBuildFailure("new product ABI preflight did not pass; inspect abi-proof.json",
                                        kind="BENCHMARK_ABI_FAILURE")
        raise ValueError("ABI preflight failed a global/unknown identity check; inspect abi-proof.json")
    proof = read_json(proof_path)
    native.require(proof.get("status") == "PASS" and not proof.get("blockers"), "ABI command/proof disagreement")
    info, libraries, unused2 = commands.run("new-product-linked-libraries", ["ldd", str(binary)], required=False)
    if info["exit_code"] is None:
        raise ValueError("shared-library inspection infrastructure failed")
    if info["exit_code"] != 0 or b"not found" in libraries:
        raise BenchmarkBuildFailure("new product has unresolved shared libraries")
    return {"status": "IDENTITY_ABI_VERIFIED_RUNTIME_PROFILE_PENDING", "manifest": str(manifest_path),
            "abi_proof": str(proof_path), "build_record": str(record_path), "build_attempted": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--benchmark", required=True, choices=BENCHMARKS)
    args = parser.parse_args(argv)
    root, output = args.root.resolve(), args.output.resolve()
    if re.match(r"^/tmp/cs340-rq1-[0-9a-f]{32}$", str(root)) is None or root not in output.parents or output.exists():
        parser.error("a fresh build-evidence directory inside the accepted native session is required")
    output.mkdir(parents=True)
    sys.path.insert(0, str(root / "scripts"))
    import table2_rq1_native as native
    native.require(sys.platform == "linux" and platform.machine() == "x86_64" and os.geteuid() == 0,
                   "native build requires the original Linux x86_64 root container")
    import fcntl
    state = read_json(root / "state.json")
    before_state = copy.deepcopy(state)
    result = {"schema": "cs340-period-rq1-phase-v1", "phase": "build", "benchmark": args.benchmark,
              "status": "BLOCKED", "failure_scope": "global", "phase_excluded": False,
              "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    native.write_json(output / "state-before.json", state)
    baseline, pending, caught = None, None, None
    commands = native.Commands(output)
    protocol = read_json(root / "protocol.json")
    proof = output / "permission-proof.json"
    try:
        native.validate_protocol(protocol)
        native.require(state.get("protocol_sha256") == native.digest(root / "protocol.json"), "native protocol changed")
        native.require(state.get("root") == str(root), "native checkpoint belongs to another session")
        os.environ["ROOT_DIR"] = str(native.UPSTREAM)
        os.environ["PATH"] = str(native.UPSTREAM / "clang+llvm/bin") + ":" + os.environ.get("PATH", "")
        os.environ["LD_LIBRARY_PATH"] = str(native.UPSTREAM / "clang+llvm/lib") + ":" + os.environ.get("LD_LIBRARY_PATH", "")
        os.environ["AFL_PATH"] = str(native.UPSTREAM / "tool/staticAnalysis/DBDS-INSTRU")
        for name in ("AFL_HARDEN", "AFL_USE_ASAN", "AFL_USE_MSAN", "AFL_DONT_OPTIMIZE", "AFL_NO_BUILTIN", "AFL_INST_RATIO"):
            native.require(name not in os.environ, "inherited compiler instrumentation flag differs from official baseline: " + name)
        for variable, executable in (("AFL_CC", "clang"), ("AFL_CXX", "clang++")):
            wanted = str(native.UPSTREAM / "clang+llvm/bin" / executable)
            native.require(variable not in os.environ or os.environ[variable] == wanted,
                           "inherited compiler override differs from fixed LLVM: " + variable)
            os.environ[variable] = wanted
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        with open("/tmp/cs340-period-ipc1111.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            native.write_json(output / "environment.json", native.environment(protocol))
            commands.run("real-permissions", [sys.executable, str(native.HERE / "table2_scheduler_permissions.py"),
                "--output", str(proof)], timeout=60)
            native.write_json(output / "live-before.json", native.live_gate(protocol, proof))
            tool_scripts = fixed_tool_scripts(native, protocol, commands, output)
            baseline = protected_hashes(native, protected_paths(native) + tool_scripts)
            cache = read_json(root / "pilot-cache.json")
            runtime = native.UPSTREAM / "tool/staticAnalysis/DBDS-INSTRU/DBDSFunction.o"
            native.require(native.digest(runtime) == cache["artifacts"]["runtime_object"], "runtime object differs from validated pilot")
            native.write_json(output / "protected-before.json", baseline)
            for tool in ("clang", "clang++", "opt", "gcc", "readelf", "python3"):
                commands.run("toolchain-" + tool.replace("+", "p"), [tool, "--version"])
            try:
                pending = build_one(root, output, args.benchmark, native, state, protocol, commands)
            except BaseException as error:
                caught = error
                result.update(error=type(error).__name__ + ": " + str(error), traceback=traceback.format_exc())
            # A failed program may be skipped only after these real final guards.
            after = protected_hashes(native, [Path(path) for path in baseline])
            native.write_json(output / "protected-after.json", after)
            native.require(after == baseline, "fixed inputs changed during build; stop the whole cohort")
            native.write_json(output / "live-after.json", native.live_gate(protocol, proof))
            native.write_json(output / "environment-after.json", native.environment(protocol))
            if caught is not None:
                result["failure_scope"] = "benchmark" if isinstance(caught, BenchmarkBuildFailure) else "global"
                if isinstance(caught, BenchmarkBuildFailure):
                    result["build_failure_kind"] = caught.kind
            else:
                from table2_scheduler_preflight import verify_benchmark_manifest
                verify_benchmark_manifest(pending["manifest"], native.UPSTREAM)
                state["benchmarks"][args.benchmark] = pending
                result.update(status="BUILD_PASSED", failure_scope="none")
    except BaseException as error:
        result.setdefault("error", type(error).__name__ + ": " + str(error))
        result.update(failure_scope="global", guard_error=type(error).__name__ + ": " + str(error),
                      guard_traceback=traceback.format_exc())
    finally:
        if result["status"] != "BUILD_PASSED":
            # Retain attempt markers and every artifact, but never promote a failed ABI.
            item = state["benchmarks"].get(args.benchmark, {})
            previous = before_state["benchmarks"].get(args.benchmark, {})
            state["benchmarks"][args.benchmark] = dict(previous,
                **({"build_attempted": True} if item.get("build_attempted") else {}))
            if item.get("build_attempted"):
                state["benchmarks"][args.benchmark].update(
                    build_evidence=str(output), build_failure_reason=result.get("error", result.get("guard_error")))
        native.write_json(output / "state-after.json", state)
        native.checkpoint(root, state)
        result["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        native.write_json(output / "phase-result.json", result)
        native.checksums(output)
    print("Final status: " + result["status"] + "\nEvidence: " + str(output), flush=True)
    return 0 if result["status"] == "BUILD_PASSED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
