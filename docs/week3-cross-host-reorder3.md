# Cross-host Independent Reproduction of CS.reorder_3_bad

**22 November 2026 (China Standard Time)**

This record documents an independent rebuild and re-execution of the Table 2
benchmark `CS.reorder_3_bad` on a second machine, complementing the
[Week 3 report](week3-independent-reproduction.md). It addresses three items
listed as outstanding in that report's Section 7: an independent build and
execution by another member, per-run binary and launch-configuration identity,
and byte-level confirmation of the archived error interleavings.

## 1. Objective and Scope

Re-run the official artifact pipeline (clean build, static analysis,
instrumentation, depth-3 exploration, three invocations) on a different host,
then compare schedule counts and saved error-schedule files against the
Week 3 archive already in this repository. No other Table 2 benchmark and no
performance comparison is in scope.

## 2. Host and Container Identity

| Item | Value | Evidence |
| --- | --- | --- |
| Host | ASUS ZenBook UX481FL, Intel Core i7-10510U (4 physical cores, 8 logical CPUs, homogeneous topology), 16 GB RAM, Windows 11 Home China | [Preflight](results/table2-reorder3-crosshost-20261122/environment-x86_64-2026-11-22.txt) |
| CPU capacity view | `/sys/devices/system/cpu/cpu*/cpu_capacity` reports the single value `1024` for all CPUs (no heterogeneous-capacity topology; see Section 6) | Preflight |
| Execution layer | WSL2 kernel `6.18.58.1-microsoft-standard-WSL2`, Docker Desktop engine 29.9.2 (runc), container launched `--privileged` | [exec-env](results/table2-reorder3-crosshost-20261122/exec-env.txt) |
| Container userland | Ubuntu 18.04.5 LTS, amd64 | Preflight |
| Image provenance | Pulled `wcventure/period:stable` on 22 Nov. Registry digest `sha256:8f47d8b9148f2db579627842026e722d0f205ddeab13e70ee41a8df3dbd59fbc`, character-identical to the Docker-v2 manifest digest recorded for the 15 November image in the Week 3 report (Section 2 there). The numeric image ID differs between engines: the Week 3 records list `fcd0a751293a…` and `dfd654d5ebf1…`, while the engine used here (Docker 29.9.2) reports `8f47d8b9148f…`. The RootFS DiffID sequence was not re-extracted here, so cross-host image identity rests on the matching manifest digest only. | Preflight; Week 3 report Section 2 |
| PERIOD source | Worktree HEAD `b6f72a7b06d01ffa7114b640312873ec2578a5ea`, clean (0 dirty entries) — same commit the Week 3 report recorded for the image | Preflight |
| Toolchain | Clang/LLVM 10.0.0 (image-bundled), GCC/G++ 7.5.0, Python 3.6.9, GNU Make 4.1, CMake 3.10.2 | Preflight |
| Deadline scheduling | `chrt -d` (SCHED_DEADLINE, 10 ms/20 ms/20 ms) exit 0 inside the container before any experiment | Preflight |

## 3. Independent Build

The official `build.sh` was run from a clean target directory; the image
shipped no prebuilt products for this benchmark (verified absent in the
preflight inventory). Build exit code 0, elapsed about 3 seconds.

| Artifact | SHA-256 |
| --- | --- |
| `reorder_3_bad` (instrumented) | `ed2d13809b87a00eaaba76ac0f1faf4871a489a0960993e5963dc89b4bb13db9` |
| `reorder_3_bad.bc` | `4405d88eafa56cce1ad469c55e95cb4a98a87b6fa9b8610f2021078f5ecffc5d` |
| `ConConfig.reorder_3_bad` | `0ed49729a85b862b9a918c62f3826f3c56b89ec825ae3fe35a28f21f253d7d4d` |

The instrumentation pass reported key points at `reorder_bad.c:71`, `:72` and
`:78` — the same three locations the Week 3 report recorded — and the saved
`ConConfig` file lists exactly those three lines. DWARF metadata in the
instrumented binary identifies `clang version 10.0.0`
([build records](results/table2-reorder3-crosshost-20261122/build-records/)).

## 4. Runs and Per-run Provenance

Each invocation reused the Section 3 build and recorded: the exact command,
separated stdout and stderr (the Week 3 archive kept a merged console only),
exit code, UTC start/finish, a nanosecond-resolution external wall interval,
and the container-wide launch configuration (CPU affinity mask `0-7`, no cgroup
CPU quota or memory limit, `CapEff=000001ffffffffff` under `--privileged`, seccomp mode
2 with one filter). The binary hash and the key-point list were captured once
for the batch in `binary-identity.txt` and apply to all three runs, which
reused that single build.

