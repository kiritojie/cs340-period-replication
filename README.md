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
| 第三周 · 跨机器独立复现 | 第二台机器（x86_64 同构 4 核，Docker Desktop）从干净目录重建插桩产物并重跑三轮，三项计数逐轮一致；六份错误调度记录与第三周归档逐字节全等。补齐逐轮二进制哈希、stdout/stderr 分离与逐轮启动配置。 | [跨机器复现报告](docs/week3-cross-host-reorder3.md) · [证据清单](docs/results/table2-reorder3-crosshost-20261122/SHA256SUMS) |
| 第三周 · Table 1 CVE 基准复现 | 官方 `ConVul-CVE-Benchmarks` 全部 **10 个程序**从零构建并按论文口径（bug-depth 5、每次调用预算 10000 调度）跑满 **10 轮 / 100 次运行**，10/10 定位逐轮成立；含深度 3 负对照与轮次完整性判据。 | [Table 1 复现报告](docs/table1-cve-reproduction.md) · [证据清单](docs/results/table1-cve/SHA256SUMS) |
| 第三周 · 工作线程调度取证 | 用 `strace -f` 补齐两份报告共同遗留的缺口：每个 PERIOD 工作线程恰好发起**一次** `sched_setattr(SCHED_DEADLINE)` 且返回 0（0/2/3 次随工作线程数变化）；同时**推翻两处源码层面预测**——runtime 不做 `sched_getattr` 回读，且 `sched_attr` 参数来自 dry-run 校准而非源码默认值。 | [取证报告](docs/worker-thread-syscall-evidence.md) · [证据清单](docs/results/worker-syscall-evidence/SHA256SUMS) |

<a id="table-2-paper-vs-ours"></a>

## 实验结果

