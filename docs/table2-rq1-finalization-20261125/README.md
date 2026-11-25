# Table 2 — RQ1: Results and Reproduction

**24/24 valid formal rounds · four CS.reorder variants · Parallel versus Serial · Haoming Ye (1240011062).**

The RQ1 claim is supported within this four-variant cohort. This is a partial numerical reproduction of Table 2. Parallel detected the assertion in 12/12 rounds; Serial in 9/12. The two paper discrepancies are retained: reorder_4 Serial first error 47 versus 37, and reorder_10 Parallel error schedules 90 versus 89. Three ten-thread Serial observations are budget-censored at 10,000, with no timeout.

| Find | Direct entry |
| --- | --- |
| Final English report | [FINAL_REPORT.md](FINAL_REPORT.md) |
| Paper vs. Ours | [Readable comparison](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/statistics/paper-vs-ours.md) · [CSV with exact deltas](paper-vs-ours.csv) |
| Mean ± sample SD | [Readable statistics](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/statistics/report.md) · [Complete group CSV](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/statistics/group-statistics.csv) |
| Five comparison plots | [All five plots and chart data](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/charts/README.md) |
| Conclusions and limitations | [Critical Analysis](FINAL_REPORT.md#critical-analysis) |
| Complete commands and prerequisites | [REPRODUCTION_COMMANDS.md](REPRODUCTION_COMMANDS.md) |
| All 24 observations | [Per-round CSV](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/statistics/per-round.csv) · [Censoring](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/statistics/censored.csv) · [Anomalies](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/statistics/anomalies.csv) |
| Original evidence and historical records | [Evidence index, archive contents and safe restoration](ARCHIVE.md) |
| Submission and GitHub Desktop | [Final inventory and before/after comparison](SUBMISSION.md) · [Git integration notes](GIT_SYNC.md) |

For the group report, copy the three sections from the single English source: [Reproduction Setup](FINAL_REPORT.md#reproduction-setup), [Results](FINAL_REPORT.md#results), and [Critical Analysis](FINAL_REPORT.md#critical-analysis). Their tables and qualifications are kept together; there are no separate section copies to reconcile.

The chart files are directly available: [first error](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/charts/first_error_detected_only.svg), [total schedules](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/charts/total_schedules.svg), [error schedules](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/charts/error_interleavings.svg), [detection rate](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/charts/detection_rate.svg), and [elapsed time](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/charts/external_seconds.svg).

Count SDs are zero for this sample; ND has no numeric first-error mean. Zero SD does not establish universal determinism. The ten-thread Serial elapsed time is variable, and no cross-machine speedup is claimed. Historical runs, the team's 40-run scaling study, and CPU Affinity Extension remain separately attributed and are not pooled here.

For deeper review, see the [raw-round audit](audit-details.json), [five-plot audit](charts-audit.json), [source identities](source-identities.json), and [readability verification](readability-audit.json). The final tables, all five SVGs, exact chart data and all 24 row summaries remain ordinary repository files; archives hold detailed raw logs and historical checkpoints.
