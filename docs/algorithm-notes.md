# PERIOD 核心算法阅读笔记

阅读日期：2026-11-07。论文：Cheng Wen 等，*Controlled Concurrency Testing via Periodical Scheduling*，ICSE 2022，DOI [10.1145/3510003.3510178](https://doi.org/10.1145/3510003.3510178)。依据[作者预印本](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf) §2–3、§4.5，以及下列固定版本源码；本文件是阅读分析，不是实验结论。

## 解决的问题与调度表示

并发程序对相同输入也可能因线程交错不同而产生不同结果。PERIOD 在共享内存访问和同步等关键点之前插桩，控制执行顺序，并保存错误调度供回放。它把一次执行划成 period：下一 period 的关键点等待前一 period 完成。这里的 period 是调度区间，不是周期性重复执行测试。

一个调度可写成 `[[0], [1, 1], [0]]`：线程 0 执行一个关键点，线程 1 执行两个，最后线程 0 再执行一个。它表示关键点的线程归属与分组，不表示源码行号或固定毫秒数。并行扩展允许最后一个 period 容纳多个线程，因此不能笼统地把所有 period 都解释为全局单线程执行。[源码调度生成器](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/tool/DBDS/sbp_sched_mixed_end.py)

## 三个核心部件

| 部件 | 关键思想 | 实现阅读入口 |
| --- | --- | --- |
| Schedule generator | 从少到多增加 period 数；按线程模式及各线程关键点分配系统枚举，而非随机 sleep | `bp_sched.py`、`sbp_sched.py`、`sbp_sched_mixed_end.py` |
| Periodical executor | 在关键点前插桩；利用 Linux deadline 调度与 `sched_yield()` 实现执行区间切换，运行时信息通过共享内存反馈 | `tool/staticAnalysis/DBDS-INSTRU/llvm-mode/DBDSFunction.cpp`、同目录 `sched.h` |
| Feedback analyzer | 根据实际经过的关键点和历史调度更新待探索任务；使用 prefix 约束后续生成 | `tool/DBDS/run_PDS.py`、`external_def.py` |

论文 §3.1 的工作项是 `(DKPS, prefix)`。DKPS（dynamic key point slice）记录一次实际执行中各线程经过的有序关键点；初始模型只假设每线程一个关键点。执行反馈若发现原模型不能涵盖的新 slice，就产生进一步探索任务；prefix 保留到达新行为所需的历史调度前段。这样不必先静态枚举所有分支、循环次数的笛卡尔积，但工作量仍受关键点数量、路径和深度影响。

## 深度边界与实现核对

论文的 `P` 是 **period 数上界**，目标 bug depth `< P`。官方脚本的 `-d` 是 **bug depth 上界**，不是直接设置 period 数。固定源码 `run_PDS.py` 第 274–278 行将参数转成 `period_limit = bugDepth + 1`，第 638 行枚举 `2..period_limit`。因此 `-d 3` 对应 2、3、4 个 period。参见[参数实现](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/tool/DBDS/run_PDS.py#L274)和[探索循环](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/tool/DBDS/run_PDS.py#L636)。

在 doubleFree 中，每个子线程的关键操作可抽象为 `free(ptr)`、`ptr = NULL`。若一个线程先完成两步，另一个线程随后 `free(NULL)`，可能不报错；若两线程都在置空前取得原地址并释放，则形成 double free。系统控制关键点顺序能主动覆盖这种窗口。源码还含 `printf` 等操作，真正插桩点应以生成的 `ConConfig.df` 为准，不能只据 C 文件数行推定。[示例源码](https://github.com/wcventure/PERIOD/blob/cb8deb9a176e5bb292d70d46557dd61dc0e98069/test/doubleFree/df.c)

## 复现时应保留的边界

论文 §4.5 讨论了固定测试输入、关键点识别不完整和弱内存模型等限制。有限深度下未发现错误不等于证明程序正确。调度生成、实际调度生效、ASan 错误识别和调度回放是不同的验证层次，必须分别验收；生成若干列表也不代表成功复现 PERIOD。

第一周目标是理解上述机制并核实运行条件。论文报告的性能优势、CVE 数量和新漏洞数量均未在本项目重新测量，不作为本组实验结果。
