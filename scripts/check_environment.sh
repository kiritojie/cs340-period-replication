#!/usr/bin/env bash
# Read-only host preflight. Bash 3.2+; no installs, image pulls or containers.
# Exit 0 means the inventory completed, not that PERIOD is runnable.
set -u
export LC_ALL=C

section() { printf '\n=== %s ===\n' "$1"; }
probe() {
    printf '$'
    printf ' %s' "$@"
    printf '\n'
    "$@" 2>&1
    local status=$?
    printf '[exit_code=%s]\n' "$status"
    return 0
}

# Never let an unreachable Docker endpoint block the report. Suppress Docker
# stderr because context endpoints can contain private connection information.
# Python is optional; if neither it nor timeout is available, skip the probe.
docker_probe() {
    printf '$'
    printf ' %s' "$@"
    printf '\n'
    local status
    if command -v python3 >/dev/null 2>&1; then
        python3 - "$@" <<'PY'
import subprocess
import sys
try:
    result = subprocess.run(sys.argv[1:], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=10, universal_newlines=True)
    print(result.stdout, end="")
    if result.stderr:
        print("[stderr omitted: Docker endpoint details may be private]")
    print("[exit_code=%d]" % result.returncode)
    sys.exit(result.returncode if result.returncode >= 0 else 1)
except subprocess.TimeoutExpired:
    print("[timeout=10s; exit_code=124]")
    sys.exit(124)
except OSError as error:
    print("[execution failed: %s; exit_code=125]" % type(error).__name__)
    sys.exit(125)
PY
        status=$?
    elif command -v timeout >/dev/null 2>&1; then
        timeout 10 "$@" 2>/dev/null
        status=$?
        printf '[exit_code=%s; 124 means timeout; stderr omitted]\n' "$status"
    elif command -v gtimeout >/dev/null 2>&1; then
        gtimeout 10 "$@" 2>/dev/null
        status=$?
        printf '[exit_code=%s; 124 means timeout; stderr omitted]\n' "$status"
    else
        printf '[SKIPPED: no python3/timeout/gtimeout for a bounded Docker probe]\n'
        status=125
    fi
    return "$status"
}

section 'Report metadata'
printf 'UTC: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
printf 'Asia/Shanghai: %s\n' "$(TZ=Asia/Shanghai date '+%Y-%m-%dT%H:%M:%S%z')"
printf 'Analysis reference: wcventure/PERIOD@cb8deb9a176e5bb292d70d46557dd61dc0e98069\n'
printf 'Actual PERIOD checkout: not inferred here; record git rev-parse HEAD in that checkout.\n'
printf 'Scope: read-only inventory; no software installation or scheduler changes.\n'

section 'Host operating system and CPU'
host_os=$(uname -s)
host_arch=$(uname -m)
printf 'OS family: %s\nCPU architecture: %s\n' "$host_os" "$host_arch"
probe uname -r
probe uname -v
case "$host_os" in
    Darwin)
        probe sw_vers
        probe sysctl -n hw.logicalcpu
        # getconf also works when the execution environment denies sysctl.
        if command -v getconf >/dev/null 2>&1; then
            probe getconf _NPROCESSORS_ONLN
        fi
        printf 'Linux kernel: NOT APPLICABLE (host uses Darwin).\n'
        printf 'Native official PERIOD execution: BLOCKED (requires Linux scheduling APIs).\n'
        ;;
    Linux)
        if [ -r /etc/os-release ]; then
            # Do not source distribution metadata as shell code.
            awk '/^(NAME|VERSION|ID|VERSION_ID|PRETTY_NAME)=/' /etc/os-release
        else
            printf '/etc/os-release: unavailable\n'
        fi
        if command -v getconf >/dev/null 2>&1; then
            probe getconf _NPROCESSORS_ONLN
        fi
        printf 'Linux kernel: %s\n' "$(uname -r)"
        printf 'Native PERIOD readiness: UNVERIFIED (kernel version alone is insufficient).\n'
        ;;
    *)
        printf 'Linux kernel: NOT APPLICABLE (non-Linux host).\n'
        printf 'Native official PERIOD execution: BLOCKED (Linux required).\n'
        ;;
