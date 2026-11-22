#!/bin/bash
# PERIOD worker 线程 strace 取证 · 最终采集
# 三个场景确立模式：每 worker 线程一次 sched_setattr(SCHED_DEADLINE)，返回 0
#   A  df          Dry_Run=1 DBDS_Run=0   预测 0 次（源码 DBDSRun=false 分支）
#   B  df          Dry_Run=0 DBDS_Run=1   2 个 worker -> 2 次（已采，重采以保持同批一致）
#   C  reorder_3   Dry_Run=0 DBDS_Run=1   3 个 worker -> 预测 3 次
set -uo pipefail
EV=/lab/evidence/worker-syscall-evidence
mkdir -p "$EV"

export ROOT_DIR=/workdir/PERIOD
export PATH=$ROOT_DIR/clang+llvm/bin:$PATH
export LD_LIBRARY_PATH=$ROOT_DIR/clang+llvm/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}

capture () {  # $1=tag $2=dir $3=exe $4=Dry_Run $5=DBDS_Run
  local tag="$1" dir="$2" exe="$3" dry="$4" run="$5"
  cd "$dir" || return 1
  export Con_PATH="$dir/ConConfig.$exe"
  timeout 150 strace -f -tt -y -e signal=none -s 256 \
      -o "$EV/$tag.trace" \
      sudo "Dry_Run=$dry" "DBDS_Run=$run" \
      ASAN_OPTIONS=abort_on_error=1:detect_leaks=0 TSAN_OPTIONS=report_bugs=0 \
      "./$exe" > "$EV/$tag.stdout" 2> "$EV/$tag.stderr"
  local rc=$?
  local ss sa y cl sh
  ss=$(grep -c 'sched_setattr' "$EV/$tag.trace" 2>/dev/null || true); ss=${ss:-0}
  sa=$(grep -c 'sched_getattr' "$EV/$tag.trace" 2>/dev/null || true); sa=${sa:-0}
  y=$(grep -c 'sched_yield' "$EV/$tag.trace" 2>/dev/null || true); y=${y:-0}
  cl=$(grep -cE 'clone[3]?\(' "$EV/$tag.trace" 2>/dev/null || true); cl=${cl:-0}
  sh=$(grep -c 'shmat(' "$EV/$tag.trace" 2>/dev/null || true); sh=${sh:-0}
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$tag" "$(basename "$dir")" "$exe" "Dry_Run=$dry,DBDS_Run=$run" "$rc" "$ss" "$sa" "$y" "$cl" \
    >> "$EV/census.tsv"
  echo "  $tag rc=$rc sched_setattr=$ss sched_yield=$y clone=$cl shmat=$sh"
}

{ echo "scenario	target_dir	execute	command_env	rc	sched_setattr	sched_getattr	sched_yield	clone"
} > "$EV/census.tsv"

echo "== A. df 自然执行（预期 sched_setattr=0）=="
capture A-df-natural /workdir/PERIOD/test/doubleFree df 1 0

echo "== B. df 受控（预期 2 次，2 个 worker）=="
capture B-df-dbds /workdir/PERIOD/test/doubleFree df 0 1

echo "== C. reorder_3_bad 受控（预期 3 次，3 个 worker）=="
capture C-reorder3-dbds /workdir/PERIOD/evaluation/CS/reorder_3 reorder_3_bad 0 1

echo
echo "=== 每场景的 sched_setattr 完整条目 ==="
for tag in A-df-natural B-df-dbds C-reorder3-dbds; do
  { echo "--- $tag ---"
    grep 'sched_setattr' "$EV/$tag.trace" 2>/dev/null || echo "(none)"
  } >> "$EV/sched-setattr-entries.txt"
done
sed -n '1,20p' "$EV/sched-setattr-entries.txt" | sed 's/^/  /'

echo
echo "=== 每线程 yield 分布（strace 4.21 用行首 tid 标识）==="
for tag in B-df-dbds C-reorder3-dbds; do
  { echo "--- $tag: 线程 -> yield 次数 ---"
    grep sched_yield "$EV/$tag.trace" | awk '{print $1}' | sort | uniq -c | sort -rn
    echo "  该场景出现的 tid 全集: $(grep -oE '^[0-9]+' "$EV/$tag.trace" | sort -u | tr '\n' ' ')"
  } >> "$EV/per-thread-yield.txt"
done
grep -A5 'B-df' "$EV/per-thread-yield.txt" | head -12 | sed 's/^/  /'
grep -A6 'C-reorder3' "$EV/per-thread-yield.txt" | head -14 | sed 's/^/  /'

{ echo "kernel=$(uname -r)"
  echo "container=$(hostname)  affinity=$(taskset -pc 1 | sed 's/.*: //')  nproc=$(nproc)"
  echo "CapEff=$(grep CapEff /proc/1/status | awk '{print $2}')"
  echo "strace=4.21-1ubuntu1 (decodes raw syscall 314 as named sched_setattr)"
  echo "df_sha256=$(sha256sum /workdir/PERIOD/test/doubleFree/df | cut -d' ' -f1)"
  echo "reorder3_sha256=$(sha256sum /workdir/PERIOD/evaluation/CS/reorder_3/reorder_3_bad | cut -d' ' -f1)"
  echo "taken_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$EV/provenance.txt"
cat "$EV/provenance.txt" | sed 's/^/  /'
echo "WORKER_EVIDENCE_DONE"
