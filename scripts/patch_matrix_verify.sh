#!/usr/bin/env bash
# Complete remaining patch verification matrix cells:
#   - reorder_5_bad  : mask 0 (1 core) x3, mask 0-1 (2 cores) x3
#   - reorder_10_bad : mask 0 (1 core) x3, mask 0-3 (4 cores) x3, mask 0-7 (8 cores) x3
# Runs inside wcventure/period:stable (--privileged) with repo mounted at /repo.
set -euo pipefail

export ROOT_DIR="/workdir/PERIOD"
export PATH="$ROOT_DIR/clang+llvm/bin:$PATH"
export LD_LIBRARY_PATH="$ROOT_DIR/clang+llvm/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

OUT_ROOT="/repo/docs/results/extension-cpu-affinity-merged/patch-verification"
PATCH_FILE="/repo/patches/period-sched-deadline-failfast.patch"

echo "===== 1. Apply patch and rebuild DBDSFunction.o ====="
cd "$ROOT_DIR"
git apply "$PATCH_FILE"
cd "$ROOT_DIR/tool/staticAnalysis/DBDS-INSTRU/llvm-mode"
make -B ../DBDSFunction.o

build_prog() {
  local sub="$1" prog="$2"
  local bdir="$ROOT_DIR/evaluation/CS/$sub"
  cd "$bdir"
  ./cleanDIR.sh
  clang -g -emit-llvm -c "./${prog}.c" -o "${prog}.bc"
  "$ROOT_DIR/tool/staticAnalysis/staticAnalysis.sh" "$prog"
  export Con_PATH="$bdir/ConConfig.$prog"
  "$ROOT_DIR/tool/staticAnalysis/DBDS-INSTRU/dbds-clang-fast++" -g "./${prog}.bc" -o "$prog" -lpthread -ldl
  sha256sum "./$prog" | awk '{print $1}'
}

echo "===== 2. Build patched reorder_5_bad & reorder_10_bad ====="
R5_SHA="$(build_prog reorder_5 reorder_5_bad)"
R10_SHA="$(build_prog reorder_10 reorder_10_bad)"
echo "patched_r5_sha256=$R5_SHA"
echo "patched_r10_sha256=$R10_SHA"

{
  echo "patched_reorder_5_sha256=$R5_SHA"
  echo "patched_reorder_10_sha256=$R10_SHA"
  echo "utc_started=$(date -u +%FT%TZ)"
  echo "nproc=$(nproc)"
  echo "kernel=$(uname -r)"
} > "$OUT_ROOT/matrix-binary-identity.txt"

MATRIX_TSV="$OUT_ROOT/matrix-verification-summary.tsv"
printf 'program\tcase\tround\tcpu_mask\trc\tschedules\terror_interleavings\ttimeouts\tfirst_error\tdry_run_runtime\twall_s\n' > "$MATRIX_TSV"

run_case() {
  local sub="$1" prog="$2" label="$3" mask="$4" rounds="$5" timeout_sec="$6"
  local bdir="$ROOT_DIR/evaluation/CS/$sub"
  cd "$bdir"
  export Con_PATH="$bdir/ConConfig.$prog"

  for r in $(seq 1 "$rounds"); do
    local run_dir="$OUT_ROOT/${label}_r${r}"
    rm -rf "$run_dir"
    mkdir -p "$run_dir"
    rm -rf "$bdir"/out_"$prog"_* "$bdir"/Errors "$bdir"/Timeouts "$bdir"/DiffResult 2>/dev/null || true

    local t0 t1 rc wall_s clean_out scheds errs tos first_err dry_rt
    t0="$(date +%s%N)"
    set +e
    timeout -k 20 "$timeout_sec" taskset -c "$mask" \
      python3 -u "$ROOT_DIR/tool/DBDS/run_PDS.py" -y -d 3 "./$prog" \
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

    printf '%s\t%s\tR%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$prog" "$label" "$r" "$mask" "$rc" "${scheds:-0}" "${errs:-NA}" "${tos:-NA}" "${first_err:-NA}" "${dry_rt:-NA}" "$wall_s" \
      >> "$MATRIX_TSV"
    echo "[$label R$r] rc=$rc sched=${scheds:-0} err=${errs:-NA} to=${tos:-NA} first=${first_err:-NA} rt=${dry_rt:-NA} wall=${wall_s}s"
  done
}

echo "===== 3. Run remaining matrix cells ====="
run_case reorder_5  reorder_5_bad  "patched_r5_subset_0"    "0"   3 60
run_case reorder_5  reorder_5_bad  "patched_r5_subset_0-1"  "0-1" 3 60
run_case reorder_10 reorder_10_bad "patched_r10_subset_0"   "0"   3 60
run_case reorder_10 reorder_10_bad "patched_r10_subset_0-3" "0-3" 3 60
run_case reorder_10 reorder_10_bad "patched_r10_full_0-7"   "0-7" 3 300

echo "===== DONE ====="
cat "$MATRIX_TSV"
