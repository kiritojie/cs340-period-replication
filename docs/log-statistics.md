# PERIOD 日志统计

本工具只分析已有探索日志，支持 Python 3.8+ 和标准库，不需要在 Mac 上运行 PERIOD 或安装实验环境。每次正式实验仍在已验证的 Linux 环境中执行。

## 已验证的用途

从单轮日志提取总调度数、首次报错序号、报错调度数和超时数，并输出每项指标的原始行号和文件 SHA-256。已分别核对小组的首次 `doubleFree` 日志和 11 月 15 日重跑日志。验证范围不包含其他正式用例。

在仓库根目录先从已有证据包摘出原始日志（已存在同名文件时不会覆盖）：

```bash
python3 - <<'PYLOG'
from pathlib import Path
from zipfile import ZipFile
archive = Path("docs/results/PERIOD_doubleFree_rerun_evidence-verified.zip")
target = Path("docs/results/doublefree-rerun-explore.log")
with ZipFile(archive) as z:
    names = {n.replace(chr(92), "/"): n for n in z.namelist()}
    raw = z.read(names["results/explore/console.log"])
with target.open("xb") as f:
    f.write(raw)
PYLOG
python3 scripts/summarize_period_logs.py docs/results/doublefree-rerun-explore.log
```

原始日志已在 ZIP 中保存，不重复提交摘存副本。再次核对已有摘存文件时，直接执行最后一行统计命令。

结果为总调度数 6、首次报错序号 3、报错调度数 4、超时 0。完整来源与实际输出见[核对记录](results/doublefree-log-check-2026-11-19.md)。

## 正式实验取得日志之后

每份日志对应一次独立完整探索。人工确认用例、工具版本、参数、预算与环境一致后，再把同一组的三轮日志交给脚本：

```bash
python3 scripts/summarize_period_logs.py run-01.log run-02.log run-03.log
```

满足条件时会计算均值和样本标准差，使用 `statistics.stdev`（分母 n−1）。没有发现错误的轮次显示“未发现”，首次报错序号不填 0，也不只取成功轮次计算首错均值。

脚本遇到不完整或不支持的格式、重复文件内容、计数不一致时拒读并返回非零退出码。日志有超时或存在拒读时，本批次不自动生成均值；原始单轮数据仍显示。内容完全相同的真实独立运行也可能被重复检测拦下，应根据各自运行证据人工核对，不要改动日志来绕过检测。

输入三份文件本身不能证明实验独立或设置一致，脚本无法替代这项检查。首个正式用例的日志要先逐项手工核对，再确认脚本是否适用。本工具不解析回放日志，也不把工具验收结果当作论文基准数据。

脚本与本说明由小组在 ChatGPT 协助下编写与验证。
