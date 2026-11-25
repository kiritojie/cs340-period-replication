# Extension 实验汇总：CPU 亲和性对 PERIOD 调度的影响

采集时间：修复前主实验 2026-11-24 19:52–22:25（UTC+8）；补丁验证 2026-11-25 13:39–14:43（UTC+8）。全部在单台宿主机、同一容器镜像内完成。

> **结论适用范围声明**：本文所有现象、性能数据与故障归因均指**在本实验环境（WSL2 kernel `6.18.58.1` + `wcventure/period:stable` `--privileged` + 上游 PERIOD `b6f72a7`）与该调度设置（`run_PDS.py -y -d 3`）下观察到的结果**，不能直接外推至所有 Linux 发行版、内核配置（例如通过 cgroup `cpuset` 显式拆分独立 root domain 的场景）或任意 CPU 亲和性配置。

---

## 复现快速入口与环境指纹

| 复现要素 | 固定值 / 入口 |
| --- | --- |
| 宿主机与 CPU 拓扑 | Intel i7-10510U（4 物理核 8 线程，8 逻辑核，默认亲和性 `0-7`） |
| 内核版本 | `6.18.58.1-microsoft-standard-WSL2`（Docker Desktop / WSL2） |
| 容器镜像 | `wcventure/period:stable`（镜像 ID `8f47d8b9148f`，运行参数 `--privileged`） |
| 上游 PERIOD 版本 | `b6f72a7b06d01ffa7114b640312873ec2578a5ea` |
| 最小修复补丁 | [patches/period-sched-deadline-failfast.patch](../../../patches/period-sched-deadline-failfast.patch)（commit `60c6868`，SHA-256 `d7208418…909398b`，`+12 / -3` 行） |
| 固定二进制哈希 | `reorder_5_bad`（未打补丁 `346c4e50…d67501`；打补丁后 `7ed93e66…f8a922a`）；`reorder_10_bad`（`329744a0…c6a14e1`） |
| 核心命令行 | `taskset -c <mask> python3 -u /workdir/PERIOD/tool/DBDS/run_PDS.py -y -d 3 ./<prog>` |
| 环境自检 | `nproc=8`、`default_affinity=0-7`、`deadline_probe_rc=0`、`sudo_taskset_check=0` |
| 复现与审计脚本 | 采集 [extension_cpu_affinity.sh](../../../scripts/extension_cpu_affinity.sh) · 合并审计 [extension_cpu_merge.py](../../../scripts/extension_cpu_merge.py) · 统计 [extension_cpu_stats.py](../../../scripts/extension_cpu_stats.py) · 补丁 A/B 验证 [patch_ab_verify.sh](../../../scripts/patch_ab_verify.sh) |
| 原始取证与清单 | [32 轮合并 TSV](rounds-summary.tsv) · [4 核 strace](traces/sched-setattr-mask-0-3.txt) · [8 核 strace](traces/sched-setattr-mask-0-7.txt) · [SIGSEGV 栈帧与反汇编](traces/sigsegv-0x18-backtrace.txt) · [SHA256SUMS](SHA256SUMS) |

**样本划分说明（严格分离，不混算）**：
- **修复前故障分析样本（32 轮）**：均基于未打补丁上游 `b6f72a7` 采集，完整记录见下文“32 轮修复前逐轮原始数据对照表”与 [rounds-summary.tsv](rounds-summary.tsv)（由 [extension_cpu_merge.py](../../../scripts/extension_cpu_merge.py) 从 5 个原始批次目录自动汇总，按收紧门禁重算 `gate_pass` 并从 `footer.txt` 回填 `internal_time_s`）。
- **修复后验证样本（独立归档于 `patch-verification/`）**：包含 4 核真子集 fail-fast 验证（3 轮，[verification-summary.tsv](patch-verification/verification-summary.tsv)）、8 核干净 5+5 轮交替 A/B 零回归验证（10 轮，[ab-verification-summary.tsv](patch-verification/ab-verification-summary.tsv)）及首次高负载时段 8 核对照（3+1 轮），**不计入 32 轮修复前主表**。

