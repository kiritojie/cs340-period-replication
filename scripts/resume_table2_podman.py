#!/usr/bin/env python3
"""Ubuntu/rootful Podman bridge for the existing reorder_3 pilot.

No image download, build, container creation/removal, IPC deletion or affinity
change is implemented. Without --execute, containers are never started.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

IMAGE = "dfd654d5ebf18787ebff0b8cc35c61c6eda4d49852a93bb784fbe2e82727299a"
CONTAINERS = (("period-table2-reorder3", "8661e83e39a4"),
              ("period-table2-reorder3-v2", "3ede0d6a8445"))
PRODUCTS = {
    "binary": "/workdir/PERIOD/evaluation/CS/reorder_3/reorder_3_bad",
    "config": "/workdir/PERIOD/evaluation/CS/reorder_3/ConConfig.reorder_3_bad",
    "runtime_object": "/workdir/PERIOD/tool/staticAnalysis/DBDS-INSTRU/DBDSFunction.o",
}
BINARY_SHA = "ed2d13809b87a00eaaba76ac0f1faf4871a489a0960993e5963dc89b4bb13db9"
CONFIG_SHA = "0ed49729a85b862b9a918c62f3826f3c56b89ec825ae3fe35a28f21f253d7d4d"
PINNED_COMMIT = "b6f72a7b06d01ffa7114b640312873ec2578a5ea"
SOURCE_FILES = tuple("tool/DBDS/" + name for name in (
    "run_PDS.py", "run_OldPDS.py", "sbp_sched.py", "sbp_sched_mixed_end.py",
    "bp_sched.py", "sched.py", "pds.py", "external_def.py", "interleaving.py", "ipc.py",
)) + ("tool/staticAnalysis/DBDS-INSTRU/llvm-mode/DBDSFunction.cpp",)


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def one_inspect(text):
    value = json.loads(text)
    require(isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict),
            "inspect must contain exactly one JSON object")
    return value[0]


def normal_id(value):
    require(isinstance(value, str), "missing inspect image/container ID")
    return value.removeprefix("sha256:") if hasattr(value, "removeprefix") else value.replace("sha256:", "", 1)


def validate_container(record, expected_name, expected_prefix):
    cid = record.get("Id", record.get("ID"))
    require(normal_id(cid).startswith(expected_prefix), "container name now identifies a different container")
    require(str(record.get("Name", "")).lstrip("/") == expected_name, "unexpected container name")
    require(normal_id(record.get("Image")) == IMAGE, "container does not use the confirmed existing image")
    require(record.get("State", {}).get("Status", "").lower() in ("exited", "created", "running"),
            "container has an unsupported/unsafe state")
    return cid


def safe_idle_start(record):
    config = record.get("Config", {})
    entry = config.get("Entrypoint") or []
    command = config.get("Cmd") or []
    # Podman 3.x reports the original container's single entrypoint as a
    # string, whereas Docker commonly reports a list. Never shell-split it.
    if isinstance(entry, str):
        require(entry in ("/bin/bash", "/bin/sh"), "string entrypoint is not one absolute idle shell path")
        require(record.get("Path") == entry and isinstance(record.get("Args"), list),
                "string entrypoint requires explicit matching Path and list Args")
        entry = [entry]
    require(isinstance(entry, list) and isinstance(command, list), "cannot prove startup argv")
    argv = entry + command
    require(all(isinstance(item, str) for item in argv), "invalid startup argv")
    if argv in (["/bin/bash"], ["bash"], ["/bin/sh"], ["sh"]):
        require(config.get("OpenStdin") is True and config.get("Tty") is True,
                "shell container was not created with persistent interactive stdin and TTY")
    else:
        require(argv in (["/bin/sleep", "infinity"], ["sleep", "infinity"]),
                "startup may execute a historical experiment; not starting this container")
    if record.get("Path"):
        args = record.get("Args") or []
        require(isinstance(args, list) and all(isinstance(item, str) for item in args),
                "cannot prove actual Path/Args")
        require(record["Path"] == argv[0] and (args == argv or [record["Path"]] + args == argv),
                "Config startup argv differs from Path/Args")
    return argv


def launch_configuration(record):
    # State/PID timestamps naturally change on restart; launch configuration must not.
    return {key: record.get(key) for key in ("Image", "Config", "HostConfig", "Mounts", "OCIRuntime")}


def host_privilege_prefix():
    """Keep the engine rootful without invoking sudo when already root."""
    return [] if os.geteuid() == 0 else ["sudo", "-n"]


def validate_security_configuration(record):
    """The historical security boundary is a gate, never a repair target."""
    config = record.get("HostConfig", {})
    require(config.get("Privileged") is False, "privileged containers are forbidden")
    normalize = lambda values: {str(value).upper().replace("CAP_", "", 1) for value in (values or [])}
    dropped = normalize(config.get("CapDrop"))
    # Podman 3.4 resolves ALL to its default-capability drop list in inspect;
    # the recorded creation argv retains the literal option. Actual process
    # effective/bounding capability masks are separately checked by the gate.
    podman_default = {"AUDIT_WRITE", "CHOWN", "DAC_OVERRIDE", "FOWNER", "FSETID", "KILL",
                      "MKNOD", "NET_BIND_SERVICE", "NET_RAW", "SETFCAP", "SETGID",
                      "SETPCAP", "SETUID", "SYS_CHROOT"}
    creation = record.get("Config", {}).get("CreateCommand") or []
    require(dropped == {"ALL"} or (dropped == podman_default and "--cap-drop=ALL" in creation),
            "historical cap-drop=ALL and its resolved Podman configuration are required")
    require(normalize(config.get("CapAdd")) == {"SYS_NICE"}, "only the historical SYS_NICE capability is permitted")
    require("no-new-privileges" in (config.get("SecurityOpt") or []), "historical no-new-privileges is required")
    return {"privileged": False, "cap_drop": ["ALL"], "cap_add": ["SYS_NICE"],
            "no_new_privileges": True}


class Commands:
    def __init__(self, output):
        self.output = Path(output)
        self.number = 0

    def run(self, label, argv, timeout=60, required=True):
        self.number += 1
        stem = self.output / ("%02d-" % self.number + label)
        print("[%s] %s" % (utc(), label), flush=True)
        info = {"argv": [str(x) for x in argv], "started_at": utc()}
        started = time.monotonic()
        try:
            result = subprocess.run(info["argv"], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=timeout)
            info["exit_code"] = result.returncode
            stdout, stderr = result.stdout, result.stderr
        except subprocess.TimeoutExpired as error:
            stdout, stderr = error.stdout or b"", error.stderr or b""
            info.update(exit_code=None, exception="command timed out; contained work may still be active")
        except OSError as error:
            stdout, stderr = b"", str(error).encode("utf-8")
            info.update(exit_code=None, exception=str(error))
        info.update(finished_at=utc(), wall_seconds=time.monotonic() - started)
        stem.with_suffix(".stdout.log").write_bytes(stdout)
        stem.with_suffix(".stderr.log").write_bytes(stderr)
        stem.with_suffix(".command.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
        if required:
            require(info["exit_code"] == 0, label + " failed; see " + str(stem))
        return info, stdout, stderr


def collect_history(history, output):
    """Copy bounded, named old records; never modify/extract old archives."""
    history, output = Path(history), Path(output)
    output.mkdir()
    names = {"environment.txt", "exec-env.txt", "command.txt", "SHA256SUMS",
             "build-artifacts.sha256", "container-inspect.json", "image-inspect.json",
             "container.stdout.log", "preflight.log", "provenance.txt"}
    inventory = {"root": str(history), "records": [], "errors": []}
    if not history.is_dir():
        inventory["errors"].append("historical directory unavailable to this user")
    else:
        for current, dirs, files in os.walk(str(history), onerror=lambda e: inventory["errors"].append(str(e))):
            relative = Path(current).relative_to(history)
            dirs[:] = [d for d in dirs if not d.startswith(".") and len(relative.parts) < 2]
            for name in sorted(set(files) & names):
                source = Path(current) / name
                try:
                    require(not source.is_symlink(), "historical symlink not followed")
                    if source.stat().st_size > 512 * 1024 or len(inventory["records"]) >= 60:
                        continue
                    destination = output / relative / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(str(source), str(destination))
                    inventory["records"].append({"path": str(source), "sha256": digest(destination)})
                except (OSError, ValueError) as error:
                    inventory["errors"].append(str(error))
    (output / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    return inventory


def write_checksums(output):
    entries = []
    for path in sorted(Path(output).rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            entries.append(digest(path) + "  " + path.relative_to(output).as_posix())
    (Path(output) / "SHA256SUMS").write_text("\n".join(entries) + "\n", encoding="utf-8")


def load_preflight(repo):
    """Load only the local audit helper; it does not execute the old driver."""
    directory = Path(repo) / "scripts"
    previous = list(sys.path)
    try:
        sys.path.insert(0, str(directory))
        spec = importlib.util.spec_from_file_location("resume_preflight", directory / "table2_scheduler_preflight.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = previous


def extract_container_sources(commands, podman, cid, output, repo):
    """Read named source/HEAD files through cp, including from a stopped container.

    Copying HEAD and its named ref proves only the recorded HEAD. It cannot
    establish a complete stopped worktree status; scoped byte comparisons are
    recorded separately and a live git status is required before execution.
    """
    root = Path(output) / "original-source"
    root.mkdir()
    result = {"directory": str(root), "files": {}, "errors": [],
              "full_worktree_status": "NOT_OBSERVED: extraction never starts or execs a container",
              "historical_driver_execution": "A0_AUDIT_ONLY_NOT_RUN"}

    def copy_file(relative, destination, required):
        destination.parent.mkdir(parents=True, exist_ok=True)
        info, unused, unused2 = commands.run("extract-source-" + relative.replace("/", "-"),
            podman + ["cp", cid + ":/workdir/PERIOD/" + relative, str(destination)], required=False)
        if info["exit_code"] != 0 or not destination.is_file():
            if required:
                result["errors"].append("could not extract " + relative)
            return False
        raw = destination.read_bytes()
        result["files"][relative] = {"path": str(destination), "size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob_sha1": hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()}
        return True

    for relative in SOURCE_FILES:
        copy_file(relative, root / relative, True)
    git_root = root / "git-metadata"
    copied_head = copy_file(".git/HEAD", git_root / "HEAD", True)
    copy_file(".git/packed-refs", git_root / "packed-refs", False)
    head = None
    if copied_head:
        value = (git_root / "HEAD").read_text(encoding="utf-8").strip()
        if re.match(r"^[0-9a-f]{40}$", value):
            head = value
        elif value.startswith("ref: "):
            ref = value[5:]
            require(ref.startswith("refs/") and not any(part in ("", ".", "..") for part in ref.split("/"))
                    and re.match(r"^[A-Za-z0-9_./-]+$", ref), "unsafe symbolic HEAD reference")
            ref_path = git_root / ref
            if copy_file(".git/" + ref, ref_path, False):
                candidate = ref_path.read_text(encoding="utf-8").strip()
                if re.match(r"^[0-9a-f]{40}$", candidate):
                    head = candidate
            packed = git_root / "packed-refs"
            if head is None and packed.is_file():
                for line in packed.read_text(encoding="utf-8").splitlines():
                    parts = line.split()
                    if len(parts) == 2 and parts[1] == ref and re.match(r"^[0-9a-f]{40}$", parts[0]):
                        head = parts[0]
                        break
        if head is None:
            result["errors"].append("copied git metadata does not resolve HEAD")
    result["upstream_head"] = head
    result["head_matches_pinned"] = head == PINNED_COMMIT
    if not result["head_matches_pinned"]:
        result["errors"].append("extracted HEAD is not the fixed commit")
    try:
        manifest = json.loads((Path(repo) / "scripts/vendor/period_b6f72a7/SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
        entries = {entry.get("upstream_path", entry["path"]): entry for entry in manifest["files"]}
        scoped = {}
        for relative in SOURCE_FILES:
            observed, expected = result["files"].get(relative), entries.get(relative)
            matches = bool(observed and expected and observed["sha256"] == expected["sha256"])
            scoped[relative] = {"matches_pinned": matches, "expected_sha256": expected.get("sha256") if expected else None}
        result["scoped_source_comparison"] = scoped
        result["scoped_sources_match_pinned"] = all(item["matches_pinned"] for item in scoped.values())
    except (OSError, ValueError, KeyError, TypeError) as error:
        result["scoped_sources_match_pinned"] = False
        result["errors"].append("source manifest comparison unavailable: " + str(error))
    result["complete"] = not result["errors"] and all(relative in result["files"] for relative in SOURCE_FILES)
    (root / "extraction-audit.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def read_native_results(output):
    folders = list((Path(output) / "native-evidence").glob("table2-scheduler-pilot-*"))
    if len(folders) != 1 or not folders[0].is_dir():
        return {"status": "UNAVAILABLE", "runs": {}}
    folder = folders[0]
    result = {"directory": str(folder), "runs": {}}
    status = folder / "status.txt"
    result["status"] = status.read_text().strip() if status.is_file() else "UNAVAILABLE"
    permission_file = folder / "permission-proof.json"
    if permission_file.is_file():
        permission = json.loads(permission_file.read_text(encoding="utf-8"))
        result["permissions"] = {"schema": permission.get("schema"), "status": permission.get("status"),
                                 "identity": permission.get("identity"), "policy": permission.get("policy"),
                                 "probes": permission.get("probes", {})}
    else:
        result["permissions"] = {"status": "UNAVAILABLE"}
    proof_file = folder / "abi-proof.json"
    proof_profile = json.loads(proof_file.read_text()).get("abi_profile") if proof_file.is_file() else None
    modern = (folder / "A1-validation.json").is_file() or (folder / "A0-historical-driver").is_dir() or proof_profile == "runtime-dwarf"
    result["reference_role"] = "ABI_ONLY_CORRECTED_PARALLEL" if modern else "LEGACY_ORIGINAL_PARALLEL"
    if modern:
        result["runs"]["A0"] = {"validation": "AUDIT_ONLY_NOT_RUN",
            "reason": "historical raw driver is never used as the runtime-dwarf execution reference"}
    arms = (("A1", "A1-validation.json", "run"), ("B", "A1B-regression.json", "candidate")) if modern else (
        ("A", "A-validation.json", "run"), ("B", "AB-regression.json", "candidate"))
    for label, filename, key in arms + (("C", "C-validation.json", "run"),):
        path = folder / filename
        if not path.is_file():
            result["runs"][label] = {"status": "NO_VALIDATION_RESULT"}
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        run = record.get(key, {})
        result["runs"][label] = {"validation": record.get("status"),
            "first_bug_schedule": run.get("first_error"),
            "total_schedules": run.get("total_schedules"),
            "buggy_schedules": run.get("error_interleavings"),
            "timeouts": run.get("timeouts"), "reason": record.get("reason")}
    return result


def native_pilot_passed(result):
    """A successful wrapper/footer cannot substitute for the permission gate."""
    reference = "A1" if result.get("reference_role") == "ABI_ONLY_CORRECTED_PARALLEL" else "A"
    permission = result.get("permissions", {})
    return (permission.get("schema") == "cs340-period-permissions-v1"
            and permission.get("status") == "PASS" and result.get("status") == "PILOT_PASSED"
            and all(permission.get("probes", {}).get(probe, {}).get("status") == "PASS"
                    and permission.get("probes", {}).get(probe, {}).get("exit_code") == 0
                    for probe in ("process_control", "sched_deadline"))
            and all(result.get("runs", {}).get(arm, {}).get("validation") == "PASS"
                    for arm in (reference, "B", "C")))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="permit safe idle restart, live gates and A1/B/C")
    mode.add_argument("--extract-only", action="store_true", help="copy old sources/HEAD and audit layouts; never start or exec")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--history", type=Path, default=Path("/home/yehaoming/cs340-period-lab-2026-11-21"))
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args(argv)
    require(platform.system() == "Linux", "run this bridge in the user's Ubuntu-22.04 terminal")
    repo = args.repo.resolve()
    output_root = (args.output_root or repo / "docs/results").resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="table2-rootful-resume-" + datetime.datetime.now().strftime("%Y%m%dT%H%M%S") + "-", dir=str(output_root)))
    print("Evidence: " + str(output), flush=True)
    commands = Commands(output)
    privilege_prefix = host_privilege_prefix()
    podman = privilege_prefix + ["podman"]
    state = {"status": "BLOCKED", "started_at": utc(), "execute_requested": args.execute,
             "extract_only_requested": args.extract_only,
             "scope": "reorder_3 only", "benchmarks": "NOT_RUN", "container": None,
             "host_privilege": {"uid": os.getuid(), "euid": os.geteuid(),
                                "gid": os.getgid(), "egid": os.getegid(),
                                "mode": "root-direct" if not privilege_prefix else "nonroot-sudo"}}
    cid, container_root = None, None
    try:
        require(shutil.which("podman"), "rootful Podman unavailable")
        if privilege_prefix:
            require(shutil.which("sudo"), "nonroot execution requires noninteractive sudo for rootful Podman")
            commands.run("sudo-authentication", privilege_prefix + ["true"])
        commands.run("rootful-podman-version", podman + ["--version"])
        commands.run("rootful-podman-info", podman + ["info", "--debug"])
        commands.run("host-kernel", ["uname", "-a"])
        records = {}
        # Inspect and snapshot both before deciding anything about startup.
        for name, prefix in CONTAINERS:
            info, raw, unused = commands.run("inspect-" + name, podman + ["inspect", name], required=False)
            if info["exit_code"] == 0:
                records[name] = one_inspect(raw.decode("utf-8"))
        commands.run("inspect-existing-image", podman + ["image", "inspect", IMAGE])
        history = collect_history(args.history, output / "historical-records")
        state["history_records_copied"] = len(history["records"])
        state["history_read_limits"] = history["errors"]
        name, prefix = CONTAINERS[0]
        require(name in records, "original experiment container was not found; v2 is not selected automatically")
        record = records[name]
        cid = validate_container(record, name, prefix)
        state["container"] = cid
        state["launch_configuration"] = launch_configuration(record)
        snapshots = output / "original-products"
        snapshots.mkdir()
        observed = {}
        state["original_products"] = observed
        for label, source in PRODUCTS.items():
            destination = snapshots / label
            require(not destination.exists(), "refusing to overwrite product evidence")
            commands.run("copy-existing-" + label, podman + ["cp", cid + ":" + source, str(destination)])
            observed[label] = {"container_path": source, "sha256": digest(destination)}
        require(observed["binary"]["sha256"] == BINARY_SHA, "original binary differs from the archived build; do not rebuild it")
        require(observed["config"]["sha256"] == CONFIG_SHA, "original ConConfig differs from the archived build")
        # Old Python sources must be preserved before any restart or ABI gate.
        if args.extract_only or args.execute:
            state["source_extraction"] = extract_container_sources(commands, podman, cid, output, repo)
        # A capacity is taken from both actual binaries, never hardcoded to 1990.
        preflight, layouts = None, {}
        if shutil.which("readelf"):
            preflight = load_preflight(repo)
            abi_errors = []
            for label in ("binary", "runtime_object"):
                try:
                    unused, raw, unused2 = commands.run("host-dwarf-" + label, ["readelf", "--wide", "--debug-dump=info", str(snapshots / label)])
                    layout = preflight.runtime_layout(raw.decode("utf-8"))
                    (output / (label + "-observed-layout.json")).write_text(json.dumps(layout, indent=2) + "\n", encoding="utf-8")
                    layouts[label] = preflight.MemoryABI.from_layout(layout).layout
                except (OSError, ValueError, RuntimeError) as error:
                    abi_errors.append(label + ": " + str(error))
            state["host_dwarf_errors"] = abi_errors
            require(not abi_errors and set(layouts) == {"binary", "runtime_object"}, "could not prove both actual runtime layouts")
            require(layouts["binary"] == layouts["runtime_object"], "binary and selected runtime object layouts differ")
            state["runtime_layout"] = layouts["binary"]
            state["host_dwarf"] = "MATCHING_VERIFIED_RUNTIME_LAYOUTS"
            if "source_extraction" in state:
                old_driver = output / "original-source/tool/DBDS/run_PDS.py"
                state["historical_driver_audit"] = preflight.audit_driver_source(old_driver, layouts["binary"])
                (output / "A0-historical-driver-audit.json").write_text(json.dumps(state["historical_driver_audit"], indent=2) + "\n", encoding="utf-8")
        else:
            state["host_dwarf"] = "NOT_CHECKED: host readelf absent; container gate still mandatory"
        if args.extract_only:
            require(state["source_extraction"]["complete"], "old source/HEAD extraction is incomplete")
            require(preflight is not None and bool(layouts), "extracted sources preserved; actual ABI audit requires host readelf")
            state["status"] = "EXTRACTED_FOR_REVIEW_NO_BENCHMARK"
            state["ready_for_pilot"] = False
            return 0
        if not args.execute:
            state["status"] = "INSPECTED_NO_BENCHMARK"
            return 0
        startup = safe_idle_start(record)
        state["validated_idle_startup_argv"] = startup
        state["validated_security_configuration"] = validate_security_configuration(record)
        require(state["source_extraction"]["complete"], "old source extraction incomplete; do not start the container")
        require(state["source_extraction"]["head_matches_pinned"] and state["source_extraction"]["scoped_sources_match_pinned"],
                "extracted actual source differs from the fixed commit; review before execution")
        if record["State"]["Status"].lower() != "running":
            commands.run("start-existing-idle-container", podman + ["start", cid])
        unused, raw, unused2 = commands.run("inspect-running-container", podman + ["inspect", cid])
        current = one_inspect(raw.decode("utf-8"))
        require(current.get("State", {}).get("Running") is True, "existing container did not remain running")
        require(launch_configuration(current) == launch_configuration(record), "container launch configuration changed")
        identity_probe = ("import json,os,pathlib; print(json.dumps({'uid':os.getuid(),'euid':os.geteuid(),"
                          "'gid':os.getgid(),'egid':os.getegid(),'status':pathlib.Path('/proc/self/status').read_text()}))")
        unused, raw, unused2 = commands.run("container-effective-identity", podman + ["exec", cid, "python3", "-c", identity_probe])
        state["container_identity"] = json.loads(raw.decode("utf-8"))
        require(state["container_identity"].get("euid") == 0, "historical container must execute as root; no user or capability changes are permitted")
        unused, raw, unused2 = commands.run("live-upstream-head", podman + ["exec", cid, "git", "-C", "/workdir/PERIOD", "rev-parse", "HEAD"])
        require(raw.decode("utf-8").strip() == PINNED_COMMIT, "live source HEAD differs from the extracted fixed commit")
        unused, raw, unused2 = commands.run("live-upstream-worktree-status", podman + ["exec", cid, "git", "-C", "/workdir/PERIOD", "status", "--porcelain"])
        state["live_worktree_status"] = raw.decode("utf-8")
        unused, raw, unused2 = commands.run("live-upstream-source-diff", podman + ["exec", cid, "git", "-C", "/workdir/PERIOD", "diff", "HEAD", "--", "tool/DBDS", "tool/staticAnalysis/DBDS-INSTRU/llvm-mode/DBDSFunction.cpp"])
        require(not raw.strip(), "live official driver/generator/runtime source differs from fixed HEAD")
        # Observe, do not change, the current execution affinity. This is a new
        # paired-run baseline, not retroactive proof of historical per-run masks.
        probe = "import json,os,pathlib; print(json.dumps({'cpus':sorted(os.sched_getaffinity(0)),'status':pathlib.Path('/proc/self/status').read_text(),'ipc':pathlib.Path('/proc/sysvipc/shm').read_text()}))"
        unused, raw, unused2 = commands.run("container-current-affinity-ipc", podman + ["exec", cid, "python3", "-c", probe])
        actual = json.loads(raw.decode("utf-8"))
        require(actual["cpus"], "empty current CPU affinity")
        state["expected_cpus"] = ",".join(str(cpu) for cpu in actual["cpus"])
        state["affinity_provenance"] = "observed in selected original container before paired A/B/C; not historical per-run proof"
        stage = output / "harness"
        stage.mkdir()
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
        for directory in ("scripts", "tests"):
            shutil.copytree(str(repo / directory), str(stage / directory), ignore=ignore)
        container_root = "/tmp/cs340-rq1-resume-" + uuid.uuid4().hex
        state["container_new_work_root"] = container_root
        check = "import os,sys; p=sys.argv[1]; assert os.path.realpath(p)==p and not os.path.lexists(p), p"
        commands.run("check-unused-container-work-root", podman + ["exec", cid, "python3", "-c", check, container_root])
        commands.run("copy-new-harness-only", podman + ["cp", str(stage), cid + ":" + container_root])
        commands.run("linux-bash-syntax", podman + ["exec", cid, "/bin/bash", "-n", container_root + "/scripts/table2_scheduler_pilot.sh"])
        native = ["exec", "--env", "PYTHONDONTWRITEBYTECODE=1", cid, "/bin/bash",
                  container_root + "/scripts/table2_scheduler_pilot.sh", "--execute",
                  "--upstream", "/workdir/PERIOD", "--output-root", container_root + "/evidence",
                  "--expected-cpus", state["expected_cpus"]]
        state["benchmarks"] = "GATED_EXECUTION_REQUESTED; A0 audit only, inspect native evidence for actual A1/B/C"
        info, unused, unused2 = commands.run("gated-reorder3-pilot", podman + native, timeout=2400, required=False)
        require(info["exit_code"] == 0, "native environment/ABI/tests/A-B regression/pilot blocked; see native evidence")
        state["status"] = "NATIVE_WRAPPER_RETURNED_ZERO_VERIFY_STATUS"
        return 0
    except (Exception, KeyboardInterrupt) as error:
        state.update(status="BLOCKED", reason=type(error).__name__ + ": " + str(error))
        print("BLOCKED: " + state["reason"], file=sys.stderr)
        return 2
    finally:
        # Export even a failed ABI proof or partial pilot. Keep the existing
        # container and all new evidence in place; never stop/remove anything.
        if cid and container_root:
            exported, unused, unused2 = commands.run("export-native-evidence", podman + ["cp", cid + ":" + container_root + "/evidence", str(output / "native-evidence")], required=False)
            if exported["exit_code"] != 0:
                state.update(status="BLOCKED", evidence_export_error="native evidence export failed; originals remain in " + container_root)
        if cid:
            commands.run("inspect-container-after", podman + ["inspect", cid], required=False)
            for label, source in PRODUCTS.items():
                destination = output / ("post-" + label)
                info, unused, unused2 = commands.run("recheck-original-" + label, podman + ["cp", cid + ":" + source, str(destination)], required=False)
                if info["exit_code"] == 0 and label in state.get("original_products", {}):
                    try:
                        require(digest(destination) == state.get("original_products", {}).get(label, {}).get("sha256"),
                                "original " + label + " changed")
                    except Exception as error:
                        state.update(status="BLOCKED", integrity_error=str(error))
                elif label in state.get("original_products", {}):
                    state.update(status="BLOCKED", integrity_error="could not recheck original " + label)
            extraction = state.get("source_extraction", {})
            if extraction:
                state["source_integrity_rechecks"] = {}
                for relative in SOURCE_FILES:
                    before = extraction.get("files", {}).get(relative)
                    if not before:
                        continue
                    destination = output / "post-source" / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    info, unused, unused2 = commands.run("recheck-source-" + relative.replace("/", "-"),
                        podman + ["cp", cid + ":/workdir/PERIOD/" + relative, str(destination)], required=False)
                    try:
                        require(info["exit_code"] == 0 and destination.is_file(), "could not recheck original source " + relative)
                        after = digest(destination)
                        require(after == before["sha256"], "original source changed: " + relative)
                        state["source_integrity_rechecks"][relative] = {"status": "UNCHANGED", "sha256": after}
                    except (OSError, ValueError) as error:
                        state["source_integrity_rechecks"][relative] = {"status": "BLOCKED", "reason": str(error)}
                        state.update(status="BLOCKED", source_integrity_error=str(error))
        # Rootful cp preserves root-owned 0700 evidence directories. Change
        # ownership only inside this newly created host evidence directory.
        require(output.resolve().parent == output_root and output.name.startswith("table2-rootful-resume-"),
                "unexpected evidence directory; refusing ownership normalization")
        if privilege_prefix:
            owned, unused, unused2 = commands.run("own-new-evidence-only", privilege_prefix + ["chown", "-R", "--no-dereference", "--",
                str(os.getuid()) + ":" + str(os.getgid()), str(output)], required=False)
            state["evidence_ownership"] = {"action": "normalized-new-evidence-only", "exit_code": owned["exit_code"]}
            if owned["exit_code"] != 0:
                state.update(status="BLOCKED", ownership_error="could not normalize new exported evidence ownership")
        else:
            state["evidence_ownership"] = {"action": "root-host-no-chown-needed", "uid": os.getuid(), "gid": os.getgid()}
        try:
            state["native_results"] = read_native_results(output)
            if state["status"] == "NATIVE_WRAPPER_RETURNED_ZERO_VERIFY_STATUS":
                state["status"] = "PILOT_PASSED" if native_pilot_passed(state["native_results"]) else "BLOCKED"
        except (OSError, ValueError) as error:
            state.update(status="BLOCKED", reason="native evidence unavailable: " + str(error))
        state["finished_at"] = utc()
        state["formal_four_program_batch"] = "NOT_STARTED"
        (output / "resume-summary.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        report = ["# Rootful Podman reorder_3 resume", "", "Status: **" + state["status"] + "**", "",
                  "| Arm | Validation | First bug | Total | Buggy | Timeouts |", "| --- | --- | ---: | ---: | ---: | ---: |"]
        modern = args.execute or args.extract_only or state.get("native_results", {}).get("reference_role") == "ABI_ONLY_CORRECTED_PARALLEL"
        for arm in (("A0", "A1", "B", "C") if modern else ("A", "B", "C")):
            run = state.get("native_results", {}).get("runs", {}).get(arm, {})
            if arm == "A0" and "tool/DBDS/run_PDS.py" in state.get("source_extraction", {}).get("files", {}):
                run = dict(run, validation="AUDIT_ONLY_NOT_RUN")
            report.append("| " + " | ".join(str(v) for v in (arm, run.get("validation", "NOT_RUN_OR_UNVERIFIED"),
                run.get("first_bug_schedule"), run.get("total_schedules"), run.get("buggy_schedules"), run.get("timeouts"))) + " |")
        report += ["", "Reference only: historical Parallel 6/27/6/0; Serial paper 10/30/10. These are not measured values.",
                   "", "A0 is historical-source audit only. A1, when present, is an ABI-only corrected Parallel reference, not the unchanged old driver.",
                   "", "Actual launch configuration, masks, original-product hashes and all command outputs are preserved.",
                   "Restarting the old container preserves its writable layer and creation configuration; process/IPC state is freshly observed.",
                   "No formal four-program batch was started. A passed pilot is for human review, not automatic batch authorization.",
                   "See resume-summary.json and native-evidence for the full result and any blocking reason."]
        (output / "RESUME_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
        try:
            write_checksums(output)
        except OSError as error:
            state["status"] = "BLOCKED"
            state["checksum_error"] = str(error)
            (output / "resume-summary.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            report[2] = "Status: **BLOCKED**"
            report += ["", "Checksum collection failed: " + str(error)]
            (output / "RESUME_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
            print("Evidence checksum blocked by file permissions: " + str(error), file=sys.stderr)
        print("Final status: " + state["status"] + "\nEvidence: " + str(output), flush=True)
        return 0 if state["status"] in ("INSPECTED_NO_BENCHMARK", "EXTRACTED_FOR_REVIEW_NO_BENCHMARK", "PILOT_PASSED") else 2


if __name__ == "__main__":
    sys.exit(main())
