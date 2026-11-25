#!/usr/bin/env bash
# CS340 Extension Experiment (Single-Factor):
#   Factor varied : Available logical CPU cores via taskset (1 / 2 / 4 / 8 cores)
#   Held constant : Same host, same container, same instrumented binary (CS.reorder_10_bad),
#                   same PERIOD flags (-y -d 3), same clean initial output directory.
#
# Motivation:
#   In Table 2 Segment 1 (reorder_10, 8 logical CPUs), total schedules stayed pinned at 2350
#   (zero variance), whereas error interleavings varied (89/90/93) and wall time varied 2.65x.
#   Varying only the CPU affinity mask tests whether core contention / parallel execution in
#   the mixed-end period drives error-interleaving variance, timeouts, or runtime spread.
#
# Usage (inside the PERIOD container):
#   bash scripts/extension_cpu_affinity.sh
#   ROUNDS=10 CORE_MASKS="0 0-1 0-3 0-7" bash scripts/extension_cpu_affinity.sh
#
# All paths are configurable via environment variables (no hard-coded local paths).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PERIOD_ROOT="${PERIOD_ROOT:-/workdir/PERIOD}"
BENCH_DIR="${BENCH_DIR:-$PERIOD_ROOT/evaluation/CS/reorder_10}"
PROG="${PROG:-reorder_10_bad}"
DEPTH="${DEPTH:-3}"
ROUNDS="${ROUNDS:-5}"
TIMEOUT_SEC="${TIMEOUT_SEC:-600}"
CORE_MASKS="${CORE_MASKS:-0 0-1 0-3 0-7}"
TS_UTC="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="${OUT_DIR:-$PWD/extension-cpu-affinity-r${ROUNDS}-${TS_UTC}}"

mkdir -p "$OUT_DIR"

export ROOT_DIR="$PERIOD_ROOT"
export PATH="$ROOT_DIR/clang+llvm/bin:$PATH"
export LD_LIBRARY_PATH="$ROOT_DIR/clang+llvm/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

count_mask_cpus() {
  # Count logical CPUs in a taskset range spec like "0", "0-1", "0-3,6-7"
  local mask="$1" total=0 part a b
  IFS=',' read -r -a parts <<< "$mask"
  for part in "${parts[@]}"; do
    if [[ "$part" == *-* ]]; then
      a="${part%-*}"
      b="${part#*-}"
      total=$((total + b - a + 1))
    else
      total=$((total + 1))
    fi
  done
  echo "$total"
}

AVAIL_CPUS="$(nproc)"

# 1. Capture execution environment & verify taskset inheritance across sudo
{
  echo "utc_started        : $(date -u +%FT%TZ)"
  echo "kernel             : $(uname -r)"
  echo "container          : $(hostname)"
  echo "default_affinity   : $(taskset -pc $$ | sed 's/.*: //')"
  echo "nproc_available    : $AVAIL_CPUS"
  echo "cpu_capacity_uniq  : $(cat /sys/devices/system/cpu/cpu*/cpu_capacity 2>/dev/null | sort -u | tr '\n' ' ' || echo 'N/A')"
  echo "deadline_probe_rc  : $(chrt -d --sched-period 20000000 --sched-runtime 10000000 --sched-deadline 20000000 0 sleep 0.1 >/dev/null 2>&1; echo $?)"
  echo "sudo_taskset_check : $(taskset -c 0 sudo bash -c 'taskset -pc $$' 2>/dev/null | sed 's/.*: //' || echo 'check_failed')"
  echo "period_root        : $PERIOD_ROOT"
  echo "period_git_head    : $(git -C "$PERIOD_ROOT" rev-parse HEAD 2>/dev/null || echo 'unknown')"
  echo "benchmark_dir      : $BENCH_DIR"
  echo "program            : $PROG"
  echo "depth              : $DEPTH"
  echo "rounds_per_mask    : $ROUNDS"
  echo "core_masks         : $CORE_MASKS"
  echo "timeout_sec        : $TIMEOUT_SEC"
} > "$OUT_DIR/exec-env.txt"

