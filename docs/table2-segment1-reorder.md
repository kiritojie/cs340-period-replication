# Table 2 Segment 1 · CS.reorder Thread-Scaling Row

**23 November 2026 (China Standard Time)**

First deliberately-scoped segment of Table 2: the `CS.reorder` thread-scaling
row, run at the paper's full repetition count (10 rounds per program) instead of
a partial pass. One round costs ~55 s, so the whole segment cost 12.6 minutes —
cheap enough that segmenting here buys scope control rather than a shortcut.

The row is the most informative per unit of runtime in Table 2: it is the only
place where the paper gives PERIOD's schedule counts at four thread counts, so a
match reproduces a *scaling curve*, not a single point.

## 1. Command and Provenance

```bash
python3 -u /workdir/PERIOD/tool/DBDS/run_PDS.py -y -d 3 ./reorder_<N>_bad
```

`-d 3` here, deliberately unlike the CVE group's `-d 5`: the paper caps SCTBench
at bug depth ≤3, and this is also what the group's week-3 and cross-host work
used, so the numbers are directly comparable to both.

| Item | Value |
| --- | --- |
| Host | same second machine as [cross-host Table 2](week3-cross-host-reorder3.md) and [Table 1](table1-cve-reproduction.md) |
| `reorder_3` binary | `ed2d13809b87…` — **byte-identical to the cross-host reproduction** |
| `reorder_4` / `reorder_5` | built fresh this segment (1 s each), 3 key points each |
| `reorder_10` binary | `329744a03fd5…` |
| Rounds | 10 per program, 40 runs, all exit 0, 0 timeouts |
| Evidence | [SHA256SUMS](results/table2-reorder-schedules/SHA256SUMS) (291 entries) |

## 2. Result — all four published counts matched, 10/10 rounds

| Program | Paper (schedules) | This host, median (range) | Rounds matching | Error interleavings, median (range) |
| --- | ---: | ---: | :---: | ---: |
| `reorder_3` | 27 | **27 (27–27)** | 10/10 | 6 (6–6) |
| `reorder_4` | 100 | **100 (100–100)** | 10/10 | 12 (12–12) |
| `reorder_5` | 225 | **225 (225–225)** | 10/10 | 20 (20–20) |
| `reorder_10` | 2350 | **2350 (2350–2350)** | 10/10 | 90 (89–93) |

Schedule counts were **not** merely within range — every one of the 40 runs
returned exactly the published figure. This is a stronger result than the
group's week-3 work, which used 3 rounds; at 10 rounds with zero variance the
schedules-to-bug claim in the paper's Table 2 is reproduced at the paper's own
sample size.

### First-error ordinal (new data, mostly without a published counterpart)

| Program | First failing schedule | Comparable to |
| --- | ---: | --- |
| `reorder_3` | 6 | group week-3 report and cross-host record: 6 — matches |
| `reorder_4` | 9 | no published figure checked — **new observation only** |
| `reorder_5` | 12 | no published figure checked — **new observation only** |
| `reorder_10` | 27 | no published figure checked — **new observation only** |

The 6/9/12/27 progression is internally consistent (first-failure ordinal grows
with thread count), but only `reorder_3`'s value 6 has an external anchor. Do
not present the other three as paper confirmations.

### Where non-determinism actually showed up

Error-interleaving counts are stable at 3/4/5 threads (10/10 rounds identical)
but vary at 10 threads: **89 ×2, 90 ×7, 93 ×1**. So the artifact's variance is
not uniform across thread counts — it appears at the largest one. Schedule
counts nonetheless stayed pinned at 2350 in all 10 rounds, which suggests the
variance affects error *accounting* rather than the exploration path. That is an
observation, not a mechanism; nothing here proves which stage introduces it.

## 3. Wall-Clock Note

`reorder_10` wall time ranged 41.2–109.2 s (**2.65×** spread, median 51.8 s)
while its schedule count never moved. This is direct evidence for the standing
constraint that timings on this laptop are not reportable: the same
deterministic work varied 2.65×. Per-schedule throughput is therefore not a
defensible metric here, consistent with deferring Fig. 7.

## 4. What This Segment Does and Does Not Cover

Covers one Table 2 row. It does **not** touch the paper's aggregate Table 2
claims (38 bugs / 30 of 36 programs), which need the full program set — the
repository ships 22 `CS`, 3 `CB`, 4 `Chess`, 4 `Inspect_benchmarks`, 5
`RADBench`, 1 `SafeStack`, 3 `Splash2` directories (42 total), whereas the paper
evaluated 36. Which six were excluded cannot be determined from the artifact
alone; it needs the paper's Table 2 listing.

That exclusion list is the blocker for the remaining segments, and it is worth
noting the artifact's extra programs are not filler: `reorder_20/50/100` exist
in the image but are outside Table 2, and `reorder_100` was observed earlier not
to complete within 420 s, versus 41 s for `reorder_10`.

## 5. Reproduction

```bash
bash collect_sct_reorder.sh 10     # 4 programs x 10 rounds, ~13 min
```

[`collect_sct_reorder.sh`](results/table2-reorder-schedules/collect_sct_reorder.sh)
builds any missing product first, records per-run binary hashes, and exports one
error-schedule sample per bug type per round. Per-round detail:
[`rounds-summary.tsv`](results/table2-reorder-schedules/rounds-summary.tsv)
(40 rows).
