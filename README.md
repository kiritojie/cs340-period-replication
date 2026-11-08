# CS340 · PERIOD 论文复现

项目论文：Cheng Wen 等，*Controlled Concurrency Testing via Periodical Scheduling*，ICSE 2022。[论文预印本](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf) · [DOI](https://doi.org/10.1145/3510003.3510178) · [官方源码](https://github.com/wcventure/PERIOD)

官方分析版本：[`cb8deb9a176e5bb292d70d46557dd61dc0e98069`](https://github.com/wcventure/PERIOD/commit/cb8deb9a176e5bb292d70d46557dd61dc0e98069)，2022-10-09，`fix Install.md`。文件级来源记录见 [official-source.json](docs/official-source.json)。本仓库维护本组分析、脚本和实验记录，不复制官方工具代码。

## 第一周状态（2026-11-07）

- 已检查初始 Git 状态：本地尚无提交、没有工作文件，GitHub 远端尚无分支；本次全部为新增文件，没有覆盖现有内容。
- 已阅读官方 README、INSTALL、REQUIREMENTS、Dockerfile，以及 doubleFree 源码和构建/清理脚本，核对了调度器和插桩运行时。
- 已完成算法、代码结构、依赖和复现计划文档；已创建并实际运行环境检测脚本，保留原始输出与退出码。
- **官方 doubleFree 构建、受控测试和回放：NOT_RUN。** 当前可见环境为 macOS 27.0.1 / Darwin 27.0.0 / ARM64，Docker CLI 不在 PATH 中；Linux deadline 调度无法在该宿主上原生运行。另缺少 `llvm-config`、Python 的 `numpy` 和 `sysv_ipc`。
- 检测脚本退出码为 0，表示盘点完成。官方 README 的“6 个调度、4 个错误交错、首次错误在第 3 个调度”目前仅作为预期对照，**不是本组实验结果**。

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

## 下一步

优先准备 x86_64 多核 Linux 环境，核实 Docker daemon、Linux kernel 与调度权限，取得固定 commit 的官方源码或确认镜像来源。然后构建 doubleFree，运行 `run_PDS.py -y -d 3 ./df`（对应 2–4 个 period），保存输出与错误调度，并回放至少一个 ASan double-free。详细流程和后续 UAF / 小规模 benchmark 计划见 [复现计划](docs/reproduction-plan.md)。

`.gitignore` 排除了外部源码副本、下载包、镜像/磁盘文件、编译产物、Python 缓存和常见凭据；`docs/results/` 中精选的小型文本证据可以提交。所有本地改动仍待人工审核，未自动 Commit 或 Push。
