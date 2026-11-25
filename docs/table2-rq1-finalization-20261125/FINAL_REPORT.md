# Table 2 / RQ1: Final Reproduction Report

Author: Haoming Ye (1240011062). Final review: 25 November 2026 (UTC+8).

**Audit: PASS, 24/24 valid formal rounds. Claim verdict: SUPPORTED WITHIN THE FOUR-VARIANT COHORT; PARTIAL NUMERICAL REPRODUCTION OF TABLE 2.**

This report covers only the ABI-corrected Parallel/Serial cohort. The team's historical 40-run scaling study, cross-host study, Table 1 study and CPU Affinity Extension remain separately attributed and are not pooled here. No target execution, new experiment, core-code change, Commit or Push was performed during finalization.

## Reproduction Setup

We evaluated the four CS.reorder variants with 3, 4, 5 and 10 worker threads, using the pinned PERIOD source revision `b6f72a7b06d01ffa7114b640312873ec2578a5ea`. Parallel and Serial used a common ABI-corrected driver, a bug-depth bound of three, a budget of 10,000 logical exploration schedules, and three independent repetitions per variant and mode. Each repetition used a new driver process and output directory; execution was sequential in the shared IPC namespace. Calibration and preparation launches were recorded separately from exploration counts. CCT is the general testing category; Serial is PERIOD equipped with its serialized scheduler, rather than an unrelated third technique.

The cohort ran on Windows/WSL2 with an Intel Core i9-14900HX and Linux kernel `6.18.58.1-microsoft-standard-WSL2`. The existing rootful Podman container used Ubuntu 18.04.5 userland, Python 3.6.9, GCC 7.5 and LLVM/Clang 10.0. CPU affinity was fixed to logical CPUs 0–31. The container retained only SYS_NICE, with no-new-privileges enabled and privileged mode disabled. The frozen image ID was `dfd654d5ebf18787ebff0b8cc35c61c6eda4d49852a93bb784fbe2e82727299a`. The target timeout was five seconds; the formal round timeout was 3,600 seconds, with a 20-second kill grace. The earlier 600-second pilot/supervision limit is not the formal protocol.

The shared-memory layout was measured from executable and existing runtime-object DWARF. The corrected structure is 24,008 bytes, with 100 uint16 thread-count entries and 3,964 uint16 entries in each point array. The offsets for kp, kpLoc and kpOrder are 220, 8,148 and 16,076. Official scheduling generators, runtime and historical benchmark products were retained. Missing 4/5/10-thread products were built using the official steps in separate directories, with toolchain, source and product identities recorded; historical products were not replaced.

Before formal measurement, the ABI-only Parallel reference (A1) and unified Parallel driver (B) were checked for equality of generated schedules, actual yield writes, saved assertion outcomes, first errors and counts. All four benchmark checks passed. The unified Serial mode (C) then underwent its legality/depth checks. A0 denotes the preserved historical driver audit; A1 and all pilot/adaptation runs are excluded from the 24 formal observations. The frozen protocol is [config/table2-rq1-protocol.json](../../config/table2-rq1-protocol.json), also copied verbatim into the final batch.

## Results

Table 1 compares the exact paper reference entries with our mean and sample standard deviation (denominator n−1). Each mode has three valid observations. The first-error statistic includes detected rounds only. ND has no numeric first-error mean or SD. Paper repetition-level detection rates and comparable per-row runtime are not supplied by Table 2 and are not inferred.