---

## 结果一：`reorder_5_bad` 修复前汇总（5 线程，225 个调度）

| 逻辑核（掩码） | 样本用途 | 驱动 `rc=0`/总 | 有效调度/总 | 调度数（Mean ± SD） | 错误交错（Mean ± SD） | 首次命中 | 超时 | 单轮耗时 s（Mean ± SD） |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1（`0`） | 修复前分析 | 5/5 | **0/5（伪通过）** | 225.00 ± 0.00 | **0.00 ± 0.00** | — | 0 | 242.76 ± 6.39 |
| 2（`0-1`） | 修复前分析 | 5/5 | **0/5（伪通过）** | 225.00 ± 0.00 | **0.00 ± 0.00** | — | 0 | 241.06 ± 1.85 |
| 4（`0-3`） | 修复前分析 | 5/5 | **0/5（伪通过）** | 225.00 ± 0.00 | **0.00 ± 0.00** | — | 0 | 240.29 ± 0.80 |
| 8（`0-7`） | 修复前基线 | 5/5 | **5/5** | 225.00 ± 0.00 | **20.00 ± 0.00** | 12 | 0 | 17.44 ± 1.98 |

> 注：1/2/4 核 15 轮的外层驱动均返回 `rc=0` 且输出完整汇总尾行（旧门禁判为通过），但逐轮 `stderr.log` 均报 `sched_setattr error: Operation not permitted` 且 dry-run 的 `kpNumArray` 全为 `0`，实际处于调度失效的**静默假阴性（Silent False Negative）**状态；脚本门禁现已收紧以拦截此类伪通过。

---

## 结果二：`reorder_10_bad` 修复前汇总（10 线程，2350 个调度）

| 逻辑核（掩码） | 样本用途 | 有效/总 | 600 s 内推进调度数 | 错误交错 | 首次命中 | 单轮耗时 s |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| 1（`0`） | 修复前分析 | 0/5（全超时） | 566 / 569 / 569 / 569 / 566 | NA | NA | 600.00（timeout 截断） |
| 4（`0-3`） | 修复前分析 | 0/2（全超时） | 557 / 567 | NA | NA | 600.00（timeout 截断） |
| 8（`0-7`） | 修复前基线 | 5/5 | 2350 × 5 | 87.60 ± 2.07 | 27 | 115.68 ± 17.14 |

---

## 32 轮修复前逐轮原始数据对照表（全部用于修复前故障分析）

下表与 [rounds-summary.tsv](rounds-summary.tsv) 逐行一致，直接对应结果一、结果二中的汇总统计：

