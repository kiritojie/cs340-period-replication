# Paper vs. Ours

Triples mean first-error ordinal / total schedules / error schedules. Ours uses mean +/- sample SD; the first-error mean is conditional on detection.

| Benchmark | Mode | Paper triple | Ours first ordinal | Ours total | Ours errors | Detected / valid | Censored |
| --- | --- | --- | --- | --- | --- | --- | --- |
| reorder_3_bad | parallel | 6 / 27 / 6 | 6 +/- 0 (n=3) | 27 +/- 0 (n=3) | 6 +/- 0 (n=3) | 3 / 3 | 0 |
| reorder_3_bad | serial | 10 / 30 / 10 | 10 +/- 0 (n=3) | 30 +/- 0 (n=3) | 10 +/- 0 (n=3) | 3 / 3 | 0 |
| reorder_4_bad | parallel | 9 / 100 / 12 | 9 +/- 0 (n=3) | 100 +/- 0 (n=3) | 12 +/- 0 (n=3) | 3 / 3 | 0 |
| reorder_4_bad | serial | 37 / 384 / 90 | 47 +/- 0 (n=3) | 384 +/- 0 (n=3) | 90 +/- 0 (n=3) | 3 / 3 | 0 |
| reorder_5_bad | parallel | 12 / 225 / 20 | 12 +/- 0 (n=3) | 225 +/- 0 (n=3) | 20 +/- 0 (n=3) | 3 / 3 | 0 |
| reorder_5_bad | serial | 283 / 5040 / 816 | 283 +/- 0 (n=3) | 5040 +/- 0 (n=3) | 816 +/- 0 (n=3) | 3 / 3 | 0 |
| reorder_10_bad | parallel | 27 / 2350 / 89 | 27 +/- 0 (n=3) | 2350 +/- 0 (n=3) | 90 +/- 0 (n=3) | 3 / 3 | 0 |
| reorder_10_bad | serial | ND / 10000 (budget) / 0 | ND | 10000 +/- 0 (n=3) | 0 +/- 0 (n=3) | 0 / 3 | 3 |

No observed results have been inserted to force agreement with the paper. Legacy A0, adaptation and pilot data are not pooled.
Paper source: PERIOD ICSE 2022 Table 2, https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf.
