# CS340 · PERIOD 论文复现

CS340 操作系统课程小组项目，复现 PERIOD 论文中的部分实验。PERIOD 以周期为单位控制线程在关键点的执行顺序，用于探索并发错误。本仓库收录源码分析、检查脚本和可核对的实验记录。

Cheng Wen 等，*Controlled Concurrency Testing via Periodical Scheduling*，ICSE 2022。[论文 PDF](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf) · [DOI](https://doi.org/10.1145/3510003.3510178) · [官方源码](https://github.com/wcventure/PERIOD)

[Table 2 RQ1 成果入口](docs/table2-rq1-finalization-20261125/README.md) · [实验结果](#实验结果) · [复现入口](#复现入口) · [正式复现范围](#正式复现范围) · [更新历史](#更新历史) · [组员分工](#组员分工与贡献)

## 项目进度

| 阶段 | 进展 | 记录 |
| --- | --- | --- |
| 第一周 · 论文与源码 | 固定上游版本，梳理调度算法、构建、插桩与回放路径，完成两次 ARM64 Mac 环境检查。 | [算法笔记](docs/algorithm-notes.md) · [源码分析](docs/official-code-analysis.md) · [第一周记录](docs/week1-results.md) |
| 第二周 · 工具验收 | 在 Windows WSL2 + Podman 上跑通 `doubleFree` 的构建、探索和 ASan 回放，随后完成证据审计与重跑补采。 | [第二周记录](docs/week2-doublefree.md) |
| 第三周 · Table 2 基准复现 | `CS.reorder_3_bad` 完成三轮深度 3 探索，共用同一构建产物。已核对逐轮日志、错误调度和校验清单。 | [第三周详细报告](docs/week3-independent-reproduction.md) · [证据清单](docs/results/table2-reorder3/SHA256SUMS) |
| 第三周 · 跨机器独立复现 | 第二台机器（x86_64 同构 4 核，Docker Desktop）从干净目录重建插桩产物并重跑三轮，三项计数逐轮一致；六份错误调度记录与第三周归档逐字节全等。补齐逐轮二进制哈希、stdout/stderr 分离与逐轮启动配置。 | [跨机器复现报告](docs/week3-cross-host-reorder3.md) · [证据清单](docs/results/table2-reorder3-crosshost-20261122/SHA256SUMS) |
| 第三周 · Table 1 CVE 基准复现 | 官方 `ConVul-CVE-Benchmarks` 全部 **10 个程序**从零构建并按论文口径（bug-depth 5、每次调用预算 10000 调度）跑满 **10 轮 / 100 次运行**，10/10 定位逐轮成立；含深度 3 负对照与轮次完整性判据。 | [Table 1 复现报告](docs/table1-cve-reproduction.md) · [证据清单](docs/results/table1-cve/SHA256SUMS) |
| 第三周 · 工作线程调度取证 | 用 `strace -f` 补齐两份报告共同遗留的缺口：每个 PERIOD 工作线程恰好发起**一次** `sched_setattr(SCHED_DEADLINE)` 且返回 0（0/2/3 次随工作线程数变化）；同时**推翻两处源码层面预测**——runtime 不做 `sched_getattr` 回读，且 `sched_attr` 参数来自 dry-run 校准而非源码默认值。 | [取证报告](docs/worker-thread-syscall-evidence.md) · [证据清单](docs/results/worker-syscall-evidence/SHA256SUMS) |
| 第四周 · Table 2 分段复现（第一段） | 按 `CS.reorder` 线程缩放行做首个可控分段：3/4/5/10 线程四档各跑满论文口径 **10 轮**（40 次运行，全部退出码 0、超时 0），**四个调度数 27 / 100 / 225 / 2350 在 40 次运行中逐次精确命中，零方差**；单轮约 55 秒、全段 12.6 分钟。`reorder_3` 二进制与跨机器复现记录逐字节相同。 | [第一段报告](docs/table2-segment1-reorder.md) · [证据清单](docs/results/table2-reorder-schedules/SHA256SUMS) |
| 第四周 · Extension 单变量扩展实验 | 同一宿主机与镜像下仅改变 `taskset` CPU 亲和性（1/2/4/8 核，共 32 轮，覆盖 `reorder_5` 与 `reorder_10`），实测揭示：**任何真子集亲和性掩码均触发内核 `sched_setattr(SCHED_DEADLINE) = -1 EPERM`，导致首个工作线程立即 `SIGSEGV (0x18)` 崩溃、吞吐跌落至 0.93 调度/秒（慢 13.9–21.6×），而驱动静默返回 `rc=0` 且报 0 错误（100% 静默假阴性）**。 | [Extension 汇总报告](docs/results/extension-cpu-affinity-merged/stats-summary.md) · [原始数据](docs/results/extension-cpu-affinity-merged/rounds-summary.tsv) · [证据清单](docs/results/extension-cpu-affinity-merged/SHA256SUMS) |

<a id="table-2-paper-vs-ours"></a>

## 实验结果

### 核心指标速览（Paper vs. Ours）

**Table 2 英文结果。** 四档线程数的 40 轮对照、均值与样本标准差及可追溯证据见[英文对照表与图](docs/results/table2-comparison/table2-paper-vs-ours.md)。

| 实验模块 | 样本规模 | 论文基准（PERIOD） | 本组实测 | 状态与说明 |
| --- | --- | --- | --- | --- |
| 工具验收 `doubleFree` | 首次 + 重跑 | 调度 6 / 首次第 3 / 错误 4 | 调度 6 / 首次第 3 / 错误 4，0 超时 | ASan 回放确认 `double-free` |
| 跨宿主机 `CS.reorder_3_bad` | 双机各 3 轮（`-d 3`） | 首次 6 / 总调度 27 / 错误 6 | 双机逐轮一致：6 / 27 / 6，0 超时 | 32 核 Podman vs 8 核 Docker；6 份错误调度逐字节全等 |
| Table 2 `CS.reorder` 缩放行 | 4 档 × 10 轮 = 40 次（`-d 3`） | 调度数 27 / 100 / 225 / 2350 | **27 / 100 / 225 / 2350**（40/40 精确命中） | 零方差复现；10 线程错误数 89–93，耗时波动 2.65× |
| Table 1 `ConVul-CVE`（10 程序） | 10 轮 = 100 次（`-d 5`，预算 10000） | 定位 10/10；发现 15 bugs | 10/10 逐轮定位；ASan 类别和中位数 **15**（13–15） | 含 `-d 3` 负对照与静默中止门禁；15 为代理口径 |
| OS 机制取证 `strace -f` | 3 场景（Dry-run / `df` / `reorder_3`） | 工作线程启用 `SCHED_DEADLINE` | `sched_setattr` 0 / 2 / 3 次全返回 0 | 推翻两处源码静态预测（0 次 `sched_getattr`；动态校准参数） |
| Extension CPU 亲和性实验 | 1/2/4/8 核 × `reorder_5/10`（32 轮） | 论文仅要求“多核”（未量化亲和性约束） | 真子集（1/2/4 核）`reorder_5` 耗时 **240–243 s、0 错误**；完整 root domain（8 核）**17.44 s、20 错误** | `strace` 证实真子集掩码 `EPERM → SIGSEGV` 引发 100% 静默假阴性 |

- **第二周 `doubleFree` 工具验收。** 首次运行和重跑各探索 6 次调度，均在第 3 次首次触发重复释放。每轮有 4 次调度触发同一缺陷，超时 0 次。回放时 AddressSanitizer 再次检测到 `double-free`。[运行和回放记录](docs/week2-doublefree.md) · [独立统计核对](docs/results/doublefree-log-check-2026-11-19.md)
- **第三周 `CS.reorder_3_bad` 正式基准。** 每轮共探索 27 次调度，第 6 次首次触发断言失败，其中 6 次触发断言失败，超时 0 次。前三项计数逐轮与论文 Table 2 的 PERIOD 结果一致。[逐轮数据与论文对照](docs/week3-independent-reproduction.md#5-experimental-results)
- **第三周跨机器独立复现。** 第二台机器（x86_64 同构 4 核，Docker Desktop）从干净目录重建插桩产物（关键点 `reorder_bad.c:71/72/78`，二进制内嵌 Clang 10.0.0），三轮深度 3 探索的首次命中、总调度数与错误调度数逐轮一致；六份错误调度记录与第三周归档逐字节全等。[跨机器复现报告](docs/week3-cross-host-reorder3.md)
- **第三周 Table 1 CVE 基准。** 官方 10 个 CVE 程序全部从零构建，按论文 CVE 组口径（`-d 5`、每次调用预算 10000 调度）跑满 10 轮共 100 次运行：**10/10 定位在 10/10 轮均成立**、超时 0 次；`CVE-2017-6346` 在 10/10 轮同时报出 NPD＋UAF＋double-free；`CVE-2016-1972` 的 double-free 在 8/10 轮命中。逐程序 bug 类型之和的中位数为 15（范围 13–15），与论文 15 在量级上一致，但两者计数口径不同，报告中已注明为代理指标而非同一规则。[Table 1 复现报告](docs/table1-cve-reproduction.md) · [十轮摘要表](docs/results/table1-cve/rounds-summary.tsv)
- **第三周 · 工作线程调度系统调用取证。** 用 `strace -f` 直接观测 PERIOD 工作线程：每个工作线程恰好发起**一次** `sched_setattr(SCHED_DEADLINE)` 且返回 0，调用次数随工作线程数精确变化（0 / 2 / 3）。同时**推翻两处源码层面预测**：runtime 不做 `sched_getattr` 回读，且 `sched_attr` 的 runtime/deadline/period 取自 dry-run 校准（实测 4,945,020 / 82,417,000 ns）而非源码默认常量，故不可引用固定数值。`sched_yield` 次数由共享内存 `kpYield` 驱动，手工运行下为陈旧值，未作为结论。[取证报告](docs/worker-thread-syscall-evidence.md) · [跟踪记录](docs/results/worker-syscall-evidence/traces/)
- **第四周 · Table 2 第一段（`CS.reorder` 线程缩放行）。** 3/4/5/10 线程四档各跑满论文口径 10 轮，共 40 次运行、全部退出码 0、超时 0。论文该行的 PERIOD 调度数 **27 / 100 / 225 / 2350 在 40 次运行中每一次都精确命中，零方差**——比第三周的三轮样本更强，达到论文自身样本量。错误交错数在 3/4/5 线程逐轮完全一致（6 / 12 / 20），仅在 10 线程出现波动（89×2、90×7、93×1），说明该工件的非确定性并非随线程数均匀分布。首次命中序号为 6 / 9 / 12 / 27，其中仅 `reorder_3` 的 6 有外部锚点，其余三个仅作新观测记录、不可当作论文印证。单轮约 55 秒、全段 12.6 分钟。[第一段报告](docs/table2-segment1-reorder.md) · [四十轮摘要表](docs/results/table2-reorder-schedules/rounds-summary.tsv)
- **第四周 · Extension 单变量扩展实验（CPU 亲和性约束与最小修复闭环）。** 保持同一宿主机、容器与二进制不变，仅通过 `taskset` 改变 CPU 亲和性掩码（1/2/4/8 核，共 32 轮）：`reorder_5_bad` 在任何真子集掩码（1/2/4 核）下 5/5 轮外层均以 `rc=0` 跑满 225 调度，但 dry-run `kpNumArray` 全为 0、**错误交错恒为 0**、单轮耗时锁死在 ~241 s（0.93 调度/秒）；切回完整 root domain（`0-7`，8 核）后耗时降至 17.44 ± 1.98 s（快 13.9×）且精确复现 20.00 ± 0.00 次错误。`strace`、内核 `sched-deadline.rst` 与 `addr2line`/反汇编取证完整还原根因：真子集亲和性下 `sched_setattr(SCHED_DEADLINE)` 全部返回 `-1 EPERM` → `sched.h:116` 调用 `exit(-1)` → `traceEnd()`（`DBDSFunction.cpp:350/354`）先因 `joinable==0` 休眠 1 s（主线程在 510 行空转，解释 ~1.07 s/调度与 `si_utime≈100`），再遍历已析构的全局 `mapTid` 触发 `cmp 0x18(%rax), %rdi`（`SIGSEGV, si_addr=0x18`）→ `run_PDS.py:108` 显式忽略 `returncode == -11` 导致 100% 静默假阴性。进一步给出 2 文件最小 fail-fast 补丁（`sched.h` 改 `_exit(125)`、`run_PDS.py` 拦截准入失败并 `sys.exit(2)`，专门针对 `EPERM` 准入失败链路），实测 4 核真子集从 240 s 静默假阴性转为 **0.33–0.75 s 明确报错退出（`rc=2`）**，8 核完整掩码 5+5 轮交替 A/B 验证确认零回归（补丁后 5/5 轮精确命中 20 错误、首次第 12 调度、16.41 ± 1.57 s vs. 未打补丁 19.20 ± 1.79 错误、17.43 ± 1.50 s）。[Extension 汇总报告](docs/results/extension-cpu-affinity-merged/stats-summary.md) · [源码级崩溃取证](docs/results/extension-cpu-affinity-merged/traces/sigsegv-0x18-backtrace.txt) · [最小修复补丁](patches/period-sched-deadline-failfast.patch) · [补丁 A/B 验证汇总](docs/results/extension-cpu-affinity-merged/patch-verification/ab-verification-summary.tsv)

第三周结果覆盖 Table 2 的这一项基准；同一基准已在第二台机器上独立重建并重跑三轮，六份错误调度记录与归档逐字节全等，逐轮启动配置与二进制哈希同步补齐。实际 PERIOD 工作线程的调度系统调用取证已完成（每线程一次 `sched_setattr(SCHED_DEADLINE)`，返回 0）。Table 2 已按线程缩放行完成首个分段，四个调度数以论文样本量（各 10 轮）零方差复现；**Table 2 其余程序尚待论文 Table 2 的 36 程序清单**——工件内含 42 个程序目录，比论文评测的多 6 个，无法仅凭工件判定被排除的是哪 6 个（`reorder_20/50/100` 即属工件附带但不在 Table 2 范围内）。[第一段报告](docs/table2-segment1-reorder.md) · [取证报告](docs/worker-thread-syscall-evidence.md) · [第三周待完成工作](docs/week3-independent-reproduction.md#7-scope-and-outstanding-work) · [第二周验收状态](docs/week2-doublefree.md#独立复现验收状态)


### Table 2 — RQ1：统一驱动正式对照（叶浩铭）

**评阅与报告整合入口：[Table 2 RQ1 成果导航](docs/table2-rq1-finalization-20261125/README.md)。** 最终报告、Mean ± SD、五类图、复现命令和原始证据均由此进入；历史快照已归档，核心结果仍直接可读。

完成 **4 个程序 × Parallel/Serial × 各 3 轮 = 24 轮** ABI 修正后的正式实验，最终状态 `MINIMUM_24_PASSED`。深度 3、预算 10000、CPU 0–31；与历史 40 轮和 CPU Affinity Extension 分开统计。

| 程序 | Parallel：首次 / 总调度 / 错误调度 | Serial：首次 / 总调度 / 错误调度 | 检测率 P / S |
| --- | --- | --- | --- |
| reorder_3 | 6 / 27 / 6 | 10 / 30 / 10 | 3/3 / 3/3 |
| reorder_4 | 9 / 100 / 12 | **47** / 384 / 90 | 3/3 / 3/3 |
| reorder_5 | 12 / 225 / 20 | 283 / 5040 / 816 | 3/3 / 3/3 |
| reorder_10 | 27 / 2350 / **90** | ND / 10000（预算截断）/ 0 | 3/3 / 0/3 |

计数均为三轮 Mean，样本 SD 均为 0；ND 的首次错误均值及 SD 未定义。论文两处差异保留：`reorder_4 Serial` 首次 47 vs. 37（+27.03%）；`reorder_10 Parallel` 错误调度 90 vs. 89（+1.12%）。前三档 Parallel 的完整探索计数减少 10.00%、73.96%、95.54%；十线程 Serial 的 10000 是观测预算，不能当作完整搜索空间。

**Claim Verdict：RQ1 在本次四档 cohort 内得到支持，Table 2 为部分数值复现。** 原始 24 轮、SHA256、纳入标准及五类图数值审核通过；不外推到全部 36 个程序或论文性能结论。[最终英文报告](docs/table2-rq1-finalization-20261125/FINAL_REPORT.md) · [逐轮审核](docs/table2-rq1-finalization-20261125/audit-details.json) · [完整 Paper vs. Ours](docs/table2-rq1-finalization-20261125/paper-vs-ours.csv) · [提交与同步说明](docs/table2-rq1-finalization-20261125/SUBMISSION.md)

## 复现入口

1. 核对已验证的 x86_64 Linux 路线。[环境检查](#环境检查) · [首次运行环境记录](docs/results/environment.txt)
2. 从项目 Release 获取固定镜像归档 `PERIOD-amd64.oci.tar`。第二周重跑包收录镜像身份、阶段日志、原始错误调度和采集脚本。[镜像发布页](https://github.com/kiritojie/cs340-period-replication/releases/tag/doublefree-evidence-20261115) · [重跑证据包](docs/results/PERIOD_doubleFree_rerun_evidence-verified.zip)
3. 查阅 11 月 14 日的证据缺口与拟定补采步骤，以及 11 月 15 日实际完成的补采。[审计与补采方案](docs/week2-reproducibility.md) · [实际补采记录](docs/week2-doublefree.md#2026-11-15-重跑与补采)

## 正式复现范围

Table 2（RQ1）新增 ABI 修正统一驱动的 Parallel/Serial 各三轮正式对照（24/24，通过逐轮证据审核）；此 cohort 与以下历史四十轮分别报告，详见[最终报告](docs/table2-rq1-finalization-20261125/FINAL_REPORT.md)。Table 2 历史记录已完成 `CS.reorder` 线程缩放行 **4 个程序（`reorder_3/4/5/10`）** 的十轮数值复现（共 40 次运行，零方差命中论文调度数），其中 `CS.reorder_3_bad` 另完成了双机独立重建验证；Table 2 其余 32 个程序（工件共 42 目录，待对照论文确认被排除的 6 个）暂未覆盖。Table 1（RQ2）已完成官方全部 10 个 CVE 程序的十轮复现（`-d 5`、每次调用预算 10000 调度），`CVE-2016-7911` 原计划候选已连同其余 9 个程序一并跑通。`doubleFree` 用于工具功能验收。基线技术（IPB / IDB / DFS / PCT / Random / Maple）依赖 Intel Pin 与 ≤3.x 内核，性能对比图（Fig. 7）因笔记本环境墙钟耗时波动达 2.65× 不具跨机可比性，两项均未在本环境重跑，论文数字仅作引用。[论文 Table 2](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf#page=9) · [论文 Table 1](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf#page=8) · [Table 2 第一段报告](docs/table2-segment1-reorder.md) · [Table 1 复现报告](docs/table1-cve-reproduction.md) · [复现计划](docs/reproduction-plan.md)

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
| 2026-11-23 | 完成 Table 2 首个可控分段（`CS.reorder` 线程缩放行）：3/4/5/10 线程四档各 10 轮共 40 次运行，论文该行四个调度数 27 / 100 / 225 / 2350 **逐次精确命中、零方差**，达到论文自身样本量；错误交错数仅 10 线程档波动（89/90/93）。单轮 55 秒、全段 12.6 分钟，证明按行分段可控。[Table 2 第一段报告](docs/table2-segment1-reorder.md) |
| 2026-11-24 | 同步修订 `README.md` 正式复现范围（对齐 Table 2 已覆盖 4 个程序与 Fig. 7 排除说明），新增 Paper vs. Ours 核心结果速览表与组员分工贡献表。 |
| 2026-11-24 | 合并 `feat/extension-cpu-affinity` 分支至 `main`：完成 CPU 亲和性单变量 Extension 实验（1/2/4/8 核共 32 轮）及 `strace` 根因取证（真子集掩码 `EPERM → SIGSEGV` 引发 100% 静默假阴性）。[Extension 汇总报告](docs/results/extension-cpu-affinity-merged/stats-summary.md) |

## 组员分工与贡献

| 学号 | 成员 | 主要贡献与代表记录 |
| --- | --- | --- |
| `1240011062` | 叶浩铭 | 仓库初始化、第一周算法与源码分析、第二周文档与采集脚本完善、第三周 `CS.reorder_3_bad` 本地三轮正式复现（[第三周报告](docs/week3-independent-reproduction.md)）；完成 ABI 差异审计与统一驱动适配、A1/B 回归、Table 2 — RQ1 四档 Parallel/Serial 24 轮正式对照、reorder_5 原始证据恢复及最终审计报告（[最终报告](docs/table2-rq1-finalization-20261125/FINAL_REPORT.md)） |
| `1240010243` | 查舒翔 | 跨宿主机独立重建复现、Table 1 全部 10 个 CVE 十轮复现与负对照、`strace -f` 工作线程 `SCHED_DEADLINE` 系统调用取证、Table 2 `CS.reorder` 四档线程缩放十轮复现、Extension CPU 亲和性单变量扩展实验与 `EPERM → SIGSEGV` 根因取证（[跨机器报告](docs/week3-cross-host-reorder3.md) · [Table 1 报告](docs/table1-cve-reproduction.md) · [取证报告](docs/worker-thread-syscall-evidence.md) · [Table 2 第一段](docs/table2-segment1-reorder.md) · [Extension 汇总](docs/results/extension-cpu-affinity-merged/stats-summary.md)） |
| `1240011385` | 李志杰 | 项目首页与证据导航整理、`doubleFree` 日志提取与独立统计核对工作流（[日志统计文档](docs/log-statistics.md) · [独立统计核对](docs/results/doublefree-log-check-2026-11-19.md)）；复核 Table 2 四档的 40 轮归档记录与论文原表，计算均值和样本标准差，制作英文 Paper vs. Ours 对照表和图（[Table 2 数据核对与制图](docs/results/table2-comparison/table2-paper-vs-ours.md)） |
| `1240010368` | 罗韬 | 第二周 `doubleFree` 环境搭建、首次运行与 ASan 回放、重跑证据包归档（[第二周记录](docs/week2-doublefree.md)） |

提交作者与时间以 Git 历史为准。