| Benchmark | Mode | Paper first / total / errors | Ours first, mean ± SD | Ours total, mean ± SD | Ours errors, mean ± SD | Detected / valid | Difference from paper |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| reorder_3 | Parallel | 6 / 27 / 6 | 6 ± 0 | 27 ± 0 | 6 ± 0 | 3/3 (100%) | None |
| reorder_3 | Serial | 10 / 30 / 10 | 10 ± 0 | 30 ± 0 | 10 ± 0 | 3/3 (100%) | None |
| reorder_4 | Parallel | 9 / 100 / 12 | 9 ± 0 | 100 ± 0 | 12 ± 0 | 3/3 (100%) | None |
| reorder_4 | Serial | 37 / 384 / 90 | 47 ± 0 | 384 ± 0 | 90 ± 0 | 3/3 (100%) | First +10 (+27.03%) |
| reorder_5 | Parallel | 12 / 225 / 20 | 12 ± 0 | 225 ± 0 | 20 ± 0 | 3/3 (100%) | None |
| reorder_5 | Serial | 283 / 5040 / 816 | 283 ± 0 | 5040 ± 0 | 816 ± 0 | 3/3 (100%) | None |
| reorder_10 | Parallel | 27 / 2350 / 89 | 27 ± 0 | 2350 ± 0 | 90 ± 0 | 3/3 (100%) | Errors +1 (+1.12%) |
| reorder_10 | Serial | ND / 10000 (budget) / 0 | ND (n=0 detected) | 10000 ± 0 | 0 ± 0 | 0/3 (0%) | Same budget-censored outcome |

Parallel completed exploration after 27, 100, 225 and 2,350 schedules. Serial completed after 30, 384 and 5,040 schedules for the first three variants, but all three ten-thread rounds reached the 10,000-schedule budget without exposing the assertion. For completed exploration, Parallel reduced counts by 10.00%, 73.96% and 95.54%; Serial/Parallel count ratios were 1.111×, 3.84× and 22.4×. For ten threads, 10,000/2,350 = 4.255× describes only the observed workload ratio: Serial's complete schedule-space size remains unknown.

Parallel detected the assertion in 12/12 rounds and all four program variants. Serial detected it in 9/12 rounds and three variants. These are sample detection fractions and program-variant coverage, rather than estimates of distinct bugs or population detection probabilities. The aggregate was 54,468 completed exploration schedules, including 3,132 assertion-triggering schedules. Every formal attempt had zero target/round timeouts, zero retests, zero in-flight work at termination and driver exit code zero.

Two paper entries differed: reorder_4 Serial first detection was 47 rather than 37; reorder_10 Parallel produced 90 rather than 89 buggy schedules. Every remaining first-error, total-count and error-count entry matched, including ten-thread Serial nondetection at the budget. All observed count SDs were zero; this does not establish deterministic execution for arbitrary hosts or repetitions.

| Benchmark | Mode | External elapsed seconds, mean ± sample SD |
| --- | --- | ---: |
| reorder_3 | Parallel | 1.773 ± 0.052 |
| reorder_3 | Serial | 2.507 ± 0.126 |
| reorder_4 | Parallel | 4.161 ± 0.364 |
| reorder_4 | Serial | 24.958 ± 1.636 |
| reorder_5 | Parallel | 9.173 ± 0.804 |
| reorder_5 | Serial | 345.508 ± 12.504 |
| reorder_10 | Parallel | 108.761 ± 16.368 |
| reorder_10 | Serial | 524.940 ± 573.900 |

The ten-thread Serial external times were 202.723, 1,187.540 and 184.558 seconds. The long second observation was retained, satisfies the frozen 3,600-second limit, and explains the large SD. Internal driver-footer time and external wall time use different timing methods and measurement boundaries; both are retained without forcing agreement. Elapsed times include local profiling/supervision effects and are not a direct comparison with the paper's workstation or its runtime-overhead experiments.

The five original plots are linked from the [final batch chart index](../results/table2-rq1-batch-20261124T185640Z-re9h7z8a/charts/README.md). All 40 chart-data rows / 680 fields match the frozen group summary. Independent recalculation passed 120 mean/SD/n checks and eight detection-rate checks; all five SVG files reconstruct exactly from the recorded input and unchanged renderer. ND is a label with no fabricated numeric value. The chart CSV stores detection fractions such as 1.0 despite its unit label "percent"; the SVG correctly renders 100%. Proportion SD is left undefined. Runtime lower SD whiskers are clipped at zero for drawing only. Pixel rendering was not independently verified because the available headless browser produced no screenshot; the numerical and SVG-source checks passed.

## Critical Analysis

