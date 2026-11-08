# 第一周复现范围与后续实验计划

日期：2026-11-07。官方源码固定为 [`cb8deb9a176e5bb292d70d46557dd61dc0e98069`](https://github.com/wcventure/PERIOD/commit/cb8deb9a176e5bb292d70d46557dd61dc0e98069)。本组仓库只维护分析、检查脚本和可审核的小型证据；官方源码与下载资源放在仓库外，或被忽略的 `external/` 中。

## 分阶段目标与验收

| 阶段 | 工作 | 完成标准 |
| --- | --- | --- |
| 第一周 | 固定官方版本，阅读算法和构建链，检测宿主环境，明确 doubleFree 能否运行 | 文档有源码依据；检测有真实原始日志；未运行的实验标记 NOT_RUN |
| 第二周 A | 准备原生 x86_64 Linux 多核机器，优先按 Ubuntu 18.04 环境建立基线 | 记录发行版、Linux 内核、Docker client/server、CPU、LLVM 和镜像 digest；确认 deadline 调度权限 |
| 第二周 B | 构建并执行官方 doubleFree，回放至少一个错误调度 | 构建日志完整，ASan 指出 double free，错误调度文件存在且可回放 |
| 后续 | 扩展到 UAF / doubleFree2 和少量固定 benchmark；比较不同深度 | 固定输入和资源，记录每轮指标和失败原因；满足条件后再做多次测量与基线比较 |

优先选择 x86_64 Linux 是依据安装脚本下载的 x86_64 LLVM 10.0.0 包作出的工程选择，**不是声称论文已证明 ARM 不可移植**。本机为 macOS ARM64 且缺少 Docker CLI，当前结果见 [第一周实测记录](week1-results.md)。即使补装 Docker，也应先验证 Linux 虚拟机内核、CPU 平台、系统调用与权限；模拟 x86_64 的成功不能预先假定。

## 环境依赖核对

| 项目 | 官方依据 | 本组需要验证的事项 |
| --- | --- | --- |
| OS / kernel | README、INSTALL：Ubuntu ≥18.04，Linux kernel ≥4.x；REQUIREMENTS 本地安装段写 Ubuntu 18.04 | macOS 的 Darwin 版本不能代替 Linux 版本；容器内应再检查实际 Linux kernel |
| CPU | 官方要求多核；`install_llvm.sh` 明确下载 x86_64 包 | 宿主与 Docker daemon / 镜像架构分别记录，不推定 ARM64 可直接运行 |
| Docker | 官方要求版本高于 18.09.7，并以 `--privileged` 启动 | CLI 存在、daemon 可达、镜像可用与调度可用是四项独立条件 |
| 编译分析链 | Dockerfile：Ubuntu 18.04、构建工具、LLVM 10、SVF、WLLVM、staticAnalysis | LLVM 插件和 bitcode 的 ABI/版本一致；Apple Clang 不能视作官方 LLVM 10 的替代验证 |
| Python | Dockerfile 同时安装 Python 2/3 与 numpy；Python 3 另装 sysv_ipc | 确认实际解释器与模块可导入；旧脚本的 shebang、pip 版本与旧依赖需逐项核对 |
| 调度与 IPC | `sched.h` 的 Linux `sched_setattr` / `SCHED_DEADLINE`；`ipc.py` 使用 sysv_ipc | 检查调度权限与系统调用；原生进程 root / CAP_SYS_NICE 等配置和容器限制可能影响运行 |
| 检错 | build.sh 使用 `-fsanitize=address` | 区分编译失败、工具超时、ASan abort 与普通程序 exit code |

来源：[REQUIREMENTS](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/REQUIREMENTS.md)、[Dockerfile](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/Dockerfile)、[LLVM 安装脚本](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/tool/install_llvm.sh)、[调度运行时](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/tool/staticAnalysis/DBDS-INSTRU/llvm-mode/sched.h)。

## Linux 环境就绪后使用的流程（本机尚未执行）

1. 在独立目录取得官方仓库并 checkout 上述完整 commit，核对 `git rev-parse HEAD` 和工作区状态。不要从本组仓库根目录运行官方 `cleanDIR.sh`。
2. 优先尝试官方镜像；记录镜像 ID、repo digest 和镜像内源码版本。`wcventure/period:stable` 是可变标签，**不能将其自动当成固定 commit 的产物**。若无法确认镜像来源，改为从固定源码按 Dockerfile 构建，并保留构建日志与依赖版本；Dockerfile 的 apt/pip 下载未固定，仍不保证逐字节可重复。
3. 在符合官方条件的 Linux 容器中设置 `$ROOT_DIR`，进入 `$ROOT_DIR/test/doubleFree`，按官方说明执行：

   ```bash
   ./cleanDIR.sh && ./build.sh
   "$ROOT_DIR/tool/DBDS/run_PDS.py" -y -d 3 ./df
   ```

4. 保留构建、测试 stdout/stderr 和退出码，列出实际 `out_df_*/Errors/`。根 README 的预期是探索 6 个调度、4 个错误交错、首次错误位于第 3 个调度；这些是**对照目标**，不是本组测量值。若不同，先核对 commit、插桩点、参数和环境，不改写日志以符合预期。
5. 根据实际错误文件路径执行 `run_PDS.py -r <error-file> ./df`，验证 ASan double-free。保存回放输出与输入调度校验值。不要把程序正常 abort 误写成脚本基础设施失败，也不要只凭退出码认定已发现 double free。

建议每次 build / test / replay 设置并记录 5 分钟外部总时限。单次测试子进程的时限应按[固定版本源码](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/tool/DBDS/run_PDS.py#L279)核实，并通过 `-t <秒数>` 显式设置；该版本 `-h` 未列出此选项，回放分支也未使用内部超时，需由外部总时限约束。超时单独统计。这里是下一阶段计划，没有后台实验在运行。

## 需要记录的实验字段

每轮记录：时间和时区、官方 commit、镜像 digest 或构建标识、CPU/核数、OS/kernel、LLVM/Python 版本、输入、命令、深度、时限、耗时、退出码、总调度数、首次错误调度序号、错误交错数、超时数、回放结果及相关文件摘要。第二周先获得一份完整可回放结果，再决定重复次数和性能测量方式；目前不承诺可复现论文所有表格。
