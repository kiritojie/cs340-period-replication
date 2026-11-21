# 第二周提交 · PERIOD 工具运行验证

`doubleFree` 是论文作者提供的工具验收示例。小组在 Windows WSL2 + Podman 环境验证了 PERIOD 的构建、探索和回放。11 月 7 日首次运行，11 月 14 日审计既有记录，11 月 15 日另行重跑并归档证据。论文表格对应的正式基准实验另行汇报。

## 2026-11-07 首次运行

实验使用 x86_64 Ubuntu 18.04.5、Clang 10.0.0 和 Linux 内核 `6.18.33.1-microsoft-standard-WSL2`。容器内记录的源码 HEAD 为 `b6f72a7b06d01ffa7114b640312873ec2578a5ea`。[原始环境记录](results/environment.txt)

| 检查项 | 实际结果 | 日志里怎么看 |
| --- | --- | --- |
| 总调度次数 | 6 | 从 `test 0001` 到 `test 0006`，末尾 `Total` 列的 `Round` 为 6。 |
| 首次触发错误 | 第 3 次 | `test 0003` 后第一次出现 `Error Found`。 |
| 错误调度次数 | 4，均触发同一个重复释放缺陷 | `Total Error Interleavings: 4`。 |
| 超时次数 | 0 | `Total Timeouts Interleavings: 0`。 |
| 回放 | AddressSanitizer 再次检测到 `double-free` | `SUMMARY: AddressSanitizer: double-free`。 |

[原始运行记录](results/doubleFree-smoke.log) · [原始回放记录](results/doubleFree-replay.log)

## 2026-11-14 初步证据审计

当日确认原始日志支持上述功能运行和回放结果。审计只检查既有材料，未访问 WSL2、重跑 PERIOD 或更改环境、探索及回放原始日志。当时暂缓完整独立复现结项，记录了以下缺口。

- 构建与探索共用一份日志，未保存外层完整命令、起止时间和 shell 退出码。回放也未记录外层退出码。历史退出码保留为 **UNKNOWN**。探索日志的 `[0, -6]` 是目标子进程状态集合。
- 日志引用的 4 份 `out_df_1/Errors/` 文件没有随首次运行记录提交。补采方案要求优先寻找原件，并将重新生成的文件归入新一轮。控制台打印的 period 列表只用于核对日志。
- 早期文档记录的镜像摘要为 `sha256:8f47d8b9148f2db579627842026e722d0f205ddeab13e70ee41a8df3dbd59fbc`，当时没有归档首次运行对应的 `image inspect` 输出。
- [版本核对](official-code-analysis.md#version-comparison)确认两个上游提交的 `tool/`、`test/`、`evaluation/` 和 `Dockerfile` 相同，差异仅涉及文档。实验容器仍需要自己的工作树及编译对象记录。
- [调度能力补证](week2-reproducibility.md#deadline-check)将单任务探针与 PERIOD 的实际调用链分开核验。`PREEMPT_DYNAMIC` 只描述内核配置。

[当日证据审计、先归档后补跑的命令及结项条件](week2-reproducibility.md)

## 2026-11-15 重跑与补采

在 WSL2 + Podman 上使用固定镜像完成一轮新的构建、探索、回放和调度验证。证据包的 `image-inspect.log` 记录了该轮使用的镜像 ID 和 digest，digest 与早期文档记录一致。[GitHub Release](https://github.com/kiritojie/cs340-period-replication/releases/tag/doublefree-evidence-20261115)提供镜像 `PERIOD-amd64.oci.tar`，[重跑证据包](results/PERIOD_doubleFree_rerun_evidence-verified.zip)收录该轮运行记录。

| 阶段 | 重跑结果 | 证据包内路径 |
| --- | --- | --- |
| 镜像与环境 | 镜像检查、容器环境记录和外层运行的退出码均为 `0` | `image-inspect.log`、`image-inspect-command.txt`、`image-inspect-exit-code.txt`、`results/environment/`、`outer-command.txt`、`outer-console.log`、`outer-exit-code.txt` |
| 构建 | 清理、bitcode、静态分析、插桩和 ASan 链接各阶段退出码均为 `0` | `results/clean/`、`results/bitcode/`、`results/static-analysis/`、`results/instrument/`、`results/link/` |
| 探索 | 驱动退出码 `0`。共 6 次调度，第 3 次首次触发错误，共 4 次触发同一 `double-free`，0 次超时 | `results/explore/`、`raw-output/Errors/`（4 份原始错误调度） |
| 回放 | 驱动退出码 `0`。回放本轮第一个错误调度，AddressSanitizer 再次检测到 `double-free` | `results/replay/` |
| 调度验证 | 单任务检查退出码 `0`，读回策略 `SCHED_DEADLINE`，runtime/deadline/period 为 `1000000/10000000/10000000 ns` | `results/sched-deadline/` |

各阶段目录保留 `command.txt`、`console.log` 和 `exit-code.txt`。全轮起止时间见 `started-at.txt` 和 `finished-at.txt`。`run_PDS.py` 的外层退出码表示驱动完成情况，目标程序的行为以状态记录与 ASan 输出为准。`raw-output/Errors/` 中的文件属于本次重跑，首次运行的历史退出码仍为 **UNKNOWN**。

## 独立复现验收状态

工具功能验证已完成。完整独立复现验收尚未结项。现有包可核对本轮镜像身份、运行命令、输出、外层退出码、原始错误调度和单任务策略读回。按[独立复现结项条件](week2-reproducibility.md#7-封存交付与结项条件)，仓库现有记录仍不足以核实以下项目。

- 重跑容器的源码工作树状态、预编译对象和最终 `df` 的可核对身份。
- PERIOD 工作线程的实际调度系统调用跟踪。单任务策略读回的适用范围是该次检查。
- 另一位组员独立构建、回放并记录配置和二进制摘要的验收结果。

2026-11-19，组内另行核对了重跑探索日志的统计结果，确认 6 次调度、首次错误第 3 次、4 次错误调度和 0 次超时。这次核对只分析已有日志。[独立统计核对](results/doublefree-log-check-2026-11-19.md)

本说明初稿由 ChatGPT 协助整理。
