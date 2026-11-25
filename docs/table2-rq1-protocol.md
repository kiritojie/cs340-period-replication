# Table 2 — RQ1 formal study protocol

> Final status, 25 November 2026: **MINIMUM_24_PASSED, 24/24**. The frozen
> protocol and original execution instructions below are retained for provenance.
> The [final report](table2-rq1-finalization-20261125/FINAL_REPORT.md) contains the
> audited results and two paper discrepancies. No further target run is needed
> for this finalization. Formal round timeout is 3600 seconds, not the earlier 600.

Protocol identity: `rq1-abi-corrected-20261124-v1`.
Machine-readable specification: `config/table2-rq1-protocol.json`.

This preparation does not start a formal experiment. The verified reorder_3
pilot is frozen separately in `docs/frozen/table2-rq1-reorder3-pilot-20261124/`.
Its original session and raw evidence remain untouched. A0 is a historical
reference with an unverified legacy ABI; the pilot and all adaptation/reference
runs are excluded from formal statistical aggregates.

## Fixed conditions

| Item | Frozen rule |
| --- | --- |
| Programs | reorder_3_bad, reorder_4_bad, reorder_5_bad, reorder_10_bad |
| Official source | b6f72a7b06d01ffa7114b640312873ec2578a5ea |
| Formal modes | Unified Parallel and unified Serial |
| Depth / schedule budget | 3 / 10000 logical target executions |
| Target / round timeout | 5 seconds / 3600 seconds; TERM then KILL after 20 seconds |
| CPU affinity | Exactly 0–31 throughout this cohort; earlier 0–7 runs are separate references |
| Privileges | Existing original rootful container, SYS_NICE only, no-new-privileges retained |
| Repetitions | At least 3 independent valid rounds per program/mode: 24 formal rounds |
| Inputs | Existing product identities frozen from actual inspection; fresh work directory per round |
| Detection | Preserved assertion output and error schedule, reconciled with an actual yield-write record |

Each round is a new driver process. Calibration and default-schedule preparation
are recorded but are not counted as logical exploration schedules. A1 checks
Parallel regression during adaptation; it is not an extra formal algorithm.
No input, generator, prefix rule or statistic may be adjusted to match Table 2.

The 600-second pilot watchdog is not retained for the formal cohort. The real
Serial pilot took 2.338847111 external seconds for 30 schedules. A rough linear
extrapolation gives 779.6 seconds for 10000 schedules before allowing for larger
thread counts or generator overhead. A uniform 3600-second bound is fixed in
advance. This extrapolation is not a predicted completion time. A round hitting
the bound is an abnormal incomplete observation; its limit is not extended
selectively after seeing its result.

## Artifact and runtime identity

For each program, inspection records the binary, ConConfig, official benchmark
source, runtime object/source, source commit, toolchain and hashes. Existing
binaries are preferred. Missing/unverified products block that program. A
necessary build must use a separate copy of unchanged pinned source and retain
its complete command, toolchain, exit code and output hashes; historical binary
paths must not be replaced. No automatic rebuild is part of this preparation.

Static ConConfig locations and runtime KPS are different quantities: for the
verified three-thread pilot there were three static locations, but runtime KPS
was [2,2,1]. Other programs must obtain ThreadNum, MaxKpNum and per-thread KPS
from their own observed runs. Accepted adaptation freezes that runtime profile;
paired modes and subsequent repetitions must agree with it.

Yield dimensions come from the actual thread/key-point profile. At depth d,
Parallel uses p=2..d+1; Serial uses p=N..N+d-1. Each matrix must match its own
schedule conversion. Serial periods contain one thread and adjacent periods
must use different threads. Parallel permits multiple threads only in its final
period. Fixed prefixes must be respected. The small reorder_3 permutation oracle
is not copied to larger programs or expanded into factorial enumeration.

