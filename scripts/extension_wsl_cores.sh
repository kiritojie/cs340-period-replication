#!/usr/bin/env bash
# CS340 Extension Experiment Part 2 (True Root-Domain Core Count Single-Factor):
#   Factor varied : VM/root-domain logical CPU count via WSL2 .wslconfig (processors=8 / 4 / 2)
#                   WITHOUT taskset, so every run covers the full root domain.
#   Held constant : Same host, same container (wcventure/period:stable), same upstream PERIOD,
#                   same instrumented binaries (reorder_5_bad & reorder_10_bad), flags (-y -d 3).
set -uo pipefail

export ROOT_DIR="${PERIOD_ROOT:-/workdir/PERIOD}"
export PATH="$ROOT_DIR/clang+llvm/bin:$PATH"
export LD_LIBRARY_PATH="$ROOT_DIR/clang+llvm/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

OUT_BASE="${OUT_BASE:-/repo/docs/results/extension-wsl-cores}"
R5_ROUNDS="${R5_ROUNDS:-5}"
R10_ROUNDS="${R10_ROUNDS:-3}"
R5_TIMEOUT="${R5_TIMEOUT:-180}"
R10_TIMEOUT="${R10_TIMEOUT:-420}"

NCPU="$(nproc)"
AFFINITY="$(taskset -pc $$ | sed 's/.*: //')"
CORES_DIR="$OUT_BASE/cores-${NCPU}"
mkdir -p "$CORES_DIR"

{
  echo "utc_started        : $(date -u +%FT%TZ)"
  echo "kernel             : $(uname -r)"
  echo "container          : $(hostname)"
  echo "nproc_available    : $NCPU"
  echo "default_affinity   : $AFFINITY"
  echo "deadline_probe_rc  : $(chrt -d --sched-period 20000000 --sched-runtime 10000000 --sched-deadline 20000000 0 sleep 0.1 >/dev/null 2>&1; echo $?)"
  echo "period_git_head    : $(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || echo 'unknown')"
  echo "r5_rounds          : $R5_ROUNDS"
  echo "r10_rounds         : $R10_ROUNDS"
} > "$CORES_DIR/exec-env.txt"

echo "===== WSL Root-Domain Core Experiment (nproc=$NCPU, affinity=$AFFINITY) ====="
cat "$CORES_DIR/exec-env.txt"

SUMMARY_TSV="$CORES_DIR/rounds-summary.tsv"
printf 'program\tround\twsl_cores\tcpu_mask\trc\tgate_pass\tschedules\terror_interleavings\ttimeouts\tfirst_error\tdry_run_runtime\tinternal_time_s\texternal_wall_s\n' > "$SUMMARY_TSV"

run_benchmark() {
  local bench_sub="$1"
  local prog="$2"
  local rounds="$3"
  local timeout_sec="$4"
  local bench_dir="$ROOT_DIR/evaluation/CS/$bench_sub"
  local prog_out="$CORES_DIR/$prog"
  mkdir -p "$prog_out"

  cd "$bench_dir" || exit 1
  if [ ! -x "./$prog" ]; then
    echo "===== Building $prog ====="
    {
      ./cleanDIR.sh
      clang -g -emit-llvm -c "./${prog}.c" -o "${prog}.bc"
      "$ROOT_DIR/tool/staticAnalysis/staticAnalysis.sh" "$prog"
      export Con_PATH="$bench_dir/ConConfig.$prog"
      "$ROOT_DIR/tool/staticAnalysis/DBDS-INSTRU/dbds-clang-fast++" -g "./${prog}.bc" -o "$prog" -lpthread -ldl
    } > "$prog_out/build.log" 2>&1
    echo "build_rc=$?" >> "$prog_out/build.log"
  fi

  local bin_sha kp_count
  bin_sha="$(sha256sum "./$prog" | cut -d' ' -f1)"
  kp_count="$(wc -l < "./ConConfig.$prog" 2>/dev/null || echo 0)"
  {
    echo "binary_path=$bench_dir/$prog"
    echo "binary_sha256=$bin_sha"
    echo "keypoints_lines=$kp_count"
  } > "$prog_out/binary-identity.txt"

  export Con_PATH="$bench_dir/ConConfig.$prog"

  local r=1
  while [ "$r" -le "$rounds" ]; do
    local run_dir="$prog_out/round-$r"
    mkdir -p "$run_dir"
    rm -rf "$bench_dir"/out_"$prog"_* "$bench_dir"/Errors "$bench_dir"/Timeouts "$bench_dir"/DiffResult 2>/dev/null || true

    {
      echo "python3 -u $ROOT_DIR/tool/DBDS/run_PDS.py -y -d 3 ./$prog"
      echo "binary_sha256=$bin_sha"
      echo "wsl_cores=$NCPU"
      echo "default_affinity=$AFFINITY"
    } > "$run_dir/command.txt"

    local t0 t1 rc wall_s clean_out gate_pass scheds errs tos first_err dry_rt int_time int_s
    t0="$(date +%s%N)"
    date -u +%FT%TZ > "$run_dir/started-at.txt"

    timeout -k 20 "$timeout_sec" \
      python3 -u "$ROOT_DIR/tool/DBDS/run_PDS.py" -y -d 3 "./$prog" \
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
    int_time="$(echo "$clean_out" | awk '/^Time[ \t]/{print $NF}' | tr -d '\r' | tail -1 || true)"

    int_s=""
    if [[ "$int_time" =~ ^([0-9]+):([0-9]+):([0-9.]+)$ ]]; then
      int_s="$(awk -v h="${BASH_REMATCH[1]}" -v m="${BASH_REMATCH[2]}" -v s="${BASH_REMATCH[3]}" 'BEGIN{printf "%.3f", h*3600 + m*60 + s}')"
    fi

    printf '%s\tR%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$prog" "$r" "$NCPU" "$AFFINITY" "$rc" "$gate_pass" \
      "${scheds:-NA}" "${errs:-NA}" "${tos:-NA}" "${first_err:-NA}" \
      "${dry_rt:-NA}" "${int_s:-NA}" "$wall_s" >> "$SUMMARY_TSV"

    echo "  [cores-$NCPU $prog R$r] rc=$rc gate=$gate_pass sched=${scheds:-NA} err=${errs:-NA} to=${tos:-NA} first=${first_err:-NA} rt=${dry_rt:-NA} wall=${wall_s}s"
    r=$((r + 1))
  done
}

run_benchmark "reorder_5" "reorder_5_bad" "$R5_ROUNDS" "$R5_TIMEOUT"
run_benchmark "reorder_10" "reorder_10_bad" "$R10_ROUNDS" "$R10_TIMEOUT"

echo "===== DONE cores-$NCPU ====="
cat "$SUMMARY_TSV"
