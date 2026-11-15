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

> 2026-11-15 完成一轮新的 `doubleFree` 最小实验，并保留完整证据。
> 使用固定 PERIOD 镜像完成构建、探索、回放和 `SCHED_DEADLINE` 验证。
> 构建、探索、回放和调度探针的外层退出码均为 `0`。
> 探索共执行 6 个调度，第 3 个调度首次触发 double-free，共保存 4 个错误调度，超时数为 0。
> 回放第一个保存的错误调度时，AddressSanitizer 再次报告 `double-free`。
> 镜像归档见 [Release](https://github.com/kiritojie/cs340-period-replication/releases/tag/doublefree-evidence-20261115)，完整命令、输出、退出码和原始错误调度文件见 [证据包](results/PERIOD_doubleFree_rerun_evidence-verified.zip)。

这份记录覆盖 PERIOD 的示例运行与回放。论文表格对应的正式基准实验另行汇报。本说明初稿由 ChatGPT 协助整理。