| # | 程序 | 轮次 | 掩码（核数） | 退出码 `rc` | 新门禁 `gate_pass` | 调度数 | 错误数 | 超时 | 首次命中 | 内部耗时 s | 墙钟耗时 s | 样本归类 |
| :---: | --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | --- |
| 1 | `reorder_10_bad` | R1 | `0` (1) | 124 | 0 | 0566 | NA | NA | NA | NA | 599.962 | 修复前 · 真子集超时 |
| 2 | `reorder_10_bad` | R2 | `0` (1) | 124 | 0 | 0569 | NA | NA | NA | NA | 599.972 | 修复前 · 真子集超时 |
| 3 | `reorder_10_bad` | R3 | `0` (1) | 124 | 0 | 0569 | NA | NA | NA | NA | 599.981 | 修复前 · 真子集超时 |
| 4 | `reorder_10_bad` | R4 | `0` (1) | 124 | 0 | 0569 | NA | NA | NA | NA | 599.982 | 修复前 · 真子集超时 |
| 5 | `reorder_10_bad` | R5 | `0` (1) | 124 | 0 | 0566 | NA | NA | NA | NA | 599.986 | 修复前 · 真子集超时 |
| 6 | `reorder_10_bad` | R1 | `0-3` (4) | 124 | 0 | 0557 | NA | NA | NA | NA | 599.983 | 修复前 · 真子集超时 |
| 7 | `reorder_10_bad` | R2 | `0-3` (4) | 124 | 0 | 0567 | NA | NA | NA | NA | 599.984 | 修复前 · 真子集超时 |
| 8 | `reorder_10_bad` | R1 | `0-7` (8) | 0 | 1 | 2350 | 89 | 0 | 27 | 115.944 | 116.204 | 修复前 · 完整域基线 |
| 9 | `reorder_10_bad` | R2 | `0-7` (8) | 0 | 1 | 2350 | 86 | 0 | 27 | 119.036 | 119.262 | 修复前 · 完整域基线 |
| 10 | `reorder_10_bad` | R3 | `0-7` (8) | 0 | 1 | 2350 | 88 | 0 | 27 | 99.921 | 100.162 | 修复前 · 完整域基线 |
| 11 | `reorder_10_bad` | R4 | `0-7` (8) | 0 | 1 | 2350 | 90 | 0 | 27 | 100.467 | 100.691 | 修复前 · 完整域基线 |
| 12 | `reorder_10_bad` | R5 | `0-7` (8) | 0 | 1 | 2350 | 85 | 5 | 27 | 141.787 | 142.072 | 修复前 · 完整域基线 |
| 13 | `reorder_5_bad` | R1 | `0` (1) | 0 | 0 | 0225 | 0 | 0 | NA | 253.584 | 254.180 | 修复前 · 静默假阴性 |
| 14 | `reorder_5_bad` | R2 | `0` (1) | 0 | 0 | 0225 | 0 | 0 | NA | 239.891 | 240.132 | 修复前 · 静默假阴性 |
| 15 | `reorder_5_bad` | R3 | `0` (1) | 0 | 0 | 0225 | 0 | 0 | NA | 239.667 | 239.836 | 修复前 · 静默假阴性 |
| 16 | `reorder_5_bad` | R4 | `0` (1) | 0 | 0 | 0225 | 0 | 0 | NA | 239.572 | 239.743 | 修复前 · 静默假阴性 |
| 17 | `reorder_5_bad` | R5 | `0` (1) | 0 | 0 | 0225 | 0 | 0 | NA | 239.727 | 239.904 | 修复前 · 静默假阴性 |
| 18 | `reorder_5_bad` | R1 | `0-1` (2) | 0 | 0 | 0225 | 0 | 0 | NA | 239.249 | 239.422 | 修复前 · 静默假阴性 |
| 19 | `reorder_5_bad` | R2 | `0-1` (2) | 0 | 0 | 0225 | 0 | 0 | NA | 240.271 | 240.452 | 修复前 · 静默假阴性 |
| 20 | `reorder_5_bad` | R3 | `0-1` (2) | 0 | 0 | 0225 | 0 | 0 | NA | 239.471 | 239.649 | 修复前 · 静默假阴性 |
| 21 | `reorder_5_bad` | R4 | `0-1` (2) | 0 | 0 | 0225 | 0 | 0 | NA | 241.658 | 241.850 | 修复前 · 静默假阴性 |
| 22 | `reorder_5_bad` | R5 | `0-1` (2) | 0 | 0 | 0225 | 0 | 0 | NA | 243.672 | 243.904 | 修复前 · 静默假阴性 |
| 23 | `reorder_5_bad` | R1 | `0-3` (4) | 0 | 0 | 0225 | 0 | 0 | NA | 239.589 | 239.784 | 修复前 · 静默假阴性 |
| 24 | `reorder_5_bad` | R2 | `0-3` (4) | 0 | 0 | 0225 | 0 | 0 | NA | 239.139 | 239.332 | 修复前 · 静默假阴性 |
| 25 | `reorder_5_bad` | R3 | `0-3` (4) | 0 | 0 | 0225 | 0 | 0 | NA | 241.254 | 241.454 | 修复前 · 静默假阴性 |
| 26 | `reorder_5_bad` | R4 | `0-3` (4) | 0 | 0 | 0225 | 0 | 0 | NA | 240.252 | 240.464 | 修复前 · 静默假阴性 |
| 27 | `reorder_5_bad` | R5 | `0-3` (4) | 0 | 0 | 0225 | 0 | 0 | NA | 240.206 | 240.401 | 修复前 · 静默假阴性 |
| 28 | `reorder_5_bad` | R1 | `0-7` (8) | 0 | 1 | 0225 | 20 | 0 | 12 | 14.466 | 14.657 | 修复前 · 完整域基线 |
| 29 | `reorder_5_bad` | R2 | `0-7` (8) | 0 | 1 | 0225 | 20 | 0 | 12 | 17.323 | 17.569 | 修复前 · 完整域基线 |
| 30 | `reorder_5_bad` | R3 | `0-7` (8) | 0 | 1 | 0225 | 20 | 0 | 12 | 19.992 | 20.198 | 修复前 · 完整域基线 |
| 31 | `reorder_5_bad` | R4 | `0-7` (8) | 0 | 1 | 0225 | 20 | 0 | 12 | 17.632 | 17.819 | 修复前 · 完整域基线 |
| 32 | `reorder_5_bad` | R5 | `0-7` (8) | 0 | 1 | 0225 | 20 | 0 | 12 | 16.758 | 16.945 | 修复前 · 完整域基线 |

