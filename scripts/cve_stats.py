#!/usr/bin/env python3
"""Table 1 (CVE) 统计：只纳入完全干净的轮次，报中位数/极值，并核对论文判据。"""
import glob, os, re, statistics, subprocess, tempfile, tarfile, io
from collections import Counter

EV = "/lab/evidence"
PROGS = ["CVE-2009-3547", "CVE-2011-2183", "CVE-2013-1792", "CVE-2015-7550",
         "CVE-2016-1972", "CVE-2016-1973", "CVE-2016-7911", "CVE-2016-9806",
         "CVE-2017-15265", "CVE-2017-6346"]
ANSI = re.compile(rb"\x1b\[[0-9;]*m")


def batches():
    out = []
    for d in sorted(glob.glob(f"{EV}/cve-runs-d5-*") + glob.glob(f"{EV}/cve-rep-d5-*")):
        runs = {p: os.path.join(d, f"{p}-depth5") for p in PROGS}
        clean = True
        for p, r in runs.items():
            rc = os.path.join(r, "exit-code.txt")
            ft = os.path.join(r, "footer.txt")
            if not os.path.isfile(rc) or open(rc).read().strip() != "0":
                clean = False; break
            if not os.path.isfile(ft) or b"Total Error Interleavings" not in open(ft, "rb").read():
                clean = False; break
        if clean:
            out.append(d)
    return out


def total_schedules(run_dir):
    p = os.path.join(run_dir, "stdout.log")
    if not os.path.isfile(p):
        return None
    txt = ANSI.sub(b"", open(p, "rb").read()).decode("utf-8", "replace")
    hits = re.findall(r"^test (\d+)", txt, re.M)
    return int(hits[-1]) if hits else None


def err_inter(run_dir):
    p = os.path.join(run_dir, "footer.txt")
    if not os.path.isfile(p):
        return None
    m = re.findall(rb"Total Error Interleavings: (\d+)", open(p, "rb").read())
    return int(m[-1]) if m else None


def timeouts(run_dir):
    p = os.path.join(run_dir, "footer.txt")
    if not os.path.isfile(p):
        return None
    m = re.findall(rb"Total Timeouts Interleavings: (\d+)", open(p, "rb").read())
    return int(m[-1]) if m else None


def bug_types(run_dir):
    """返回该程序该轮的错误类型集合（来自归档内 Errors 文件名）。"""
    arc = os.path.join(run_dir, "raw-output.tar.gz")
    types = set()
    if not os.path.isfile(arc):
        return types
    with tarfile.open(arc, "r:gz") as tf:
        for m in tf.getmembers():
            if "/Errors/" in m.path and m.isfile():
                name = os.path.basename(m.path)
                parts = name.split("_", 2)
                if len(parts) == 3:
                    types.add(parts[2])
    return types


def fmt(vals):
    vals = [v for v in vals if isinstance(v, int)]
    if not vals:
        return "NA"
    return f"{statistics.median(vals):g} ({min(vals)}–{max(vals)})"


bs = batches()
print(f"纳入统计的干净轮次: {len(bs)}")
for b in bs:
    print("   ", os.path.basename(b))
print()

hdr = f"{'PROGRAM':<15} {'schedules med(min-max)':<24} {'errInter med(min-max)':<22} {'timeouts':<9} {'types/轮':<9} 类型全集"
print(hdr); print("-" * len(hdr))

per_round_bugsum = []
for p in PROGS:
    scheds, errs, tos, typesets = [], [], [], []
    for b in bs:
        r = os.path.join(b, f"{p}-depth5")
        scheds.append(total_schedules(r))
        errs.append(err_inter(r))
        tos.append(timeouts(r))
        typesets.append(bug_types(r))
    per_round_bugsum.append(typesets)
    n_types = sorted({len(t) for t in typesets})
    union = sorted(set().union(*typesets)) if typesets else []
    print(f"{p:<15} {fmt(scheds):<24} {fmt(errs):<22} "
          f"{fmt([t for t in tos if t is not None]):<9} {'/'.join(map(str,n_types)):<9} {'+'.join(union)}")

print()
print("=== 每轮合计（判据：定位 10/10，bug 类型之和 = 论文 15）===")
sums = []
for i, b in enumerate(bs):
    loc = sum(1 for ts in [per_round_bugsum[j][i] for j in range(len(PROGS))] if ts)
    s = sum(len(per_round_bugsum[j][i]) for j in range(len(PROGS)))
    sums.append(s)
    print(f"   {os.path.basename(b):<34} 定位={loc}/10  bug类型之和={s}")
print(f"   → bug 类型之和：中位数 {statistics.median(sums):g}，范围 {min(sums)}–{max(sums)}（论文 15）")

print()
print("=== 判据专项 ===")
print("-- CVE-2016-1972 是否报出 double-free（论文：只有 Period 能发现，bug-depth 5）--")
hit = 0
for b in bs:
    t = bug_types(os.path.join(b, "CVE-2016-1972-depth5"))
    ok = "double-free" in t
    hit += ok
    print(f"   {os.path.basename(b):<34} {'命中' if ok else '未命中'}   类型={sorted(t)}")
print(f"   → {hit}/{len(bs)} 轮命中")

print("-- CVE-2017-6346 是否同时报 NPD(SEGV) + UAF + DF --")
hit = 0
for b in bs:
    t = bug_types(os.path.join(b, "CVE-2017-6346-depth5"))
    ok = {"SEGV", "heap-use-after-free", "double-free"} <= t
    hit += ok
    print(f"   {os.path.basename(b):<34} {'三类齐全' if ok else '缺项'}   {sorted(t)}")
print(f"   → {hit}/{len(bs)} 轮三类齐全")

print("-- CVE-2016-7911 总调度数（官方 README 文字称 6，其自身输出实为 19）--")
vals = [total_schedules(os.path.join(b, "CVE-2016-7911-depth5")) for b in bs]
errs = [err_inter(os.path.join(b, "CVE-2016-7911-depth5")) for b in bs]
print(f"   总调度数：{fmt(vals)}   错误交错：{fmt(errs)}")

print("-- 超时次数合计（每轮应为 0）--")
for b in bs:
    t = [timeouts(os.path.join(b, f"{p}-depth5")) or 0 for p in PROGS]
    print(f"   {os.path.basename(b):<34} 合计 {sum(t)}")
