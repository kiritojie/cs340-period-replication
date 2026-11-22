#!/bin/bash
# CS.reorder_3_bad 独立复现 · 阶段二：从零构建插桩产物
# 全程 set -x 留痕；输出与产物校验值落到挂载的 /lab/evidence
set -uo pipefail
export LANG=C.UTF-8

TS=$(date -u +%Y%m%dT%H%M%SZ)
EV=/lab/evidence/build-$TS
mkdir -p "$EV"

echo "===== build started (UTC) ====="
date -u +%Y-%m-%dT%H:%M:%SZ | tee "$EV/started-at.txt"

cd /workdir/PERIOD/evaluation/CS/reorder_3 || exit 2

echo "===== assertion site (for cross-check against paper/report) ====="
grep -n 'assert\|checkThread\|pthread_create' reorder_3_bad.c | head -14 | tee "$EV/assertion-site.txt"

echo "===== source identity ====="
sha256sum reorder_3_bad.c build.sh cleanDIR.sh | tee "$EV/source.sha256"

echo "===== running official build.sh ====="
# 官方脚本内含 set -eux，能同时留下 clang / staticAnalysis / dbds-clang-fast++ 的真实命令行
time ./build.sh > "$EV/build.log" 2>&1
BUILD_RC=$?
echo "BUILD_RC=$BUILD_RC" | tee "$EV/exit-code.txt"

date -u +%Y-%m-%dT%H:%M:%SZ | tee "$EV/finished-at.txt"

echo "===== build products ====="
ls -la | tee "$EV/product-listing.txt"

echo "===== product checksums ====="
sha256sum reorder_3_bad reorder_3_bad.bc ConConfig.reorder_3_bad 2>/dev/null | tee "$EV/build-artifacts.sha256"

echo "===== instrumentation config (key points) ====="
if [ -f ConConfig.reorder_3_bad ]; then
  wc -l ConConfig.reorder_3_bad
  head -20 ConConfig.reorder_3_bad
fi | tee "$EV/ConConfig.head.txt"

echo "===== DWARF producer (proves compiler version baked into binary) ====="
readelf --debug-dump=info reorder_3_bad 2>/dev/null | grep -m3 -A1 DW_AT_producer | tee "$EV/dwarf-producer.txt"

echo "===== instrumented call sites recorded by the pass ====="
grep -ci 'DBDS\|keypoint\|Con_' "$EV/build.log" 2>/dev/null | tee "$EV/build-log-hits.txt" || true

echo "===== archive whole build dir snapshot ====="
tar -czf "$EV/build-dir.tar.gz" . 2>/dev/null && ls -la "$EV/build-dir.tar.gz"

echo "BUILD_DONE $TS"
