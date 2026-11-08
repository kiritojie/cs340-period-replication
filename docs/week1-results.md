# 第一周检查与实验记录

## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: run（用户授权的环境盘点及实验可行性检查）
- Origin Date: 2026-11-07（Asia/Shanghai）
- Verification Status: UNVERIFIED（官方 PERIOD 实验尚未执行；环境盘点已有真实日志）
- Version Label: week1_v1

## 初始仓库与来源核实

工作目录为当前 CS340 项目。首次检查时，`git status --short --branch` 输出：

```text
## No commits yet on main...origin/main [gone]
```

当时工作目录只有 `.git/`，`git ls-files` 和 `git status --porcelain=v1 --untracked-files=all` 都没有文件输出。`origin` 为 `https://github.com/kiritojie/cs340-period-replication.git`。通过 GitHub 只读接口确认该仓库 size 为 0、分支列表为空；`[gone]` 在这里不表示本次操作删除了分支。没有覆盖、删除或移动已有工作文件，没有变更远端、暂存、Commit 或 Push。

官方 `main` 在本次读取时解析为 `cb8deb9a176e5bb292d70d46557dd61dc0e98069`。已按该完整 hash 读取指定四个根文档及 doubleFree 示例，并核对相关构建和运行源码；来源与 blob ID 见 [official-source.json](official-source.json)。未克隆或复制整份官方工具进本组仓库。

## 环境检测：COMPLETED

- 命令：`./scripts/check_environment.sh`，工作目录为本组仓库根目录。
- 首次检测：2026-11-07 16:42:39 +08:00；补充 `getconf` 备用核数检测后再次运行：16:43:18 +08:00。
- 两次脚本退出码均为 **0**；单次检测均在 60 秒总时限内完成。
- 原始 stdout/stderr、各项退出码及最终脚本 SHA-256 保存在 [environment-2026-11-07.txt](results/environment-2026-11-07.txt)。首次日志原样保留，第二次结果追加在其后。

| 检测项 | 实际结果 | 解释 |
| --- | --- | --- |
| OS | macOS 27.0.1，Build 26A434 | 来自 `sw_vers` |
| 宿主内核 | Darwin 27.0.0 | 不是 Linux；不能用数字 27 与官方 Linux ≥4.x 直接比较 |
| 架构 | arm64 | 与官方脚本所下载的 x86_64 LLVM 包不同 |
| 在线处理器数 | `getconf _NPROCESSORS_ONLN` 返回 11 | `sysctl -n hw.logicalcpu` 被当前执行权限拒绝，真实错误留在日志；使用备用接口读到 11，不推测物理核数 |
| Git | 2.50.1 (Apple Git-155) | 可执行 |
| Python 3 | 3.12.8 | 可执行；不等于旧脚本全部兼容 |
| clang / clang++ | Apple clang 17.0.0，target arm64-apple-darwin27.0.0 | 可执行；不是官方 LLVM 10 环境 |
| llvm-config | NOT FOUND in PATH | 官方 LLVM pass 构建环境未就绪 |
| CMake / Make | 3.30.3 / GNU Make 3.81 | 可执行 |
| numpy / sysv_ipc | 两者实际 import 均 ModuleNotFoundError | 本次 Python 解释器中缺少依赖；不能推断机器所有 Python 环境都没有安装 |
| Docker CLI | NOT FOUND in PATH | 无法通过当前命令环境探测 daemon 或 PERIOD 镜像，不声称已排查所有磁盘安装位置 |
| Linux deadline 调度 | NOT APPLICABLE on Darwin | 原生执行的必要条件不满足，未尝试修改调度策略 |

脚本整体 exit 0 只表示报告生成结束，不表示所有探测成功。模块异常逐项报告，CPU 主接口失败也保留；Docker 查询失败或超时会单独标记。该脚本未测试真实 deadline 系统调用，即使在 Linux 上检查通过也仍需受控执行验收。

## doubleFree：NOT_RUN

在 [doublefree-feasibility-2026-11-07.txt](results/doublefree-feasibility-2026-11-07.txt) 中保存了额外的真实前提检查：

| 命令 | 结果 |
| --- | --- |
| `uname -s` / `uname -m` | Darwin / arm64，均 exit 0 |
| `command -v docker`（通过 Bash） | 无输出，exit 1 |
| `docker --version`（通过 Bash） | `docker: command not found`，exit 127 |

**决定：不运行官方构建、受控探索或回放。** 宿主不提供 Linux 调度 API，当前也没有 Docker CLI 可建立官方容器路径，且 LLVM/模块未就绪；不具备“条件允许时尝试运行”的前提。官方 `build.sh` 的 macOS 分支可能自动安装 coreutils，因此没有为取得一份必然失败的日志而运行带安装副作用的构建脚本。

未执行官方 `cleanDIR.sh`、`build.sh`、`run_PDS.py`，未拉镜像或安装软件。没有本组生成的 `df`、`out_df_*`、ASan 报告或错误回放。可行性日志是前提探测输出，**不是 doubleFree 实验输出**。本组调度总数、错误交错数、首次错误序号和耗时均为 **N/A（未运行）**，不是 0。

官方根 README 的 6 个调度、4 个错误交错和第 3 个首次错误仅作为后续验收对照。四个错误交错不表示四个不同源代码缺陷。

## 已完成的验证与未解决事项

已通过 Bash 语法检查、来源 JSON 格式与固定 hash 核对、仓库内链接检查、忽略规则检查和新增文件空白检查，详见 [验证日志](results/validation-2026-11-07.txt)。这类静态检查不验证算法性能或官方实验可重复性。

首次验证的检查程序把 `git diff --no-index` 对新增文件返回的差异状态码 1 误判为空白错误。日志保留失败和修正过程，包含干净/含尾随空格文件的对照检查；检查程序自身生成的一处日志尾随空格也已清理并注明。最终验证通过，环境与前提探测的原始输出未改动。

尚需：可用的 Linux 实验环境及实际调度权限；Docker daemon/镜像验证；LLVM 10、SVF、插桩工具与旧 Python 依赖安装；doubleFree 完整构建、探索和回放。ARM64/仿真支持未验证；官方可变镜像标签与固定 commit 的对应关系未验证；旧 INSTALL 中 wllvm 路径问题已定位但未实际安装验证。后续步骤及成功标准见 [reproduction-plan.md](reproduction-plan.md)。

本次没有与论文性能数字进行比较，没有展开完整 benchmark。

## 适合第一周提交的文件

本次所有新增的 11 个文件均适合审核后作为第一周提交：

- 根目录：`README.md`、`.gitignore`。
- 脚本：`scripts/check_environment.sh`（保留可执行权限）。
- 分析与记录：`docs/algorithm-notes.md`、`docs/official-code-analysis.md`、`docs/reproduction-plan.md`、`docs/official-source.json`、`docs/week1-results.md`。
- 小型原始证据：`docs/results/environment-2026-11-07.txt`、`docs/results/doublefree-feasibility-2026-11-07.txt`、`docs/results/validation-2026-11-07.txt`。

日志只记录本次检查所需信息，没有读取凭据或环境变量全集；不提交官方源码、编译产物、依赖下载或大型实验目录。提交前可再次查看 `git status --short --untracked-files=all` 并逐个审核；本次保持未暂存、未 Commit、未 Push。
