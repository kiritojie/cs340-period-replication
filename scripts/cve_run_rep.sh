#!/bin/bash
# Table 1 · CVE 重复轮次（带单程序看门狗）
# 与 run_cve.sh 相同的命令与口径，仅增加外层 timeout 与挂起留证
set -uo pipefail
export LANG=C.UTF-8

DEPTH=${1:-5}
PER_PROG_TIMEOUT=${2:-300}     # 单程序外层上限（秒）；实测正常一轮全批约 1.5-2.5 分钟
TS=$(date -u +%Y%m%dT%H%M%SZ)
BENCH=/workdir/PERIOD/evaluation/ConVul-CVE-Benchmarks
DRIVER=/workdir/PERIOD/tool/DBDS/run_PDS.py
ROOT=/lab/evidence/cve-rep-d${DEPTH}-$TS
mkdir -p "$ROOT"

export ROOT_DIR=/workdir/PERIOD
export PATH=$ROOT_DIR/clang+llvm/bin:$PATH
export LD_LIBRARY_PATH=$ROOT_DIR/clang+llvm/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

{ echo "depth             : $DEPTH"
  echo "schedule_budget   : 10000 (driver -f, paper per-invocation budget)"
  echo "outer_watchdog_s  : $PER_PROG_TIMEOUT per program"
  echo "source HEAD       : $(cd /workdir/PERIOD && git rev-parse HEAD)"
} > "$ROOT/batch-config.txt"

: > "$ROOT/binary-identity.txt"
for d in "$BENCH"/CVE-*; do
  n=$(basename "$d"); prog=$(ls "$d" | grep -E '^20[0-9]{2}-[0-9]+$' | head -1)
  [ -z "$prog" ] && continue
  printf '%-14s %s\n' "$n" "$(sha256sum "$d/$prog" | cut -d' ' -f1)" >> "$ROOT/binary-identity.txt"
done

{ echo "kernel    : $(uname -r)"
  echo "container : $(hostname)"
  echo "affinity  : $(taskset -pc 1 2>/dev/null | sed 's/.*: //')"
  echo "nproc     : $(nproc)"
  echo "deadline  : chrt -d rc=$(chrt -d --sched-period 20000000 --sched-runtime 10000000 --sched-deadline 20000000 0 sleep 0.1 >/dev/null 2>&1; echo $?)"
} > "$ROOT/exec-env.txt"

for d in "$BENCH"/CVE-*; do
  n=$(basename "$d")
  cd "$d" || continue
  prog=$(ls . | grep -E '^20[0-9]{2}-[0-9]+$' | head -1)
  [ -z "$prog" ] && { echo "$n SKIP no executable"; continue; }

  export Con_PATH="$d/ConConfig.$prog"
  RUN="$ROOT/$n-depth$DEPTH"; mkdir -p "$RUN"
  rm -rf out_"$prog"_* Errors Timeouts DiffResult 2>/dev/null

  CMD="python3 -u $DRIVER -y -d $DEPTH -f 10000 ./$prog"
  echo "timeout -k 20 $PER_PROG_TIMEOUT $CMD" > "$RUN/command.txt"
  echo "Con_PATH=$Con_PATH" >> "$RUN/command.txt"
  echo "binary_sha256=$(sha256sum "./$prog" | cut -d' ' -f1)" >> "$RUN/command.txt"

  T0=$(date +%s%N); date -u +%Y-%m-%dT%H:%M:%SZ > "$RUN/started-at.txt"
  timeout -k 20 "$PER_PROG_TIMEOUT" $CMD > "$RUN/stdout.log" 2> "$RUN/stderr.log"
  RC=$?
  if [ "$RC" -eq 124 ] || [ "$RC" -eq 137 ]; then
    { echo "event: outer watchdog fired (rc=$RC) after ${PER_PROG_TIMEOUT}s"
      echo "observed_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
      echo "driver stdout at fire time:"; sed 's/\x1b\[[0-9;]*m//g' "$RUN/stdout.log"
      echo "note: paper states the study is non-deterministic; hang logged, not retried."
    } > "$RUN/WATCHDOG.txt"
  fi
  T1=$(date +%s%N); date -u +%Y-%m-%dT%H:%M:%SZ > "$RUN/finished-at.txt"
  echo "$RC" > "$RUN/exit-code.txt"
  { echo "external_wall_ns=$((T1 - T0))"
    awk -v x=$((T1 - T0)) 'BEGIN{printf "external_wall_s=%.3f\n", x/1e9}'
  } > "$RUN/walltime.txt"
  cat "$RUN/stdout.log" "$RUN/stderr.log" > "$RUN/console.log"
  tar -czf "$RUN/raw-output.tar.gz" out_"$prog"_* Errors Timeouts DiffResult 2>/dev/null
  sed 's/\x1b\[[0-9;]*m//g' "$RUN/stdout.log" \
    | grep -E "Total Error Interleavings|Total Timeouts Interleavings|ThreadNum|^Round|^Time|Runtime:" > "$RUN/footer.txt"
  printf '%-16s rc=%s %s\n' "$n" "$RC" "$(grep -o 'Total Error Interleavings: [0-9]*' "$RUN/footer.txt" | tail -1)"
done

cd "$ROOT" || exit 2
find . -type f ! -name SHA256SUMS -printf '%P\n' | sort | xargs sha256sum > SHA256SUMS
echo "CVE_REP_DONE $TS"
