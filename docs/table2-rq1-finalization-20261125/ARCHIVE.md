# Original Evidence and Historical Checkpoints

The final [tables](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/statistics/report.md), [24 row summaries](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/statistics/per-round.csv), [exact chart data](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/charts/chart-data.csv) and [five plots](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/charts/README.md) are directly readable. Archives provide the deeper evidence and historical stages rather than replacing these core results.

| Package | Contents | Integrity |
| --- | --- | --- |
| [Original text evidence](../evidence/table2-rq1-evidence-20261125.zip) | 6,769 exact original text files: canonical 24-round session, actual-source/ABI extraction, pilot, recovery and necessary failures | 12,752,967 bytes; SHA256 `8e0540ed36a3a9b2e5b38158fed42280c724aeb30ef4d2b57b7aa262b7c54fec`; every included file listed in PACKAGE_SHA256SUMS |
| [Historical checkpoints](../evidence/table2-rq1-history-20261125.zip) | Original 81 freeze/patch files, complete 65-file final batch snapshot, 22 pre-cleanup documentation/rule snapshots, 51 original artifacts complementing the text package, and the cleanup baseline | 4,962,185 bytes; SHA256 `5ffce594291b2cbcc3bce0ff1ae1117ca1bc2cf87c135cc6bf709b7d9618da0d`; ARCHIVE_MANIFEST.json verifies every payload member |

All original local files remain in place. No original experiment or checkpoint manifest has been rewritten. The editable submission-document manifest is refreshed after preserving its previous bytes in the historical archive. The original text ZIP is unchanged. The historical ZIP contains existing execution/checkpoint artifacts; no binary was compiled or executed during cleanup. These artifacts close the original hash contracts, including the three pilot work binaries required by the existing frozen-pilot check. They are stored as evidence rather than added as loose build outputs.

## Archive layout

| Prefix or entry | Purpose |
| --- | --- |
| Text ZIP: docs/results/... | Original repository-relative raw evidence, including error schedules and ConConfig records ignored by general Git rules |
| History ZIP: repository/docs/frozen/... | Exact pilot, six-round and twelve-round checkpoints, their original SHA manifests, earlier statistics and source snapshots |
| History ZIP: repository/docs/patches/... | All five review patches; these are historical diffs, not steps to apply over current code |
| History ZIP: repository/docs/results/... | Complete original final-batch snapshot and the 51 artifact copies omitted by the text ZIP |
| History ZIP: snapshots/before-readability/... | Previous reports, submission metadata, README and Git rules; review in a separate directory, never restore over current documentation |
| History ZIP: _meta/baseline.json | Original 240-file identities, protected core/data/manifest identities and duplicate analysis |

The original 81-file checkpoint/patch group is retained in full, although only its three FREEZE.json identities stay visible in the submission. Of 56 pilot harness snapshot files, 54 match current sources and two record older versions; all 56 are preserved exactly. The earlier six/twelve-round result tables are checkpoint history, not extra observations in the final dataset.

The final batch's 39 launcher/preflight files are archived; its eight root records, nine statistics files and nine chart files remain visible. The original root SHA256SUMS still covers the full original batch, so it requires restoration of launcher/preflight before checking the complete tree. The statistics and chart subdirectory manifests can be verified directly without extraction.

The original 19 documentation files had no byte-identical duplicates. Three preparation reports and three superseded inventory/Git/check snapshots are archived according to their historical role. The final report, independent audits, current source identities, protocol and reproduction commands remain directly readable.

## Raw evidence map

| Question | Original location after safe restoration |
| --- | --- |
| All 24 formal rounds and recovery proof | docs/results/table2-rq1-recovered-session-20261124T180224Z-210n7nbf/ |
| Actual historical driver and ABI/source extraction | docs/results/table2-rootful-resume-20261124T223147-rn8x19fu/ |
| Successful three-thread pilot and A1/B regression | docs/results/table2-permission-stage-20261124T151059Z-1zwxlb1z/ |
| Final batch launch/preflight records | docs/results/table2-rq1-batch-20261124T185640Z-re9h7z8a/launcher/ and preflight/ |
| Stage explanations | History ZIP snapshots/before-readability/docs/table2-abi-compatibility.md, table2-permission-stages.md and table2-scheduler-pilot.md |

## Restore and verify

Use the exact commands in [REPRODUCTION_COMMANDS.md](REPRODUCTION_COMMANDS.md#restore-evidence-without-overwriting). Restoration checks package hashes and existing files before writing missing files, and refuses different existing bytes. It restores only original repository trees; earlier editable documentation/rules remain separate snapshots.

After restoring both packages, verify the original 59 formal/session manifests and four freeze manifests with the existing read-only helper. The frozen-pilot prerequisite can also be checked offline, without Podman, compilation or target execution. [readability-audit.json](readability-audit.json) records isolated restoration and verification results.

Old interrupted-session resume commands also depend on the original host/container state and additional local history. Archive restoration does not authorize an interrupted container to resume, and is not a claim that the container can be recreated from evidence alone.
