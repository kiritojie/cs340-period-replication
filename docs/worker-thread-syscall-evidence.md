# PERIOD Worker-Thread Scheduling Syscall Evidence

**22 November 2026 (China Standard Time)**

Closes the one gap both the [Table 1](table1-cve-reproduction.md) and
[cross-host Table 2](week3-cross-host-reorder3.md) reports listed as "remains
open on both hosts": direct evidence of what a real PERIOD worker thread does at
the syscall level, from thread creation through its scheduling-policy request.

## 1. Method

`strace -f` (version 4.21-1ubuntu1) attached to the whole process group spawned
by the `sudo` wrapper, over three scenarios. The minimal `test/doubleFree/df`
target (2 workers) and `evaluation/CS/reorder_3` (3 workers) keep the traces
small enough to read in full.

| Scenario | Command env | Workers | Result |
| --- | --- | ---: | --- |
| A — natural (dry-run) | `Dry_Run=1 DBDS_Run=0` | — | 0 × `sched_setattr` |
| B — `df` under DBDS | `Dry_Run=0 DBDS_Run=1` | 2 | 2 × `sched_setattr`, all return 0 |
| C — `reorder_3_bad` under DBDS | `Dry_Run=0 DBDS_Run=1` | 3 | 3 × `sched_setattr`, all return 0 |

Host: WSL2 `6.18.58.1-…`, container `--privileged`, `CapEff=000001ffffffffff`,
affinity `0-7`, 8 logical CPUs. Binary SHA-256 and full provenance:
[provenance.txt](results/worker-syscall-evidence/provenance.txt).

## 2. Finding — one `SCHED_DEADLINE` request per worker, unconditionally

The call count equals the worker-thread count exactly (0 / 2 / 3). Each worker
thread, on its own first scheduling step, issues:

```
sched_setattr(0,
  {size=48, sched_policy=SCHED_DEADLINE, sched_flags=0, sched_nice=0,
   sched_priority=0, sched_runtime=<R>, sched_deadline=<D>, sched_period=<D>},
  0) = 0
```

`strace` 4.21 decodes the raw syscall `__NR_sched_setattr` (314) as the named
call; the runtime itself calls it through bare `syscall()` (see
`sched.h:82-86` in the LLVM pass), which is why an earlier grep for a literal
`syscall(314` found nothing while the named form was present all along.
Full entries:
[sched-setattr-entries.txt](results/worker-syscall-evidence/sched-setattr-entries.txt);
per-worker timelines (thread birth → `gettid` poll → `sched_setattr` → next
step): [timelines/worker-timelines.txt](results/worker-syscall-evidence/timelines/worker-timelines.txt).

This is the mechanism the paper relies on: worker threads run under real
deadline scheduling, so a `sched_yield()` from one yields deterministically to
the deadline-ordered peer rather than to whatever CFS picks.

### What was **not** found (correcting two source-level predictions)

1. **No `sched_getattr` read-back** (0 occurrences). The runtime never reads the
   policy back; the `= 0` return value is the only success signal. The earlier
   "read-back policy" item is therefore answered as: it does not happen.
2. **The parameter values are runtime-calibrated, not the source defaults.** The
   pass declares `DBDSruntime = 1000*1000` and calls
   `set_sched_dl(DBDSruntime*1000, DBDSruntime*1000*10, …)`, which would predict
   `runtime=1e9, deadline=period=1e10`. Actual captures were
   `runtime=4,945,020, deadline=period=82,417,000` (scenarios B/C) and
   `runtime=236,150, deadline=period=4,723,000` in an earlier batch — the value
   is overwritten from shared memory (`DBDSruntime = si->time`, the dry-run
   calibration), so it is not reproducible as a fixed number. What *is* stable:
   `deadline == period`, and `deadline` an integer multiple of `runtime` (ratios
   16.67× and 20× in the two batches captured). The ratio is likewise
   calibration-dependent. Do not quote a fixed deadline/period figure from this
   artifact.

### Why this gap persisted

The worker's "wait for my turn" loop
(`while(get_tid_to_run() == 0);`) is a **spin on shared memory**, not a
blocking syscall — it produces no `futex`/`wait`. A scheduler-level trace of the
interesting coordination therefore shows only `gettid` polling around the single
`sched_setattr`, which is easy to mistake for "nothing happened". The yield loop
(`DBDSFunction.cpp:325-329`) fires `sched_yield` a number of times read from the
shared-memory `kpYield` array; under manual (un-driven) runs that array holds
stale or zero values, so the observed `sched_yield` counts (50 / 48 / 0 across
A / B / C) reflect shared-memory state, **not** a per-scenario property. Yield
counts are deliberately not treated as a finding here.

## 3. Scope and Outstanding Work

- Captured on manually-invoked runs, not inside a full `run_PDS.py` loop (which
  would produce tens of thousands of traces). The `sched_setattr` mechanism is
  per-thread-creation and fires identically in a loop; what a loop adds is the
  `sched_yield` sequencing driven by freshly written `kpYield` values.
- Tracing under a live driver (per-schedule policy re-application, if any) was
  not done; nothing in the code suggests a re-apply, and the single
  request-per-thread pattern is consistent with that.

## 4. Verification

```bash
cd docs/results/worker-syscall-evidence && sha256sum -c SHA256SUMS
```

Trimed traces and the collection script
(`collect_worker_evidence.sh`) are included; rerunning it needs `strace`
installed in the container.