---

## 结果三：内核机制取证（strace，受控校准路径）

先用 `run_PDS.py` 走完整的 dry-run 校准，再在受控执行上挂 `strace`：

```bash
taskset -c <mask> strace -f -e trace=sched_setattr -o trace.txt \
  python3 -u /workdir/PERIOD/tool/DBDS/run_PDS.py -y -d 3 ./reorder_5_bad
```

| 掩码 | `sched_setattr` 次数 | 返回 0 | 返回 -1 | `sched_runtime` | `sched_deadline = period` |
| --- | :---: | :---: | :---: | :---: | :---: |
| 4 核（`0-3`） | 226 | **0** | **226（全部 EPERM）** | 407,240 ns | 7,635,750 ns |
| 8 核（`0-7`） | 1,132 | 1,130 | 0 | 495,640 ns | 9,293,250 ns |

Trace 原文：[4 核](traces/sched-setattr-mask-0-3.txt) · [8 核](traces/sched-setattr-mask-0-7.txt)。两次运行的二进制哈希均为 `346c4e50…d67501`。

4 核原文样例（226 次全部如此，每次 `EPERM` 后紧接 `SIGSEGV` 杀掉子进程）：

```
383  sched_setattr(0, {size=48, sched_policy=SCHED_DEADLINE, ..., sched_runtime=407240,
       sched_deadline=7635750, sched_period=7635750}, 0) = -1 EPERM (Operation not permitted)
383  --- SIGSEGV {si_signo=SIGSEGV, si_code=SEGV_MAPERR, si_addr=0x18} ---
383  +++ killed by SIGSEGV (core dumped) +++
381  --- SIGCHLD {..., si_status=SIGSEGV, si_utime=100, si_stime=1} ---
```

8 核原文样例：

```
sched_setattr(0, {size=48, sched_policy=SCHED_DEADLINE, ..., sched_runtime=495640,
  sched_deadline=9293250, sched_period=9293250}, 0) = 0
```

**方法学注记（重要）**：直接用 `Dry_Run=0 DBDS_Run=1 ./reorder_5_bad` 跑裸二进制（不带 dry-run 校准）时，`set_sched_dl()` 收到的参数是 `runtime=0, deadline=0, period=0`，4 核与 8 核**都**返回 `-1 EINVAL`，无法区分核数——该路径不可用于本实验的取证，必须先经 `run_PDS.py` 校准。

---

## 结果四：源码级崩溃链与静默假阴性定位