- **第二周 `doubleFree` 工具验收。** 首次运行和重跑各探索 6 次调度，均在第 3 次首次触发重复释放。每轮有 4 次调度触发同一缺陷，超时 0 次。回放时 AddressSanitizer 再次检测到 `double-free`。[运行和回放记录](docs/week2-doublefree.md) · [独立统计核对](docs/results/doublefree-log-check-2026-11-19.md)
- **第三周 `CS.reorder_3_bad` 正式基准。** 每轮共探索 27 次调度，第 6 次首次触发断言失败，其中 6 次触发断言失败，超时 0 次。前三项计数逐轮与论文 Table 2 的 PERIOD 结果一致。[逐轮数据与论文对照](docs/week3-independent-reproduction.md#5-experimental-results)
- **第三周跨机器独立复现。** 第二台机器（x86_64 同构 4 核，Docker Desktop）从干净目录重建插桩产物（关键点 `reorder_bad.c:71/72/78`，二进制内嵌 Clang 10.0.0），三轮深度 3 探索的首次命中、总调度数与错误调度数逐轮一致；六份错误调度记录与第三周归档逐字节全等。[跨机器复现报告](docs/week3-cross-host-reorder3.md)
- **第三周 Table 1 CVE 基准。** 官方 10 个 CVE 程序全部从零构建，按论文 CVE 组口径（`-d 5`、每次调用预算 10000 调度）跑满 10 轮共 100 次运行：**10/10 定位在 10/10 轮均成立**、超时 0 次；`CVE-2017-6346` 在 10/10 轮同时报出 NPD＋UAF＋double-free；`CVE-2016-1972` 的 double-free 在 8/10 轮命中。逐程序 bug 类型之和的中位数为 15（范围 13–15），与论文 15 在量级上一致，但两者计数口径不同，报告中已注明为代理指标而非同一规则。[Table 1 复现报告](docs/table1-cve-reproduction.md) · [十轮摘要表](docs/results/table1-cve/rounds-summary.tsv)
- **第三周 · 工作线程调度系统调用取证。** 用 `strace -f` 直接观测 PERIOD 工作线程：每个工作线程恰好发起**一次** `sched_setattr(SCHED_DEADLINE)` 且返回 0，调用次数随工作线程数精确变化（0 / 2 / 3）。同时**推翻两处源码层面预测**：runtime 不做 `sched_getattr` 回读，且 `sched_attr` 的 runtime/deadline/period 取自 dry-run 校准（实测 4,945,020 / 82,417,000 ns）而非源码默认常量，故不可引用固定数值。`sched_yield` 次数由共享内存 `kpYield` 驱动，手工运行下为陈旧值，未作为结论。[取证报告](docs/worker-thread-syscall-evidence.md) · [跟踪记录](docs/results/worker-syscall-evidence/traces/)

第三周结果覆盖 Table 2 的这一项基准；同一基准已在第二台机器上独立重建并重跑三轮，六份错误调度记录与归档逐字节全等，逐轮启动配置与二进制哈希同步补齐。实际 PERIOD 工作线程的调度系统调用取证已完成（每线程一次 `sched_setattr(SCHED_DEADLINE)`，返回 0）。[取证报告](docs/worker-thread-syscall-evidence.md) · [第三周待完成工作](docs/week3-independent-reproduction.md#7-scope-and-outstanding-work) · [第二周验收状态](docs/week2-doublefree.md#独立复现验收状态)

## 复现入口

1. 核对已验证的 x86_64 Linux 路线。[环境检查](#环境检查) · [首次运行环境记录](docs/results/environment.txt)
2. 从项目 Release 获取固定镜像归档 `PERIOD-amd64.oci.tar`。第二周重跑包收录镜像身份、阶段日志、原始错误调度和采集脚本。[镜像发布页](https://github.com/kiritojie/cs340-period-replication/releases/tag/doublefree-evidence-20261115) · [重跑证据包](docs/results/PERIOD_doubleFree_rerun_evidence-verified.zip)
3. 查阅 11 月 14 日的证据缺口与拟定补采步骤，以及 11 月 15 日实际完成的补采。[审计与补采方案](docs/week2-reproducibility.md) · [实际补采记录](docs/week2-doublefree.md#2026-11-15-重跑与补采)

## 正式复现范围

`CS.reorder_3_bad` 是目前完成数值复现的 Table 2（RQ1）基准；Table 2 其余 35 个程序未在本次范围内。Table 1（RQ2）已完成官方 10 个 CVE 程序的十轮复现（bug-depth 5、每次调用预算 10000 调度），`CVE-2016-7911` 原计划候选已连同其余 9 个程序一并跑通，此前的"待小组确认"项已关闭。`doubleFree` 用于工具功能验收。基线技术（IPB / IDB / DFS / PCT / Random / Maple）依赖 Intel Pin 与 ≤3.x 内核，未在本环境重跑，论文数字为引用。[论文 Table 2](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf#page=9) · [论文 Table 1](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf#page=8) · [Table 1 复现报告](docs/table1-cve-reproduction.md) · [复现计划](docs/reproduction-plan.md)

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
| 2026-11-22 | 第二台机器独立重建并重跑 `CS.reorder_3_bad` 三轮：计数逐轮一致，六份错误调度记录与既有归档逐字节全等；补齐逐轮启动配置、二进制哈希、stdout/stderr 分离记录与复现脚本。[跨机器复现报告](docs/week3-cross-host-reorder3.md) |
| 2026-11-22 | 完成 Table 1 CVE 基准复现：官方 10 个程序从零构建，按论文 CVE 口径（`-d 5`、预算 10000）跑满 10 轮 100 次运行，10/10 定位逐轮成立、超时 0；附深度 3 负对照（说明 CVE 组必须用 `-d 5`）与轮次完整性判据（驱动退出码 0 但 dry-run 中止的 21 次已剔除）。[Table 1 复现报告](docs/table1-cve-reproduction.md) |
| 2026-11-22 | 用 `strace -f` 补齐两份报告共同遗留的工作线程取证：确认每个 PERIOD 工作线程恰好一次 `sched_setattr(SCHED_DEADLINE)` 且返回 0（次数随工作线程数 0/2/3 变化）；推翻两处源码预测——runtime 不做 `sched_getattr` 回读、`sched_attr` 参数取自 dry-run 校准而非源码常量。[工作线程取证报告](docs/worker-thread-syscall-evidence.md) |

组员贡献见各自的提交和报告分工。提交作者与时间以 Git 历史为准。