```bash
python3 -u /workdir/PERIOD/tool/DBDS/run_PDS.py -y -d 3 ./reorder_3_bad
```

Output directories `out_reorder_3_bad_*` were removed before each run so the
three invocations start from identical state; the driver's incrementally named
output directories were archived per run.

## 5. Results

### Counts vs. paper and vs. the Week 3 archive

| Metric | Paper Table 2 | Week 3 (Run 01–03) | This host (Run 01–03) |
| --- | ---: | ---: | ---: |
| First error schedule | 6 | 6 / 6 / 6 | 6 / 6 / 6 |
| Total schedules | 27 | 27 / 27 / 27 | 27 / 27 / 27 |
| Error schedules | 6 | 6 / 6 / 6 | 6 / 6 / 6 |
| Timeouts | — | 0 / 0 / 0 | 0 / 0 / 0 |
| Worker threads (excl. main) | 3 | 3 / 3 / 3 | 3 / 3 / 3 |

### Saved error schedules — byte-level agreement

The six files saved per run (`000001_0000006` … `000006_0000025`, each the
yield matrix plus the `reorder_bad.c:80` assertion text) were unpacked from
both this host's runs and the Week 3 archive in
[`table2-reorder3`](results/table2-reorder3/). All six files are byte-identical
between the two hosts and identical across all six run directories; the
concatenated six-file MD5 is `73eea7143a72…` in every case. The six files are
also stored as plain text under each
[`run-*/error-schedules/`](results/table2-reorder3-crosshost-20261122/run-01-depth3/error-schedules/)
directory so the comparison needs no unpacking.

### Timing (context only, not a comparison target)

| Metric | This host Run 01/02/03 | Week 3 Run 01/02/03 |
| --- | --- | --- |
| PERIOD internal total (s) | 1.434 / 0.754 / 1.121 | 1.138 / 1.223 / 0.998 |
| External wall interval | 2.169 / 1.139 / 1.630 (ns resolution) | 11 / 11 / 7 (whole-second timestamps, boundaries unresolved) |
| Driver `Runtime:` calibration | 3086 / 1613 / 7580 | 8430 / 9280 / 5370 |

Different CPUs, different execution stacks; the calibration value is a scaled
dry-run duration and jitters on both hosts. Per the paper's own note, this
study is not deterministic; only the schedule counts are treated as
comparable.

## 6. Heterogeneity Note

The Week 3 host (i9-14900HX) is a heterogeneous design whose E-cores expose
capacity below 1024; the Linux deadline scheduler's capacity-aware admission
and placement can therefore interact with `SCHED_DEADLINE` tasks there, and
that report left per-run affinity unverified. This host is homogeneous (all
`cpu_capacity` values `1024`, affinity `0-7`, no cgroup quota). The byte-level
agreement of all six error-schedule files across the two hosts shows the saved
interleavings are reproducible despite that topology difference; it does not
eliminate the Week 3 host's per-run affinity gap for other measurements.

## 7. Scope and Outstanding Work

- Three invocations per host; the paper used ten. Counts matched with zero
  variance on both hosts, but the sample size remains below the paper's.
- Syscall-level evidence for the actual PERIOD worker threads (per-TID
  `sched_attr` requests, return values, read-back policy, subsequent yields)
  is still not captured on either host; strace-level tracing is the next step.
- Table 1 (RQ2) and the remaining Table 2 benchmarks were not run here.
- The instrumented binary and image remain outside Git (repository ignore
  rules); the digests above are the cross-host linking evidence.

## 8. Verification

```bash
cd docs/results/table2-reorder3-crosshost-20261122 && sha256sum -c SHA256SUMS
```

55 entries verified. The Week 3 counterpart verifies under
`docs/results/table2-reorder3/SHA256SUMS`.

## 9. Reproduction Scripts

The three scripts used are in [`scripts/`](../scripts/):
[`crosshost_preflight.sh`](../scripts/crosshost_preflight.sh) (read-only
toolchain, source and scheduling-capability inventory),
[`crosshost_build_reorder3.sh`](../scripts/crosshost_build_reorder3.sh) (clean
build through the official `build.sh`, with artifact digests) and
[`crosshost_run_reorder3.sh`](../scripts/crosshost_run_reorder3.sh) (three
depth-3 invocations with per-run capture, output cleanup and archiving). Each
run's exact inner command is also in its `command.txt`.