对与归档逐字节一致的 `reorder_5_bad`（sha256 `346c4e50…d67501`，内置 `DBDSFunction.o` 含完整 DWARF 调试信息）在 `taskset -c 0-3` 下通过 `SA_SIGINFO` 捕获崩溃现场，并结合 `addr2line` 与 `objdump` 反汇编完整还原了 `EPERM → 1 s 阻塞 → SIGSEGV (0x18) → 静默假阴性` 的源码级因果链（完整栈帧与反汇编见 [traces/sigsegv-0x18-backtrace.txt](traces/sigsegv-0x18-backtrace.txt)）：

1. **工作线程调用 `exit(-1)`**：`setThread`（`reorder_bad.c:70`）→ `instr_PthreadCall`（`DBDSFunction.cpp:492`）→ `setDeadLineSched`（`DBDSFunction.cpp:225`）→ `set_sched_dl`（`sched.h:113-116`）。`sched_setattr(SCHED_DEADLINE)` 返回 `-1 EPERM` 后，第 116 行直接调用 `exit(-1)`，导致未执行到第 504 行的 `set_tid_to_run(0)`。
2. **精确解释 ~1.07 s/调度与 `si_utime ≈ 100`**：`exit(-1)` 触发 `__run_exit_handlers`，先析构全局 C++ 对象（含全局 `std::map mapTid`），随后经 `_dl_fini` 调用 `__attribute__((destructor))` 函数 `traceEnd()`（`DBDSFunction.cpp:344`）。因尚未进入 `pthread_join`，`joinable == 0`，`traceEnd()` 第 348–351 行执行 `usleep(1000000)`（休眠 1.00 秒）；同一时刻主线程卡在 `before_pthread_create()` 第 510 行 `while(get_tid_to_run() != 0);` 空转 1.00 秒，恰好对应 `SIGCHLD` 记录的 `si_utime ≈ 100`（1.00 s 用户态 CPU 时间）与每调度 ~1.07 s 耗时。
3. **精确解释 `SIGSEGV (si_addr=0x18)`**：`usleep` 结束后，`traceEnd()` 第 354 行遍历**已被析构**的全局 `mapTid`（`for(Tiditer = mapTid.begin(); Tiditer != mapTid.end(); Tiditer++)`，构成析构后使用 Use-After-Destruction）。`operator++`（`stl_tree.h:295`）进入 `libstdc++.so.6` 的 `_ZSt18_Rb_tree_incrementPSt18_Rb_tree_node_base`：偏移 `+0x20` 处 `mov 0x8(%rdi), %rax` 读出空父指针 `RAX = 0x0`，紧接着 `+0x24` 处执行 `cmp 0x18(%rax), %rdi`，解引用 `0x0 + 0x18 = 0x18` 触发 `SIGSEGV (SEGV_MAPERR)`。
4. **精确解释 100% 静默假阴性**：归档 4 核 `stdout.log` 尾部明确记录了 `1 status found: [-11]`（全部 225 次子进程均因 `SIGSEGV` 返回 `-11`），但 `tool/DBDS/run_PDS.py` 第 **108 行**（`record_error_message`）与第 **360 行**（dry-run 检查）显式写死了：
   ```python
   if(process.returncode!=0 and process.returncode!=1 and process.returncode!=6 and process.returncode!=-11):
   ```
   **直接排除了 `-11`（`SIGSEGV`）**，且第 493–494 行的预运行阶段未检查返回码（导致 `kpNumArray` 保持全 `0`）。因此驱动既不报错也不中止，最终以 `rc=0`、0 错误、0 超时静默结束。

---

## 结果五：最小修复补丁与修复前后验证覆盖范围

针对结果四定位的两处根因，编写了仅改动 2 个文件（`+12 / -3`）的最小 fail-fast 补丁 [patches/period-sched-deadline-failfast.patch](../../../patches/period-sched-deadline-failfast.patch)（SHA-256 `d7208418…909398b`）：