esac
case "$host_arch" in
    x86_64|amd64) printf 'Architecture matches the official x86_64 Linux LLVM binary target.\n' ;;
    *) printf 'Architecture differs from the official x86_64 Linux LLVM binary target.\n' ;;
esac

section 'Build and analysis commands'
for tool in git python3 clang clang++ llvm-config cmake make; do
    if command -v "$tool" >/dev/null 2>&1; then
        probe "$tool" --version
    else
        printf '%s: NOT FOUND in PATH\n' "$tool"
    fi
done

section 'Python dependency imports'
if command -v python3 >/dev/null 2>&1; then
    python3 - <<'PY'
import importlib
import sys
print("Python runtime: %s" % sys.version.replace("\n", " "))
for name in ("numpy", "sysv_ipc"):
    try:
        module = importlib.import_module(name)
        print("%s: IMPORT OK; version=%s" % (name, getattr(module, "__version__", "unknown")))
    except Exception as error:
        print("%s: IMPORT FAILED; %s: %s" % (name, type(error).__name__, error))
PY
    printf '[exit_code=%s; module failures are reported individually]\n' "$?"
else
    printf 'SKIPPED: python3 is unavailable.\n'
fi

section 'Linux scheduling prerequisites (read only)'
if [ "$host_os" = Linux ]; then
    probe id -u
    if [ -r /proc/sys/kernel/sched_rt_runtime_us ]; then
        printf 'sched_rt_runtime_us: '
        cat /proc/sys/kernel/sched_rt_runtime_us
    else
        printf 'sched_rt_runtime_us: unavailable\n'
    fi
    if [ -r /proc/self/status ]; then
        awk '/^(CapEff|Cpus_allowed_list):/' /proc/self/status
    fi
    if command -v chrt >/dev/null 2>&1; then
        probe chrt --max
    else
        printf 'chrt: NOT FOUND; policy listing unavailable.\n'
    fi
    printf 'SCHED_DEADLINE execution/CPU affinity/CAP_SYS_NICE: NOT VALIDATED.\n'
    printf 'No sched_setattr call or real-time policy change was attempted.\n'
else
    printf 'SCHED_DEADLINE and Linux /proc scheduling data: NOT APPLICABLE on %s.\n' "$host_os"
fi

section 'Docker client and daemon'
if command -v docker >/dev/null 2>&1; then
    docker_probe docker --version || true
    if docker_probe docker info --format 'OSType={{.OSType}} Architecture={{.Architecture}} KernelVersion={{.KernelVersion}} ServerVersion={{.ServerVersion}}'; then
        printf 'Docker daemon: REACHABLE in the current context.\n'
        printf 'Daemon kernel above belongs to the Docker environment, not necessarily the host.\n'
        section 'Locally available PERIOD images (no pull)'
        for image in period:latest wcventure/period:stable; do
            if docker_probe docker image inspect --format 'ID={{.Id}} OS={{.Os}} Architecture={{.Architecture}}' "$image"; then
                printf '%s: present locally; compatibility not yet validated.\n' "$image"
            else
                printf '%s: not inspectable; absence/access/timeout must be distinguished manually.\n' "$image"
            fi
        done
    else
        printf 'Docker daemon: NOT VERIFIED (probe failed, timed out, or could not be bounded).\n'
        printf 'Local PERIOD image checks: SKIPPED.\n'
    fi
else
    printf 'Docker CLI: NOT FOUND in PATH.\n'
    printf 'Docker daemon and local PERIOD images: NOT CHECKED without the CLI.\n'
fi

section 'Interpretation'
printf 'Official baseline: multicore Ubuntu >=18.04, Linux kernel >=4.x, Docker >18.09.7.\n'
printf 'Official Dockerfile: Ubuntu 18.04; LLVM 10 x86_64 Linux toolchain.\n'
printf 'Official container launch uses --privileged; Linux SCHED_DEADLINE needs runtime validation.\n'
printf 'Docker CLI/daemon availability does not prove scheduler privileges or example success.\n'
printf 'Inventory completed. No doubleFree build, systematic test or replay was performed by this script.\n'
exit 0
