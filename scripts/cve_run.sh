#!/bin/bash
# Table 1 · CVE 基准阶段：10 个 CVE 程序 × 1 轮 × 深度 3（第一轮缩规模，判据对齐后再扩）
set -uo pipefail
export LANG=C.UTF-8

TS=$(date -u +%Y%m%dT%H%M%SZ)
BENCH=/workdir/PERIOD/evaluation/ConVul-CVE-Benchmarks
DRIVER=/workdir/PERIOD/tool/DBDS/run_PDS.py
DEPTH=${1:-3}   # 论文 CVE 组 bug-depth 上限 5；SCTBench 组为 3
ROOT=/lab/evidence/cve-runs-d${DEPTH}-$TS
mkdir -p "$ROOT"

export ROOT_DIR=/workdir/PERIOD
export PATH=$ROOT_DIR/clang+llvm/bin:$PATH
export LD_LIBRARY_PATH=$ROOT_DIR/clang+llvm/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

echo "===== batch identity ====="
{ echo "depth      : $DEPTH"
  echo "programs   : 10 (official ConVul-CVE-Benchmarks set)"
  echo "runs/prog  : 1 (round one; paper used 10)"
  echo "source HEAD: $(cd /workdir/PERIOD && git rev-parse HEAD)"
} > "$ROOT/batch-config.txt"

# 逐程序二进制身份 + 关键点（构建后一次性采集）
: > "$ROOT/binary-identity.txt"
for d in "$BENCH"/CVE-*; do
  n=$(basename "$d"); prog=$(ls "$d" | grep -E '^20[0-9]{2}-[0-9]+$' | head -1)
  [ -z "$prog" ] && continue
  printf '%-14s %s\n' "$n" "$(sha256sum "$d/$prog" | cut -d' ' -f1)" >> "$ROOT/binary-identity.txt"
done

# 执行环境快照
{ echo "kernel     : $(uname -r)"
  echo "container  : $(hostname)"
  echo "affinity   : $(taskset -pc 1 2>/dev/null | sed 's/.*: //')"
  echo "nproc      : $(nproc)"
  echo "deadline   : chrt -d rc=$(chrt -d --sched-period 20000000 --sched-runtime 10000000 --sched-deadline 20000000 0 sleep 0.1 >/dev/null 2>&1; echo $?)"
  echo "privilege  : --privileged (CapEff $(grep CapEff /proc/1/status | awk '{print $2}'))"
} > "$ROOT/exec-env.txt"
cat "$ROOT/exec-env.txt"

for d in "$BENCH"/CVE-*; do
  n=$(basename "$d")                       # CVE-2016-7911
  cd "$d" || continue
  prog=$(ls . | grep -E '^20[0-9]{2}-[0-9]+$' | head -1)
  [ -z "$prog" ] && { echo "$n SKIP no executable"; continue; }

  export Con_PATH="$d/ConConfig.$prog"
  RUN="$ROOT/$n-depth$DEPTH"
  mkdir -p "$RUN"

  rm -rf out_"$prog"_* Errors Timeouts DiffResult 2>/dev/null
  # -f 10000 = 论文"每次调用预算上限 10,000 调度"（驱动在超限时记录 reach_runs_limit）
  CMD="python3 -u $DRIVER -y -d $DEPTH -f 10000 ./$prog"
  echo "$CMD" > "$RUN/command.txt"
  echo "Con_PATH=$Con_PATH" >> "$RUN/command.txt"
  echo "binary_sha256=$(sha256sum "./$prog" | cut -d' ' -f1)" >> "$RUN/command.txt"

  T0=$(date +%s%N); date -u +%Y-%m-%dT%H:%M:%SZ > "$RUN/started-at.txt"
  $CMD > "$RUN/stdout.log" 2> "$RUN/stderr.log"
  RC=$?
  T1=$(date +%s%N); date -u +%Y-%m-%dT%H:%M:%SZ > "$RUN/finished-at.txt"
  echo "$RC" > "$RUN/exit-code.txt"
  { echo "external_wall_ns=$((T1 - T0))"
    awk -v x=$((T1 - T0)) 'BEGIN{printf "external_wall_s=%.3f\n", x/1e9}'
  } > "$RUN/walltime.txt"
  cat "$RUN/stdout.log" "$RUN/stderr.log" > "$RUN/console.log"

  tar -czf "$RUN/raw-output.tar.gz" out_"$prog"_* Errors Timeouts DiffResult 2>/dev/null

  # 页脚计数抽取（便于汇总）
  { sed 's/\x1b\[[0-9;]*m//g' "$RUN/stdout.log" \
      | grep -E "Total Error Interleavings|Total Timeouts Interleavings|ThreadNum|^Round|^Time|Runtime:"
  } > "$RUN/footer.txt"

  printf '%-16s rc=%s  %s\n' "$n" "$RC" "$(grep -o 'Total Error Interleavings: [0-9]*' "$RUN/footer.txt" | tail -1)"
done

cd "$ROOT" || exit 2
find . -type f ! -name SHA256SUMS -printf '%P\n' | sort | xargs sha256sum > SHA256SUMS
echo "SHA256SUMS entries: $(wc -l < SHA256SUMS)"
echo "CVE_RUNS_DONE $TS"
