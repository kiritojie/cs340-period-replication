#!/usr/bin/env bash
# Future, explicitly invoked Linux-container pilot. Never builds a benchmark.
# Default: preflight only. --execute is required before any A1/B/C target launch.
set -euo pipefail
export LANG=C.UTF-8
export PYTHONDONTWRITEBYTECODE=1

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
UPSTREAM=/workdir/PERIOD
DRIVER="$HERE/run_scheduler_comparison.py"
REFERENCE_DRIVER="$HERE/run_abi_parallel_reference.py"
OUTPUT_ROOT=/lab/evidence
BINARY=
CONFIG=
RUNTIME_OBJECT=
PERMISSION_PROOF=
EXECUTE=0
EXPECTED_CPUS=0-7
EXPECTED_CPUS_SOURCE=legacy_default_0-7

usage() {
  cat <<'EOF'
Usage: bash table2_scheduler_pilot.sh [--execute] [options]
  --upstream PATH        Existing fixed PERIOD checkout (/workdir/PERIOD)
  --driver PATH          Unified adapter (sibling run_scheduler_comparison.py)
  --reference-driver PATH ABI-only corrected Parallel reference (A1)
  --binary PATH          Existing reorder_3_bad; never rebuilt
  --config PATH          Existing ConConfig.reorder_3_bad
  --runtime-object PATH Existing DBDSFunction.o with runtime DWARF
  --permission-proof PATH Reuse a separately measured proof; revalidate live state
  --output-root PATH     Parent for a new, unique evidence directory
  --expected-cpus LIST   Expected actual affinity (default 0-7; never sets affinity)

Without --execute, only preflight evidence is collected. Even with --execute,
any missing provenance/ABI/environment proof blocks all target launches.
Do not run another PERIOD driver in the same IPC namespace concurrently.
EOF
}

while (($#)); do
  case "$1" in
    --execute) EXECUTE=1; shift ;;
    --upstream|--driver|--reference-driver|--binary|--config|--runtime-object|--permission-proof|--output-root|--expected-cpus)
      (($# >= 2)) || { usage >&2; exit 2; }
      case "$1" in
        --upstream) UPSTREAM=$2 ;; --driver) DRIVER=$2 ;;
        --reference-driver) REFERENCE_DRIVER=$2 ;;
        --binary) BINARY=$2 ;; --config) CONFIG=$2 ;;
        --runtime-object) RUNTIME_OBJECT=$2 ;; --output-root) OUTPUT_ROOT=$2 ;;
        --permission-proof) PERMISSION_PROOF=$2 ;;
        --expected-cpus) EXPECTED_CPUS=$2; EXPECTED_CPUS_SOURCE=explicit_cli_expected_cpus ;;
      esac
      shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || {
  echo 'BLOCKED: run preflight inside the existing x86_64 Linux container; no target started.' >&2
  exit 2
}
for tool in python3 git readelf sha256sum timeout flock taskset ldd realpath; do
  command -v "$tool" >/dev/null || { printf 'BLOCKED: missing %s\n' "$tool" >&2; exit 2; }
done
# A root process needs neither sudo's credential switching nor CAP_SETUID.
# Nonroot execution retains noninteractive sudo and must pass the same live gate.
if [[ "$EUID" != 0 ]]; then
  command -v sudo >/dev/null || { echo 'BLOCKED: nonroot execution requires sudo.' >&2; exit 2; }
fi
UPSTREAM=$(realpath -e -- "$UPSTREAM")
DRIVER=$(realpath -e -- "$DRIVER")
REFERENCE_DRIVER=$(realpath -e -- "$REFERENCE_DRIVER")
BINARY=$(realpath -e -- "${BINARY:-$UPSTREAM/evaluation/CS/reorder_3/reorder_3_bad}")
CONFIG=$(realpath -e -- "${CONFIG:-$UPSTREAM/evaluation/CS/reorder_3/ConConfig.reorder_3_bad}")
RUNTIME_OBJECT=$(realpath -e -- "${RUNTIME_OBJECT:-$UPSTREAM/tool/staticAnalysis/DBDS-INSTRU/DBDSFunction.o}")
mkdir -p -- "$OUTPUT_ROOT"
OUTPUT_ROOT=$(realpath -e -- "$OUTPUT_ROOT")
ROOT=$(mktemp -d "$OUTPUT_ROOT/table2-scheduler-pilot-$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")
STATE=BLOCKED
printf '%s\n' "$ROOT"

