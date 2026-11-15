# 第二周提交 · PERIOD 工具运行验证

> 2026-11-14 第二周证据复核：**功能验证已完成，完整可复现性验收尚未完成，暂不结项。** 本次没有访问 WSL2 或重跑 PERIOD；没有改写以下三份原始日志。缺失证据、补采命令及结项条件见[第二周证据补全说明](week2-reproducibility.md)。

2026 年 11 月 7 日，在 Windows 的 WSL2 + Podman 环境中运行了论文作者提供的 `doubleFree` 示例。本次验证检查 PERIOD 能否找到会触发已知错误的线程执行顺序，以及保存的顺序能否用于再次验证。示例中的错误是同一块内存被释放了两次。

实验使用 Ubuntu 18.04.5、Clang 10.0.0 和 Linux 内核 `6.18.33.1-microsoft-standard-WSL2`。容器内的官方源码提交为 `b6f72a7b06d01ffa7114b640312873ec2578a5ea`。[环境记录](results/environment.txt)支持上述版本信息。本说明先前记载的镜像摘要为 `sha256:8f47d8b9148f2db579627842026e722d0f205ddeab13e70ee41a8df3dbd59fbc`；目前没有归档对应的 image inspect 原始输出，镜像身份仍待补证。

| 检查项 | 实际结果 | 日志里怎么看 |
| --- | --- | --- |
| 总共尝试多少种执行顺序 | 6 | 运行记录从 `test 0001` 到 `test 0006`，末尾 `Total` 列的 `Round` 为 6。 |
| 第几次首次报错 | 第 3 次 | `test 0003` 后第一次出现 `Error Found`。 |
| 多少种执行顺序触发错误 | 4 | 运行记录末尾显示 `Total Error Interleavings: 4`。 |
| 有多少次超时 | 0 | 运行记录末尾显示 `Total Timeouts Interleavings: 0`。 |
| 回放是否再次检测到错误 | 是 | 回放记录出现 `SUMMARY: AddressSanitizer: double-free`。 |

[原始运行记录](results/doubleFree-smoke.log) · [原始回放记录](results/doubleFree-replay.log)

## 第二周证据审计补充

- 原始日志支持 6 个调度、首次错误第 3 个、4 个错误交错、0 个超时及 ASan double-free 回放；4 个错误交错对应同一个示例缺陷。
- 构建与探索合并在同一日志中，未保存外层完整命令、起止时间和 shell 退出码；回放日志同样没有 shell 退出码。探索末尾的 `[0, -6]` 是目标子进程状态集合，不能写成构建或 Python 驱动退出码。历史退出码保留为 **UNKNOWN**。
- 日志中提到的 4 个 `out_df_1/Errors/` 原始文件没有进入本仓库；需从原容器恢复，或执行明确标为“补采”的新运行。不能用控制台打印的 period 列表伪造回放文件。
- [版本核对](official-code-analysis.md#version-comparison)确认两个上游提交的 `tool/`、`test/`、`evaluation/` 相同；容器工作树和编译对象来源仍待记录。
- [调度能力补证](week2-reproducibility.md#deadline-check)保留待执行的环境检查、单任务探针和实际调用链核验要求。`PREEMPT_DYNAMIC` 不能单独证明 SCHED_DEADLINE 已生效。
- [补采说明](week2-reproducibility.md)包含先归档旧文件、再构建/探索/回放的完整命令及验收清单。

这份记录覆盖 PERIOD 的示例运行与回放。论文表格对应的正式基准实验另行汇报。本说明初稿由 ChatGPT 协助整理。