- **运行时（`sched.h:116`）**：将 `exit(-1)` 改为 `_exit(125)`，避免从工作线程触发全局 C++ 析构与 `traceEnd()` 的 1 秒 `usleep` 及 Use-After-Destruction `SIGSEGV (0x18)`，以专用内部哨兵码 `125` 立即结束子进程。
- **驱动端（`run_PDS.py:493, 757`）**：在预运行与主调度循环捕获子进程退出码 `125` 或 `stderr` 中的 `sched_setattr error`，打印明确 `[FATAL] SCHED_DEADLINE admission failed` 诊断并以非零退出码 `rc=2` 立即终止，消除静默假阴性。
- **补丁边界说明**：该最小补丁专门修复 `SCHED_DEADLINE` 准入失败（`EPERM`）链路，未改动 `run_PDS.py` 原有第 108/360/507 行对普通目标程序 `-11`（`SIGSEGV`）的过滤逻辑；退出码 `125` 仅作为 `sched.h` 与 `run_PDS.py` 之间的内部约定，对外由驱动统一转为 `rc=2`（与 `timeout` 的退出码 `125` 区分）。

### 修复前后验证覆盖矩阵（`reorder_5_bad` 与 `reorder_10_bad` 逐档对照）

| 程序 | 掩码（核数） | 修复前实测（32 轮主表） | 修复后实测（`patch-verification/`） | 覆盖状态说明 |
| --- | :---: | --- | --- | --- |
| `reorder_5_bad` | `0`（1 核） | 5 轮：`rc=0` 伪通过，0 错误，242.76 ± 6.39 s | **未实测** | 与 `0-3` 走同一 `sched_setattr EPERM` 预运行拦截路径，但本仓库未逐档重跑 |
| `reorder_5_bad` | `0-1`（2 核） | 5 轮：`rc=0` 伪通过，0 错误，241.06 ± 1.85 s | **未实测** | 同上，未逐档重跑 |
| `reorder_5_bad` | **`0-3`（4 核）** | 5 轮：`rc=0` 伪通过，0 错误，240.29 ± 0.80 s | **3 轮实测**：**`rc=2`（Fail-Fast）**，0 调度拦截，**0.33–0.75 s**（快 ~440×） | 已实测验证（[verification-summary.tsv](patch-verification/verification-summary.tsv)） |
| `reorder_5_bad` | **`0-7`（8 核）** | 5 轮：`rc=0`，20.00 ± 0.00 错误，17.44 ± 1.98 s | **5+5 轮干净 A/B**：补丁后 **20.00 ± 0.00** 错误 / **16.59 ± 0.50 s** vs. 未打补丁 **19.80 ± 0.45** / **16.43 ± 2.63 s** | 已实测确认零回归（[ab-verification-summary.tsv](patch-verification/ab-verification-summary.tsv)） |
| `reorder_10_bad` | `0`（1 核） | 5 轮：`rc=124` 全超时（600 s，推进 566–569 调度） | **未实测** | 未对 `reorder_10_bad` 单独重跑补丁验证 |
| `reorder_10_bad` | `0-3`（4 核） | 2 轮：`rc=124` 全超时（600 s，推进 557–567 调度） | **未实测** | 同上 |
| `reorder_10_bad` | `0-7`（8 核） | 5 轮：`rc=0`，87.60 ± 2.07 错误，115.68 ± 17.14 s | **未实测** | 同上；补丁仅修改错误退出分支，正常路径不触及 |

> 另注：在 `wcventure/period:stable` 容器内以 `git apply` 干净合入补丁、重新编译 `DBDSFunction.o` 与 `reorder_5_bad`（未打补丁 sha256 `346c4e50…d67501`，打补丁后 sha256 `7ed93e66…f8a922a`，见 [ab-binary-identity.txt](patch-verification/ab-binary-identity.txt)）后，还保留了首次高负载时段的 3+1 轮 8 核对照（补丁后 8/13/8，`Runtime` 1034–1439 ns vs. 未打补丁 7，`Runtime` 1189 ns，22.8–49.8 s），与干净 A/B 组未打补丁 R4（19 错误、`Runtime=1113 ns`）一并支持错误数下降与低 `Runtime` 校准/宿主机负载相关，非补丁回归。此前一次 A/B 尝试因中止不彻底存在后台重叠容器污染，已整体作废并由 [patch_ab_verify.sh](../../../scripts/patch_ab_verify.sh) 的本次干净重跑替代。