The ABI decoder, permission handling, process cleanup, scheduler adapters and
yield observer retain the exact bytes that passed the real pilot. Parameterized
preflight adds benchmark-manifest identity checks; it does not alter measured
layout parsing. Live permissions, affinity, active processes and IPC are checked
again even when immutable source/product proofs are reused.

## Termination and inclusion

| State | Research treatment |
| --- | --- |
| COMPLETED | Include if all logical launches completed and all evidence reconciles |
| BUDGET_EXHAUSTED | Include at exactly 10000 executed/completed schedules, no in-flight work or target timeout |
| TARGET_TIMEOUT | Preserve counts, timeout records and partial trace; exclude from ordinary result means |
| ROUND_TIMEOUT | Preserve the partial attempt and actual completed count; never relabel it budget exhaustion |
| INFRASTRUCTURE_FAILURE | Preserve environment/identity/permission/export failure and stop the phase |
| DRIVER_EXCEPTION | Preserve exception and full traceback; stop the phase |

Generated candidates, successful logical launches, completed logical schedules,
physical retries and in-flight work have distinct counts. A candidate generated
after the logical budget is reached is not an executed schedule. Metadata,
printed ordinals, actual writes and saved error/timeout files must reconcile.
Unexpected runtime KPS changes or retests require manual review in this fixed
CS.reorder cohort; they are retained as invalid attempts, not silently dropped.

Normal budget exhaustion is a valid observation. In particular, the paper's
reorder_10 Serial entry reaches its 10000-schedule limit without finding a bug.
Nondetection is `first_error=null`, with its actual observation limit and reason.
Never substitute 10000 as a fabricated first failing schedule. Infrastructure
or incomplete rounds are not ordinary right-censored successful experiments.

All attempted rounds remain in the per-round/anomaly tables. A failed phase
stops; no automatic retry or selective removal is performed. A changed timeout
or protocol creates a separately identified cohort.

## Execution order

1. Inspect and freeze actual identities, environment and current harness.
2. Run reorder_3 with the unified driver: 3 Parallel and 3 Serial formal rounds.
3. For each of reorder_4/5/10, perform one A1/B/C adaptation validation. Verify
   identities, ABI, runtime KPS, legality and A1/B equivalence before accepting it.
4. Only after that program passes adaptation, run its 3 Parallel and 3 Serial
   formal rounds. Pilot/adaptation records never count toward the 24 formal runs.
5. Review the minimum dataset before considering 10 repetitions per group.

A1/B adaptation requires matching schedules, actual yield matrices and error
outcomes. Historical reorder_10 error counts varied, but those legacy runs do
not establish the cause or justify waiving the corrected comparison. If an
adaptation pair differs, preserve both outcomes and investigate before that
program's formal phase; do not rerun pairs until a matching one appears.

Exact Ubuntu commands and pending live checks are listed in the preparation
review. Every command creates fresh output; raw historical evidence is preserved.

## Statistics and limitations

The reporting command produces per-round results, group statistics, Paper vs.
Ours tables, censored observations, anomaly records and checksums. Mean ± sample
standard deviation uses denominator n−1; SD is undefined for fewer than two
observations. First-error means are conditional on detected valid rounds only,
and are always accompanied by detection counts and censored observations.

Bug Detection Rate is the number of valid rounds exposing the assertion divided
by all valid rounds. Planned, attempted, valid and invalid counts are reported
separately. Six error interleavings of the same assertion are not six distinct
bugs. No-results groups remain NOT_RUN rather than receiving zero-valued data.

Internal footer time and external wall time are separate measurements. Python
profiling, WSL, laptop hardware, hybrid cores and historical affinity differences
limit timing comparisons. Yield records show successful write-path arguments,
not a complete physical worker interleaving trace. The initial three repetitions
are fewer than the paper's ten, and these four variants are only a subset of
Table 2. Published paper counts are reference points, never pass/fail targets.
For budget-censored rounds, the observed total of 10000 is a truncated workload,
not an estimate of the complete schedule-space size.
