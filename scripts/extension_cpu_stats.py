#!/usr/bin/env python3
"""Summarize Extension CPU-affinity rounds-summary.tsv into Mean +/- SD and Median (Range).

Compatible with Python 3.6+ (standard library only).
"""

import csv
import math
import statistics
import sys
from collections import defaultdict


def fmt_mean_sd(vals):
    if not vals:
        return "N/A"
    mean = statistics.mean(vals)
    sd = statistics.stdev(vals) if len(vals) >= 2 else 0.0
    return "{:.2f} +/- {:.2f}".format(mean, sd)


def fmt_med_range(vals, is_int=True):
    if not vals:
        return "N/A"
    med = statistics.median(vals)
    lo, hi = min(vals), max(vals)
    if is_int:
        med_s = "{:.0f}".format(med) if float(med).is_integer() else "{:.1f}".format(med)
        return "{} ({}-{})".format(med_s, int(lo), int(hi))
    return "{:.2f} ({:.2f}-{:.2f})".format(med, lo, hi)


def parse_float(s):
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def main():
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: extension_cpu_stats.py <rounds-summary.tsv>\n")
        sys.exit(1)

    groups = defaultdict(list)
    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        fields = reader.fieldnames or []
        has_program = "program" in fields
        core_col = "cpu_count" if "cpu_count" in fields else "wsl_cores"
        for row in reader:
            prog = row["program"] if has_program else ""
            key = (prog, int(row[core_col]), row["cpu_mask"])
            groups[key].append(row)

    if has_program:
        print("| Program | Logical CPUs (mask) | Valid / Total | Schedules (Mean +/- SD) | Error Interleavings (Mean +/- SD) | Error Median (Range) | Timeouts | Wall Time s (Mean +/- SD) |")
        print("| --- | --- | :---: | :---: | :---: | :---: | :---: | :---: |")
    else:
        print("| Logical CPUs (mask) | Valid / Total | Schedules (Mean +/- SD) | Error Interleavings (Mean +/- SD) | Error Median (Range) | Timeouts | Wall Time s (Mean +/- SD) |")
        print("| --- | :---: | :---: | :---: | :---: | :---: | :---: |")

    for (prog, ncpu, mask) in sorted(groups.keys()):
        rows = groups[(prog, ncpu, mask)]
        valid = [r for r in rows if r.get("gate_pass") == "1"]
        scheds = [v for v in (parse_float(r["schedules"]) for r in valid) if v is not None]
        errs = [v for v in (parse_float(r["error_interleavings"]) for r in valid) if v is not None]
        tos = [v for v in (parse_float(r["timeouts"]) for r in valid) if v is not None]
        walls = [v for v in (parse_float(r["external_wall_s"]) for r in valid) if v is not None]

        to_sum = int(sum(tos)) if tos else 0
        prefix = "| `{}` ".format(prog) if has_program else ""
        print(
            "{}| {} (`{}`) | {} / {} | {} | {} | {} | {} | {} |".format(
                prefix,
                ncpu,
                mask,
                len(valid),
                len(rows),
                fmt_mean_sd(scheds),
                fmt_mean_sd(errs),
                fmt_med_range(errs, is_int=True),
                to_sum,
                fmt_mean_sd(walls),
            )
        )


if __name__ == "__main__":
    main()