echo "===== Extension Preflight ====="
cat "$OUT_DIR/exec-env.txt"

# 2. Build binary once if missing (all masks share the exact same binary)
cd "$BENCH_DIR" || { echo "ERROR: benchmark directory not found: $BENCH_DIR" >&2; exit 1; }
if [ ! -x "./$PROG" ]; then
  echo "===== Building $PROG from clean state ====="
  {
    ./cleanDIR.sh
    clang -g -emit-llvm -c "./${PROG}.c" -o "${PROG}.bc"
    "$ROOT_DIR/tool/staticAnalysis/staticAnalysis.sh" "$PROG"
    export Con_PATH="$BENCH_DIR/ConConfig.$PROG"
    "$ROOT_DIR/tool/staticAnalysis/DBDS-INSTRU/dbds-clang-fast++" -g "./${PROG}.bc" -o "$PROG" -lpthread -ldl
  } > "$OUT_DIR/build.log" 2>&1
  echo "build_rc=$?" >> "$OUT_DIR/build.log"
fi

BIN_SHA="$(sha256sum "./$PROG" | cut -d' ' -f1)"
KP_COUNT="$(wc -l < "./ConConfig.$PROG" 2>/dev/null || echo 0)"
{
  echo "binary_path=$BENCH_DIR/$PROG"
  echo "binary_sha256=$BIN_SHA"
  echo "keypoints_lines=$KP_COUNT"
} > "$OUT_DIR/binary-identity.txt"
echo "===== Binary Identity ====="
cat "$OUT_DIR/binary-identity.txt"

# 3. Prepare TSV header
SUMMARY_TSV="$OUT_DIR/rounds-summary.tsv"
printf 'program\tround\tcpu_mask\tcpu_count\trc\tgate_pass\tschedules\terror_interleavings\ttimeouts\tfirst_error\tdry_run_runtime\tinternal_time_s\texternal_wall_s\n' > "$SUMMARY_TSV"

# 4. Run single-factor sweep across CPU affinity masks
export Con_PATH="$BENCH_DIR/ConConfig.$PROG"