finish() {
  local rc=$?
  trap - EXIT
  if [[ "$rc" != 0 && "$STATE" != BLOCKED* ]]; then
    STATE="BLOCKED_${STATE}"
  fi
  printf '%s\n' "$STATE" > "$ROOT/status.txt"
  printf '%s\n' "$rc" > "$ROOT/wrapper-exit-code.txt"
  date -u +%FT%TZ > "$ROOT/finished-at.txt"
  python3 - "$ROOT" <<'PY'
import hashlib
import sys
from pathlib import Path
root = Path(sys.argv[1])
entries = []
for path in sorted(root.rglob('*')):
    if path.is_file() and path.name != 'SHA256SUMS':
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        entries.append(digest.hexdigest() + '  ' + str(path.relative_to(root)))
(root / 'SHA256SUMS').write_text('\n'.join(entries) + '\n')
PY
  printf '%s: %s\n' "$STATE" "$ROOT"
  exit "$rc"
}
trap finish EXIT
date -u +%FT%TZ > "$ROOT/started-at.txt"

# This lock coordinates this pilot wrapper only. IPC/proc checks below also
# detect other attached users; no existing segment is removed or overwritten.
exec 9>/tmp/cs340-period-ipc1111.lock
flock -n 9 || { echo 'BLOCKED: another pilot wrapper owns IPC1111 lock.' >&2; exit 2; }

export ROOT_DIR="$UPSTREAM"
export PATH="$ROOT_DIR/clang+llvm/bin:$PATH"
export LD_LIBRARY_PATH="$ROOT_DIR/clang+llvm/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
{
  date -u +%FT%TZ
  uname -a
  cat /etc/os-release
  python3 --version
  git -C "$UPSTREAM" rev-parse HEAD
  printf 'container_hostname=%s\n' "$(hostname)"
  taskset -pc $$
  printf 'cpu_model='; sed -n 's/^model name[[:space:]]*: //p' /proc/cpuinfo | head -1
  printf 'cpu_max='; cat /sys/fs/cgroup/cpu.max 2>/dev/null || true
  printf 'memory_max='; cat /sys/fs/cgroup/memory.max 2>/dev/null || true
  sed -n '/^Uid:/p;/^Gid:/p;/^Cap/p;/^NoNewPrivs:/p;/^Seccomp/p' /proc/self/status
  cat /proc/self/cgroup
  printf 'ROOT_DIR=%s\nPATH=%s\nLD_LIBRARY_PATH=%s\n' "$ROOT_DIR" "$PATH" "$LD_LIBRARY_PATH"
  printf 'depth=3\nschedule_budget=10000\ntarget_timeout_s=5\nouter_timeout_s=600\nouter_kill_after_s=20\n'
  printf 'execute_requested=%s\n' "$EXECUTE"
  printf 'expected_cpu_list=%s\nexpected_cpu_list_source=%s\n' "$EXPECTED_CPUS" "$EXPECTED_CPUS_SOURCE"
} > "$ROOT/environment.txt" 2>&1
ldd "$BINARY" > "$ROOT/linked-libraries.txt" 2>&1
if grep -q 'not found' "$ROOT/linked-libraries.txt"; then
  echo 'BLOCKED: unresolved benchmark shared libraries.' >&2
  exit 2
fi
(cd -- "$HERE/.." && python3 -B -m unittest discover -s tests -v) \
  > "$ROOT/offline-tests.stdout.log" 2> "$ROOT/offline-tests.stderr.log" || {
    echo 'BLOCKED: offline generator/controller/ABI/evidence checks failed.' >&2; exit 2;
  }
