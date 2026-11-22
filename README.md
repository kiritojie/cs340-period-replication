# CS340 · PERIOD 论文复现

CS340 操作系统课程小组项目，复现 PERIOD 论文中的部分实验。PERIOD 以周期为单位控制线程在关键点的执行顺序，用于探索并发错误。本仓库收录源码分析、检查脚本和可核对的实验记录。

Cheng Wen 等，*Controlled Concurrency Testing via Periodical Scheduling*，ICSE 2022。[论文 PDF](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf) · [DOI](https://doi.org/10.1145/3510003.3510178) · [官方源码](https://github.com/wcventure/PERIOD)

[实验结果](#实验结果) · [复现入口](#复现入口) · [正式复现范围](#正式复现范围) · [更新历史](#更新历史)

## 项目进度

| 阶段 | 进展 | 记录 |
| --- | --- | --- |
| 第一周 · 论文与源码 | 固定上游版本，梳理调度算法、构建、插桩与回放路径，完成两次 ARM64 Mac 环境检查。 | [算法笔记](docs/algorithm-notes.md) · [源码分析](docs/official-code-analysis.md) · [第一周记录](docs/week1-results.md) |
| 第二周 · 工具验收 | 在 Windows WSL2 + Podman 上跑通 `doubleFree` 的构建、探索和 ASan 回放，随后完成证据审计与重跑补采。 | [第二周记录](docs/week2-doublefree.md) |
| 第三周 · Table 2 基准复现 | `CS.reorder_3_bad` 完成三轮深度 3 探索，共用同一构建产物。已核对逐轮日志、错误调度和校验清单。 | [第三周详细报告](docs/week3-independent-reproduction.md) · [证据清单](docs/results/table2-reorder3/SHA256SUMS) |

<a id="table-2-paper-vs-ours"></a>

## 实验结果

- **第二周 `doubleFree` 工具验收。** 首次运行和重跑各探索 6 次调度，均在第 3 次首次触发重复释放。每轮有 4 次调度触发同一缺陷，超时 0 次。回放时 AddressSanitizer 再次检测到 `double-free`。[运行和回放记录](docs/week2-doublefree.md) · [独立统计核对](docs/results/doublefree-log-check-2026-11-19.md)
- **第三周 `CS.reorder_3_bad` 正式基准。** 每轮共探索 27 次调度，第 6 次首次触发断言失败，其中 6 次触发断言失败，超时 0 次。前三项计数逐轮与论文 Table 2 的 PERIOD 结果一致。[逐轮数据与论文对照](docs/week3-independent-reproduction.md#5-experimental-results)

第三周结果覆盖 Table 2 的这一项基准。实际 PERIOD 工作线程的调度系统调用取证、逐轮容器与二进制身份核验，以及另一位组员的独立构建和运行记录仍待补齐。[第三周待完成工作](docs/week3-independent-reproduction.md#7-scope-and-outstanding-work) · [第二周验收状态](docs/week2-doublefree.md#独立复现验收状态)

## 复现入口

1. 核对已验证的 x86_64 Linux 路线。[环境检查](#环境检查) · [首次运行环境记录](docs/results/environment.txt)
2. 从项目 Release 获取固定镜像归档 `PERIOD-amd64.oci.tar`。第二周重跑包收录镜像身份、阶段日志、原始错误调度和采集脚本。[镜像发布页](https://github.com/kiritojie/cs340-period-replication/releases/tag/doublefree-evidence-20261115) · [重跑证据包](docs/results/PERIOD_doubleFree_rerun_evidence-verified.zip)
3. 查阅 11 月 14 日的证据缺口与拟定补采步骤，以及 11 月 15 日实际完成的补采。[审计与补采方案](docs/week2-reproducibility.md) · [实际补采记录](docs/week2-doublefree.md#2026-11-15-重跑与补采)

## 正式复现范围

`CS.reorder_3_bad` 是目前完成数值复现的 Table 2（RQ1）基准。`doubleFree` 用于工具功能验收。Table 1（RQ2）的原计划候选 `CVE-2016-7911` 仍待小组确认。[论文 Table 2](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf#page=9) · [论文 Table 1](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf#page=8) · [复现计划](docs/reproduction-plan.md)

## 环境检查

首次工具验证使用 Windows WSL2 + Podman 上的 x86_64 Ubuntu 18.04.5 容器和 Clang 10.0.0。第一周两次 ARM64 Mac 环境盘点记录了 Docker CLI 在当时的 PATH 中缺失，示例状态为 `NOT_RUN`。[Mac 环境日志](docs/results/environment-2026-11-07.txt) · [示例前提检查](docs/results/doublefree-feasibility-2026-11-07.txt)

在 macOS 或 Linux 的仓库根目录，用 Bash 3.2+ 执行 `./scripts/check_environment.sh` 可盘点系统、构建依赖和调度线索。退出码 `0` 表示盘点完成。依赖状态见盘点报告，实际调度能力见运行记录。[环境检查脚本](scripts/check_environment.sh)

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

两个上游提交的净差异仅涉及四份文档。11 月 15 日重跑的容器工作树、预编译对象和最终可执行文件的来源仍待核验。[上游版本核对](docs/official-code-analysis.md#version-comparison)

第一周保留两次 Mac 检查的输出和退出码。第二次增加 CPU 核数备用检测，并记录脚本 SHA-256。[脚本语法、链接及忽略规则验证](docs/results/validation-2026-11-07.txt)

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
| 2026-11-22 | 归档 `CS.reorder_3_bad` 三轮深度 3 探索的日志和错误调度，并记录镜像、工具链及单任务探针证据。[第三周报告](docs/week3-independent-reproduction.md) |

组员贡献见各自的提交和报告分工。提交作者与时间以 Git 历史为准。
