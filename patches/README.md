# PERIOD 最小修复补丁说明

本目录收录针对上游 `wcventure/PERIOD`（基线提交 `b6f72a7b06d01ffa7114b640312873ec2578a5ea`）的最小 fail-fast 修复补丁。

## 补丁文件

| 文件 | 改动规模 | SHA-256 | 适用范围 |
| --- | :---: | --- | --- |
| [period-sched-deadline-failfast.patch](period-sched-deadline-failfast.patch) | 2 文件，`+12 / -3` 行 | `d72084186ff9b0fbc4705d23d2ec3aab6da44340cd274c52e9a191f98909398b` | 修复 `sched_setattr(SCHED_DEADLINE)` 准入失败（`EPERM`）引发的 1 秒阻塞、Use-After-Destruction `SIGSEGV (0x18)` 与静默假阴性 |

## 修改内容

1. **`tool/staticAnalysis/DBDS-INSTRU/llvm-mode/sched.h`（第 116 行）**：将 `sched_setattr < 0` 分支中的 `exit(-1)` 改为 `_exit(125)`，直接跳过 C++ 全局对象析构与 `traceEnd()` 的 1 秒 `usleep` / 遍历已析构 `mapTid` 崩溃。
2. **`tool/DBDS/run_PDS.py`（第 493、757 行）**：在预运行与主调度循环捕获子进程退出码 `125` 或 `stderr` 中的 `sched_setattr error`，打印 `[FATAL] SCHED_DEADLINE admission failed` 并以非零退出码 `rc=2` 立即终止。未改动原有第 108/360/507 行对普通目标程序 `-11` 的过滤逻辑。

## 应用与重建命令（`wcventure/period:stable` 容器内）

```bash
cd /workdir/PERIOD
git apply --check /repo/patches/period-sched-deadline-failfast.patch
git apply /repo/patches/period-sched-deadline-failfast.patch

# 重新编译运行时对象 DBDSFunction.o
export ROOT_DIR=/workdir/PERIOD
export PATH="$ROOT_DIR/clang+llvm/bin:$PATH"
export LD_LIBRARY_PATH="$ROOT_DIR/clang+llvm/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
make -C "$ROOT_DIR/tool/staticAnalysis/DBDS-INSTRU/llvm-mode" -B ../DBDSFunction.o
```

## 验证证据索引（全 7 档实测覆盖）

- **汇总与覆盖矩阵**：[docs/results/extension-cpu-affinity-merged/stats-summary.md](../docs/results/extension-cpu-affinity-merged/stats-summary.md)
- **8 核 5+5 轮干净交替 A/B 零回归**：[ab-verification-summary.tsv](../docs/results/extension-cpu-affinity-merged/patch-verification/ab-verification-summary.tsv) · 复现脚本 [scripts/patch_ab_verify.sh](../scripts/patch_ab_verify.sh)
- **全 7 档矩阵补跑（`reorder_5` 1/2/4/8 核 + `reorder_10` 1/4/8 核）**：[matrix-verification-summary.tsv](../docs/results/extension-cpu-affinity-merged/patch-verification/matrix-verification-summary.tsv) · 复现脚本 [scripts/patch_matrix_verify.sh](../scripts/patch_matrix_verify.sh)
