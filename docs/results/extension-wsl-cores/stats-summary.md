# Extension 实验第二部分：WSL2 真实 Root-Domain 核数单变量对照（2 / 4 / 8 核）

采集时间 2026-11-25 13:50–14:49（UTC+8），全部在同一宿主机、同一容器镜像（`wcventure/period:stable`）与同一上游 PERIOD（`b6f72a7`）下完成。

## 实验动机与设置

在第一部分（[extension-cpu-affinity-merged/stats-summary.md](../extension-cpu-affinity-merged/stats-summary.md)）中，我们证实 `taskset` 构造的真子集掩码会违反 Linux `SCHED_DEADLINE` 的 root domain 准入约束（返回 `EPERM` 并引发 `SIGSEGV` 静默假阴性），因此不能用 `taskset` 回答“物理/逻辑核数本身是否影响 PERIOD 的错误检出率与波动”。

本实验改用 WSL2 `.wslconfig` 的 `processors=2 / 4 / 8` 改变 VM 级别的 root domain 核数，**不使用 `taskset`**，使每一档进程亲和性均覆盖完整 root domain（`0,1` / `0-3` / `0-7`），从而剥离 `EPERM` 干扰，独立观测核数对 `reorder_5_bad`（5 线程，225 调度）与 `reorder_10_bad`（10 线程，2350 调度）的影响。

| 项目 | 值 |
| --- | --- |
| 宿主机 | Intel i7-10510U（4 物理核 8 线程），Docker Desktop / WSL2 kernel `6.18.58.1` |
| 容器与版本 | `wcventure/period:stable`（`8f47d8b9148f`），`--privileged`，上游 PERIOD `b6f72a7b06d01ffa7114b640312873ec2578a5ea` |
| 自变量 | `.wslconfig` `processors=2 / 4 / 8`（每次切换后 `wsl --shutdown` 重启，容器内实测 `nproc` 与 `default_affinity` 分别为 `2 (0,1)`、`4 (0-3)`、`8 (0-7)`） |
| 主扫描轮次 | `-y -d 3`；按 8→4→2 顺序，`reorder_5_bad` 每档 5 轮、`reorder_10_bad` 每档 3 轮，共 **24 轮**（全部 `deadline_probe_rc=0`、收紧门禁 `gate_pass=1`、0 `sched_setattr` 错误、0 超时） |
| 逆序复核轮次 | 按 **2→8** 逆序补跑 `reorder_5_bad` 各 3 轮（共 6 轮，见 `order-check/rounds-summary.tsv`），用于排除 8→4→2 运行顺序/温度漂移混淆 |
| 采集与统计脚本 | [scripts/extension_wsl_cores.sh](../../../scripts/extension_wsl_cores.sh) · [scripts/extension_wsl_cores_driver.ps1](../../../scripts/extension_wsl_cores_driver.ps1) · [scripts/extension_cpu_stats.py](../../../scripts/extension_cpu_stats.py) |

原始逐轮数据见 [rounds-summary.tsv](rounds-summary.tsv)（24 轮主扫描）与 [order-check/rounds-summary.tsv](order-check/rounds-summary.tsv)（6 轮逆序复核），均可直接用 `python3 scripts/extension_cpu_stats.py <tsv>` 复现统计值。

## 主扫描结果（8 → 4 → 2）

### 1. `reorder_5_bad`（5 线程，225 个调度）

| 真实核数（完整 root domain） | 有效/总 | 调度数（Mean ± SD） | 错误交错（Mean ± SD） | 错误中位数（范围） | 首次命中序号 | 超时 | 单轮耗时 s（Mean ± SD） |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2 核（`0,1`）** | **5/5** | 225.00 ± 0.00 | **16.40 ± 2.79** | 15 (14–21) | 12 (×2) / 90–91 (×3) | 0 | 15.34 ± 1.51 |
| **4 核（`0-3`）** | **5/5** | 225.00 ± 0.00 | **20.00 ± 0.00** | 20 (20–20) | **12** (5/5) | 0 | 18.39 ± 3.60 |
| **8 核（`0-7`）** | **5/5** | 225.00 ± 0.00 | **20.00 ± 0.00** | 20 (20–20) | **12** (5/5) | 0 | 16.58 ± 0.87 |

### 2. `reorder_10_bad`（10 线程，2350 个调度）

| 真实核数（完整 root domain） | 有效/总 | 调度数（Mean ± SD） | 错误交错（Mean ± SD） | 错误中位数（范围） | 首次命中序号 | 超时 | 单轮耗时 s（Mean ± SD） |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2 核（`0,1`）** | **3/3** | 2350.00 ± 0.00 | **79.33 ± 4.16** | 78 (76–84) | 27 (×1) / 75–82 (×2) | 0 | **208.52 ± 26.79** |
| **4 核（`0-3`）** | **3/3** | 2350.00 ± 0.00 | **89.67 ± 0.58** | 90 (89–90) | **27** (3/3) | 0 | 93.60 ± 2.89 |
| **8 核（`0-7`）** | **3/3** | 2350.00 ± 0.00 | **90.00 ± 0.00** | 90 (90–90) | **27** (3/3) | 0 | 88.83 ± 7.22 |

