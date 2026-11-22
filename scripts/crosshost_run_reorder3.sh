#!/bin/bash
# CS.reorder_3_bad 独立复现 · 阶段三：三轮深度 3 正式探索
# 与小组一致的命令与深度；额外补齐小组缺的逐轮溯源字段
set -uo pipefail
export LANG=C.UTF-8

TARGET=/workdir/PERIOD/evaluation/CS/reorder_3
DRIVER=/workdir/PERIOD/tool/DBDS/run_PDS.py
DEPTH=3
RUNS=3

TS=$(date -u +%Y%m%dT%H%M%SZ)
ROOT=/lab/evidence/runs-$TS
mkdir -p "$ROOT"

# 与 build.sh 一致的工具链与关键点配置（run_PDS.py 依赖 Con_PATH）
export ROOT_DIR=/workdir/PERIOD
export PATH=$ROOT_DIR/clang+llvm/bin:$PATH
export LD_LIBRARY_PATH=$ROOT_DIR/clang+llvm/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
export Con_PATH=$TARGET/ConConfig.reorder_3_bad

# 复现前锁定被测二进制身份（补小组缺的逐轮二进制哈希）
echo "===== binary under test =====" | tee "$ROOT/binary-identity.txt"
sha256sum "$TARGET/reorder_3_bad" | tee -a "$ROOT/binary-identity.txt"
echo "ConConfig: $(cat $Con_PATH | head -1) key points" | tee -a "$ROOT/binary-identity.txt"

# 逐轮运行环境身份（补小组缺的逐轮镜像/能力/亲和/cgroup 字段）
echo "===== execution environment (per-run identical, captured once) =====" | tee "$ROOT/exec-env.txt"
echo "kernel            : $(uname -r)"                              | tee -a "$ROOT/exec-env.txt"
echo "container ID      : $(hostname)"                              | tee -a "$ROOT/exec-env.txt"
echo "cpu affinity mask : $(taskset -pc 1 2>/dev/null | sed 's/.*: //')" | tee -a "$ROOT/exec-env.txt"
echo "nproc             : $(nproc)"                                 | tee -a "$ROOT/exec-env.txt"
echo "cpu.max           : $(cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo n/a)" | tee -a "$ROOT/exec-env.txt"
echo "mem.max           : $(cat /sys/fs/cgroup/memory.max 2>/dev/null || echo n/a)" | tee -a "$ROOT/exec-env.txt"
echo "cap_effective     : $(grep CapEff /proc/1/status 2>/dev/null | awk '{print $2}')" | tee -a "$ROOT/exec-env.txt"
echo "seccomp           : $(grep Seccomp /proc/1/status 2>/dev/null | tr '\n' ' ')" | tee -a "$ROOT/exec-env.txt"
echo "capabilities note : container launched with --privileged"     | tee -a "$ROOT/exec-env.txt"

for i in $(seq 1 "$RUNS"); do
  RUN="$ROOT/run-0$i-depth$DEPTH"
  mkdir -p "$RUN"
  cd "$TARGET" || exit 2

  # 清掉上一轮的探索产物，保证每轮从同一初始状态开始
  # 驱动按 out_<target>_<n> 递增命名，必须带通配清理，否则轮间会串
  rm -rf out_reorder_3_bad_* Errors Timeouts DiffResult 2>/dev/null

  # 外层完整命令一并留痕（小组只留了内层 python 命令）
  CMD="python3 -u $DRIVER -y -d $DEPTH ./reorder_3_bad"
  echo "$CMD" > "$RUN/command.txt"
  echo "outer-workdir: $TARGET" >> "$RUN/command.txt"

  T0=$(date +%s%N)
  date -u +%Y-%m-%dT%H:%M:%SZ > "$RUN/started-at.txt"

  # stdout / stderr 分离捕获（小组只留了合并 console，这是可补的缺口）
  $CMD > "$RUN/stdout.log" 2> "$RUN/stderr.log"
  RC=$?

  T1=$(date +%s%N)
  date -u +%Y-%m-%dT%H:%M:%SZ > "$RUN/finished-at.txt"
  # 外部墙钟间隔：纳秒差值，比整秒时间戳更细（补小组的"外测边界不明"缺口）
  echo "external_wall_ns=$((T1 - T0))" > "$RUN/walltime.txt"
  awk -v d=$((T1 - T0)) 'BEGIN{printf "external_wall_s=%.3f\n", d/1e9}' >> "$RUN/walltime.txt"
  echo "$RC" > "$RUN/exit-code.txt"
  cat "$RUN/stdout.log" "$RUN/stderr.log" > "$RUN/console.log"

  # 归档原始探索产物（错误交错调度等）；目录名带递增后缀，用通配匹配
  tar -czf "$RUN/raw-output.tar.gz" out_reorder_3_bad_* Errors Timeouts DiffResult 2>/dev/null
  echo "raw_archive_entries=$(tar -tzf "$RUN/raw-output.tar.gz" 2>/dev/null | wc -l)" >> "$RUN/walltime.txt"

  echo "run-0$i rc=$RC -> $RUN"
done

cd "$ROOT" || exit 2
echo "===== per-run summary ====="
for i in $(seq 1 "$RUNS"); do
  RUN="$ROOT/run-0$i-depth$DEPTH"
  printf '%s rc=%s start=%s\n' "run-0$i" "$(cat $RUN/exit-code.txt)" "$(cat $RUN/started-at.txt)"
done

# 逐轮产物校验清单（与小组 SHA256SUMS 惯例一致）
find . -type f ! -name 'SHA256SUMS' -printf '%P\n' | sort | xargs sha256sum > SHA256SUMS
echo "SHA256SUMS entries: $(wc -l < SHA256SUMS)"
echo "RUNS_DONE $TS"
