#!/usr/bin/env python3
"""Run the pinned Parallel controller with its shared-memory ABI corrected.

This is A1, an ABI-only corrected reference, never the historical original A0.
The original generator, prefix/feedback logic, error classification, statistics,
and budget implementation are retained. A shared launch permission/supervision
policy is also applied equally to A1/B/C. A0 must be audited without execution
when its memory layout is incompatible with the measured linked runtime.
Python 3.6+; importing this module never starts a target.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import traceback

from run_scheduler_comparison import (
    UPSTREAM_COMMIT, VENDOR, _positive, load_official_modules,
    prepare_abi_source, runtime_abi_from_result, verify_harness_identity, verify_official_files,
    ProcessSupervisor,
)


class _ReferenceInterrupted(BaseException):
    def __init__(self, signum):
        self.signum = signum
        BaseException.__init__(self, "ABI reference interrupted by signal " + str(signum))


def _normal_exit_line(source):
    final = ast.parse(source).body[-1]
    if not (isinstance(final, ast.Expr) and isinstance(final.value, ast.Call)
            and isinstance(final.value.func, ast.Name) and final.value.func.id == "exit"):
        raise RuntimeError("pinned Parallel reference normal-exit anchor changed")
    return final.lineno


def _exit_reached(error, filename, lineno):
    tb = error.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == filename and tb.tb_lineno == lineno:
            return True
        tb = tb.tb_next
    return False


def _cleanup_process(process, own_group):
    from table2_scheduler_permissions import cleanup_owned_process
    cleanup_owned_process(process, own_group=own_group)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period-root", type=Path, default=Path(os.environ.get("PERIOD_ROOT", "/workdir/PERIOD")))
    parser.add_argument("--manifest", type=Path, default=VENDOR / "SOURCE_MANIFEST.json")
    parser.add_argument("--depth", type=int, default=3)
    parser.add_argument("--budget", type=int, default=10000)
    parser.add_argument("--target-timeout", type=int, default=5)
    parser.add_argument("--abi-proof", type=Path)
    parser.add_argument("--permission-proof", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--emit-adapted-source", type=Path)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("target", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    for value, name in ((args.depth, "depth"), (args.target_timeout, "target timeout")):
        _positive(value, name)
    if args.budget < 0:
        raise ValueError("budget must be nonnegative; zero means upstream unlimited")
    directory = args.period_root.resolve() / "tool" / "DBDS"
    verified = verify_official_files(directory, manifest_path=args.manifest)
    raw = (directory / "run_PDS.py").read_bytes()
    adapted = prepare_abi_source(raw.decode("utf-8"))
    normal_exit = _normal_exit_line(adapted)
    filename = str(directory / "run_PDS.py") + " [comparison]"
    if args.emit_adapted_source:
        with args.emit_adapted_source.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(adapted)
    metadata = {
        "schema_version": 2, "role": "abi-only-parallel-reference", "scheduler": "parallel",
        "abi_profile": "runtime-dwarf", "abi_validation": "NOT_EXECUTED",
        "upstream_commit": UPSTREAM_COMMIT, "depth": args.depth, "budget": args.budget,
        "target_timeout_seconds": args.target_timeout,
        "original_source_sha256": hashlib.sha256(raw).hexdigest(),
        "adapted_source_sha256": hashlib.sha256(adapted.encode("utf-8")).hexdigest(),
        "verified_sources": verified, "status": "CHECK_ONLY" if args.check_only else "STARTING",
        "statistics_policy": "unchanged upstream; reject truncated budget or retest results at acceptance",
    }
    namespace = {}
    return_code = 0
    old_argv, old_path, original_popen = sys.argv, list(sys.path), subprocess.Popen
    supervisor = ProcessSupervisor(original_popen)
    previous_sigterm = None
    try:
        if args.check_only:
            print(json.dumps(metadata, sort_keys=True))
            return 0
        if sys.platform != "linux":
            raise RuntimeError("ABI reference execution requires the verified Linux environment")
        target = args.target[1:] if args.target[:1] == ["--"] else args.target
        if not target or args.abi_proof is None:
            raise ValueError("provide --abi-proof and the existing target after --")
        if args.permission_proof is None:
            raise ValueError("--permission-proof is required before any target execution")
        from table2_scheduler_permissions import validate_permission_proof, permission_policy
        metadata["permission_proof"] = validate_permission_proof(args.permission_proof)
        metadata["permission_policy"] = permission_policy()
        from table2_scheduler_preflight import validate_abi_proof
        import period_shared_memory
        result = validate_abi_proof(args.abi_proof, Path(target[0]).resolve(), directory)
        abi = runtime_abi_from_result(result)
        verify_harness_identity(result, "reference", __file__)
        verify_harness_identity(result, "driver", sys.modules[prepare_abi_source.__module__].__file__)
        layer_hash = verify_harness_identity(result, "abi_layer", period_shared_memory.__file__)
        metadata.update({"abi_proof": result, "abi_validation": "PASS", "abi_layout": abi.layout,
                         "abi_layer_sha256": layer_hash})
        load_official_modules(directory, args.manifest)
        sys.path.insert(0, str(directory))
        sys.argv = [str(directory / "run_PDS.py"), "-y", "-d", str(args.depth),
                    "-f", str(args.budget), "-t", str(args.target_timeout)] + target
        if args.budget == 0:
            del sys.argv[4:6]
        metadata["upstream_argv"] = sys.argv[:]

        def interrupted(signum, frame):
            if supervisor.defer_signal(signum):
                return
            raise _ReferenceInterrupted(signum)

        previous_sigterm = signal.signal(signal.SIGTERM, interrupted)
        supervisor.enable_subreaper()
        subprocess.Popen = supervisor
        namespace.update({"__name__": "__main__", "__file__": str(directory / "run_PDS.py"),
                          "_comparison_abi": abi,
                          "_comparison_setup_share_memory": period_shared_memory.setup_share_memory})
        try:
            exec(compile(adapted, filename, "exec"), namespace)
        except SystemExit as error:
            if error.code not in (None, 0) or not _exit_reached(error, filename, normal_exit):
                raise RuntimeError("Parallel reference aborted before its normal result footer") from error
        else:
            raise RuntimeError("Parallel reference did not reach its original normal exit")
        metadata["status"] = "COMPLETED"
    except BaseException as error:
        return_code = 130 if isinstance(error, KeyboardInterrupt) else 128 + error.signum if isinstance(error, _ReferenceInterrupted) else 2
        metadata["status"] = "INTERRUPTED" if return_code in (130, 143) else "FAILED"
        metadata["exception"] = type(error).__name__ + ": " + str(error)
        metadata["exception_traceback"] = traceback.format_exc()
        traceback.print_exc()
    finally:
        subprocess.Popen = original_popen
        try:
            supervisor.cleanup()
        except BaseException as error:
            return_code = 2
            metadata["status"] = "FAILED"
            metadata.setdefault("cleanup_errors", []).append({
                "error": str(error), "traceback": traceback.format_exc()})
        sys.argv, sys.path[:] = old_argv, old_path
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
        metadata["observed_process_launches_including_preparation"] = len(supervisor.processes)
        metadata["process_launches_including_preparation"] = supervisor.launches
        metadata["reaped_descendants"] = supervisor.reaped_descendants
        metadata["upstream_statistics"] = {key: namespace.get(key) for key in (
            "rounds", "total_errors_interleavings", "total_timeouts_interleavings", "statusL")}
        metadata["exit_code"] = return_code
        print("COMPARISON_SUMMARY " + json.dumps(metadata, sort_keys=True))
        if args.metadata:
            args.metadata.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
