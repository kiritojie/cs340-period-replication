# Reproduction Commands and Offline Review

Reading and verifying existing evidence requires Python and this checkout.
Executing experiments additionally requires the original x86_64 Ubuntu/WSL2
environment, fixed Podman image/container, permissions, pinned source/products
and unchanged runtime identities. No experiment is needed for grading or report
integration. The final protocol is [table2-rq1-protocol.md](../table2-rq1-protocol.md)
and [the exact JSON](../../config/table2-rq1-protocol.json).

## Restore evidence without overwriting

The final tables/plots need no extraction. For deep raw review or the frozen-pilot
prerequisite, run this from the repository root in PowerShell. It verifies both
packages, validates relative paths, checks *all* existing destination files first,
and then writes only missing files. It never overwrites different bytes, runs an
executable, changes privileges or launches a container. The expanded historical
trees are ignored for Git.

~~~powershell
@'
from pathlib import Path, PurePosixPath
import hashlib, json, zipfile
root = Path.cwd().resolve()
payload = {}
def add(name, data):
    parts = PurePosixPath(name).parts
    assert parts and parts[0] == "docs"
    assert not PurePosixPath(name).is_absolute()
    assert all(p not in ("", ".", "..") and ":" not in p and "\\" not in p for p in parts)
    if name in payload:
        assert payload[name] == data, name
    payload[name] = data
packages = {
    "table2-rq1-evidence-20261125.zip": "8e0540ed36a3a9b2e5b38158fed42280c724aeb30ef4d2b57b7aa262b7c54fec",
    "table2-rq1-history-20261125.zip": "5ffce594291b2cbcc3bce0ff1ae1117ca1bc2cf87c135cc6bf709b7d9618da0d",
}
for filename, expected in packages.items():
    archive = root / "docs/evidence" / filename
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        if filename == "table2-rq1-evidence-20261125.zip":
            for line in z.read("PACKAGE_SHA256SUMS").decode("utf-8").splitlines():
                checksum, name = line.split("  ", 1)
                data = z.read(name)
                assert hashlib.sha256(data).hexdigest() == checksum, name
                add(name, data)
        else:
            for item in json.loads(z.read("ARCHIVE_MANIFEST.json"))["members"]:
                data = z.read(item["member"])
                assert len(data) == item["bytes"]
                assert hashlib.sha256(data).hexdigest() == item["sha256"]
                if item["member"].startswith("repository/"):
                    add(item["member"][len("repository/"):], data)
for name, data in payload.items():
    target = root.joinpath(*PurePosixPath(name).parts)
    assert root in target.resolve().parents and not target.is_symlink(), name
    if target.exists():
        assert target.is_file() and target.read_bytes() == data, name
written = 0
for name, data in payload.items():
    target = root.joinpath(*PurePosixPath(name).parts)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
        written += 1
print("PASS: verified", len(payload), "original files; restored", written)
'@ | python -X utf8 -B -
~~~

Earlier editable reports and Git rules under snapshots/before-readability/ are
deliberately not restored over current files. Inspect those snapshots in the ZIP
or extract them to a separate directory.

## Verify restored evidence and the frozen prerequisite

These calls perform only file/JSON/hash checks:
~~~powershell
@'
from pathlib import Path
import sys
sys.path.insert(0, "orchestration")
sys.path.insert(0, "scripts")
from rq1_integrity import verify_tree
from table2_rq1 import verify_frozen_pilot
root = Path.cwd()
paths = [
    "docs/results/table2-rq1-recovered-session-20261124T180224Z-210n7nbf",
    "docs/results/table2-rq1-batch-20261124T185640Z-re9h7z8a",
    "docs/frozen/table2-rq1-reorder3-pilot-20261124",
    "docs/frozen/table2-rq1-reorder3-formal-20261124",
    "docs/frozen/table2-rq1-twelve-formal-20261124",
]
for name in paths:
    result = verify_tree(root / name)
    print(result["status"], result["manifests"], result["entries"], name)
_, pilot = verify_frozen_pilot(root)
print("Frozen-pilot prerequisite:", pilot["status"])
'@ | python -X utf8 -B -
~~~

The cleanup exercised archive restoration into an isolated review directory,
then these read-only checks. See [readability-audit.json](readability-audit.json).
This verifies portable evidence/checkpoint prerequisites, not a new live
container run or a new scientific experiment.

## Historical execution command

The completed recovery/continuation used:
~~~bash
python3 -B /mnt/e/cs340-period-replication/orchestration/table2_rq1_batch.py --recover-from /mnt/e/cs340-period-replication/docs/results/table2-rq1-batch-20261124T164754Z-zphvi2gi
~~~
This is an execution command, not a grading/cleanup step. Historical resume also
depends on the original host/container state and retained earlier local records.

## A separately authorized fresh cohort

After restoring prerequisites above and confirming the original measured Linux
environment and fixed image/products, the existing entry point is:
~~~bash
cd /mnt/e/cs340-period-replication
sudo -v
python3 -B orchestration/table2_rq1_batch.py --prepare
~~~
The driver checks source/runtime/product identities, permissions and fresh
evidence paths before execution; no gate is relaxed here. It fixes depth 3,
budget 10000, target timeout 5 s, formal round timeout 3600 s and CPU affinity
0-31. A three-round Parallel/Serial cohort covers four variants (24 rounds).
Native complete argv/exit/stderr and official build steps remain in the raw
canonical session. The old 600-second pilot watchdog is not the formal timeout.

## Offline report regeneration

The unchanged report writer does not launch a target:
~~~powershell
python -X utf8 -B scripts/table2_rq1_report.py --session docs/results/table2-rq1-recovered-session-20261124T180224Z-210n7nbf --output docs/results/table2-rq1-offline-review-new
~~~
The output directory must be new. This exact writer was exercised on evidence
restored into an isolated Windows directory: all 24 formal observations and all
240 group fields agreed (maximum floating-point difference 1.12e-16). Raw Linux
provenance remains unchanged; regenerated run_dir labels refer to the restored
location and are not byte-for-byte copies of the original CSV.

Generate the five charts into another new directory:
~~~powershell
python -X utf8 -B -c "import sys; from pathlib import Path; sys.path.insert(0,'orchestration'); from rq1_charts import write_charts; print(write_charts(Path('docs/results/table2-rq1-offline-review-new'), Path('docs/results/table2-rq1-offline-charts-new')))"
~~~
The existing chart renderer and recomputed groups reproduced all five SVG texts
after ordinary newline decoding. No pixel-rendering or live-execution claim is
made. Generated review directories follow the existing ignore rules.
