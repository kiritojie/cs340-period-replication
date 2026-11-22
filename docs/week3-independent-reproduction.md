# Week 3 · Independent Reproduction of CS.reorder_3_bad

**22 November 2026 (China Standard Time)**

## 1. Objective and Scope

The experiment tests whether the released PERIOD artifact reproduces the schedule counts for the three-worker SCTBench benchmark `CS.reorder_3_bad` in Table 2 of Wen et al. (ICSE 2022). It covers three exploration invocations of one instrumented build on one local WSL2 host. [Paper, Table 2](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf#page=9)

## 2. Experimental Environment

| Item | Archived environment and evidence |
| --- | --- |
| Host and execution layer | Windows 11, Ubuntu 22.04 on WSL2, x86-64 kernel `6.18.58.1-microsoft-standard-WSL2`, Podman `3.4.4`. The experiment archive is on the WSL ext4 filesystem. |
| CPU | The audit host reports an Intel Core i9-14900HX and 32 logical CPUs. The earlier host and container inventory recorded affinity `0–31`. Per-run affinity and cgroup limits are unverified. |
| Container userland | Ubuntu 18.04.5 LTS, amd64. The archived image tag is `docker.io/wcventure/period:stable`. |
| OCI image identity | Image ID `dfd654d5ebf18787ebff0b8cc35c61c6eda4d49852a93bb784fbe2e82727299a`. Manifest digest `sha256:c9447d44596f0cf339d394f59c51fa04b089a64b2d43aa59576e29694c7c9741`. |
| Source and toolchain | The image inventory recorded a clean PERIOD worktree at `b6f72a7b06d01ffa7114b640312873ec2578a5ea`, Clang/LLVM `10.0.0`, GCC/G++ `7.5.0`, Python `3.6.9`, GNU Make `4.1`, and CMake `3.10.2`. |
| Prebuilt tooling | The inventory recorded paths and digests for 128 prebuilt objects, archives, and shared libraries, including `DBDSFunction.o` and `dbds-llvm-pass.so`. The SVF and LLVM pass CMake caches preserve configuration fields, with empty build-type and generic compiler flags. Object-level build commands are unavailable. |

The image ID, tool versions, source status, and affinity come from the [separate preflight inventory](#preflight-and-scheduler-probe). The build backup's five tracked benchmark files match the Git blobs at both the pinned image commit and the earlier source-analysis commit `cb8deb9a176e5bb292d70d46557dd61dc0e98069`. Per-run launch details remain open as described in [Section 7](#7-scope-and-outstanding-work). [Pinned benchmark tree](https://github.com/wcventure/PERIOD/tree/b6f72a7b06d01ffa7114b640312873ec2578a5ea/evaluation/CS/reorder_3)

Archived inventories for the 15 November tool-validation image and the Week 3 OCI image record the same 12 ordered RootFS DiffIDs, visible configuration, history, and creation time. The 15 November inventory records Docker v2 manifest digest `sha256:8f47d8b9148f2db579627842026e722d0f205ddeab13e70ee41a8df3dbd59fbc`, image ID `fcd0a751293a4f6b3d567989357333b0b9bf9448b0b2f6a38580cd691069f312`, and WSL2 kernel `6.18.33.1-microsoft-standard-WSL2`. The earlier build's source worktree and build product identities remain unverified. The Week 3 inventory's source HEAD matches the 7 November environment record. [15 November evidence](results/PERIOD_doubleFree_rerun_evidence-verified.zip) · [7 November environment record](results/environment.txt)

## 3. Benchmark Configuration

The benchmark in `evaluation/CS/reorder_3` creates two setter threads and one checker thread with the default workload. Each run logged three worker threads, excluding the main thread, and per-thread key-point counts of `[2, 2, 1]`. Every saved failure records the `checkThread` assertion at `reorder_bad.c:80`, the source location embedded in the benchmark. [Official benchmark source](https://github.com/wcventure/PERIOD/blob/b6f72a7b06d01ffa7114b640312873ec2578a5ea/evaluation/CS/reorder_3/reorder_3_bad.c)

Each formal run records the following command.

```bash
python3 -u /workdir/PERIOD/tool/DBDS/run_PDS.py -y -d 3 ./reorder_3_bad
```

The target uses the default workload. Python's `-u` enables unbuffered I/O, PERIOD's `-y` skips the interactive prompt, and `-d 3` sets the maximum exploration depth to 3, consistent with the paper's SCTBench configuration. The omitted `-t` leaves the pinned driver's 5-second subprocess timeout in effect. Omitting `-f` leaves the schedule budget unset. Each run finished after 27 schedules, within the paper's 10,000-schedule budget. The paper leaves the exact per-case command and timeout unspecified. [Driver defaults and options](https://github.com/wcventure/PERIOD/blob/b6f72a7b06d01ffa7114b640312873ec2578a5ea/tool/DBDS/run_PDS.py#L172-L268) · [Timeout initialization](https://github.com/wcventure/PERIOD/blob/b6f72a7b06d01ffa7114b640312873ec2578a5ea/tool/DBDS/run_PDS.py#L28-L35) · [Paper, Section 4.1.3](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf#page=8)

## 4. Build and Schedule Verification

The archived build exited with status 0. The official `build.sh` flow cleans the target directory, compiles LLVM bitcode with `clang -g -emit-llvm -c`, uses `staticAnalysis.sh` to generate the instrumentation configuration, exports `Con_PATH`, and links the instrumented target with `dbds-clang-fast++ -g` and `-lpthread -ldl`. The build trace records instrumentation at `reorder_bad.c:71`, `:72`, and `:78`. The executable, bitcode, and configuration in the build backup match the archived SHA-256 values. The executable's DWARF metadata identifies Clang 10.0.0 for the benchmark and runtime compilation units. Each invocation reused this build and has a separate command log and raw-output archive. [Official build script](https://github.com/wcventure/PERIOD/blob/b6f72a7b06d01ffa7114b640312873ec2578a5ea/evaluation/CS/reorder_3/build.sh) · [Build log](results/table2-reorder3/build.log) · [Build checksums](results/table2-reorder3/build-artifacts.sha256)

The audit used the repository's log summarizer to check that the one-based `test` ordinals were contiguous and to reconcile the counts with the PERIOD footer. For each saved failure, the audit matched the filename and ordinal to the console's saved-file line, checked the assertion text, and recomputed the saved yield matrix from the printed schedule using PERIOD's zero-padding rule. All 18 records matched. [Log summarizer](../scripts/summarize_period_logs.py) · [Yield-pattern implementation](https://github.com/wcventure/PERIOD/blob/b6f72a7b06d01ffa7114b640312873ec2578a5ea/tool/DBDS/bp_sched.py#L138-L153) · [Error output and padding call](https://github.com/wcventure/PERIOD/blob/b6f72a7b06d01ffa7114b640312873ec2578a5ea/tool/DBDS/run_PDS.py#L636-L654)

### Depth selection and troubleshooting

The driver explores 2 through `d + 1` execution periods at exploration depth `d`. The bare invocation in the official benchmark README defaults to depth 2. The archived default-depth run (`run-01-v2`, exit code 0) logged 3 two-period schedules and 10 three-period schedules, with the first failure at schedule 6, 2 failures in total, and 0 timeouts. Its 13 schedules match the first 13 schedules in every formal run. Depth 3 added 14 four-period schedules and 4 assertion failures, giving totals of 27 schedules and 6 failures. Table 2's bug depth of 2 describes the defect. The exploration bound of 3 describes the SCTBench search. [Official benchmark README](https://github.com/wcventure/PERIOD/blob/b6f72a7b06d01ffa7114b640312873ec2578a5ea/evaluation/CS/reorder_3/README.md) · [Driver period loop](https://github.com/wcventure/PERIOD/blob/b6f72a7b06d01ffa7114b640312873ec2578a5ea/tool/DBDS/run_PDS.py#L578-L619) · [Paper, Table 2](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf#page=9)

An earlier attempt (`run-01`) exited with status 1 after container-side `sudo` reported a `setresuid` permission error during preparation. The subsequent default-depth run recorded an interactive prompt. Both records remain in the local WSL archive. The results below use the three completed noninteractive depth-3 invocations.

## 5. Experimental Results

### Paper vs. Ours

|      Metric     | Paper | Run 01 | Run 02 | Run 03 | Mean (SD) |
| ----------------| ----: | -----: | -----: | -----: | --------: |
| First error     |   6   |   6    |    6   |    6   | 6.00 (0.00) |
| Total schedules |   27  |   27   |   27   |   27   |27.00 (0.00)|
| Error schedules |   6   |   6    |    6   |    6   |6.00 (0.00)|

Each run matched the three published PERIOD schedule counts and the paper's count of 3 worker threads, excluding the main thread. **First error** gives the one-based schedule ordinal of the first assertion failure. **Error schedules** gives the number of schedules with assertion failures. [Paper, Table 2](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf#page=9)

### Experimental Measurements

| Metric | Run 01 | Run 02 | Run 03 | Mean (SD) |
| --- | ---: | ---: | ---: | ---: |
| Worker threads | 3 | 3 | 3 | — |
| Timeouts | 0 | 0 | 0 | 0.00 (0.00) |
| PERIOD internal runtime (s) | 1.13771 | 1.22326 | 0.99822 | 1.11973 (0.11359) |
| External timestamp interval (s) | 11 | 11 | 7 | 9.67 (2.31) |
| Exit code | 0 | 0 | 0 | — |

Both tables report the arithmetic mean and the sample standard deviation (SD) for `n = 3`. The SD uses divisor `n − 1`. A dash marks a field reported per run only.

The paper reports ten invocations per technique and program on an Intel Xeon Silver 4214 workstation with Ubuntu 18.04, GCC 7.5, and LLVM 10.0. The versions reported for the paper align with those of the local container userland and compilers at the stated precision. The local runs used a different CPU, a WSL2 kernel, and Podman. Table 2 gives schedule counts for this case, so the comparison is limited to those counts. [Paper, Sections 4.1.3–4.2](https://wcventure.github.io/pdf/ICSE2022_PERIOD.pdf#page=8)

### Schedule and assertion evidence

The three consoles list the same 27 schedules in the same order. All saved failures match the assertion and the six schedule ordinals below, with identical yield matrices across runs. The `Timeouts/` and `DiffResult/` directories are empty in each archive. The driver exit code records successful completion of the exploration, which includes the six target assertion failures.

| First field in error filename | Schedule ordinal | Saved yield matrix (same in all three runs) |
| --- | ---: | --- |
| `000001` | 6 | `[[0,2],[2,0],[1,0]]` |
| `000002` | 7 | `[[2,0],[0,2],[1,0]]` |
| `000003` | 19 | `[[0,2],[3,0],[1,0]]` |
| `000004` | 20 | `[[0,3],[2,0],[1,0]]` |
| `000005` | 24 | `[[2,0],[0,3],[1,0]]` |
| `000006` | 25 | `[[3,0],[0,2],[1,0]]` |

### Timing measurements

PERIOD's internal elapsed time is the `Total` column of the footer's `Time` row. The driver uses `time.time()` from initialization, before the dry run, to the final report. The header's `Runtime:` field gives the driver's scaled calibration value from the dry-run duration recorded in microseconds. The reported values are 8430, 9280, and 5370. [Timer initialization](https://github.com/wcventure/PERIOD/blob/b6f72a7b06d01ffa7114b640312873ec2578a5ea/tool/DBDS/run_PDS.py#L28-L35) · [Dry-run measurement](https://github.com/wcventure/PERIOD/blob/b6f72a7b06d01ffa7114b640312873ec2578a5ea/tool/staticAnalysis/DBDS-INSTRU/llvm-mode/DBDSFunction.cpp#L372-L378) · [Driver calibration](https://github.com/wcventure/PERIOD/blob/b6f72a7b06d01ffa7114b640312873ec2578a5ea/tool/DBDS/run_PDS.py#L350-L365) · [Footer calculation](https://github.com/wcventure/PERIOD/blob/b6f72a7b06d01ffa7114b640312873ec2578a5ea/tool/DBDS/run_PDS.py#L812-L826)

Each external interval is the difference between `started-at.txt` and `finished-at.txt` at whole-second resolution. The outer timing command and exact capture boundaries are unavailable, leaving the contributions of Python execution, container setup, and logging unresolved. The recorded UTC start and finish pairs on 22 November 2026 were 06:59:46–06:59:57, 07:01:40–07:01:51, and 07:03:05–07:03:12.

## 6. Reproducibility Evidence

The WSL originals are under `/home/yehaoming/cs340-period-lab-2026-11-21/table2-reorder3-hDVCsu4z`. The repository holds byte-identical copies of the three formal runs and selected build records. The local build backup (`reorder3-build-backup.tar.gz`, SHA-256 `a7c13037b1f3904b131107ae6e8ad9c29851e3d9977da99f94f9e5a9143b6ef5`) contains the executable and intermediate artifacts. Each original run manifest covers the console, command, and raw archive, for nine verified entries across the three runs. The repository's audit-time manifest also covers the original manifests, build records, exit codes, and timestamps. [Repository evidence manifest](results/table2-reorder3/SHA256SUMS)

| Formal run | Recorded input and console | Saved error schedules | Original SHA-256 manifest |
| --- | --- | --- | --- |
| `run-01-depth3` | [Command](results/table2-reorder3/run-01-depth3/command.txt) · [Console](results/table2-reorder3/run-01-depth3/console.log) | [Archive `_3`](results/table2-reorder3/run-01-depth3/raw-output.tar.gz) | [SHA256SUMS](results/table2-reorder3/run-01-depth3/SHA256SUMS) |
| `run-02-depth3` | [Command](results/table2-reorder3/run-02-depth3/command.txt) · [Console](results/table2-reorder3/run-02-depth3/console.log) | [Archive `_4`](results/table2-reorder3/run-02-depth3/raw-output.tar.gz) | [SHA256SUMS](results/table2-reorder3/run-02-depth3/SHA256SUMS) |
| `run-03-depth3` | [Command](results/table2-reorder3/run-03-depth3/command.txt) · [Console](results/table2-reorder3/run-03-depth3/console.log) | [Archive `_5`](results/table2-reorder3/run-03-depth3/raw-output.tar.gz) | [SHA256SUMS](results/table2-reorder3/run-03-depth3/SHA256SUMS) |

Each run directory also contains `exit-code.txt`, `started-at.txt`, and `finished-at.txt`. The following command verifies the copies from the repository root.

```bash
(cd docs/results/table2-reorder3 && sha256sum -c SHA256SUMS)
```

### Preflight and scheduler probe

These earlier records are stored locally under `/home/yehaoming/cs340-period-lab-2026-11-21`.

| Evidence | Local directory | SHA-256 of `SHA256SUMS` |
| --- | --- | --- |
| Read-only rootless inventory, exit 0 | `week3-preflight-20261122T061124Z-DJ0EBmhW/` | `46d4dc580a50f46ac39edf51caaab345466935a767f476edbfb49ed939318181` |
| First inventory, exit 125 | `week3-preflight-20261122T061052Z-v8G2JqH5/` | `2cbe54696025569975ab6a206330422aa37090ddb742ca18597c421d435f3244` |
| Restricted rootful single-task probe | `scheduler-validation/period-deadline-20261122T060516Z-ot7YNIb3/` | `64430240317f9e617a3562df5819f9b87e7a11aa4ecd360bfe45d0fb2f168c46` |

The first inventory stopped before container startup because Podman 3.4.4 rejected a Go-template field for seccomp status. The second queried the field through JSON and ran a read-only rootless container with the network disabled, all capabilities dropped, and default seccomp. Its cleanup check confirmed container removal. Both inventories' manifests verified. The successful inventory's `container.stdout.log` has SHA-256 `8bb13eb82cf93bb2151a781a3f60c2ef7581db25deb97e6f409c1d6604d8ca78`. The single-task probe log matched its manifest. The audit user could not read two other probe entries, `approved-command.sh` and `container-init.pid`.

## 7. Scope and Outstanding Work

The evidence supports numerical reproduction of the PERIOD schedule counts for this one Table 2 benchmark. Performance comparisons and the remaining Table 2 benchmarks are outside the scope of this experiment.

- **Worker scheduling.** The restricted rootful single-task probe recorded successful `sched_setattr` and `sched_getattr` calls for PID/TID `13/13`, with policy 6 (`SCHED_DEADLINE`), runtime/deadline/period of `1/10/10 ms`, and a return to policy 0. The actual PERIOD workers still need syscall evidence that maps thread creation to worker TIDs, records requested `sched_setattr` attributes, return values and errno, reads back the policy for the same TIDs, and captures subsequent `sched_yield` calls. [Earlier scheduling audit](week2-reproducibility.md#deadline-check)
- **Execution provenance.** The formal runs preserve the inner command and a merged console. Missing records include separate stdout and stderr, outer Podman and timing commands, and per-run image ID, capabilities, seccomp, IPC settings, CPU affinity, and cgroup limits. The build backup and its digest identify the shared binary. Per-run binary hashes remain outstanding.
- **Independent confirmation.** A second team member's independent rebuild and execution remain undocumented.