**Claim verdict.** The observations support the RQ1 claim that allowing a parallel final period reduces exploration work relative to serialization, within these four CS.reorder variants. The relative reductions in completed exploration counts increase with thread count (10.00%, 73.96% and 95.54%), and the ten-thread Parallel mode detects the assertion while Serial exhausts its budget. This is a partial reproduction of Table 2, not a replication of all 36 evaluated programs, the paper's eight additional detected bugs / 26.67% aggregate improvement, or RQ3's overhead claims. We used three repetitions per group rather than the paper's ten.

**Observed compatibility defect and engineering repair.** Extraction of the preserved historical container's actual run_PDS.py confirmed 1,990-element arrays, a 12,160-byte allocation, and feedback offsets 4,200/8,180, incompatible with the measured 3,964-element runtime layout. The extracted driver SHA256 is `c6ed1312f61f7ec739e3dcead0086e0265d37f07bd88ef64d6588d3ff61a8e8f`; its scoped upstream sources match the pinned revision. The common ctypes-based adapter validates field offsets, unsigned widths, dimensions, full structure size and bounded reads/writes against measured DWARF. Root-direct execution accommodates no-new-privileges without changing runtime privilege policy; process-cleanup fixes keep supervision idempotent. These are engineering changes needed to obtain interpretable measurements, not new scientific findings about scheduler quality.

**Regression evidence and its limit.** A1/B agreement on every schedule, requested yield matrix and validated failure outcome establishes consistency of the unified driver with its ABI-corrected reference for the tested workloads. Their raw stdout and trace hashes need not be identical because roles and times differ. Agreement does not retroactively validate the mismatched historical interface. Header/count fields and small yield writes can share offsets across layouts, so earlier actual assertion failures are not automatically imaginary; feedback fields can still be read incorrectly. An extracted historical file also cannot prove exact driver bytes for every past invocation without per-run provenance. Historical runs remain separate.

**Unresolved causes.** The causes of the two numerical differences remain unverified. Host-dependent execution in a shared final period is a plausible explanation for error-count variation, but these data do not isolate that cause. It does not explain the Serial first-error difference. Enumeration, artifact provenance and hardware differences are hypotheses requiring separate evidence. Requested yield-write records are not complete physical worker-interleaving traces, and no such trace is claimed here.

**Censoring and failures.** The three ten-thread Serial rounds are valid right-censored observations at 10,000 completed schedules; their first_error remains null. They do not establish that the program is bug-free, that the first error is 10,000, or that the complete space has 10,000 schedules. Target/round timeouts, driver exceptions and infrastructure failures would be excluded from ordinary means and retained as failed attempts, rather than recoded as nondetection. None occurred inside the accepted 24 observations. Earlier export/setup failures remain documented separately: reorder_5 native experiments had completed successfully, and their failed 60-second transfer was recovered by copying the existing native evidence with a separate 1,800-second export allowance. The 3,600-second research timeout was unchanged and reorder_5 was not rerun to replace lost data.

## Audit and Evidence Map

The independent final audit rehashed 59 SHA256 manifests: 56 in the recovered session and three in the final batch, totaling 16,607 manifest entries and 6,293 distinct referenced files. No file was missing or mismatched. All 24 CSV context/analysis hashes and the common protocol hash (`5685e140d2ecb9c5a9290f39b9f8be39b8c1f607ad1208c04ec3bafe20c78312`) were checked. Actual stdout ordinals/footer, completed yield traces, saved assertion files and their matrices, frozen binary/ConConfig identities, mode/depth/budget commands, KPS profiles and before/after environment records reconcile. Checksums demonstrate consistency with recorded evidence; they are not independent proof of execution authenticity.

