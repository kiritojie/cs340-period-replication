<h1 align="center">PERIOD · 论文复现</h1>
<p align="center"><strong>CS340 Operating Systems · 小组项目</strong></p>
<p align="center"><em>Controlled Concurrency Testing via Periodical Scheduling</em><br>
Cheng Wen 等 · ICSE 2022</p>
<p align="center">
  <a href="https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf">论文 PDF</a> ·
  <a href="https://github.com/wcventure/PERIOD">官方源码</a> ·
  <a href="#复现入口">复现入口</a> ·
  <a href="#更新历史">更新历史</a>
</p>

> **已验证：`doubleFree` 构建、探索与回放**
>
> **6 种调度 · 第 3 种首次报错 · 4 种触发同一错误 · 0 次超时**
>
> [运行记录](docs/week2-doublefree.md) · [11 月 15 日重跑证据](docs/results/PERIOD_doubleFree_rerun_evidence-verified.zip)

PERIOD 通过控制线程在关键位置的执行顺序，测试程序在不同调度下的行为。小组已验证工具能运行，并能用保存的调度再次触发示例错误。**这组数据属于工具验收，论文基准尚无本组结果。**

## 项目进度

| 阶段 | 状态 | 从这里看 |
| --- | --- | --- |
| 论文与源码 | 已梳理算法和构建链 | [算法笔记](docs/algorithm-notes.md) · [源码分析](docs/official-code-analysis.md) |
| 工具验收 | 已重跑，回放再次报告 `double-free` | [首次探索](docs/results/doubleFree-smoke.log) · [首次回放](docs/results/doubleFree-replay.log) |
| 论文基准 | 首个正式用例待小组确认 | [复现计划](docs/reproduction-plan.md) |

**下一项交付：** 做出第一行 `Paper vs. Ours`。确定表号和用例后，在同一设置下至少独立完整运行三次，报告首错调度序号、总调度数和报错调度数的均值与样本标准差；每轮链接原始日志，另记超时、未发现和设置差异。

## 复现入口

- **检查环境：** 已验证路线为 Windows WSL2 + Podman 上的 x86_64 Linux；容器使用 Ubuntu 18.04.5 和 Clang 10.0.0。先看[环境记录](docs/results/environment.txt)，再运行下方检查脚本。
- **查看复跑说明：** [复现步骤](docs/week2-reproducibility.md)记录了环境、构建及证据保存方法；当时的缺口与后续重跑证据见[第二周记录](docs/week2-doublefree.md)。
- **获取固定镜像：** [GitHub Release](https://github.com/kiritojie/cs340-period-replication/releases/tag/doublefree-evidence-20261115)。重跑证据包保留了命令、退出码、原始错误调度与 `SCHED_DEADLINE` 实测记录。

```bash
./scripts/check_environment.sh
```

检查脚本不运行基准；退出码为 `0` 仅表示盘点结束。

<details>
<summary><strong>保存环境检查日志与退出码</strong></summary>

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

<details>
<summary><strong>源码版本、论文范围与早期记录</strong></summary>

| 项目 | 记录 |
| --- | --- |
| 第一周源码分析 | [`cb8deb9`](https://github.com/wcventure/PERIOD/commit/cb8deb9a176e5bb292d70d46557dd61dc0e98069) · [文件来源](docs/official-source.json) |
| 第二周环境记录中的容器源码 | [`b6f72a7`](https://github.com/wcventure/PERIOD/commit/b6f72a7b06d01ffa7114b640312873ec2578a5ea) · [版本核对](docs/official-code-analysis.md#version-comparison) |

两个固定上游提交的工具、示例、基准代码和 Dockerfile 相同，差异只涉及文档。容器实际运行依据见环境记录与重跑证据；上游版本对比本身不能证明容器里的构建来源。

原计划从论文 Table 1（RQ2）的 `CVE-2016-7911` 开始；另一个候选是 Table 2（RQ1）的 `CS.reorder_3_bad`。首个正式用例由小组确认，目前两者均无本组结果。

- [第一周记录](docs/week1-results.md) · [ARM Mac 环境日志](docs/results/environment-2026-11-07.txt)
- [示例前提检查](docs/results/doublefree-feasibility-2026-11-07.txt) · [静态验证日志](docs/results/validation-2026-11-07.txt)

</details>

## 更新历史

| 日期 | 小组进展 |
| --- | --- |
| 2026-11-08 | [初始化仓库](https://github.com/kiritojie/cs340-period-replication/commit/67f4574ac9c82a05439d2d1f1e525d09a84f5da6)，记录源码来源、环境检查与第一周进展。 |
| 2026-11-09 | [整理小组首页](https://github.com/kiritojie/cs340-period-replication/commit/2f5fa9307414ed30ba32323f47f5ab89a9397dd2)，补上实验范围、验收标准和更新历史。 |
| 2026-11-14 | [记录首次工具验证](docs/week2-doublefree.md)，公开环境、探索和回放日志。 |
| 2026-11-15 | [提交重跑证据](https://github.com/kiritojie/cs340-period-replication/commit/c0a4ce7329c24cb6ac87cd90212b3580e59262f7)，补齐原始调度、命令、退出码和调度能力记录。 |

本仓库保存小组分析、脚本与实验记录；个人贡献见各自的提交和报告分工。