grep -Eq 'Ran [1-9][0-9]* tests?' "$ROOT/offline-tests.stderr.log" || {
  echo 'BLOCKED: no offline tests were discovered.' >&2; exit 2;
}
sha256sum "$DRIVER" "$REFERENCE_DRIVER" "$HERE/period_shared_memory.py" \
  "$HERE/table2_scheduler_pilot.sh" "$HERE/table2_scheduler_preflight.py" \
  "$HERE/table2_scheduler_evidence.py" "$HERE/trace_period_driver.py" \
  "$HERE/table2_scheduler_affinity.py" "$HERE/table2_scheduler_permissions.py" \
  > "$ROOT/harness-identity.sha256"
python3 "$HERE/table2_scheduler_preflight.py" \
  --binary "$BINARY" --config "$CONFIG" --runtime-object "$RUNTIME_OBJECT" \
  --runtime-source "$UPSTREAM/tool/staticAnalysis/DBDS-INSTRU/llvm-mode/DBDSFunction.cpp" \
  --upstream "$UPSTREAM" --driver "$DRIVER" --reference-driver "$REFERENCE_DRIVER" \
  --abi-profile runtime-dwarf --output "$ROOT/abi-proof.json" \
  > "$ROOT/preflight.stdout.log" 2> "$ROOT/preflight.stderr.log" || {
    echo 'BLOCKED: ABI/provenance proof failed; see abi-proof.json. No target started.' >&2
    exit 2
  }
ABI_MAP_SIZE=$(python3 - "$ROOT/abi-proof.json" <<'PY'
import json
import sys
from pathlib import Path
proof = json.loads(Path(sys.argv[1]).read_text())
if proof.get('schema') != 'cs340-period-abi-proof-v2' or proof.get('abi_profile') != 'runtime-dwarf' or proof.get('status') != 'PASS':
    raise SystemExit('BLOCKED: runtime-dwarf v2 proof is required')
size = proof.get('map_size')
if type(size) is not int or size <= 0 or proof.get('layout', {}).get('byte_size') != size:
    raise SystemExit('BLOCKED: inconsistent runtime-dwarf mapping size')
print(size)
PY
)

# A0 is a byte-preserved historical source audit, not an execution arm. It may
# have mismatched offsets even though the existing benchmark binary is valid.
mkdir -p -- "$ROOT/A0-historical-driver/source"
for source_name in run_PDS.py run_OldPDS.py sched.py pds.py bp_sched.py sbp_sched.py \
  sbp_sched_mixed_end.py external_def.py interleaving.py ipc.py; do
  cp -p -- "$UPSTREAM/tool/DBDS/$source_name" "$ROOT/A0-historical-driver/source/$source_name"
done
cp -p -- "$UPSTREAM/tool/staticAnalysis/DBDS-INSTRU/llvm-mode/DBDSFunction.cpp" \
  "$ROOT/A0-historical-driver/source/DBDSFunction.cpp"
python3 - "$HERE" "$UPSTREAM/tool/DBDS/run_PDS.py" "$ROOT/abi-proof.json" \
  "$ROOT/A0-historical-driver/audit.json" <<'PY'
