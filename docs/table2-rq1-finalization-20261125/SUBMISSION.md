# Table 2 RQ1: Final Submission

**Review entry: [Table 2 RQ1 results](README.md). Submit manually in GitHub Desktop; no Commit or Push has been performed.**

## Before and after

| Item | Previous selection | Readable selection |
| --- | ---: | ---: |
| Proposed new/changed files | 240 | 121 |
| Total bytes | 15,492,369 | 19,408,585 |
| Total MB (decimal) | 15.492 | 19.409 |
| Freeze records / review patches visible | 81 | 3 FREEZE identities |
| Final batch files visible | 65 | 26, including all final statistics and plots |
| Original report/document group visible | 19 | 13 retained, plus 3 navigation/audit documents |
| Evidence packages | 1 | 2 |

The visible change count falls by **119 files (49.58%)**. The package bytes increase because the historical archive also supplies 51 original checkpoint artifacts omitted by the previous text-only package. Those artifacts are needed for the original hashes and frozen-pilot prerequisite; none was rebuilt. Both the total payload and every file remain below **50,000,000 bytes**.

## Suggested submission

| Category | Files | Bytes |
| --- | ---: | ---: |
| Code, configuration and tests | 71 | 893,993 |
| Final batch, statistics and charts | 26 | 147,663 |
| README and Git rules | 3 | 30,349 |
| Raw evidence and historical archives | 2 | 17,715,152 |
| Report, navigation and audit documents | 16 | 136,014 |
| Visible frozen identities | 3 | 485,414 |
| **Total** | **121** | **19,408,585** |

Exact paths and sizes: [submission-files.csv](submission-files.csv). Optional CLI allowlist: [staging-paths.txt](staging-paths.txt). Unchanged tracked files covered by a directory pathspec are not additional changes. GitHub Desktop Changes should correspond to this new/modified selection; a later teammate update or local edit can change the count.

## What stays directly readable

- One [English report](FINAL_REPORT.md), with direct [Reproduction Setup](FINAL_REPORT.md#reproduction-setup), [Results](FINAL_REPORT.md#results) and [Critical Analysis](FINAL_REPORT.md#critical-analysis) anchors for the group report.
- [Paper vs. Ours](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/statistics/paper-vs-ours.md), [exact deltas CSV](paper-vs-ours.csv), [Mean / sample SD](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/statistics/report.md), and all [24 observations](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/statistics/per-round.csv).
- All [five SVGs and their exact data](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/charts/README.md); final scientific data are not hidden solely in ZIP.
- All runnable sources, configuration, tests and pinned vendor bytes, plus the three original FREEZE identities and current [source identities](source-identities.json).
- [Complete restoration, offline checking and experiment commands](REPRODUCTION_COMMANDS.md). Experiment commands are documentation only; no new live run was performed.

## What was archived

- 78 of the old 81 visible freeze/patch files: historical source snapshots, early six/twelve-round statistics, checkpoint notes/checksums and review diffs. All 81 originals are preserved; three key identities remain directly visible.
- 39 launcher/preflight files from the final batch, retaining exact bytes and the original complete batch snapshot.
- Three preparation reports and three superseded inventory/Git/check snapshots. The 19 original documentation files had no exact byte duplicates; archival follows historical purpose, not an assumption that similarly named reports are identical.
- Exact before-readability reports, README, Git rules and the original submission manifest are preserved in a separate snapshot namespace. Current documentation is not overwritten during restoration.

Nothing was deleted or moved from the local original trees. Ignored expanded historical files remain on disk. The archive additionally preserves two pilot source versions that differ from the current source, rather than reconstructing them from newer files.

## Evidence integrity and reproduction

See [ARCHIVE.md](ARCHIVE.md) for package contents, SHA256 and safe restoration. The original text ZIP is unchanged. The companion history ZIP closes its omitted-artifact coverage after restoration. Historical experiment/checkpoint SHA manifests were not rewritten; only this current submission-document SHA manifest is refreshed after archiving its previous version.

Validated in an isolated restored directory:

- 6,966 original repository files restored without overwriting local evidence.
- 63 experiment/freeze SHA manifests, covering 16,688 entries, PASS.
- The existing frozen-pilot prerequisite PASS, including the original pilot work binaries.
- The unchanged offline report writer returns 24 valid rounds, zero invalid attempts and three budget-censored observations. All eight group records agree with the frozen result (maximum numeric difference 1.12e-16).
- All five SVG texts reproduce from the regenerated group statistics after normal newline decoding. Pixel rendering is not claimed.
- 83 source/config/test/orchestration files, 64 frozen harness identities and 504 existing tracked teammate data files are unchanged.
- Navigation checks find no new broken local links or links into ignored files. The 11 existing teammate links absent from this checkout remain preserved for remote integration.

The pilot parent permission manifest predates the later pilot subdirectory. Its existing gate correctly verifies its declared entries and the two later pilot manifests separately; it is not resealed to cover subsequently appended files. Offline restoration is not a claim of a new Linux/container execution.

The detailed verification record is [readability-audit.json](readability-audit.json). Existing raw [round audit](audit-details.json) and [chart audit](charts-audit.json) remain available.

## GitHub Desktop

Inspect Changes and the inventory, review README/.gitattributes/.gitignore, then commit manually. [GIT_SYNC.md](GIT_SYNC.md) describes normal Fetch/Merge and conflict preservation for teammate CPU Affinity and Table 2 contributions. This cleanup did not perform a Git merge. No Force Push, reset --hard or discard changes is needed.

Suggested Commit Message:

~~~text
Finalize Table 2 RQ1 results and streamline evidence navigation
~~~
