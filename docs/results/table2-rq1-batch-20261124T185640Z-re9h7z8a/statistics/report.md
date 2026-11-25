# Table 2 / RQ1 formal results

Only explicit formal rounds are included. Pilot, adaptation and legacy A0 are separate.

| Benchmark | Mode | Planned / attempted / valid | Detection rate | First ordinal, detected only | Total schedules | Error schedules |
| --- | --- | --- | --- | --- | --- | --- |
| reorder_3_bad | parallel | 3 / 3 / 3 | 3/3 (100.0%) | 6 +/- 0 (n=3) | 27 +/- 0 (n=3) | 6 +/- 0 (n=3) |
| reorder_3_bad | serial | 3 / 3 / 3 | 3/3 (100.0%) | 10 +/- 0 (n=3) | 30 +/- 0 (n=3) | 10 +/- 0 (n=3) |
| reorder_4_bad | parallel | 3 / 3 / 3 | 3/3 (100.0%) | 9 +/- 0 (n=3) | 100 +/- 0 (n=3) | 12 +/- 0 (n=3) |
| reorder_4_bad | serial | 3 / 3 / 3 | 3/3 (100.0%) | 47 +/- 0 (n=3) | 384 +/- 0 (n=3) | 90 +/- 0 (n=3) |
| reorder_5_bad | parallel | 3 / 3 / 3 | 3/3 (100.0%) | 12 +/- 0 (n=3) | 225 +/- 0 (n=3) | 20 +/- 0 (n=3) |
| reorder_5_bad | serial | 3 / 3 / 3 | 3/3 (100.0%) | 283 +/- 0 (n=3) | 5040 +/- 0 (n=3) | 816 +/- 0 (n=3) |
| reorder_10_bad | parallel | 3 / 3 / 3 | 3/3 (100.0%) | 27 +/- 0 (n=3) | 2350 +/- 0 (n=3) | 90 +/- 0 (n=3) |
| reorder_10_bad | serial | 3 / 3 / 3 | 0/3 (0.0%) | ND (0/3 detected; censored) | 10000 +/- 0 (n=3) | 0 +/- 0 (n=3) |

Mean +/- sample standard deviation uses only validated formal rounds. SD is undefined for n=1.
First-error means use detected runs only and must be read with detection rate and censoring; they are not unconditional means.
Budget exhaustion at exactly the frozen count is a valid result. ND is not the numeric value 10000.
Invalid, timed-out, unfinished or duplicate attempts remain in anomalies.csv and are not silently replaced or counted as no-bug runs.

Paper comparison is in paper-vs-ours.csv. Source: PERIOD ICSE 2022, Table 2 (PDF page 9), https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf.
The paper's reorder_10 Serial result is ND / budget 10000 / 0 errors; no comparable paper runtime is supplied.

Limitations: at least three rounds per group are the local minimum, below the paper's ten; one workload family does not reproduce all Table 2.
CPU affinity is frozen at 0-31; historical 0-7 and legacy ABI data must not be pooled. Profiling/supervision and hardware affect elapsed time.
Yield-write observations are not complete worker execution-order traces. Error schedules are not distinct bugs.
