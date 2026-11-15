# 官方 PERIOD 源码分析与 doubleFree 复现路径

分析日期：2026-11-07。以下结论来自对官方固定版本的文档和源码阅读，**不是本机实验结果**。本仓库不导入官方工具源码。

- 官方项目：[wcventure/PERIOD](https://github.com/wcventure/PERIOD)。
- 分析版本：[cb8deb9a176e5bb292d70d46557dd61dc0e98069](https://github.com/wcventure/PERIOD/commit/cb8deb9a176e5bb292d70d46557dd61dc0e98069)，提交时间 2022-10-09 07:21:09 UTC，提交说明 `fix Install.md`。
- 论文：[Controlled Concurrency Testing via Periodical Scheduling](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf)，ICSE 2022，DOI [10.1145/3510003.3510178](https://doi.org/10.1145/3510003.3510178)。

<a id="version-comparison"></a>

## 实验版本补充（2026-11-15 整理）

第二周[环境日志](results/environment.txt)记录的实际源码提交为 `b6f72a7b06d01ffa7114b640312873ec2578a5ea`，与本文的第一周分析版本不同。2026-11-14 的上游版本核对结论如下：

- 两个固定提交中的 `tool/`、`test/`、`evaluation/` 目录和 `Dockerfile` 内容相同；净差异仅涉及四项文档更新，包括安装说明、用法说明和示例结果文字。[官方版本对比](https://github.com/wcventure/PERIOD/compare/b6f72a7b06d01ffa7114b640312873ec2578a5ea...cb8deb9a176e5bb292d70d46557dd61dc0e98069)
- 本文对调度生成器、驱动、插桩运行时及 doubleFree 构建链的源码分析仍适用于该实验提交，无须仅为对齐提交编号而升级已跑通的环境。
- 这一结论只覆盖上游源码，不能证明实验容器内没有本地修改，也不能证明预编译对象、插桩器和最终 `df` 来自该源码。

后续应记录容器工作树状态、源码差异、镜像身份、构建日志及相关对象/可执行文件摘要；补采步骤见[第二周复现补采说明](week2-reproducibility.md)。文件摘要用于固定身份，不能单独证明源码与二进制的对应关系。

## 1. 目录与技术职责

固定版本中的实际路径与 README 的概括存在大小写、单复数差异；运行命令应以源码树为准。

| 实际路径 | 职责与复现关联 |
| --- | --- |
| `tool/DBDS/run_PDS.py` | 实验驱动：dry run、共享内存、调度枚举、运行目标、分析错误、维护反馈任务和回放。是第一阶段实验入口。 |
| `tool/DBDS/sbp_sched.py`、`sbp_sched_mixed_end.py` | 有界 period 调度生成器；后者的 `SBPMESched` 支持最后一个 period 的混合线程执行，对应论文允许并行的调度生成。 |
| `tool/DBDS/ipc.py`、`external_def.py` | System V 共享内存封装、运行信息辅助函数、覆盖摘要、prefix 去冗余和 ASan 错误分类。 |
| `tool/staticAnalysis/` | LLVM bitcode 静态分析，借助 SVF 识别共享内存与敏感操作，生成插桩配置。实际目录不是 README 中的 `staticanalysis`。 |
| `tool/staticAnalysis/LLVM-PASS/` | 包括敏感操作分析等 LLVM pass；由 CMake/Make 构建。 |
| `tool/staticAnalysis/DBDS-INSTRU/llvm-mode/` | 编译包装器、LLVM 插桩 pass、C++ 调度运行时。Makefile 把 `dbds-clang-fast`、`dbds-llvm-pass.so`、`DBDSFunction.o` 生成到上一层目录。 |
| `tool/SVF/`、`tool/wllvm/` | 随官方项目提供的第三方分析和 whole-program LLVM bitcode 工具。doubleFree 的单文件 bitcode 由 clang 直接生成，不能因此推断较大项目不需要 WLLVM。 |
| `tool/install_llvm.sh`、`install_SVF.sh`、`install_staticAnalysis.sh` | 下载 LLVM 10.0.0、构建 SVF 和分析/插桩组件。`clang+llvm/` 是安装时生成的目录，不是该固定 Git 源码树已包含的预编译目录。 |
| `test/doubleFree/` | 最小安装验收案例：目标 C 程序、构建脚本、清理脚本和较旧格式的案例说明。 |
| `evaluation/` | 完整评估对象：ConVul CVE 用例及 CB、CS、Chess、Inspect、RADBench、SafeStack、Splash2 等基准。第一周不运行完整评估。 |

源码依据：[run_PDS.py](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/tool/DBDS/run_PDS.py)、[SBPMESched](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/tool/DBDS/sbp_sched_mixed_end.py)、[插桩 Makefile](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/tool/staticAnalysis/DBDS-INSTRU/llvm-mode/Makefile)、[LLVM 安装脚本](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/tool/install_llvm.sh)。官方 README 将工具总目录写作 `tools`，实际为 `tool`。

## 2. doubleFree 为什么会出错

[`df.c`](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/test/doubleFree/df.c#L7) 定义共享指针 `ptr`；主线程分配 7 字节后创建两个工作线程。两个线程都执行“释放 `ptr`，随后把 `ptr` 置空”，没有互斥或其他同步。`pthread_join` 只让主线程等待两个工作线程，不能给两个工作线程的这两个操作建立相互排斥。

可用于理解的关键操作模型是：每线程各有释放 `F` 和置空 `N` 两个操作。完整串行的 `F0 → N0 → F1 → N1` 中，后一个 `free` 可能读到 NULL；`free(NULL)` 本身允许。`F0 → F1 → N0 → N1` 则可能让两个 `free` 使用同一非空地址，触发 double free。源码还存在对共享指针的未同步访问，属于 C 语言的数据竞争；这个操作模型解释工具要探索的典型交错，不能把所有本机执行都当作语言层面的确定行为保证。

官方根 README 中 `[[1], [0, 0], [1]]` 的含义是三个 period：线程 1 先执行一个关键点，线程 0 执行两个关键点，再由线程 1 执行另一个关键点。它展示为什么普通反复运行不能替代有控制的调度探索。ASan 负责报告内存错误，PERIOD 负责生成、执行并记录导致错误的调度；两者职责不同。

## 3. 从源码到可测程序的流水线

[`test/doubleFree/build.sh` 第 25–36 行](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/test/doubleFree/build.sh#L25) 给出了实际构建步骤：

1. 设置官方根目录、LLVM 和 SVF 的搜索路径，进入示例目录并执行 `cleanDIR.sh`。
2. 用 `clang -g -emit-llvm -c` 从 `df.c` 生成 `df.bc`，保留静态分析所需的调试位置。
3. 调用 `staticAnalysis.sh df`：SVF 的 `wpa` 分析生成 `mssa.df`；分析脚本形成并更新 `ConConfig.df`；敏感操作 pass 和内存配对分析产生配置及 `mempair.df.npz` 等分析文件。
4. 将 `Con_PATH` 指向 `ConConfig.df`；用 `dbds-clang-fast` 按配置插桩，并带 `-fsanitize=address` 编译为 `df.o`。
5. 用 `clang++` 把 `df.o` 与调度运行时 `DBDSFunction.o` 链接成 `df`，同时链接 pthread、dl 和 ASan。

[`staticAnalysis.sh`](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/tool/staticAnalysis/staticAnalysis.sh) 会移除部分中间文件，不应把每一个短暂出现的分析文件都列为最终产物。`DBDSFunction.o` 并非示例自己生成；它来自 `install_staticAnalysis.sh` 调用插桩目录中的 Makefile。缺少该对象应先检查工具安装是否完成。

`build.sh` 在真正编译之前就打印 `Installation completed. Everything's fine!`；这行文字不能证明构建成功，必须检查脚本退出码、最终文件和后续实际测试结果。其 macOS 分支还可能执行 `brew install coreutils`，因此它不是只读的环境检查脚本。

`cleanDIR.sh` 使用相对路径删除 bitcode、目标文件、分析结果、`out_*`、日志和可执行文件。只应在独立的官方源码工作副本的示例目录中运行；实验日志应在执行清理前保存到本项目的结果目录。

## 4. 调度器、运行时和论文的对应

论文的 schedule generator 对应 `SBPSched`/`SBPMESched`；periodical executor 对应插桩生成的调度点及 C++ 运行时；feedback analyzer 对应 `run_PDS.py` 对共享内存中关键点数量、位置、顺序和覆盖摘要的读取，以及后续任务和 prefix 的维护。

[`run_PDS.py` 第 196–197 行](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/tool/DBDS/run_PDS.py#L196) 定义 `period_limit = bugDepth + 1`；[`第 636–638 行`](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/tool/DBDS/run_PDS.py#L636) 从 2 periods 开始循环。因此命令行 `-d 3` 的 period 上界为 4，不能把它写成“只运行三个 period”。

| 参数 | 固定版本中的含义 | 第一阶段用途 |
| --- | --- | --- |
| `-y` | 跳过交互 Enter 确认 | 便于保存一次完整测试输出。 |
| `-d 3` | bug depth 上界设为 3，period 上界为 4 | 对齐官方根 README 示例。 |
| `-t <秒数>` | 单次目标子进程超时，默认 5 秒 | 不等于整个探索任务的总时限。 |
| `-r <错误文件>` | 从记录中读取调度并回放目标程序 | 验证错误交错能否再次产生 ASan double-free。 |
| `-f <次数>` | 设置运行次数限制 | 限制调试运行规模时使用；正式验收需记录是否截断。 |
| `-e` | 禁用 prefix 引导 | 后续对照实验候选；不用于第一阶段默认验收。 |

参数源码依据：[解析逻辑第 209–285 行](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/tool/DBDS/run_PDS.py#L209)。驱动通过 `sudo` 启动 dry run 和受控目标（[第 309–310 行](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/tool/DBDS/run_PDS.py#L309)），故仅能执行 Python、仅安装编译器或仅能启动普通容器都不足以证明运行条件满足。

运行时通过 `set_sched_dl` 设置 Linux `SCHED_DEADLINE` 并在关键点使用 `sched_yield()` 推进 period。参见 [`DBDSFunction.cpp`](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/tool/staticAnalysis/DBDS-INSTRU/llvm-mode/DBDSFunction.cpp#L225) 与其同目录的 [`sched.h`](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/tool/staticAnalysis/DBDS-INSTRU/llvm-mode/sched.h)。源码中的 Darwin 路径处理和类型定义分支，不能证明 macOS 提供对应的 Linux deadline 调度系统调用。

## 5. 官方文档中的环境约束与复现风险

| 来源 | 明确说明或实际执行 | 复现时的解释 |
| --- | --- | --- |
| [README.md](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/README.md) | 多核；Ubuntu ≥18.04；Linux kernel ≥4.x；Docker 版本高于 18.09.7；推荐 `--privileged` 容器 | 这是官方建议条件，不是已在本机验证的结果。 |
| [INSTALL.md](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/INSTALL.md) | 给出 Docker 路径和源码安装顺序；安装 Python 2/3 的 numpy、Python 3 的 sysv_ipc | 工具链同时含旧式 `/usr/bin/python` 脚本，不能直接把 Python 3 可用等同于所有脚本都兼容。 |
| [REQUIREMENTS.md](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/REQUIREMENTS.md) | Docker 部分写 Ubuntu ≥18.04，源码部分写 Ubuntu 18.04 | 第一阶段优先使用官方 Ubuntu 18.04 用户空间；更新发行版的兼容性另行验证。 |
| [Dockerfile](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/Dockerfile) | 基于 `ubuntu:18.04`，安装构建工具及开发库；安装 wllvm、numpy、sysv_ipc，再构建 LLVM/SVF/插桩工具 | 容器提供用户空间；不能单靠基础镜像判断实际内核调度权限可用。 |
| [install_llvm.sh](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/tool/install_llvm.sh) | 实际下载 LLVM 10.0.0 的 x86_64 Ubuntu 18.04 或 x86_64 Darwin 包 | 固定安装路径依赖 x86_64 预编译工具链；ARM 原生或仿真运行效果需要单独实测。脚本中较早的 LLVM 版本变量不代表实际下载版本。 |

需要跟踪的具体问题：

- `INSTALL.md` 的 wllvm 安装路径写成 `$ROOT_DIR/ConFuzz/tool/wllvm/`；Dockerfile 使用 `/workdir/PERIOD/tool/wllvm/`，固定源码树也是 `tool/wllvm/`。该路径应按源码核对后使用，并记录任何本地修正。
- Dockerfile 对 apt 仓库、pip 依赖版本、下载包和基础镜像都没有完整的不可变锁定。固定 Git hash 能锁定脚本，不能自动锁定最终镜像及全部第三方依赖；后续必须记录镜像 digest/ID 和实际版本。
- 官方预构建 Docker 镜像来自可变标签 `wcventure/period:stable`；未检查容器内源码版本前，不能说它一定等于本文分析的 commit。
- 普通用户、容器权限、cpuset/CPU 限制以及 Linux deadline 调度的准入检查仍可能阻止执行。环境检测可以报告线索；只有在目标 Linux 环境中完成构建、受控测试和回放，才能确认可运行。

## 6. doubleFree 的验收指标与记录方法

官方根 README 针对 `run_PDS.py -y -d 3 ./df` 展示：**共 6 个调度，4 个触发 double-free，第 3 个调度首次发现错误**。这些是官方参考目标，不是本项目测得数据，也不能解释成发现 4 个不同源代码缺陷。

错误记录保存到 `out_df_<序号>/Errors/`，文件名含错误序号、探索序号和错误类别；文件内容包括调度和配置允许时的 stderr，回放应使用该次运行实际生成的路径。驱动还区分超时与不同输出，不能把超时直接计为已确认 double-free。参见 [错误记录第 99–127 行](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/tool/DBDS/run_PDS.py#L99)。

`test/doubleFree/README.md` 展示的是较旧的调度文本格式，根 README 则展示嵌套列表；分析时采用固定版本根 README 加实际驱动代码。根 README 有一处把输出目录写成 `out_work_1`，与同段 doubleFree 命令和 `out_df_1` 记录不符，应视为示例文字笔误。

下一阶段验收需要同时保留：固定源码 hash、镜像 digest/ID、环境检测、构建命令及退出码、受控探索的 stdout/stderr、实际调度总数、首次错误序号、错误交错数量、超时数量，以及至少一次 `-r` 回放的 ASan 报告。若结果与官方目标不同，应先定位工具链、关键点配置、调度权限和源码/镜像差异，再评价算法表现。
