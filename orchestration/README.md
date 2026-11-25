# RQ1：先恢复已完成数据，再继续尚未执行的程序

> 收尾状态（2026-11-25）：恢复与四档正式实验已完成，最终
> `MINIMUM_24_PASSED / 24 / 24`。下方命令保留为历史复现说明，本阶段不再执行。
> 结果、精简证据包与安全 Git 同步步骤见
> [最终报告](../docs/table2-rq1-finalization-20261125/FINAL_REPORT.md)。

已通过的 reorder_3 / reorder_4 共12轮冻结于 `docs/frozen/table2-rq1-twelve-formal-20261124/FREEZE.json`。reorder_5 原生阶段退出0，但其证据复制在60秒时超时；旧副本不完整，尚不能纳入统计。

在 Ubuntu x86_64 root 终端运行：

```bash
python3 -B /mnt/e/cs340-period-replication/orchestration/table2_rq1_batch.py --recover-from /mnt/e/cs340-period-replication/docs/results/table2-rq1-batch-20261124T164754Z-zphvi2gi
```

命令先核验并冻结12轮、确认原导出失败只属于传输问题，创建独立恢复视图。它保留相同容器、native root、协议和 harness，旧 Session、HALTED、排除收据和残缺文件完全保留。复制已验收的准备、3/4正式及5构建/适配阶段，使用1800秒导出期限从原容器目录重新复制5正式阶段到新目录。

恢复必须通过原始 SHA 清单绑定、全文件哈希与完整覆盖、六轮 stdout/stderr/yield trace/metadata/错误调度核验、原有正式验收器、历史正常后置状态与当前实时检查。恢复的状态必须与原18-after-native-guard和当前 checkpoint 一致。环境后置文件按真实原生布局逐轮检查。

只有恢复视图恰好包含18轮有效原始数据、无重复，才继续。reorder_3、4、5 的 completed 标记使它们不再执行。保留已构建且验收的二进制；reorder_10 如确实缺产物，才按已授权官方流程构建、验收，并执行其 Parallel/Serial 各三轮。

恢复视图只纳入一次有效原始记录，不扫描旧失败5副本，因此既不修改原 phase_excluded，也不因重复轮次把恢复数据再次排除。视图含 recovery-provenance.json，完整来源及恢复证明存于已封存的 recovery-control/ 中。

任一恢复文件缺失、改变、校验失败或环境不一致都会停止并保存新恢复证据；不根据 formal_complete 标记单独接受数据，也不自动重跑5来替代丢失数据。明确单程序失败及全局失败继续沿用现有协议处理。

后续自动生成逐轮统计、Mean ± sample SD、Paper vs. Ours、检测率、截尾/异常、五类 SVG 和最终报告。首次错误 ND 不写成10000，历史 A0、pilot、adaptation 和 Extension 不混入正式均值。

只有八组各三轮、总24轮有效，输出 MINIMUM_24_PASSED / 24 / 24。不足为 INCOMPLETE_MINIMUM_24；全局或未知故障为 BLOCKED_GLOBAL。此前有效数据保留且不自动重试或替换。

传输时限与实验时限分开：证据导出1800秒，正式整轮3600秒协议不变。冻结 scripts/、tests/、算法、ABI、权限、清理与 runtime 均未修改。当前代码还修复了导出失败后错误比较运行前 checkpoint 的问题；始终执行真实后置检查，但只有实际加载已验证的导出状态后才比较它与当前状态。

--complete-from、--prepare、--session 保留旧用途；本次使用 --recover-from，不删除旧 HALTED 或覆盖原目录。不改变容器权限，不自动 Commit/Push。