for mask in $CORE_MASKS; do
  ncpu="$(count_mask_cpus "$mask")"
  if [ "$ncpu" -gt "$AVAIL_CPUS" ]; then
    echo "[SKIP] mask=$mask requires $ncpu CPUs, only $AVAIL_CPUS available."
    continue
  fi

  mask_tag="cpus-${ncpu}_mask-${mask}"
  echo "===== Running mask=$mask ($ncpu logical CPUs) x $ROUNDS rounds ====="

  r=1
  while [ "$r" -le "$ROUNDS" ]; do
    run_dir="$OUT_DIR/$mask_tag/round-$r"
    mkdir -p "$run_dir"

    rm -rf "$BENCH_DIR"/out_"$PROG"_* "$BENCH_DIR"/Errors "$BENCH_DIR"/Timeouts "$BENCH_DIR"/DiffResult 2>/dev/null || true

    {
      echo "taskset -c $mask python3 -u $ROOT_DIR/tool/DBDS/run_PDS.py -y -d $DEPTH ./$PROG"
      echo "binary_sha256=$BIN_SHA"
      echo "cpu_mask=$mask"
      echo "cpu_count=$ncpu"
    } > "$run_dir/command.txt"

    t0="$(date +%s%N)"
    date -u +%FT%TZ > "$run_dir/started-at.txt"

    timeout -k 20 "$TIMEOUT_SEC" \
      taskset -c "$mask" python3 -u "$ROOT_DIR/tool/DBDS/run_PDS.py" -y -d "$DEPTH" "./$PROG" \
      > "$run_dir/stdout.log" 2> "$run_dir/stderr.log"
    rc=$?

    t1="$(date +%s%N)"
    date -u +%FT%TZ > "$run_dir/finished-at.txt"
    echo "$rc" > "$run_dir/exit-code.txt"

    wall_s="$(awk -v d=$((t1 - t0)) 'BEGIN{printf "%.3f", d/1e9}')"
    echo "external_wall_s=$wall_s" > "$run_dir/walltime.txt"

    clean_out="$(sed 's/\x1b\[[0-9;]*m//g' "$run_dir/stdout.log")"
    {
      echo "$clean_out" | grep -E "Total Error Interleavings|Total Timeouts Interleavings|ThreadNum|^kpNumArray|^Round|^Time|Runtime:" || true
    } > "$run_dir/footer.txt"

    # Completeness & validity gate:
    #   1) exit code 0 and summary footer present
    #   2) no SCHED_DEADLINE EPERM / sched_setattr error in stderr
    #   3) dry-run kpNumArray is not all zeros (guards against silent false negative)
    gate_pass=0
    if [ "$rc" -eq 0 ] \
       && grep -q "Total Error Interleavings" "$run_dir/footer.txt" \
       && ! grep -q "sched_setattr error" "$run_dir/stderr.log" \
       && ! grep -qE '^kpNumArray:[[:space:]]+(0[[:space:]]*)+$' "$run_dir/footer.txt"; then
      gate_pass=1
    fi

    scheds="$(echo "$clean_out" | grep -oE '^test [0-9]+' | tail -1 | grep -oE '[0-9]+' || true)"
    errs="$(echo "$clean_out" | grep -m1 -oE 'Total Error Interleavings: [0-9]+' | grep -oE '[0-9]+$' || true)"
    tos="$(echo "$clean_out" | grep -m1 -oE 'Total Timeouts Interleavings: [0-9]+' | grep -oE '[0-9]+$' || true)"
    first_err="$(echo "$clean_out" | grep -m1 -oE 'Errors/000001_[0-9]+' | sed -E 's/.*000001_0*([0-9]+)/\1/' || true)"
    dry_rt="$(echo "$clean_out" | grep -m1 -oE 'Runtime: [0-9]+' | grep -oE '[0-9]+$' || true)"
    # Use [ \t] instead of [[:space:]] for Ubuntu 18.04 default mawk compatibility
    int_time="$(echo "$clean_out" | awk '/^Time[ \t]/{print $NF}' | tr -d '\r' | tail -1 || true)"

    # Convert HH:MM:SS.fffff internal time to seconds if present
    int_s=""
    if [[ "$int_time" =~ ^([0-9]+):([0-9]+):([0-9.]+)$ ]]; then
      int_s="$(awk -v h="${BASH_REMATCH[1]}" -v m="${BASH_REMATCH[2]}" -v s="${BASH_REMATCH[3]}" 'BEGIN{printf "%.3f", h*3600 + m*60 + s}')"
    fi

    printf '%s\tR%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$PROG" "$r" "$mask" "$ncpu" "$rc" "$gate_pass" \
      "${scheds:-NA}" "${errs:-NA}" "${tos:-NA}" "${first_err:-NA}" \
      "${dry_rt:-NA}" "${int_s:-NA}" "$wall_s" >> "$SUMMARY_TSV"

    echo "  [$mask_tag R$r] rc=$rc gate=$gate_pass sched=${scheds:-NA} err=${errs:-NA} to=${tos:-NA} first=${first_err:-NA} wall=${wall_s}s"
    r=$((r + 1))
  done
done

# 5. Compute Mean +/- SD and Median (Range) summary if companion script exists
if [ -f "$SCRIPT_DIR/extension_cpu_stats.py" ]; then
  python3 "$SCRIPT_DIR/extension_cpu_stats.py" "$SUMMARY_TSV" > "$OUT_DIR/stats-summary.md"
  echo "===== Summary (Mean +/- SD) ====="
  cat "$OUT_DIR/stats-summary.md"
fi

# 6. Generate SHA256SUMS for auditability
cd "$OUT_DIR" || exit 2
find . -type f ! -name SHA256SUMS -printf '%P\n' | sort | xargs sha256sum > SHA256SUMS
echo "EXTENSION_DONE out_dir=$OUT_DIR files=$(wc -l < SHA256SUMS) size=$(du -sh . | cut -f1)"
