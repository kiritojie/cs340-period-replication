#!/usr/bin/env python3
"""Merge raw Extension CPU-affinity batch directories into a single audited TSV.

Re-evaluates the tightened validity gate against each round's archived
exit-code.txt, footer.txt, and stderr.log, and backfills internal_time_s
from footer.txt when the original batch recorded NA.

Compatible with Python 3.6+ (standard library only).
"""

import argparse
import csv
import os
import re
import sys

DEFAULT_BATCH_DIRS = [
    "extension-cpu-affinity",
    "extension-cpu-affinity-mask4-8",
    "extension-cpu-affinity-mask0-7",
    "extension-cpu-affinity-reorder5",
    "extension-cpu-affinity-reorder5-mask0-7",
]

FIELDNAMES = [
    "program",
    "round",
    "cpu_mask",
    "cpu_count",
    "rc",
    "gate_pass",
    "schedules",
    "error_interleavings",
    "timeouts",
    "first_error",
    "dry_run_runtime",
    "internal_time_s",
    "external_wall_s",
]

KP_ALL_ZERO_RE = re.compile(r"^kpNumArray:[ \t]+(0[ \t]*)+$", re.MULTILINE)
TIME_LINE_RE = re.compile(r"^Time[ \t]+.*$", re.MULTILINE)
HMS_RE = re.compile(r"^(\d+):(\d+):(\d+(?:\.\d+)?)$")


def read_text(path):
    if not os.path.isfile(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def parse_program(batch_dir):
    env_txt = read_text(os.path.join(batch_dir, "exec-env.txt"))
    for line in env_txt.splitlines():
        if line.startswith("program"):
            parts = line.split(":", 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
    return os.path.basename(os.path.normpath(batch_dir))


def eval_tight_gate(rc_str, footer_txt, stderr_txt):
    try:
        rc = int(rc_str)
    except (ValueError, TypeError):
        return "0"
    if rc != 0:
        return "0"
    if "Total Error Interleavings" not in footer_txt:
        return "0"
    if "sched_setattr error" in stderr_txt:
        return "0"
    if KP_ALL_ZERO_RE.search(footer_txt):
        return "0"
    return "1"


def parse_internal_time_s(footer_txt):
    matches = TIME_LINE_RE.findall(footer_txt)
    if not matches:
        return "NA"
    last_line = matches[-1].strip()
    tokens = last_line.split()
    if not tokens:
        return "NA"
    m = HMS_RE.match(tokens[-1])
    if not m:
        return "NA"
    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return "{:.3f}".format(h * 3600 + mi * 60 + s)


def collect_rows(batch_dirs):
    merged = []
    for bdir in batch_dirs:
        tsv_path = os.path.join(bdir, "rounds-summary.tsv")
        if not os.path.isfile(tsv_path):
            sys.stderr.write("[WARN] missing {}\n".format(tsv_path))
            continue
        default_prog = parse_program(bdir)
        with open(tsv_path, "r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            for row in reader:
                prog = row.get("program") or default_prog
                rnd = row["round"]
                rnum = rnd[1:] if rnd.startswith("R") else rnd
                mask = row["cpu_mask"]
                ncpu = row["cpu_count"]
                run_dir = os.path.join(
                    bdir, "cpus-{}_mask-{}".format(ncpu, mask), "round-{}".format(rnum)
                )
                footer_txt = read_text(os.path.join(run_dir, "footer.txt"))
                stderr_txt = read_text(os.path.join(run_dir, "stderr.log"))
                exit_txt = read_text(os.path.join(run_dir, "exit-code.txt")).strip()
                rc_val = exit_txt if exit_txt else row["rc"]

                gate = eval_tight_gate(rc_val, footer_txt, stderr_txt)
                int_s = row.get("internal_time_s", "NA")
                if not int_s or int_s == "NA":
                    int_s = parse_internal_time_s(footer_txt)

                merged.append(
                    {
                        "program": prog,
                        "round": rnd,
                        "cpu_mask": mask,
                        "cpu_count": ncpu,
                        "rc": rc_val,
                        "gate_pass": gate,
                        "schedules": row["schedules"],
                        "error_interleavings": row["error_interleavings"],
                        "timeouts": row["timeouts"],
                        "first_error": row["first_error"],
                        "dry_run_runtime": row["dry_run_runtime"],
                        "internal_time_s": int_s,
                        "external_wall_s": row["external_wall_s"],
                    }
                )
    return merged


def main():
    parser = argparse.ArgumentParser(description="Merge and audit extension CPU-affinity batches.")
    parser.add_argument(
        "--results-dir",
        default="docs/results",
        help="Parent directory containing extension-cpu-affinity* batch folders",
    )
    parser.add_argument(
        "--out",
        default="docs/results/extension-cpu-affinity-merged/rounds-summary.tsv",
        help="Output merged TSV path",
    )
    parser.add_argument(
        "batch_dirs",
        nargs="*",
        help="Optional explicit list of batch directories to merge",
    )
    args = parser.parse_args()

    dirs = (
        args.batch_dirs
        if args.batch_dirs
        else [os.path.join(args.results_dir, d) for d in DEFAULT_BATCH_DIRS]
    )
    rows = collect_rows(dirs)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    sys.stderr.write("Wrote {} rows to {}\n".format(len(rows), args.out))


if __name__ == "__main__":
    main()
