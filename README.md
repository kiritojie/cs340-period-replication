# CS340 · PERIOD 论文复现

CS340 Operating Systems 小组项目。PERIOD 通过控制线程在关键位置的执行顺序，探索并发程序在不同调度下的行为。本仓库收录小组的源码分析、检查脚本和实验记录，官方工具源码由上游维护。

Cheng Wen 等，*Controlled Concurrency Testing via Periodical Scheduling*，ICSE 2022。[论文 PDF](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf) · [DOI](https://doi.org/10.1145/3510003.3510178) · [官方源码](https://github.com/wcventure/PERIOD)

[复现入口](#复现入口) · [正式复现范围](#正式复现范围) · [更新历史](#更新历史)

## 项目进度

| 阶段 | 进展 | 记录 |
| --- | --- | --- |
| 第一周 · 论文与源码 | 固定上游版本，梳理调度算法、构建、插桩与回放路径，完成两次 ARM64 Mac 环境检查。 | [算法笔记](docs/algorithm-notes.md) · [源码分析](docs/official-code-analysis.md) · [第一周记录](docs/week1-results.md) |
| 第二周 · 工具验收 | 在 Windows WSL2 + Podman 上跑通 `doubleFree` 的构建、探索和 ASan 回放，随后完成证据审计与重跑补采。 | [第二周记录](docs/week2-doublefree.md) |
| 日志统计 | 已用首次探索日志与重跑探索日志核对统计脚本。 | [统计说明](docs/log-statistics.md) · [11 月 19 日独立统计核对](docs/results/doublefree-log-check-2026-11-19.md) |
| 论文基准 | 首个正式用例待小组确认，暂无本组 `Paper vs. Ours` 数据。 | [复现计划](docs/reproduction-plan.md) |

## 第二周 doubleFree 验证摘要

官方 `doubleFree` 示例中，某些线程执行顺序会让同一块内存被释放两次。11 月 7 日的首次运行和 11 月 15 日的重跑分别记录了以下结果。

| 指标 | 两轮各自的记录 | 日志定位 |
| --- | --- | --- |
| 总调度次数 | 6 | `test 0001` 至 `test 0006`，汇总 `Round` 为 6 |
| 首次触发错误 | 第 3 次 | `test 0003` 后首次出现 `Error Found` |
| 错误调度次数 | 4，均触发同一示例缺陷 | `Total Error Interleavings: 4` |
| 超时次数 | 0 | `Total Timeouts Interleavings: 0` |
| 回放 | AddressSanitizer 再次检测到 `double-free` | `SUMMARY: AddressSanitizer: double-free` |

- **2026-11-07** 在 WSL2 + Podman 容器完成首次构建、探索和回放。[首次探索日志](docs/results/doubleFree-smoke.log) · [首次回放日志](docs/results/doubleFree-replay.log)
- **2026-11-14** 完成初步审计，发现首次运行的原始调度、外层命令及退出码、容器与构建身份、实际调度验证等证据尚不完整。[当日审计与补采方案](docs/week2-reproducibility.md)
- **2026-11-15** 用固定镜像完成新一轮构建、探索与回放，归档命令、输出、退出码、4 份原始错误调度、镜像检查及 `SCHED_DEADLINE` 单任务策略读回。[重跑证据包](docs/results/PERIOD_doubleFree_rerun_evidence-verified.zip)

工具功能验证已完成。完整独立复现仍有待核验项，包括重跑容器的源码工作树与编译对象身份、PERIOD 工作线程的实际调度调用链，以及由另一位组员独立构建和回放的记录。[验收状态明细](docs/week2-doublefree.md#独立复现验收状态)

## 复现入口

1. 核对已验证的 x86_64 Linux 路线，参见下方[环境检查](#环境检查)及首次运行的[环境记录](docs/results/environment.txt)。
2. 从 [GitHub Release](https://github.com/kiritojie/cs340-period-replication/releases/tag/doublefree-evidence-20261115) 获取固定镜像归档 `PERIOD-amd64.oci.tar`。重跑证据包同时提供镜像身份、各阶段记录及附带的采集脚本。
3. 参阅[第二周证据补采说明](docs/week2-reproducibility.md)中的环境、构建和记录保存方法。该文档记录 11 月 14 日的审计和当时拟定的命令，已执行的补采以[第二周记录](docs/week2-doublefree.md#2026-11-15-重跑与补采)为准。

## 正式复现范围

| 用例 | 用途 | 本组进度 |
| --- | --- | --- |
| `doubleFree` | 工具功能验收，验证构建、受控调度和回放 | 已完成工具验证，示例数据仅用于验收 |
| `CVE-2016-7911` | [论文 Table 1（RQ2）](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf#page=8)，并发错误检测基准 | 原计划首选，待小组确认 |
| `CS.reorder_3_bad` | [论文 Table 2（RQ1）](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf#page=9)，并行调度评估基准 | 候选，待小组确认 |

确认首个正式用例后，按选定的论文设置至少独立完整运行三次，产出所选表中该用例的第一行 `Paper vs. Ours`。记录首次触发错误的调度序号、总调度数和错误调度数，报告均值和样本标准差，另记超时和未发现错误的情况。逐轮记录运行环境、命令和参数，说明与论文设置的差异，并链接原始日志。将小型原始日志、回放调度文件和回放输出保存至 `docs/results/`。[正式实验计划](docs/reproduction-plan.md) · [日志统计用法](docs/log-statistics.md)

## 环境检查

首次验证环境为 Windows WSL2 + Podman 上的 x86_64 Ubuntu 18.04.5 容器，使用 Clang 10.0.0。第一周的 ARM64 Mac 检查保留了两次环境盘点和 Docker CLI 不在当时 PATH 中的记录，当时在该宿主上的示例状态为 `NOT_RUN`。[Mac 环境日志](docs/results/environment-2026-11-07.txt) · [示例前提检查](docs/results/doublefree-feasibility-2026-11-07.txt)

在仓库根目录使用 Bash 3.2+ 执行（macOS/Linux）。

```bash
./scripts/check_environment.sh
```

[环境检查脚本](scripts/check_environment.sh)只读盘点系统、CPU、构建工具、Python 模块、Linux 调度线索和 Docker 状态。退出码 `0` 表示盘点完成。依赖是否齐全以报告为准，实际调度能力以运行记录为准。

<details>
<summary><strong>保存环境检查日志与退出码</strong></summary>

运行以下命令可将报告同时保留在终端和文件中。`noclobber` 防止覆盖同名记录。

```bash
mkdir -p docs/results
(
  set -o noclobber
  report="docs/results/environment-$(date -u +%Y%m%dT%H%M%SZ).txt"
  exec 3> "$report" || exit 1
  ./scripts/check_environment.sh >&3 2>&1
  status=$?
  printf '\n[script_exit_code=%s]\n' "$status" >&3
  exec 3>&-
  cat "$report"
  exit "$status"
)
```

</details>

## 源码版本与历史记录

| 用途 | 固定上游提交 | 依据 |
| --- | --- | --- |
| 第一周源码分析 | [`cb8deb9a176e5bb292d70d46557dd61dc0e98069`](https://github.com/wcventure/PERIOD/commit/cb8deb9a176e5bb292d70d46557dd61dc0e98069) | 2022-10-09，`fix Install.md`。[文件 blob ID 与版本链接](docs/official-source.json) |
| 第二周首次运行环境记录中的源码 HEAD | [`b6f72a7b06d01ffa7114b640312873ec2578a5ea`](https://github.com/wcventure/PERIOD/commit/b6f72a7b06d01ffa7114b640312873ec2578a5ea) | [首次运行环境记录](docs/results/environment.txt) |

两个上游提交中的 `tool/`、`test/`、`evaluation/` 和 `Dockerfile` 内容相同，净差异仅涉及四份文档。11 月 15 日的镜像检查和构建记录用于确认该轮运行条件。容器内工作树、预编译对象与最终可执行文件的来源仍需结合该轮的源码状态和构建产物摘要核验。[上游版本核对](docs/official-code-analysis.md#version-comparison)

第一周保存了两次 Mac 检查的输出与退出码，第二次增加 CPU 核数备用检测并记录脚本 SHA-256。作者示例当时仅作验收参考，本组实际结果见第二周两轮日志。[脚本语法、链接及忽略规则验证](docs/results/validation-2026-11-07.txt)

[仓库忽略规则](.gitignore)覆盖外部源码副本、下载包、镜像/磁盘文件、编译产物、Python 缓存和常见凭据。小型实验记录集中在 `docs/results/`。

## 更新历史

| 日期 | 小组进展 |
| --- | --- |
| 2026-11-08 | [初始化仓库](https://github.com/kiritojie/cs340-period-replication/commit/67f4574ac9c82a05439d2d1f1e525d09a84f5da6)，记录源码来源、忽略规则、算法和源码分析、复现计划及第一周环境检查。 |
| 2026-11-09 | [整理小组首页](https://github.com/kiritojie/cs340-period-replication/commit/2f5fa9307414ed30ba32323f47f5ab89a9397dd2)，补充实验范围、测量指标、验收标准和证据链接。 |
| 2026-11-14 | [记录首次工具验证和初步审计](docs/week2-doublefree.md#2026-11-14-初步证据审计)，整理环境、探索与回放日志，并记录证据缺口。 |
| 2026-11-15 | [提交重跑证据](https://github.com/kiritojie/cs340-period-replication/commit/c0a4ce7329c24cb6ac87cd90212b3580e59262f7)，补充原始调度、命令、退出码、镜像信息和单任务调度验证。 |
| 2026-11-18 | [整理项目首页和证据导航](https://github.com/kiritojie/cs340-period-replication/commit/7b355b8b65a8159e86484725be05cc9f4928af3e)。 |
| 2026-11-19 | [新增日志统计工作流](docs/log-statistics.md)，并对重跑探索日志完成[独立统计核对](docs/results/doublefree-log-check-2026-11-19.md)。 |

组员贡献见各自的提交和报告分工。提交作者与时间以 Git 历史为准。