---

## 结论（限定于本实验环境与 `-y -d 3` 设置）

1. **根因（内核规则 + strace 实测）：在本实验环境下，真子集亲和性掩码违反 Linux `SCHED_DEADLINE` root domain 准入约束，触发 `EPERM → SIGSEGV`，且驱动静默吞掉异常。** 按 Linux 内核文档 `Documentation/scheduler/sched-deadline.rst` 第 5 节（*Bandwidth management*），`SCHED_DEADLINE` 任务的 CPU 亲和性掩码必须覆盖其所在的整个 root domain，否则内核以 `EPERM` 拒绝。在我们的 8 逻辑核 WSL2 容器环境下，4 核真子集（`0-3`）下 226/226 次 `sched_setattr` 全部返回 `-1 EPERM`，且紧接着在 `si_addr=0x18` 处触发 `SIGSEGV` 杀掉整个子进程——因此每次调度仅第 1 个工作线程执行到 `sched_setattr`（共 226 次），其余 4 个线程未及运行；而在完整 root domain（`0-7`，8 核）下全部 5 个工作线程均返回 `0`（共 1,130 次 `= 5 × 226`）。子进程每次崩溃前在 `SIGCHLD` 记录 `si_utime ≈ 100`（约 1.00 秒），精确解释了真子集掩码下约 1.07 秒/调度的固定耗时；更致命的是，外层 `run_PDS.py` 未将该 `SIGSEGV` 识别为调度器致命失效，在 `reorder_5_bad` 上仍输出 `rc=0`、225/225 调度、0 超时、0 错误，构成 **100% 静默假阴性（Silent False Negative）**。
2. **吞吐变化是“真子集失效 vs. 完整 root domain”的二态跳变，而非核数缩放拐点。** 在本实验环境中，1/2/4 核本质上都处于同一条真子集失效路径（`taskset` 真子集 → `EPERM` → 约 1 s 后 `SIGSEGV` 崩溃），因此在两个程序（225 与 2350 个调度）上吞吐全部锁死在 **0.93 ± 0.01 调度/秒**，1→2→4 核完全无加速；切回完整 root domain（`0-7`）恢复周期节拍后，吞吐跳至 12.9 调度/秒（`reorder_5`）与 20.3 调度/秒（`reorder_10`），快 13.9–21.6 倍。
3. **真子集亲和性下形成伪通过，完整 root domain 下精确复现基线。** `reorder_5_bad` 在 1/2/4 核下 5/5 轮虽在形式上跑满 225 个调度、外层退出码为 0，但 dry-run 的 `kpNumArray` 全为 `0`、`stderr` 持续报 `sched_setattr error: Operation not permitted`，**错误交错恒为 0、首次命中不存在**，实际并未完成有效并发探索；切回完整 root domain（`0-7`）后每轮精确复现 20 次错误交错、首次命中第 12 个调度（与本组 [Table 2 第一段](../../table2-segment1-reorder.md) `reorder_5` 十轮基线一致）。
4. **排除“单次 5 秒超时”假设。** 1 核与 4 核 `reorder_10` 的日志内部 `Timeout` 计数均为 0，但仍在 600 s 内只推进 566 / 557 个调度；dry-run 的 `Runtime` 校准值与吞吐不成单调关系，真正决定速度的是 `SCHED_DEADLINE` 周期节拍是否成功建立。
5. **8 核 `reorder_10` 与历史基线的对照说明。** 调度数 `2350.00 ± 0.00` 与首次命中 `27` 均与既有记录完全一致；错误交错均值 `87.60 ± 2.07`（范围 85–90），略低于此前 Table 2 第一段记录的 89–93，其中 R5 出现 5 次内部超时（错误数 85），其余 4 轮为 0 超时（错误数 86–90）。单轮墙钟耗时 `115.68 ± 17.14 s` 约为此前 55 s 的 2 倍，说明高线程数下的墙钟耗时与错误计数均受宿主机负载与超时影响（不可跨机或跨负载横向比较）。
6. **适用范围与真实核数单变量对照（已完成第二部分）。** 本部分结论限定于本实验环境（单一 8 核 root domain 下使用 `taskset` 设真子集），不能直接等同于“核数不足导致交错变少”或所有 Linux/cgroup 配置均会复现相同故障。为此我们进一步通过修改 `.wslconfig` 的 `processors=2 / 4 / 8`（不使用 `taskset`，每档均覆盖完整 root domain）完成了 24 轮主扫描与 6 轮 2→8 逆序复核（详见 [extension-wsl-cores/stats-summary.md](../extension-wsl-cores/stats-summary.md)）：真实 4 核与 8 核表现基本持平（`reorder_5` 均为 `20.00 ± 0.00` 错误、`18.39 s` vs. `16.58 s`；`reorder_10` 为 `89.67 ± 0.58` vs. `90.00 ± 0.00` 错误、`93.60 s` vs. `88.83 s`），直接支持本部分 4 核真子集失效归因于 root domain 约束；而降至真实 2 核时，即使 `SCHED_DEADLINE` 全部正常准入，仍出现明显的检出率下降（`reorder_5` 合并精确双侧 Mann–Whitney $p=0.00575$）。另外，`reorder_10`（2350 调度）在真子集退化路径下按 0.93 调度/秒推算需约 2500 s/轮，后续验证退化行为应继续优先使用 `reorder_5`（225 调度，约 240 s/轮）。