import json
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from table2_scheduler_preflight import audit_driver_source
proof = json.loads(Path(sys.argv[3]).read_text())
result = audit_driver_source(Path(sys.argv[2]), proof['layout'])
result['execution'] = 'AUDIT_ONLY_NOT_RUN'
result['reference_role'] = 'A0_historical_raw_driver'
Path(sys.argv[4]).write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
PY
printf 'AUDIT_ONLY_NOT_RUN\n' > "$ROOT/A0-historical-driver/status.txt"
sha256sum "$ROOT"/A0-historical-driver/source/* > "$ROOT/A0-historical-driver/source.sha256"
python3 -c 'import numpy; import sysv_ipc' > "$ROOT/python-dependencies.txt" 2>&1 || {
  echo 'BLOCKED: required Python modules unavailable.' >&2; exit 2;
}
# This is a live acceptance gate, not a substitute success after skipping sudo.
# It records credentials/capabilities, TERM/KILL/timeout/descendant cleanup and
# SCHED_DEADLINE syscall readback/restoration in harmless, bounded helpers.
if [[ -n "$PERMISSION_PROOF" ]]; then
  PERMISSION_PROOF=$(realpath -e -- "$PERMISSION_PROOF")
  python3 "$HERE/table2_scheduler_permissions.py" --validate-proof "$PERMISSION_PROOF" \
    > "$ROOT/permission-probe.stdout.log" 2> "$ROOT/permission-probe.stderr.log" || {
      echo 'BLOCKED: measured permission proof or current security state changed.' >&2
      exit 2
    }
  cp -p -- "$PERMISSION_PROOF" "$ROOT/permission-proof.json"
  printf '%s\n' "$PERMISSION_PROOF" > "$ROOT/permission-proof-origin.txt"
else
  python3 "$HERE/table2_scheduler_permissions.py" --output "$ROOT/permission-proof.json" \
    > "$ROOT/permission-probe.stdout.log" 2> "$ROOT/permission-probe.stderr.log" || {
      echo 'BLOCKED: actual permission acceptance failed; see permission-proof.json.' >&2
      exit 2
    }
fi
permission_gate() {
  python3 "$HERE/table2_scheduler_permissions.py" --validate-proof "$ROOT/permission-proof.json"
}
permission_gate > "$ROOT/permission-acceptance.txt" 2>&1

ipc_gate() {
  python3 "$HERE/table2_scheduler_affinity.py" --expected-cpus "$EXPECTED_CPUS" || return 2
  python3 - "$ABI_MAP_SIZE" <<'PY'
import os
import sys
from pathlib import Path
expected_size = int(sys.argv[1])
path = Path('/proc/sysvipc/shm')
if not path.is_file():
    raise SystemExit('BLOCKED: cannot inspect SysV IPC state')
rows = path.read_text().splitlines()
header = rows[0].split()
for row in rows[1:]:
    fields = dict(zip(header, row.split()))
    if int(fields['key']) == 1111:
        if int(fields['nattch']) != 0 or int(fields['size']) != expected_size:
            raise SystemExit('BLOCKED: IPC1111 attached or has incompatible segment size; no automatic ipcrm')
for process in Path('/proc').iterdir():
    if not process.name.isdigit() or int(process.name) == os.getpid():
        continue
    try:
        argv = (process / 'cmdline').read_bytes().split(b'\0')
        argv = [arg.decode('utf-8', errors='replace') for arg in argv if arg]
        if not argv:
            continue
        executable = Path(argv[0]).name
        target = executable == 'reorder_3_bad'
        driver = executable.startswith('python') and any(
            Path(arg).name in ('run_PDS.py', 'run_abi_parallel_reference.py', 'run_scheduler_comparison.py', 'trace_period_driver.py')
            for arg in argv[1:3])
        if target or driver:
            raise SystemExit('BLOCKED: active PERIOD process PID ' + process.name)
    except (FileNotFoundError, ProcessLookupError):
        continue
    except PermissionError:
        raise SystemExit('BLOCKED: cannot inspect process ' + process.name)
print('PASS: no active PERIOD process or attached incompatible IPC1111 segment')
PY
}
ipc_gate > "$ROOT/ipc-before.txt" 2>&1
if [[ "$EXECUTE" == 0 ]]; then
  STATE=PREFLIGHT_PASSED_NO_BENCHMARK
  exit 0
fi

run_one() {
  local name=$1 mode=$2 run work rc before after
  local -a command_line
  run="$ROOT/$name"
  work="$run/work"
  mkdir -p -- "$work"
  cp -p -- "$BINARY" "$work/reorder_3_bad"
  cp -p -- "$CONFIG" "$work/ConConfig.reorder_3_bad"
  export Con_PATH="$work/ConConfig.reorder_3_bad"
  printf '%s  %s\n' \
    ed2d13809b87a00eaaba76ac0f1faf4871a489a0960993e5963dc89b4bb13db9 "$work/reorder_3_bad" \
    0ed49729a85b862b9a918c62f3826f3c56b89ec825ae3fe35a28f21f253d7d4d "$work/ConConfig.reorder_3_bad" \
    | sha256sum -c - > "$run/frozen-input-check.txt" 2>&1
  sha256sum "$work/reorder_3_bad" "$work/ConConfig.reorder_3_bad" > "$run/input.sha256"
  permission_gate > "$run/permission-before.txt" 2>&1 || return 2
  ipc_gate > "$run/ipc-before.txt" 2>&1
  if [[ "$mode" == reference ]]; then
    command_line=(python3 -u "$HERE/trace_period_driver.py" --trace "$run/actual-yield.jsonl"
      --expected-source "$UPSTREAM/tool/DBDS/run_PDS.py" -- "$REFERENCE_DRIVER" --period-root "$UPSTREAM"
      --depth 3 --budget 10000 --target-timeout 5 --abi-proof "$ROOT/abi-proof.json"
      --permission-proof "$ROOT/permission-proof.json"
      --emit-adapted-source "$run/abi-only-source.py" --metadata "$run/adapter-metadata.json" -- ./reorder_3_bad)
  else
    command_line=(python3 -u "$HERE/trace_period_driver.py" --trace "$run/actual-yield.jsonl"
      --expected-source "$UPSTREAM/tool/DBDS/run_PDS.py" -- "$DRIVER" --scheduler "$mode" --period-root "$UPSTREAM"
      --depth 3 --budget 10000 --target-timeout 5 --abi-proof "$ROOT/abi-proof.json"
      --permission-proof "$ROOT/permission-proof.json"
      --emit-adapted-source "$run/adapted-source.py" --metadata "$run/adapter-metadata.json" -- ./reorder_3_bad)
  fi
  {
    printf 'cwd=%q\n' "$work"
    printf 'Con_PATH=%q\n' "$Con_PATH"
    printf 'timeout --signal=TERM --kill-after=20s 600s '
    printf '%q ' "${command_line[@]}"
    printf '\n'
  } > "$run/command.txt"
  date -u +%FT%TZ > "$run/started-at.txt"
  before=$(date +%s%N)
  set +e
  (cd -- "$work" && timeout --signal=TERM --kill-after=20s 600s "${command_line[@]}") \
    > "$run/stdout.log" 2> "$run/stderr.log"
  rc=$?
  set -e
  after=$(date +%s%N)
  date -u +%FT%TZ > "$run/finished-at.txt"
  printf '%s\n' "$rc" > "$run/exit-code.txt"
  printf 'external_wall_ns=%s\n' "$((after-before))" > "$run/walltime.txt"
  sha256sum -c "$run/input.sha256" > "$run/input-integrity.txt" 2>&1 || return 2
  permission_gate > "$run/permission-after.txt" 2>&1 || return 2
  ipc_gate > "$run/ipc-after.txt" 2>&1 || return 2
  [[ "$rc" == 0 ]] || {
    printf 'BLOCKED: %s exit=%s; output preserved, later runs not started.\n' "$name" "$rc" >&2
    return 2
  }
}

# A1 retains the official Parallel controller with the validated Python ABI
# adaptation and the same permission/process-control wrapper as B and C.
# The original raw A0 driver is preserved above and is never run.
STATE=RUNNING_A1
run_one A1-abi-corrected-parallel reference
python3 "$HERE/table2_scheduler_evidence.py" analyze --run-dir "$ROOT/A1-abi-corrected-parallel" \
  --mode reference --baseline abi-corrected --output "$ROOT/A1-validation.json"
STATE=RUNNING_B
run_one B-adapted-parallel parallel
python3 "$HERE/table2_scheduler_evidence.py" compare \
  --reference-dir "$ROOT/A1-abi-corrected-parallel" --candidate-dir "$ROOT/B-adapted-parallel" \
  --baseline abi-corrected --output "$ROOT/A1B-regression.json"
STATE=RUNNING_C
run_one C-adapted-serial serial
python3 "$HERE/table2_scheduler_evidence.py" analyze --run-dir "$ROOT/C-adapted-serial" \
  --mode serial --baseline abi-corrected --output "$ROOT/C-validation.json"
STATE=PILOT_PASSED
