# 第二周 doubleFree 证据审计与补采说明

## 说明

- 日期：2026-11-14（Asia/Shanghai）；归属：第二周证据整理。
- 材料：本项目已提交的环境、构建/探索、回放日志；官方固定提交源码。
- 状态：完整独立复现仍待补证；本次仅核对已有文件，未访问目标 WSL2 或重跑 PERIOD。
- 本文命令状态：**待组员在原 WSL2/容器执行**。新补采证据不得回填为 11 月 7 日的历史执行记录。

## 1. 结项判断

**第二周“doubleFree 功能运行与 ASan 回放”已完成；按完整可复现性标准，暂不能结项。** 缺少原始错误调度文件、命令及退出码、镜像原始身份记录、源码/二进制身份、当前内核调度实测证据。下面给出补齐方式，不要求改动 PERIOD 核心算法或升级已跑通环境。

若历史退出码已经丢失，必须保留 UNKNOWN；用一轮完整标记为“第二周补采”的构建、探索和回放建立新的可复现证据链即可。若历史调度文件也丢失，明确标注 LOST，不可从控制台文本重建后冒充原件。历史证据遗失不等于程序不能运行，但需要新证据才能完成验收。

## 2. 现有证据及缺口

| 项目 | 可核对的现有证据 | 尚缺 / 处理 |
| --- | --- | --- |
| 环境 | `environment.txt`：2026-11-07 UTC、Ubuntu 18.04.5、x86_64、16 CPU、WSL2 6.18.33.1、Clang 10、GCC 7.5、Python 2.7/3.6、源码 HEAD | 当前容器/镜像 inspect、启动方式、调度权限、affinity/cpuset；旧文档 digest 尚无原始输出 |
| 构建 | `doubleFree-smoke.log` 第 2–48 行记录 clean、bitcode、静态分析、插桩和 ASan 链接 | 顶层调用、退出码、起止时间、最终文件摘要；不能把提前打印的 `Everything's fine!` 当验收 |
| 探索命令 | 同日志第 55–57 行证明 `-y -d 3 ./df`，`bugDepth: 3` | 外层完整命令和退出码；未显示的参数不能当作历史显式设置 |
| 探索结果 | 第 78–105 行：6 次、首次第 3 次、错误 4 次、超时 0 次 | 原始 Errors 文件和各文件摘要；保留错误 stderr |
| 运行时间 | 驱动打印 Total Time `00:00:00.34745` | 只是该驱动内部时间字段，不能当构建时间或论文性能比较 |
| 回放 | `doubleFree-replay.log` 第 30–32 行给出 `-r out_df_1/Errors/000001_0000003_double-free ./df`；第 2、28 行为 ASan double-free | 输入文件原件、输入摘要、同一二进制身份、完整命令和外层退出码 |
| 源码版本 | `environment.txt` 的 HEAD 为 `b6f72a7…` | 工作树状态、tracked diff、预编译对象和工具摘要；见[版本核对](official-code-analysis.md#version-comparison) |
| 调度 | 示例成功、日志未显示调度系统调用错误，是间接证据 | 当前同容器 syscall 成功/策略读回、实际 PERIOD 路径；见[调度能力补证](#deadline-check) |

### 已观察到的 6 个控制台调度

| test | period 列表（控制台原文） | 日志判断 | 日志中引用的错误文件 |
| --- | --- | --- | --- |
| 0001 | `[[0, 0], [1, 1]]` | 未报告错误 | 无 |
| 0002 | `[[1, 1], [0, 0]]` | 未报告错误 | 无 |
| 0003 | `[[0], [1, 1], [0]]` | double-free | `000001_0000003_double-free` |
| 0004 | `[[1], [0, 0], [1]]` | double-free | `000002_0000004_double-free` |
| 0005 | `[[0], [1], [0], [1]]` | double-free | `000003_0000005_double-free` |
| 0006 | `[[1], [0], [1], [0]]` | double-free | `000004_0000006_double-free` |

四个文件位于当时的 `out_df_1/Errors/`；目前只存在路径引用，不存在本仓库中的文件实体。本仓库 `.gitignore` 会排除 `out_*/`、`ConConfig.*` 等生成物；复制小型证据时使用下文的 `raw-output/`、`instrumentation-config.txt`，并检查 `git check-ignore`，不需要放宽整个仓库的忽略规则。

**控制台 period 列表不是回放文件格式。** 驱动传给 `record_error_message` 的是转换后的逐线程 yield pattern，文件第一行写该 pattern，后面写 stderr；回放则将该行当成逐线程关键点的 yield 数据。因此只能保留实际生成的原件，不能将本表的列表直接写入回放文件。[驱动记录与回放源码](https://github.com/wcventure/PERIOD/blob/b6f72a7b06d01ffa7114b640312873ec2578a5ea/tool/DBDS/run_PDS.py)

### 退出码的证据边界

| 对象 | 当前能说什么 |
| --- | --- |
| 历史 build / 探索驱动 / 回放驱动 shell 退出码 | 三者均 UNKNOWN，日志未记录，不能从后续成功反推 0 |
| 探索中的目标进程状态 | 日志记录状态集合 `[0, -6]`；Python 子进程 `-6` 表示被 SIGABRT 终止 |
| 历史回放中的目标进程 | ASan 明确报告 double-free 和 ABORTING；其精确 returncode 未单独记录 |
| 新补采的外层退出码 | 捕获脚本逐命令写 `exit-code.txt`；若用 timeout，记录的是 timeout 包装后的状态 |
| 新补采的回放目标退出码 | 上游回放 `communicate()` 后直接 `sys.exit()`，未传播目标 returncode；外层 0 不能代表目标正常退出。若需精确目标退出状态，用下文 strace 保存 |

## 3. 补采前：保存宿主与容器身份

在 **WSL2 启动 Podman 的原用户会话**执行；先确认目标容器名称。`REPL` 必须指向本项目实际路径，本项目脚本需已同步到该机器。下面是 Bash 命令；不要在启用 `set -e` 的会话一次性盲跑全部步骤，应逐步检查结果。

```bash
REPL=/absolute/path/to/cs340-period-replication
PERIOD_CONTAINER=replace-with-actual-container-name
HOST_EVIDENCE=$(mktemp -d "$REPL/docs/results/week2-host-XXXXXXXX")
CAPTURE="$REPL/scripts/capture_period_command.sh"

bash "$CAPTURE" "$HOST_EVIDENCE/podman-version" -- podman version
bash "$CAPTURE" "$HOST_EVIDENCE/container-inspect" -- podman inspect "$PERIOD_CONTAINER"
# 上一条必须成功且 console.log 是有效 JSON，再读取镜像 ID。
image_id=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[0]["Image"])' \
  "$HOST_EVIDENCE/container-inspect/console.log")
bash "$CAPTURE" "$HOST_EVIDENCE/image-inspect" -- podman image inspect "$image_id"
```

同时附上当时实际使用的 `podman run/create` 命令（若历史记录不存在，标 UNKNOWN，保存 inspect，并在重建容器时记录新命令）。保存 Windows 的 `wsl --version`、`wsl --status`、`wsl -l -v` 输出；不要从容器 hostname 猜测容器名。容器 inspect 至少保留镜像 ID、privileged、capabilities、seccomp、IPC 模式和资源限制。发布前检查 inspect 中的挂载路径或自定义环境变量是否需要脱敏；保留本地原件。

## 4. 原容器：先归档，后决定是否重建

在**没有其他 PERIOD 任务运行**的原容器执行。本项目必须能被容器访问（挂载或复制均可），`EVIDENCE` 必须在官方 PERIOD 树以外。保持该容器原有调度权限配置。

```bash
export REPL=/absolute/path/to/cs340-period-replication
export ROOT_DIR=/workdir/PERIOD
export PATH="$ROOT_DIR/clang+llvm/bin:$ROOT_DIR/tool/SVF/Release-build/bin:$PATH"
export LD_LIBRARY_PATH="$ROOT_DIR/clang+llvm/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export EVIDENCE=$(mktemp -d "$REPL/docs/results/week2-supplement-XXXXXXXX")
CAPTURE="$REPL/scripts/capture_period_command.sh"
cd "$ROOT_DIR"

bash "$CAPTURE" "$EVIDENCE/source-head" -- git rev-parse HEAD
bash "$CAPTURE" "$EVIDENCE/source-status" -- git status --short --untracked-files=all
bash "$CAPTURE" "$EVIDENCE/source-diff" -- git diff --no-ext-diff HEAD -- tool test evaluation Dockerfile
bash "$CAPTURE" "$EVIDENCE/source-tree" -- git ls-tree HEAD tool test evaluation Dockerfile
bash "$CAPTURE" "$EVIDENCE/environment-current" -- bash "$REPL/scripts/check_environment.sh"

# 在任何 build/clean 前，完整备份原示例目录。
bash "$CAPTURE" "$EVIDENCE/archive-original" -- \
  tar -cf "$EVIDENCE/prebuild-originals.tar" -C "$ROOT_DIR/test" doubleFree
bash "$CAPTURE" "$EVIDENCE/archive-original-list" -- \
  tar -tf "$EVIDENCE/prebuild-originals.tar"
```

`source-head` 应为 `b6f72a7b06d01ffa7114b640312873ec2578a5ea`；不同则原样记录，不要为了符合文字直接 checkout 或清空工作区。`source-diff` 必须检查有无核心代码本地修改。环境脚本打印的 `Analysis reference` 仅指第一周分析参考，不能替代 `source-head`。检查 tar 清单确实包含原有 `df` 和 `out_df_*`（若原本存在）；归档失败时先解决保存问题，**不要继续构建**：官方 `build.sh` 会调用 `cleanDIR.sh` 删除 `out_*`、配置和可执行文件。[官方构建](https://github.com/wcventure/PERIOD/blob/b6f72a7b06d01ffa7114b640312873ec2578a5ea/test/doubleFree/build.sh) · [清理脚本](https://github.com/wcventure/PERIOD/blob/b6f72a7b06d01ffa7114b640312873ec2578a5ea/test/doubleFree/cleanDIR.sh)

将旧输出另外复制为便于审核的小型文件，并保存构建对象身份：

```bash
mkdir "$EVIDENCE/historical-output"
found=0
for d in "$ROOT_DIR"/test/doubleFree/out_df_*; do
  [ -d "$d" ] || continue
  found=1
  saved="$EVIDENCE/historical-output/run-${d##*_}"
  mkdir "$saved" && cp -a "$d/." "$saved/" || break
done
printf 'historical_output_found=%s\n' "$found" > "$EVIDENCE/historical-output-status.txt"

bash "$CAPTURE" "$EVIDENCE/prebuild-hashes" -- sha256sum \
  "$ROOT_DIR/test/doubleFree/df.c" \
  "$ROOT_DIR/test/doubleFree/df" \
  "$ROOT_DIR/test/doubleFree/ConConfig.df" \
  "$ROOT_DIR/tool/DBDS/run_PDS.py" \
  "$ROOT_DIR/tool/staticAnalysis/DBDS-INSTRU/DBDSFunction.o" \
  "$ROOT_DIR/tool/staticAnalysis/DBDS-INSTRU/dbds-clang-fast" \
  "$ROOT_DIR/tool/staticAnalysis/DBDS-INSTRU/dbds-llvm-pass.so"
```

若文件缺失，保留 sha256sum 的错误与非零状态；不要填推算值。先尝试用历史错误文件和**尚未重建的原二进制**回放。`ERROR_FILE` 必须人工选取实际存在的原件，例如已归档的 `historical-output/run-1/Errors/000001_0000003_double-free`；文件不存在就标为缺失，转到新补采流程。

```bash
cd "$ROOT_DIR/test/doubleFree"
ERROR_FILE="$EVIDENCE/historical-output/run-1/Errors/000001_0000003_double-free"
test -f "$ERROR_FILE" && \
  bash "$CAPTURE" "$EVIDENCE/historical-replay" -- \
    timeout --signal=TERM --kill-after=10s 60s \
    python3 -u "$ROOT_DIR/tool/DBDS/run_PDS.py" -r "$ERROR_FILE" ./df
```

<a id="deadline-check"></a>

## 5. 当前 deadline 调度能力补证

示例成功是调度路径可工作的间接证据；`PREEMPT_DYNAMIC` 不能单独证明线程已使用 SCHED_DEADLINE。本节命令仍待执行。先按第 3 节保存容器 inspect，再在原容器中、与驱动启动目标相同的 sudo 权限上下文保存权限、CPU affinity 和 cgroup 记录，并运行独立探针：

```bash
bash "$CAPTURE" "$EVIDENCE/scheduling-context" -- sudo python3 -c '
import os
print("uid/euid:", os.getuid(), os.geteuid())
print("sched_getaffinity:", sorted(os.sched_getaffinity(0)))
for path in ("/proc/self/status", "/proc/self/cgroup",
             "/proc/self/uid_map", "/proc/self/gid_map"):
    print("\n== {} ==".format(path))
    with open(path) as source:
        print(source.read(), end="")
'

bash "$CAPTURE" "$EVIDENCE/deadline-probe" -- \
  sudo python3 "$REPL/scripts/probe_period_deadline.py"
```

探针仅适用于 Linux x86_64，在一个有 5 秒超时的短命子进程中申请、读回并恢复调度策略。默认 runtime 为 `485500 ns`、deadline/period 为 `9710000 ns`，由历史 `Runtime: 9710`、2 个线程、16 个 CPU 及上游公式推导，**不是当日系统调用观测值**，也不代表新运行的实际参数。退出码 `0` 表示此次单任务通过，`1` 表示失败，`77` 表示主机不适用，`124` 表示探针超时。该探针尚未在目标 Linux 上实测。

验收要求为 `sched_setattr` 成功、`sched_getattr` 成功且读回 policy=6、参数匹配、yield 返回。`PASS_SINGLE_TASK` 仅证明该任务申请成功；还需实际 PERIOD 调用链证据。若已装 strace，可在第 6 节的新错误回放中一并保存。若探针失败，保留 errno 和上下文，先定位权限、CPU 范围或准入问题，不计作目标程序缺陷。

## 6. 一轮新的完整补采：构建、探索、回放

以下仅在旧文件已备份、身份已记录、调度检查通过后执行。源码/权限异常应先解决并记录；不自动改算法。建议在专用容器中操作，避免固定 System V IPC key `1111` 被另一个 PERIOD 任务覆盖。

```bash
cd "$ROOT_DIR/test/doubleFree"
bash "$CAPTURE" "$EVIDENCE/build" -- \
  timeout --signal=TERM --kill-after=10s 300s bash ./build.sh
# 必须检查 build/exit-code.txt = 0，且 df、ConConfig.df 存在后再继续。

bash "$CAPTURE" "$EVIDENCE/explore" -- \
  timeout --signal=TERM --kill-after=10s 300s \
  python3 -u "$ROOT_DIR/tool/DBDS/run_PDS.py" -y -d 3 -t 5 ./df

# 本轮 clean 后、无并发任务时应新建 out_df_1；仍应以实际输出为准。
NEW_OUTPUT="$ROOT_DIR/test/doubleFree/out_df_1"
test -d "$NEW_OUTPUT/Errors" && \
  bash "$CAPTURE" "$EVIDENCE/archive-new-output" -- \
    cp -a "$NEW_OUTPUT" "$EVIDENCE/raw-output"
# archive-new-output 必须成功；raw-output/Errors 保留原件和 stderr。

cp -p ./ConConfig.df "$EVIDENCE/instrumentation-config.txt"
bash "$CAPTURE" "$EVIDENCE/postbuild-hashes" -- sha256sum \
  ./df ./df.c ./ConConfig.df ./mempair.df.npz \
  "$ROOT_DIR/tool/staticAnalysis/DBDS-INSTRU/DBDSFunction.o" \
  "$ROOT_DIR/tool/staticAnalysis/DBDS-INSTRU/dbds-clang-fast" \
  "$ROOT_DIR/tool/staticAnalysis/DBDS-INSTRU/dbds-llvm-pass.so"

ERROR_FILE="$EVIDENCE/raw-output/Errors/000001_0000003_double-free"
test -f "$ERROR_FILE" && \
  bash "$CAPTURE" "$EVIDENCE/replay" -- \
    timeout --signal=TERM --kill-after=10s 60s \
    python3 -u "$ROOT_DIR/tool/DBDS/run_PDS.py" -r "$ERROR_FILE" ./df
```

上面的错误文件名是历史参考；如果新运行生成不同文件名，必须选择新运行**实际生成**且含 double-free 报告的文件。每个 step 目录保存 `command.txt`（cwd、命令、UTC 起止）、`console.log`（完整 stdout/stderr）、`exit-code.txt`。同名 step 已存在时脚本拒绝覆盖。单次子进程超时显式设为 5 秒；外部 300/60 秒为本组补采保护条件，不是已知历史命令。

外层 timeout=124 或被 kill 时，保留失败记录。驱动为部分子进程另建进程组，timeout 不保证清掉所有后代；停止该专用容器并确认清理后，再创建新容器进行新的人工决定的补采，不要在可能残留 IPC/进程的环境中自动重试。

若已安装 strace，补一次不用于计时的实际运行时跟踪，同时保留目标退出/信号记录：

```bash
test -f "$ERROR_FILE" && \
  bash "$CAPTURE" "$EVIDENCE/replay-trace" -- \
    timeout --signal=TERM --kill-after=10s 60s \
    sudo strace -f -o "$EVIDENCE/replay-syscalls.log" \
      -e trace=sched_setattr,sched_getattr,sched_yield,exit,exit_group \
      python3 -u "$ROOT_DIR/tool/DBDS/run_PDS.py" -r "$ERROR_FILE" ./df
```

检查工作线程 `sched_setattr(...SCHED_DEADLINE...) = 0`，有 yield，回放仍有 ASan double-free；trace 中应能定位目标进程的 SIGABRT/退出状态。运行时本身不调用 getattr，读回由探针提供。若 strace 不可用或被阻止，应保存原因并使用等价系统调用取证方式，不能声称已完成实际路径观察。跟踪会影响时间，不把该次时间用于性能结论。

## 7. 封存、交付与结项条件

```bash
# 全部命令结束后在证据根目录封存；之后修改文件需重新生成清单。
cd "$EVIDENCE"
find . -type f ! -name SHA256SUMS -print0 | sort -z | \
  xargs -0 sha256sum > SHA256SUMS
sha256sum -c SHA256SUMS
```

提交前检查小型证据的忽略状态：

```bash
cd "$REPL"
git check-ignore -v "$EVIDENCE/raw-output/Errors/000001_0000003_double-free"
git status --short --untracked-files=all
```

`git check-ignore` 返回 1 且无输出表示该路径未被忽略，不是失败证据。交付时保留完整本地证据包；仓库可收录命令/日志/退出码、Errors/Timeouts 原件、配置文本及摘要。`prebuild-originals.tar` 和二进制放本地归档；它们被忽略属于预期行为。不要自动 Commit/Push。

完成以下验收后，第二周可结项：

1. 环境、镜像、容器权限和源码/对象身份均有原始记录；历史无法恢复项明确 UNKNOWN/LOST。
2. 至少一轮完整补采具有构建、探索、回放的命令、cwd、起止时间、完整输出和外层退出码。
3. 原始错误调度文件与 SHA-256 可交给另一组员；该组员能够按同样构建链回放得到 ASan double-free，并记录使用的配置和二进制摘要。
4. 探索日志可核对总数、首次错误、错误交错数、超时；6 / 3 / 4 / 0 是当前参考，若不同须解释并原样保存，不能修日志凑数。
5. 同容器 deadline 探针及实际 PERIOD 路径证据通过；明确只完成 doubleFree 范围验证，尚未证明所有正式基准的负载都可准入。

本说明仅整理现有证据和待执行步骤，不产生新实验数据。正式基准实验另行记录。
