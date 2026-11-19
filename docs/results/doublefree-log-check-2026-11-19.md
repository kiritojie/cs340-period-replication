# doubleFree 重跑日志的独立统计核对

核对日期：2026-11-19。本次只分析小组已有输出，没有重新运行 PERIOD，也没有新增正式基准数据。

## 来源

- 仓库快照：[`7b355b8b`](https://github.com/kiritojie/cs340-period-replication/tree/7b355b8b65a8159e86484725be05cc9f4928af3e)。
- 原始证据：[11 月 15 日重跑包](https://github.com/kiritojie/cs340-period-replication/blob/7b355b8b65a8159e86484725be05cc9f4928af3e/docs/results/PERIOD_doubleFree_rerun_evidence-verified.zip)。
- ZIP 内成员：`results/explore/console.log`（压缩包内使用反斜杠分隔符）。
- ZIP 的 SHA-256：`c1c7fd0d76b055cc5cb4d149d3609d0304d58e83ba09b2e4938cb836eabd99ac`。
- 核对时在本地摘存为 `docs/results/doublefree-rerun-explore.log`，与 ZIP 中的该成员逐字节一致。未清理原始颜色字符；仓库保留原 ZIP，不重复提交摘存文件。

## 复核命令与输出

先按[使用说明](../log-statistics.md)从已有 ZIP 摘存原始日志，再在仓库根目录执行：

```bash
python3 scripts/summarize_period_logs.py docs/results/doublefree-rerun-explore.log
```

以下行号以该摘存文件为准。脚本提取的数字已与原始测试行、首次报错标记和结尾汇总逐项核对：

| 日志 | 总调度数 | 首次报错调度 | 报错调度数 | 超时数 |
| --- | ---: | ---: | ---: | ---: |
| doublefree-rerun-explore.log | 6 | 3 | 4 | 0 |

- `docs/results/doublefree-rerun-explore.log`：L60 总数，L53 错误数，L54 超时数，L37–L38 首次报错；SHA-256 `cb44cf855aaed3d0e7d52677f9d6c26440619db2792f88839dd25043b4f79299`。

不生成汇总统计：需要至少 3 份独立完整日志，且本批次无拒读或超时。

## 结论

统计脚本能读取第二份真实 `doubleFree` 探索日志，结果为总调度数 6、首次错误序号 3、报错调度数 4、超时 0。这是单轮工具验收的核对结果，不能填入 Table 1 或 Table 2 的正式基准对照表。不得把两次不同阶段的示例记录拼成正式基准重复实验。

脚本仅验证日志格式、计数和文件身份；三轮是否属于同一设置、是否真正独立运行，需要根据运行命令和环境记录人工确认。后续须用正式用例日志再次核对兼容性。

本说明和脚本由小组在 ChatGPT 协助下整理与验证。
