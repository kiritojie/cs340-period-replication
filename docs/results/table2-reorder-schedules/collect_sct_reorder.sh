#!/bin/bash
# Table 2 第一段：CS.reorder 的 3/4/5/10 线程版 × 10 轮
# 目的：对齐论文 Table 2 该行 PERIOD 的四个数字 27 / 100 / 225 / 2350
#       （reorder_3=27 与 reorder_10=2350 此前已各自对上，本段补齐 4 与 5 两档）
# 口径：与组员第三周及本机跨机器复现逐字一致 —— python3 -u run_PDS.py -y -d 3 ./<prog>
#       SCTBench 组论文 bug-depth 上限为 3，故用 -d 3（不同于 CVE 组的 -d 5）
set -uo pipefail
ROUNDS=${1:-10}
E=/workdir/PERIOD/evaluation/CS
ROOT=/lab/evidence/sct-reorder-r${ROUNDS}-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$ROOT"
PROGS="reorder_3 reorder_4 reorder_5 reorder_10"

export ROOT_DIR=/workdir/PERIOD
export PATH=$ROOT_DIR/clang+llvm/bin:$PATH
export LD_LIBRARY_PATH=$ROOT_DIR/clang+llvm/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

{ echo "kernel    : $(uname -r)"
  echo "container : $(hostname)"
  echo "affinity  : $(taskset -pc 1 | sed 's/.*: //')"
  echo "nproc     : $(nproc)"
  echo "deadline  : chrt -d rc=$(chrt -d --sched-period 20000000 --sched-runtime 10000000 --sched-deadline 20000000 0 sleep 0.1 >/dev/null 2>&1; echo $?)"
  echo "command   : python3 -u /workdir/PERIOD/tool/DBDS/run_PDS.py -y -d 3 ./<prog>"
  echo "rounds    : $ROUNDS per program"
  echo "source    : $(cd /workdir/PERIOD && git rev-parse HEAD)"
} > "$ROOT/exec-env.txt"

echo "===== 构建缺失产物 ====="
: > "$ROOT/build-log.txt"
for n in $PROGS; do
  cd "$E/$n" || continue
  if [ -x "${n}_bad" ]; then
    echo "$n 已有产物，跳过构建" >> "$ROOT/build-log.txt"
  else
    T0=$(date +%s)
    { echo "### build $n"; ./cleanDIR.sh
      clang -g -emit-llvm -c ./${n}_bad.c -o ${n}_bad.bc
      $ROOT_DIR/tool/staticAnalysis/staticAnalysis.sh ${n}_bad
      export Con_PATH=$PWD/ConConfig.${n}_bad
      $ROOT_DIR/tool/staticAnalysis/DBDS-INSTRU/dbds-clang-fast++ -g ./${n}_bad.bc -o ${n}_bad -lpthread -ldl
    } >> "$ROOT/build-log.txt" 2>&1
    echo "$n 构建 rc=$? 用时 $(( $(date +%s) - T0 ))s 关键点=$(head -1 ConConfig.${n}_bad 2>/dev/null)" | tee -a "$ROOT/build-summary.txt"
  fi
done

echo "===== 被测二进制身份（逐程序，全轮共用一次构建）====="
for n in $PROGS; do
  [ -x "$E/$n/${n}_bad" ] && printf '%-12s %s  keypoints=%s\n' "$n" \
    "$(sha256sum "$E/$n/${n}_bad" | cut -d' ' -f1)" \
    "$(wc -l < "$E/$n/ConConfig.${n}_bad" 2>/dev/null)" >> "$ROOT/binary-identity.txt"
done
cat "$ROOT/binary-identity.txt"

echo "===== 逐轮探索 ====="
i=1
while [ "$i" -le "$ROUNDS" ]; do
  for n in $PROGS; do
    cd "$E/$n" || continue
    prog="${n}_bad"
    export Con_PATH="$E/$n/ConConfig.$prog"
    R="$ROOT/round-$i/$n"; mkdir -p "$R"
    rm -rf "$E/$n"/out_"$prog"_* "$E/$n"/Errors "$E/$n"/Timeouts "$E/$n"/DiffResult 2>/dev/null
    echo "python3 -u $ROOT_DIR/tool/DBDS/run_PDS.py -y -d 3 ./$prog" > "$R/command.txt"
    echo "binary_sha256=$(sha256sum ./$prog | cut -d' ' -f1)" >> "$R/command.txt"
    T0=$(date +%s%N); date -u +%FT%TZ > "$R/started-at.txt"
    timeout -k 20 600 python3 -u "$ROOT_DIR/tool/DBDS/run_PDS.py" -y -d 3 "./$prog" \
      > "$R/stdout.log" 2> "$R/stderr.log"
    RC=$?; T1=$(date +%s%N); date -u +%FT%TZ > "$R/finished-at.txt"
    echo "$RC" > "$R/exit-code.txt"
    awk -v d=$((T1-T0)) 'BEGIN{printf "external_wall_s=%.3f\n", d/1e9}' > "$R/walltime.txt"
    C=$(sed 's/\x1b\[[0-9;]*m//g' "$R/stdout.log")
    { echo "$C" | grep -E "Total Error Interleavings|Total Timeouts Interleavings|ThreadNum|^kpNumArray|^Round|^Time|Runtime:"
    } > "$R/footer.txt"
    tar -czf "$R/raw-output.tar.gz" -C "$E/$n" $(cd "$E/$n" && ls -d out_"$prog"_* Errors Timeouts DiffResult 2>/dev/null) 2>/dev/null
    # 错误调度记录导出纯文本（仅首条与各类型首条，控制体积）
    T=$(mktemp -d); tar -xzf "$R/raw-output.tar.gz" -C "$T" 2>/dev/null
    mkdir -p "$R/error-schedules"
    find "$T" -path '*Errors/*' -type f | sed 's/.*_\([A-Za-z-]*\)$/\1\t&/' | sort -u -k1,1 \
      | cut -f2 | while read -r f; do cp "$f" "$R/error-schedules/$(basename "$f").txt"; done
    rm -rf "$T"
    printf 'R%s\t%s\t%s\t%s\t%s\t%s\n' "$i" "$n" "$RC" \
      "$(echo "$C" | grep -oE '^test [0-9]+' | tail -1 | grep -oE '[0-9]+')" \
      "$(echo "$C" | grep -m1 -oE 'Total Error Interleavings: [0-9]+' | grep -oE '[0-9]+$')" \
      "$(awk -F= '/external/{print $2}' "$R/walltime.txt")" >> "$ROOT/progress.tsv"
  done
  echo "  第 $i 轮完成: $(tail -4 "$ROOT/progress.tsv" | tr '\n' ' ')"
  i=$((i+1))
done

cd "$ROOT" || exit 2
{ printf 'round\tprogram\trc\tschedules\terror_interleavings\texternal_wall_s\n'
  cat progress.tsv; } > rounds-summary.tsv
rm -f progress.tsv
find . -type f ! -name SHA256SUMS -printf '%P\n' | sort | xargs sha256sum > SHA256SUMS
echo "SCT_REORDER_DONE $ROOT  清单=$(wc -l < SHA256SUMS)条 体积=$(du -sh . | cut -f1)"
