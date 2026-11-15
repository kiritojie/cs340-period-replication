# CS340 · PERIOD 论文复现（小组项目）

项目论文：Cheng Wen 等，*Controlled Concurrency Testing via Periodical Scheduling*，ICSE 2022。[论文预印本](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf) · [DOI](https://doi.org/10.1145/3510003.3510178) · [官方源码](https://github.com/wcventure/PERIOD)

官方分析版本：[`cb8deb9a176e5bb292d70d46557dd61dc0e98069`](https://github.com/wcventure/PERIOD/commit/cb8deb9a176e5bb292d70d46557dd61dc0e98069)，2022-10-09，`fix Install.md`。文件级来源记录见 [official-source.json](docs/official-source.json)。本仓库汇总小组的分析、脚本和实验记录，不复制官方工具代码。README 记录小组整体进展；各成员的实际贡献通过各自的提交记录和报告中的分工说明体现。

第二周实验环境记录的源码版本为 `b6f72a7b06d01ffa7114b640312873ec2578a5ea`。已核对两个上游提交：工具、示例和 evaluation 目录相同，净差异仅涉及文档；容器本地修改与编译对象身份仍需补证。见[版本核对](docs/official-code-analysis.md#version-comparison)。

## 小组第一周进展（2026-11-07）

| 项目 | 状态 | 证据 |
| --- | --- | --- |
| 官方版本与构建链 | 已固定官方 commit；已梳理核心算法、构建、插桩与回放路径 | [源码分析](docs/official-code-analysis.md) · [算法笔记](docs/algorithm-notes.md) |
| 实验准备：环境盘点 | 小组记录了在一台 ARM64 Mac 上执行的两次环境检查，保留输出和退出码 | [第一周记录](docs/week1-results.md) · [原始环境日志](docs/results/environment-2026-11-07.txt) |
| PERIOD 构建、`doubleFree` 测试与回放 | **NOT_RUN**。已检查的 Mac 宿主不提供 Linux 调度接口，Docker CLI 不在当前 PATH 中；尚未验证 x86_64 Linux 环境 | [前提检查日志](docs/results/doublefree-feasibility-2026-11-07.txt) |
| 论文基准复现 | **NOT_RUN**，暂无本组 `Paper vs. Ours` 数据 | [复现计划](docs/reproduction-plan.md) |

环境检测脚本退出码为 0 仅表示盘点完成。官方示例的 6 个调度、4 个错误交错、首次错误在第 3 个调度，均为作者提供的验收对照，并非本组实验结果。


## 第二周进展：跑通 PERIOD 的 `doubleFree` 示例

**第二周证据复核（2026-11-14）：功能运行与回放已完成，完整可复现性验收暂未结项。** 尚缺原始错误调度文件、命令及退出码、镜像原始身份和当前 deadline 调度证据。详见[缺口、WSL2 补采命令及结项条件](docs/week2-reproducibility.md)。本次只整理证据，没有新增 PERIOD 实测数据。

第一周在 Mac 上检查了运行条件。随后在 Windows 上通过 WSL2 和 Podman 运行 Ubuntu 容器，成功构建并测试了论文作者提供的 `doubleFree` 示例。运行时使用 Ubuntu 18.04.5 和 Clang 10.0.0，完整版本见[环境记录](docs/results/environment.txt)。

`doubleFree` 是一个用来验证工具能否正常工作的小程序。某些线程执行顺序会让程序对同一块内存释放两次。PERIOD 会在程序的关键位置安排线程的执行顺序，每尝试一套安排，日志就记下一次测试。

| 实际结果 | 怎么理解 | 在日志里找什么 |
| --- | --- | --- |
| 共尝试 6 次 | PERIOD 测试了 6 套线程执行顺序。 | `test 0001` 到 `test 0006` |
| 第 3 次首次报错 | 前两次未报告该错误，第 3 次第一次触发。 | `test 0003` 后的第一条 `Error Found` |
| 4 次触发错误 | 6 套顺序中有 4 套触发了同一个重复释放问题。 | `Total Error Interleavings: 4` |

PERIOD 保存了报错时的执行顺序。按第 3 次的顺序重新运行，就是一次**回放**。回放时，内存错误检测工具 AddressSanitizer 再次报告 `double-free`，确认保存的顺序能再次触发示例里的错误。

组员第一次看时，可以先读[第二周运行说明](docs/week2-doublefree.md)，再打开[原始运行日志](docs/results/doubleFree-smoke.log)，用 `Ctrl+F` 找 `test 0003`。最后到[回放日志](docs/results/doubleFree-replay.log)找 `SUMMARY: AddressSanitizer: double-free`。这一步验证了 PERIOD 的运行和回放流程。论文表 2 的正式对照实验使用的是另一组 `reorder` 用例。


## 正式复现范围

已用官方 `doubleFree` 示例验证构建、受控调度和回放，详见[第二周运行说明](docs/week2-doublefree.md)。正式实验从[论文 Table 1（RQ2）](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf#page=8) 的 `CVE-2016-7911` 开始，验证 PERIOD 能否在该用例上触发已知并发错误。

计划按论文设置独立完整运行至少三次，记录与论文相同的三项 PERIOD 指标：首次触发错误的调度序号、总调度数、触发错误的调度数。报告均值与样本标准差，逐项链接原始日志，并注明运行次数、环境或参数与论文的差异。超时与未发现错误单独记录。该范围仅覆盖 Table 1 的部分结果。

## 运行环境检查

在仓库根目录执行（Bash 3.2+，支持 macOS/Linux）：

```bash
./scripts/check_environment.sh
```

脚本只读报告系统/CPU/内核、构建工具、Python 模块、Linux 调度线索以及 Docker CLI/daemon 和已有 PERIOD 镜像。Docker 查询有超时；脚本不会安装软件、拉取镜像、启动容器或修改调度策略。它不自动确认环境满足官方要求，也不执行 doubleFree。

若要保存新检测记录，可用以下命令生成独立日志；`noclobber` 防止覆盖同名文件，输出保留在终端及文件中：

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

exit 0 不表示依赖全部存在。缺少工具、模块导入失败、Docker 不可达等会在报告中单独标出；Linux 的实际 `SCHED_DEADLINE` 权限仍需在后续实验中验证。

## 文档与证据

| 文件 | 内容 |
| --- | --- |
| [algorithm-notes.md](docs/algorithm-notes.md) | period 有界探索、DKPS、prefix、反馈执行和适用边界 |
| [official-code-analysis.md](docs/official-code-analysis.md) | 源码结构、doubleFree 时序、bitcode→分析→插桩→ASan 链接、实验版本核对 |
| [reproduction-plan.md](docs/reproduction-plan.md) | 环境依赖、Linux 复现流程、验收指标及后续实验计划 |
| [official-source.json](docs/official-source.json) | 官方 commit、文件 blob ID 和固定版本链接 |
| [week2-reproducibility.md](docs/week2-reproducibility.md) | 第二周缺失证据、先归档后补跑的完整 WSL2 命令、退出码解释和结项条件 |
| [week1-results.md](docs/week1-results.md) | 真实检查结论、未执行项、剩余问题与提交范围 |
| [环境原始日志](docs/results/environment-2026-11-07.txt) | 两次真实检测；第二次加入 CPU 核数备用检测，附脚本 SHA-256 |
| [doubleFree 前提检查日志](docs/results/doublefree-feasibility-2026-11-07.txt) | `docker --version` 实际失败输出与 NOT_RUN 决定 |
| [验证日志](docs/results/validation-2026-11-07.txt) | 脚本语法、文件链接/来源记录、忽略规则和空白检查 |

## 下一步与验收

1. **运行环境已搭好。** 在 Windows 的 WSL2 + Podman 环境中运行了 Ubuntu 容器，版本见[环境记录](docs/results/environment.txt)。
2. **工具运行与回放已有成功日志，第二周待补证后结项。** 优先补齐原始调度、退出码、环境身份及调度实测记录，详见[第二周补采说明](docs/week2-reproducibility.md)。
3. **产出第一组论文对照数据。** 在已验证环境中执行 `CVE-2016-7911`，按上述指标生成第一条 `Paper vs. Ours` 对照记录。小型原始日志、用于回放的调度文件和回放输出摘存到 `docs/results/`，并记录对应的命令与参数。

具体命令及环境要求见[复现计划](docs/reproduction-plan.md)。

`.gitignore` 排除了外部源码副本、下载包、镜像/磁盘文件、编译产物、Python 缓存和常见凭据；`docs/results/` 中精选的小型文本证据可以提交。

## 小组更新历史

下表汇总小组项目进展。每次提交的作者和实际提交时间以 GitHub 提交历史为准。

| 日期 | 更新内容 |
| --- | --- |
| 2026-11-08 | [首次提交 `67f4574`](https://github.com/kiritojie/cs340-period-replication/commit/67f4574ac9c82a05439d2d1f1e525d09a84f5da6)：初始化仓库与忽略规则，记录官方版本和文件来源，加入算法笔记、源码分析、复现计划、第一周记录及环境检测脚本，保留环境检查、前提检查和验证日志。 |
| 2026-11-09 | 更新小组 README：明确项目为小组合作，把第一周状态与证据链接集中到首页；注明 `doubleFree` 和论文基准的实际状态；明确 Table 1 的首个正式复现用例、测量指标与重复实验计划；补充 Linux、构建、回放和证据保存的验收标准；移除过时的仓库初始化说明。此次是文档更新，未新增实验数据。 |