| Evidence | Repository-relative location |
| --- | --- |
| Original final batch, statistics and five plots | `docs/results/table2-rq1-batch-20261124T185640Z-re9h7z8a/` |
| Canonical 24-round session | `docs/results/table2-rq1-recovered-session-20261124T180224Z-210n7nbf/` |
| Independent per-round/integrity audit | [audit-details.json](audit-details.json) |
| Independent chart audit | [charts-audit.json](charts-audit.json) |
| Actual historical driver / source audit | `docs/results/table2-rootful-resume-20261124T223147-rn8x19fu/A0-historical-driver-audit.json` and `original-source/extraction-audit.json` |
| reorder_3 A1/B regression | `docs/results/table2-permission-stage-20261124T151059Z-1zwxlb1z/pilot-20261124T151138Z-yu48cwra/native-evidence/table2-scheduler-pilot-20261124T151141Z.rkkK2o/A1B-regression.json` |
| reorder_4 / 5 / 10 A1/B regression | Canonical session `batch-adapt-20261124T164926Z-ga9y2h3v/`, `batch-adapt-20261124T165627Z-bn7rgkx3/`, `batch-adapt-20261124T192351Z-bfqlkndd/`, each under `native-evidence/A1B-regression.json` |
| Accepted six/twelve-round freeze | `docs/frozen/table2-rq1-reorder3-formal-20261124/` and `table2-rq1-twelve-formal-20261124/` |
| Export recovery proof | Canonical session `recovery-control/` and `recovery-provenance.json` |
| Portable evidence and exact omissions | [SUBMISSION.md](SUBMISSION.md) and [evidence-archive.json](evidence-archive.json) |

The original text archive retains byte-exact raw logs, error schedules and ConConfig records. A companion [historical archive](ARCHIVE.md) now supplies the 51 original artifact copies omitted by that text package, together with complete freeze and final-batch snapshots. This closes the original evidence hash contracts after both archives are restored. The final statistics, all 24 row summaries, five SVGs and exact chart data remain directly readable. No original experiment or checkpoint manifest was resealed; all original local files remain unchanged. See the [safe restoration and verification commands](REPRODUCTION_COMMANDS.md#restore-evidence-without-overwriting). Stage reports and code snapshots are preserved for provenance rather than duplicated in the review path.

## Personal Contribution

Haoming Ye completed the local ABI audit, common driver-interface adaptation and prerequisite regression workflow; specified the fixed Parallel/Serial protocol and inclusion/censoring rules; executed and organized the 24-round four-variant cohort; froze accepted observations across interruptions; recovered completed reorder_5 evidence without rerunning it; and prepared the final statistical comparison, chart audit, critical analysis and safe Git integration materials. Earlier local algorithm/source analysis, evidence tooling and reorder_3 reproduction remain credited separately. Teammates' cross-host work, 40-run scaling study, Table 1, CPU Affinity Extension and separate data verification/visualization remain credited to their authors in README. Individual schedule failures are not counted as individual bug discoveries.

## Rechecking Existing Results

These commands are documentation for offline review; none launches a target. From the repository root, inspect [audit-details.json](audit-details.json), the per-round CSV and the [archive contents/verification instructions](ARCHIVE.md). To verify all full local original manifests with the existing read-only helper:

```powershell
python -X utf8 -B -c "import sys; from pathlib import Path; sys.path.insert(0,'orchestration'); from rq1_integrity import verify_tree; print(verify_tree(Path('docs/results/table2-rq1-recovered-session-20261124T180224Z-210n7nbf'))); print(verify_tree(Path('docs/results/table2-rq1-batch-20261124T185640Z-re9h7z8a')))"
```

This requires full original evidence, including historical artifact copies. Restore both packages as documented in ARCHIVE.md; the text archive alone remains incomplete. Existing experiment entry points remain documented in [protocol](../table2-rq1-protocol.md) and [orchestration notes](../../orchestration/README.md) for reproducibility; their execution is outside finalization and no new experiment is requested.

## References

Cheng Wen et al. *Controlled Concurrency Testing via Periodical Scheduling*. ICSE 2022. DOI: [10.1145/3510003.3510178](https://doi.org/10.1145/3510003.3510178). [Official PDF](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf), §4.1.3–4.2 and Table 2 (PDF pp.8–9). Paper source entries were rechecked on 25 November 2026. [Pinned upstream source](https://github.com/wcventure/PERIOD/tree/b6f72a7b06d01ffa7114b640312873ec2578a5ea).
