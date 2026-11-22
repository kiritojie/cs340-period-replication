#!/bin/bash
# CS.reorder_3_bad 独立复现 · 阶段一：环境溯源记录（只读盘点，不构建、不跑实验）
set -u
export LANG=C.UTF-8

echo "########## PREFLIGHT INVENTORY ##########"
echo "UTC now        : $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "kernel         : $(uname -r)"
echo "container OS   : $(grep -m1 PRETTY /etc/os-release)"
echo

echo "===== PERIOD source identity ====="
cd /workdir/PERIOD || exit 1
echo "git HEAD       : $(git rev-parse HEAD 2>/dev/null || echo '(not a git repo)')"
echo "git describe   : $(git describe --always --dirty 2>/dev/null)"
echo "commit subject : $(git log -1 --format='%h %ad %s' --date=short 2>/dev/null)"
echo "worktree dirty : $(git status --porcelain 2>/dev/null | wc -l) entries"
echo

echo "===== toolchain ====="
for t in clang clang++ opt llvm-config python3 make cmake gcc g++; do
  p=$(command -v "$t" 2>/dev/null) || { printf '%-12s MISSING\n' "$t"; continue; }
  v=$("$t" --version 2>/dev/null | head -1)
  printf '%-12s %s\n' "$t" "$v"
  printf '%-12s   path: %s\n' "" "$p"
done
echo "python3 -V     : $(python3 -V 2>&1)"
echo

echo "===== deadline scheduling capability (in-container) ====="
chrt -d --sched-period 20000000 --sched-runtime 10000000 --sched-deadline 20000000 0 sleep 0.1
echo "chrt -d rc=$?"
echo "cpu_capacity (unique): $(cat /sys/devices/system/cpu/cpu*/cpu_capacity 2>/dev/null | sort -u | tr '\n' ' ')"
echo "nproc (container)    : $(nproc)"
echo "nproc (affinity mask): $(taskset -pc 1 2>/dev/null | sed 's/.*: //')"
echo "cpu.max (cgroup)     : $(cat /sys/fs/cgroup/cpu.max 2>/dev/null || cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us 2>/dev/null || echo n/a)"
echo

echo "===== benchmark target: evaluation/CS/reorder_3 ====="
cd /workdir/PERIOD/evaluation/CS/reorder_3 || exit 1
echo "--- files present BEFORE any build ---"
find . -maxdepth 1 -printf '%y %10s  %f\n' 2>/dev/null | sort -k3
echo
echo "--- pre-existing build products (must be absent for a clean independent build) ---"
for f in reorder_3_bad reorder_3_bad.bc reorder_3_bad.con ConConfig.out; do
  if [ -e "$f" ]; then echo "PRESENT: $f  sha256=$(sha256sum "$f" | cut -d' ' -f1)"; else echo "absent : $f"; fi
done
echo
echo "--- build.sh (as shipped in image) ---"
sed -n '1,60p' build.sh
echo
echo "--- key point source: reorder_bad.c assertion site ---"
grep -n 'assert\|checkThread\|pthread_create' reorder_bad.c | head -12
echo
echo "########## END PREFLIGHT ##########"