---

## 数据目录与原始日志索引

| 目录 | 内容与链接 |
| --- | --- |
| [extension-cpu-affinity/](../extension-cpu-affinity/) | `reorder_10` 1 核 5 轮原始日志与 [SHA256SUMS](../extension-cpu-affinity/SHA256SUMS)（全超时，含 566/569 推进量证据）；另含 1 个提前中止的 `cpus-2_mask-0-1/round-1` 半截目录，未计入 32 轮统计 |
| [extension-cpu-affinity-mask4-8/](../extension-cpu-affinity-mask4-8/) | 原计划跑 `0-3` 与 `0-7` 的批次目录，实际保留 `reorder_10` 4 核（`0-3`）R1–R2（全超时）与 [SHA256SUMS](../extension-cpu-affinity-mask4-8/SHA256SUMS)；另含提前中止的 `round-3` 半截目录，未计入 32 轮统计 |
| [extension-cpu-affinity-mask0-7/](../extension-cpu-affinity-mask0-7/) | `reorder_10` 8 核（`0-7`）5 轮有效日志与 [SHA256SUMS](../extension-cpu-affinity-mask0-7/SHA256SUMS) |
| [extension-cpu-affinity-reorder5/](../extension-cpu-affinity-reorder5/) | `reorder_5` 1/2/4 核各 5 轮原始日志与 [SHA256SUMS](../extension-cpu-affinity-reorder5/SHA256SUMS)（驱动 `rc=0`，实为静默假阴性）；另含提前中止的 `cpus-6_mask-0-5/round-1` 半截目录，未计入 32 轮统计 |
| [extension-cpu-affinity-reorder5-mask0-7/](../extension-cpu-affinity-reorder5-mask0-7/) | `reorder_5` 8 核（`0-7`）5 轮有效日志与 [SHA256SUMS](../extension-cpu-affinity-reorder5-mask0-7/SHA256SUMS) |
| [extension-cpu-affinity-merged/](./) | 本汇总（[32 轮合并 TSV](rounds-summary.tsv) + 本文件 + `traces/` 下两份 `sched_setattr` 原始 trace 与源码级 `SIGSEGV (0x18)` 取证 + `patch-verification/` 下修复后验证日志 + [SHA256SUMS](SHA256SUMS)） |