## 逆序顺序复核（2 → 8，`reorder_5_bad` 各 3 轮）

| 真实核数（完整 root domain） | 有效/总 | 调度数 | 错误交错（Mean ± SD） | 逐轮错误数 | 首次命中序号 | 单轮耗时 s（Mean ± SD） |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| **2 核（`0,1`，先跑）** | **3/3** | 225 | **14.67 ± 0.58** | 15 / 14 / 15 | 95 / 20 / 91 | 15.04 ± 1.68 |
| **8 核（`0-7`，后跑）** | **3/3** | 225 | **20.00 ± 0.00** | 20 / 20 / 20 | **12** (3/3) | 18.03 ± 3.00 |

逆序复核在先跑 2 核、再切回 8 核时完整复现了相同分化（`14.67 ± 0.58` vs. `20.00 ± 0.00`，且 2 核 R1 的 dry-run `Runtime=7076 ns` 处于正常区间时错误数仍为 15），排除了主扫描 8→4→2 顺序或宿主机热节流导致该现象的可能。

## 核心发现、机制假设与实验边界

1. **对照实验支持分离“亲和性真子集失效”与“真实核数效应”**：
   - 在 8 核宿主机上用 `taskset -c 0-3`（4 核真子集）运行 `reorder_5_bad` 会触发 `EPERM → SIGSEGV`（耗时 240.29 s、0 错误）；而在 `.wslconfig processors=4` 构造的**真实 4 核完整 root domain（`0-3`）**下，`reorder_5_bad` 仅需 **18.39 s** 且 5/5 轮检出 **20** 次错误，`reorder_10_bad` 仅需 **93.60 s** 且检出 **89–90** 次错误，与 8 核基线（`16.58 s / 20` 与 `88.83 s / 90`）基本持平。该反事实对照直接支持第一部分 4 核失效归因于 `SCHED_DEADLINE` root domain 准入约束，而非 4 核算力不足。
2. **2 核下的检出率下降、首次命中延后与两项需关注的观测**：
   - 在 2 核完整 root domain 下（全部 11 轮 `SCHED_DEADLINE` 均正常准入、无 `EPERM`/无 `EBUSY`、0 超时），两个基准均出现错误检出率下降与首次命中推迟：`reorder_5_bad` 主扫描降至 `16.40 ± 2.79`（逆序复核 `14.67 ± 0.58`），`reorder_10_bad` 降至 `79.33 ± 4.16`（耗时升至 `208.52 s`，约为 4/8 核的 2.3×）。
   - **关于原因的谨慎表述（假设而非定论）**：在 `reorder_10_bad` 上，2 核的 dry-run `Runtime` 校准值从 4/8 核的 `1018–1428 ns` 膨胀至 `5180–12364 ns`，因此 `reorder_10_bad` 的耗时增加与错误减少可能同时受“dry-run 校准参数漂移”与“线程数远超核数时的并发竞争/节拍精度下降”共同影响（而在逆序复核的 2 核 `reorder_5_bad` R1 中，`Runtime=7076 ns` 正常但错误仍降至 15，提示核数本身确有独立贡献）。
   - **关于 `reorder_5_bad` 耗时反常现象**：在主扫描（`15.34 s`）和逆序复核（`15.04 s`）中，2 核 `reorder_5_bad` 的单轮耗时反而**略快于** 4 核（`18.39 s`）和 8 核（`16.58–18.03 s`），并未呈现“核数越少越慢”的单调关系。这可能与 2 核下 `reorder_5_bad` 的 dry-run `Runtime` 均值偏低（3808–5020 ns vs. 8 核 5970–9060 ns，对应更短的周期节拍）或部分错误交错未触发断言/清理路径有关，具体机理尚待进一步插桩验证。
3. **实验局限性**：
   - `reorder_10_bad` 每档仅跑 3 轮，未做正式统计显著性检验，结论应视为受控环境下的有条件实证观测；
   - WSL2 的 2 个 vCPU 无法指定绑定到两个独立物理核还是同一物理核的两个超线程（SMT），该拓扑变量在 WSL2 环境下不可控；
   - 主扫描按 8→4→2 顺序执行，仅对 `reorder_5_bad` 做了 2→8 逆序复核，未对 `reorder_10_bad` 重复逆序扫描。

## 目录结构

- `cores-2/`、`cores-4/`、`cores-8/`：主扫描各核数档位的 `exec-env.txt`、二进制构建日志与哈希、逐轮日志及分档 `rounds-summary.tsv`。
- `order-check/`：2→8 逆序复核（`reorder_5_bad` 各 3 轮）的原始日志与 `rounds-summary.tsv`。
- `rounds-summary.tsv`：24 轮主扫描合并汇总表。
- `SHA256SUMS`：本目录全量文件 SHA-256 校验清单。
