#!/usr/bin/env bash
# Clean alternating A/B zero-regression verification for patches/period-sched-deadline-failfast.patch
# Runs inside wcventure/period:stable (--privileged) with repo mounted at /repo.
set -euo pipefail

export ROOT_DIR="/workdir/PERIOD"
export PATH="$ROOT_DIR/clang+llvm/bin:$PATH"
export LD_LIBRARY_PATH="$ROOT_DIR/clang+llvm/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

BENCH_DIR="$ROOT_DIR/evaluation/CS/reorder_5"
OUT_ROOT="${OUT_ROOT:-/repo/docs/results/extension-cpu-affinity-merged/patch-verification}"
PATCH_FILE="${PATCH_FILE:-/repo/patches/period-sched-deadline-failfast.patch}"
ROUNDS="${ROUNDS:-5}"

cd "$BENCH_DIR"

echo "===== 1. Save unpatched run_PDS.py & build unpatched reorder_5_bad ====="
cp "$ROOT_DIR/tool/DBDS/run_PDS.py" "$ROOT_DIR/tool/DBDS/run_PDS.orig.py"
./cleanDIR.sh
clang -g -emit-llvm -c ./reorder_5_bad.c -o reorder_5_bad.bc
"$ROOT_DIR/tool/staticAnalysis/staticAnalysis.sh" reorder_5_bad
export Con_PATH="$BENCH_DIR/ConConfig.reorder_5_bad"
"$ROOT_DIR/tool/staticAnalysis/DBDS-INSTRU/dbds-clang-fast++" -g ./reorder_5_bad.bc -o /tmp/reorder_5_bad.orig -lpthread -ldl
ORIG_SHA="$(sha256sum /tmp/reorder_5_bad.orig | awk '{print $1}')"
echo "orig_sha256=$ORIG_SHA"

echo "===== 2. Apply patch, rebuild DBDSFunction.o & patched reorder_5_bad ====="
cd "$ROOT_DIR"
git apply "$PATCH_FILE"
cd "$ROOT_DIR/tool/staticAnalysis/DBDS-INSTRU/llvm-mode"
make -B ../DBDSFunction.o
cd "$BENCH_DIR"
"$ROOT_DIR/tool/staticAnalysis/DBDS-INSTRU/dbds-clang-fast++" -g ./reorder_5_bad.bc -o /tmp/reorder_5_bad.patched -lpthread -ldl
PATCHED_SHA="$(sha256sum /tmp/reorder_5_bad.patched | awk '{print $1}')"
echo "patched_sha256=$PATCHED_SHA"

{
  echo "orig_binary_sha256=$ORIG_SHA"
  echo "patched_binary_sha256=$PATCHED_SHA"
  echo "utc_started=$(date -u +%FT%TZ)"
  echo "nproc=$(nproc)"
  echo "kernel=$(uname -r)"
} > "$OUT_ROOT/ab-binary-identity.txt"

AB_TSV="$OUT_ROOT/ab-verification-summary.tsv"
printf 'case\tround\tcpu_mask\trc\tschedules\terror_interleavings\ttimeouts\tfirst_error\tdry_run_runtime\twall_s\n' > "$AB_TSV"

run_one() {
  local label="$1"
  local r="$2"
  local bin_src="$3"
  local driver="$4"
  local run_dir="$OUT_ROOT/${label}_r${r}"
  rm -rf "$run_dir"
  mkdir -p "$run_dir"

  rm -rf "$BENCH_DIR"/out_reorder_5_bad_* "$BENCH_DIR"/Errors "$BENCH_DIR"/Timeouts "$BENCH_DIR"/DiffResult 2>/dev/null || true
  cp "$bin_src" "$BENCH_DIR/reorder_5_bad"
  chmod +x "$BENCH_DIR/reorder_5_bad"

  local t0 t1 rc wall_s clean_out scheds errs tos first_err dry_rt
  t0="$(date +%s%N)"
  set +e
  timeout -k 20 300 taskset -c 0-7 python3 -u "$driver" -y -d 3 ./reorder_5_bad \
    > "$run_dir/stdout.log" 2> "$run_dir/stderr.log"
  rc=$?
  set -e
  t1="$(date +%s%N)"
  wall_s="$(awk -v d=$((t1 - t0)) 'BEGIN{printf "%.3f", d/1e9}')"

  clean_out="$(sed 's/\x1b\[[0-9;]*m//g' "$run_dir/stdout.log")"
  scheds="$(echo "$clean_out" | grep -oE '^test [0-9]+' | tail -1 | grep -oE '[0-9]+' || true)"
  errs="$(echo "$clean_out" | grep -m1 -oE 'Total Error Interleavings: [0-9]+' | grep -oE '[0-9]+$' || true)"
  tos="$(echo "$clean_out" | grep -m1 -oE 'Total Timeouts Interleavings: [0-9]+' | grep -oE '[0-9]+$' || true)"
  first_err="$(echo "$clean_out" | grep -m1 -oE 'Errors/000001_[0-9]+' | sed -E 's/.*000001_0*([0-9]+)/\1/' || true)"
  dry_rt="$(echo "$clean_out" | grep -m1 -oE 'Runtime: [0-9]+' | grep -oE '[0-9]+$' || true)"

  printf '%s\tR%s\t0-7\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$label" "$r" "$rc" "${scheds:-0}" "${errs:-NA}" "${tos:-NA}" "${first_err:-NA}" "${dry_rt:-NA}" "$wall_s" \
    >> "$AB_TSV"
  echo "[$label R$r] rc=$rc sched=${scheds:-0} err=${errs:-NA} to=${tos:-NA} first=${first_err:-NA} rt=${dry_rt:-NA} wall=${wall_s}s"
}

echo "===== 3. Alternating A/B verification ($ROUNDS rounds each, taskset -c 0-7) ====="
for r in $(seq 1 "$ROUNDS"); do
  run_one "ab_orig_full_0-7" "$r" /tmp/reorder_5_bad.orig "$ROOT_DIR/tool/DBDS/run_PDS.orig.py"
  run_one "ab_patched_full_0-7" "$r" /tmp/reorder_5_bad.patched "$ROOT_DIR/tool/DBDS/run_PDS.py"
done

echo "===== DONE ====="
cat "$AB_TSV"
