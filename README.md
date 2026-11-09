# CS340 · PERIOD 论文复现（小组项目）

项目论文：Cheng Wen 等，*Controlled Concurrency Testing via Periodical Scheduling*，ICSE 2022。[论文预印本](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf) · [DOI](https://doi.org/10.1145/3510003.3510178) · [官方源码](https://github.com/wcventure/PERIOD)

官方分析版本：[`cb8deb9a176e5bb292d70d46557dd61dc0e98069`](https://github.com/wcventure/PERIOD/commit/cb8deb9a176e5bb292d70d46557dd61dc0e98069)，2022-10-09，`fix Install.md`。文件级来源记录见 [official-source.json](docs/official-source.json)。本仓库汇总小组的分析、脚本和实验记录，不复制官方工具代码。README 记录小组整体进展；各成员的实际贡献通过各自的提交记录和报告中的分工说明体现。

## 小组第一周进展（2026-11-07）

| 项目 | 状态 | 证据 |
| --- | --- | --- |
| 官方版本与构建链 | 已固定官方 commit；已梳理核心算法、构建、插桩与回放路径 | [源码分析](docs/official-code-analysis.md) · [算法笔记](docs/algorithm-notes.md) |
| 实验准备：环境盘点 | 小组记录了在一台 ARM64 Mac 上执行的两次环境检查，保留输出和退出码 | [第一周记录](docs/week1-results.md) · [原始环境日志](docs/results/environment-2026-11-07.txt) |
| PERIOD 构建、`doubleFree` 测试与回放 | **NOT_RUN**。已检查的 Mac 宿主不提供 Linux 调度接口，Docker CLI 不在当前 PATH 中；尚未验证 x86_64 Linux 环境 | [前提检查日志](docs/results/doublefree-feasibility-2026-11-07.txt) |
| 论文基准复现 | **NOT_RUN**，暂无本组 `Paper vs. Ours` 数据 | [复现计划](docs/reproduction-plan.md) |

环境检测脚本退出码为 0 仅表示盘点完成。官方示例的 6 个调度、4 个错误交错、首次错误在第 3 个调度，均为作者提供的验收对照，并非本组实验结果。

## 正式复现范围

先用官方 `doubleFree` 示例验证构建、受控调度和回放。正式实验从[论文 Table 1（RQ2）](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf#page=8) 的 `CVE-2016-7911` 开始，验证 PERIOD 能否在该用例上触发已知并发错误。

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
| [official-code-analysis.md](docs/official-code-analysis.md) | 源码结构、doubleFree 时序、bitcode→分析→插桩→ASan 链接、官方文档差异 |
| [reproduction-plan.md](docs/reproduction-plan.md) | 环境依赖、Linux 复现流程、验收指标及后续实验计划 |
| [official-source.json](docs/official-source.json) | 官方 commit、文件 blob ID 和固定版本链接 |
| [week1-results.md](docs/week1-results.md) | 真实检查结论、未执行项、剩余问题与提交范围 |
| [环境原始日志](docs/results/environment-2026-11-07.txt) | 两次真实检测；第二次加入 CPU 核数备用检测，附脚本 SHA-256 |
| [doubleFree 前提检查日志](docs/results/doublefree-feasibility-2026-11-07.txt) | `docker --version` 实际失败输出与 NOT_RUN 决定 |
| [验证日志](docs/results/validation-2026-11-07.txt) | 脚本语法、文件链接/来源记录、忽略规则和空白检查 |

## 下一步与验收

1. **准备 x86_64 多核 Linux VM。** 记录发行版、内核、CPU 核数、工具版本和官方镜像摘要或构建来源；在容器内实际验证 `SCHED_DEADLINE` 可用。
2. **跑通工具验收。** 在固定版本的官方源码目录构建 `doubleFree`，按官方示例执行 `run_PDS.py -y -d 3 ./df`，保留构建和运行日志、错误调度文件；使用保存的调度回放一次并确认 ASan 报告 double-free。
3. **产出第一组论文对照数据。** 在已验证环境中执行 `CVE-2016-7911`，按上述指标生成第一条 `Paper vs. Ours` 对照记录。小型原始日志、用于回放的调度文件和回放输出摘存到 `docs/results/`，并记录对应的命令与参数。

具体命令及环境要求见[复现计划](docs/reproduction-plan.md)。

`.gitignore` 排除了外部源码副本、下载包、镜像/磁盘文件、编译产物、Python 缓存和常见凭据；`docs/results/` 中精选的小型文本证据可以提交。

## 小组更新历史

下表汇总小组项目进展。每次提交的作者和实际提交时间以 GitHub 提交历史为准。

| 日期 | 更新内容 |
| --- | --- |
| 2026-11-08 | [首次提交 `67f4574`](https://github.com/kiritojie/cs340-period-replication/commit/67f4574ac9c82a05439d2d1f1e525d09a84f5da6)：初始化仓库与忽略规则，记录官方版本和文件来源，加入算法笔记、源码分析、复现计划、第一周记录及环境检测脚本，保留环境检查、前提检查和验证日志。 |
| 2026-11-09 | 更新小组 README：明确项目为小组合作，把第一周状态与证据链接集中到首页；注明 `doubleFree` 和论文基准的实际状态；明确 Table 1 的首个正式复现用例、测量指标与重复实验计划；补充 Linux、构建、回放和证据保存的验收标准；移除过时的仓库初始化说明。此次是文档更新，未新增实验数据。 |
