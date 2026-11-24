# Extension 实验汇总：CPU 亲和性对 PERIOD 调度的影响

采集时间 2026-11-24 19:52–22:25（UTC+8），全部在单台宿主机、同一容器镜像内完成。

## 实验设置

| 项目 | 值 |
| --- | --- |
| 宿主机 | Intel i7-10510U（4 核 8 线程，8 逻辑核），Docker Desktop / WSL2 kernel 6.18.58.1 |
| 容器 | `wcventure/period:stable`（镜像 ID `8f47d8b9148f`），`--privileged` |
| PERIOD 版本 | `b6f72a7b06d01ffa7114b640312873ec2578a5ea` |
| 调度参数 | `-y -d 3`，`python3 tool/DBDS/run_PDS.py` |
| 轮次 | 每档 5 轮；单轮超时 600 s（1/4 核 reorder_10）、900 s（8 核 reorder_10、全部 reorder_5） |
| 二进制 | `reorder_5_bad` sha256 `346c4e50…d67501`；`reorder_10_bad` sha256 `329744a0…c6a14e1` |
| 环境自检 | `nproc=8`、`default_affinity=0-7`、`deadline_probe_rc=0`、`sudo_taskset_check=0` |

原始逐轮数据见 [rounds-summary.tsv](rounds-summary.tsv)（31 轮）。

## 结果一：`reorder_5_bad`（5 线程，225 个调度）

| 逻辑核（掩码） | 有效/总 | 调度数（Mean ± SD） | 错误交错（Mean ± SD） | 首次命中 | 超时 | 单轮耗时 s（Mean ± SD） |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| 1（`0`） | 5/5 | 225.00 ± 0.00 | **0.00 ± 0.00** | — | 0 | 242.76 ± 6.39 |
| 2（`0-1`） | 5/5 | 225.00 ± 0.00 | **0.00 ± 0.00** | — | 0 | 241.06 ± 1.85 |
| 4（`0-3`） | 5/5 | 225.00 ± 0.00 | **0.00 ± 0.00** | — | 0 | 240.29 ± 0.80 |
| 8（`0-7`） | 5/5 | 225.00 ± 0.00 | **20.00 ± 0.00** | 12 | 0 | 17.44 ± 1.98 |

## 结果二：`reorder_10_bad`（10 线程，2350 个调度）

| 逻辑核（掩码） | 有效/总 | 600 s 内推进调度数 | 错误交错 | 首次命中 | 单轮耗时 s |
| --- | :---: | :---: | :---: | :---: | :---: |
| 1（`0`） | 0/5（全超时） | 566 / 569 / 569 / 569 / 566 | NA | NA | 600.00（timeout 截断） |
| 4（`0-3`） | 0/2（全超时） | 557 / 567 | NA | NA | 600.00（timeout 截断） |
| 8（`0-7`） | 5/5 | 2350 × 5 | 87.60 ± 2.07 | 27 | 115.68 ± 17.14 |

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

## 结论

1. **根因（strace 实测）：子集亲和性导致 `SCHED_DEADLINE` 被内核以 `EPERM` 拒绝，随后首个工作线程立即触发 `SIGSEGV` 崩溃，而驱动静默吞掉异常。** 4 核（`0-3`）时 226 次 `sched_setattr` 全部返回 `-1 EPERM`，且**紧接着在 `si_addr=0x18` 处触发 `SIGSEGV` 杀掉整个子进程**——因此每次调度只有第 1 个工作线程执行到 `sched_setattr`（共 226 次），其余 4 个线程未及运行；而 8 核（`0-7`，完整 root domain）时全部 5 个工作线程均返回 `0`（共 1,130 次 `= 5 × 226`）。子进程每次崩溃前在 `SIGCHLD` 记录 `si_utime ≈ 100`（约 1.00 秒），精确解释了 1/2/4 核下约 1.07 秒/调度的固定耗时；更致命的是，外层 `run_PDS.py` 未将该 `SIGSEGV` 识别为调度器致命失效，在 `reorder_5_bad` 上仍输出 `rc=0`、225/225 调度、0 超时、0 错误，构成 **100% 静默假阴性（Silent False Negative）**。
2. **8 逻辑核是吞吐的硬拐点，且与核数、程序规模无关。** 8 核以下三种配置（1/2/4 核）× 两个程序（225 与 2350 个调度的总量）吞吐全部落在 **0.93 ± 0.01 调度/秒**；8 核时跳到 12.9 调度/秒（`reorder_5`）与 20.3 调度/秒（`reorder_10`），快 13.9–21.6 倍。1→2→4 核完全没有加速，因为三者都落入同一条失效路径（`taskset` 真子集 → `EPERM` → 约 1 s 后 `SIGSEGV` 崩溃）。
3. **核数不足时并发缺陷不可达。** `reorder_5_bad` 在 1/2/4 核下 5/5 轮都跑满全部 225 个调度（`gate_pass=1`、退出码 0），但**错误交错恒为 0、首次命中不存在**；8 核下每轮精确 20 次、首次命中第 12 个调度（与论文 `reorder_5` 的 20 一致）。
4. **排除"单次 5 秒超时"假设。** 1 核与 4 核 `reorder_10` 的日志内部 `Timeout` 计数均为 0，但仍在 600 s 内只推进 566 / 557 个调度；dry-run 的 `Runtime` 校准值与吞吐不成单调关系，真正决定速度的是周期节拍是否建立。
5. **与历史 8 核数据的可比性。** 调度数 `2350.00 ± 0.00` 与错误交错 85–90 均落在既有记录区间（历史 89/90/93），复现成立；但单轮 115.68 ± 17.14 s 是历史 55 s 的约 2 倍，**本机绝对耗时不可与旧机器横向比较**（README 已声明墙钟不可跨机比较）。8 核 `reorder_10` R5 出现 5 次内部超时，其余轮次为 0。
6. **低核档采样建议。** `reorder_10`（2350 调度）在 1/4 核下按 0.93 调度/秒推算需约 2500 s/轮，5 轮约 3.5 小时；后续低核实验应改用 `reorder_5`（225 调度，1 核约 240 s/轮）或显式放宽 `TIMEOUT_SEC`。同时应说明：低核档的结果反映的是"deadline 节拍失效后的退化行为"，不能等同于"核数不足导致交错变少"。

## 数据目录

| 目录 | 内容 |
| --- | --- |
| `extension-cpu-affinity/` | `reorder_10` 1 核 5 轮（全超时，含 566/569 推进量证据） |
| `extension-cpu-affinity-mask4-8/` | `reorder_10` 4 核 2 轮（全超时） |
| `extension-cpu-affinity-mask0-7/` | `reorder_10` 8 核 5 轮（有效） |
| `extension-cpu-affinity-reorder5/` | `reorder_5` 1/2/4 核各 5 轮（有效） |
| `extension-cpu-affinity-reorder5-mask0-7/` | `reorder_5` 8 核 5 轮（有效） |
| `extension-cpu-affinity-merged/` | 本汇总（31 轮合并 TSV + 本文件 + `traces/` 下两份 sched_setattr 原始 trace） |
