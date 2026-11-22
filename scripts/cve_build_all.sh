#!/bin/bash
# Table 1 · CVE 基准阶段：用官方 build_all.sh 从干净状态构建全部 10 个 CVE 程序
# 官方脚本内含 set -eux，可留下 clang / staticAnalysis / dbds-clang-fast++ 的真实命令行
set -uo pipefail
export LANG=C.UTF-8

TS=$(date -u +%Y%m%dT%H%M%SZ)
EV=/lab/evidence/cve-build-$TS
mkdir -p "$EV"
BENCH=/workdir/PERIOD/evaluation/ConVul-CVE-Benchmarks

date -u +%Y-%m-%dT%H:%M:%SZ > "$EV/started-at.txt"

echo "===== source identity ====="
cd /workdir/PERIOD || exit 2
git rev-parse HEAD > "$EV/source-head.txt"

echo "===== pre-build cleanliness (build products must be absent) ====="
for d in "$BENCH"/CVE-*; do
  n=$(basename "$d")
  prog=$(ls "$d" | grep -E '^20[0-9]{2}-[0-9]+$' | head -1)
  {
    printf '%-16s prog=%-12s exe=%s bc=%s con=%s\n' "$n" "${prog:-none}" \
      "$([ -e "$d/${prog}" ] && echo PRESENT || echo absent)" \
      "$([ -e "$d/${prog}.bc" ] && echo PRESENT || echo absent)" \
      "$(ls "$d"/ConConfig.* 2>/dev/null | wc -l)"
  } >> "$EV/pre-build-status.txt"
done
cat "$EV/pre-build-status.txt"

echo "===== running official build_all.sh ====="
cd "$BENCH" || exit 2
time bash ./build_all.sh > "$EV/build.log" 2>&1
BUILD_RC=$?
echo "BUILD_RC=$BUILD_RC" > "$EV/exit-code.txt"

date -u +%Y-%m-%dT%H:%M:%SZ > "$EV/finished-at.txt"

echo "===== build products + digests ====="
: > "$EV/build-artifacts.sha256"
for d in "$BENCH"/CVE-*; do
  n=$(basename "$d")
  prog=$(ls "$d" | grep -E '^20[0-9]{2}-[0-9]+$' | head -1)
  [ -z "$prog" ] && continue
  if [ -x "$d/$prog" ]; then
    h=$(sha256sum "$d/$prog" | cut -d' ' -f1)
    kp=$(wc -l < "$d/ConConfig.$prog" 2>/dev/null | tr -d ' ')
    printf '%-16s %-14s %s  keypoints=%s\n' "$n" "$prog" "$h" "${kp:-0}" >> "$EV/build-artifacts.sha256"
  else
    printf '%-16s %-14s FAILED-NO-EXECUTABLE\n' "$n" "$prog" >> "$EV/build-artifacts.sha256"
  fi
done
cat "$EV/build-artifacts.sha256"

echo "===== key points per program ====="
for d in "$BENCH"/CVE-*; do
  n=$(basename "$d")
  prog=$(ls "$d" | grep -E '^20[0-9]{2}-[0-9]+$' | head -1)
  [ -z "$prog" ] && continue
  f="$d/ConConfig.$prog"
  if [ -f "$f" ]; then
    { printf '%-16s %s\n' "$n" "$(head -1 "$f") key points"
      sed 's/^/    /' "$f" | tail -n +2
    } >> "$EV/key-points.txt"
  fi
done
cat "$EV/key-points.txt" 2>/dev/null

echo "===== ASan baked in? (CVE 组用 -fsanitize=address) ====="
for d in "$BENCH"/CVE-*; do
  n=$(basename "$d"); prog=$(ls "$d" | grep -E '^20[0-9]{2}-[0-9]+$' | head -1)
  [ -z "$prog" ] && continue
  [ -x "$d/$prog" ] && printf '%-16s asan_symbols=%s\n' "$n" \
    "$(nm -C "$d/$prog" 2>/dev/null | grep -c '__asan' || echo 0)" >> "$EV/asan-check.txt"
done
cat "$EV/asan-check.txt" 2>/dev/null

echo "CVE_BUILD_DONE $TS"
