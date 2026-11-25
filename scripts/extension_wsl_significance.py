#!/usr/bin/env python3
"""Exact two-sided Mann-Whitney U test (with ties handled exactly via rank-sum
permutation) and Cliff's delta for the WSL2 true root-domain core-count experiment.

Compatible with Python 3.6+ (standard library only, no SciPy required).
"""

import csv
import itertools
import os
import sys


def load_errors(tsv_path, prog, cores):
    vals = []
    if not os.path.isfile(tsv_path):
        return vals
    with open(tsv_path, "r", encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if (
                row.get("program") == prog
                and int(row["wsl_cores"]) == cores
                and row.get("gate_pass") == "1"
            ):
                vals.append(float(row["error_interleavings"]))
    return vals


def average_ranks(combined):
    n = len(combined)
    indexed = sorted(enumerate(combined), key=lambda x: x[1])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg
        i = j + 1
    return ranks


def exact_mann_whitney(x, y):
    """Return (U_x, U_min, exact_two_sided_p, cliffs_delta)."""
    n1, n2 = len(x), len(y)
    combined = list(x) + list(y)
    ranks = average_ranks(combined)

    r1_obs = sum(ranks[:n1])
    u1_obs = r1_obs - n1 * (n1 + 1) / 2.0
    u2_obs = n1 * n2 - u1_obs
    u_min = min(u1_obs, u2_obs)

    mean_r1 = n1 * (n1 + n2 + 1) / 2.0
    obs_dev = abs(r1_obs - mean_r1) - 1e-12

    total = 0
    extreme = 0
    for comb in itertools.combinations(ranks, n1):
        total += 1
        if abs(sum(comb) - mean_r1) >= obs_dev:
            extreme += 1
    p_exact = extreme / total

    gt = sum(1 for a in x for b in y if a > b)
    lt = sum(1 for a in x for b in y if a < b)
    cliffs_d = (gt - lt) / (n1 * n2)
    return u1_obs, u_min, p_exact, cliffs_d


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "docs/results/extension-wsl-cores"
    main_tsv = os.path.join(base, "rounds-summary.tsv")
    order_tsv = os.path.join(base, "order-check", "rounds-summary.tsv")

    r5_2_main = load_errors(main_tsv, "reorder_5_bad", 2)
    r5_4_main = load_errors(main_tsv, "reorder_5_bad", 4)
    r5_8_main = load_errors(main_tsv, "reorder_5_bad", 8)
    r5_2_pool = r5_2_main + load_errors(order_tsv, "reorder_5_bad", 2)
    r5_8_pool = r5_8_main + load_errors(order_tsv, "reorder_5_bad", 8)

    r10_2 = load_errors(main_tsv, "reorder_10_bad", 2)
    r10_4 = load_errors(main_tsv, "reorder_10_bad", 4)
    r10_8 = load_errors(main_tsv, "reorder_10_bad", 8)

    tests = [
        ("reorder_5_bad: 2 cores vs 8 cores (pooled, n=8 vs 8)", r5_2_pool, r5_8_pool),
        ("reorder_5_bad: 2 cores vs 8 cores (main only, n=5 vs 5)", r5_2_main, r5_8_main),
        ("reorder_5_bad: 2 cores (pooled) vs 4 cores (n=8 vs 5)", r5_2_pool, r5_4_main),
        ("reorder_10_bad: 2 cores vs 8 cores (n=3 vs 3)", r10_2, r10_8),
        ("reorder_10_bad: 2 cores vs 4 cores (n=3 vs 3)", r10_2, r10_4),
        ("reorder_10_bad: 4 cores vs 8 cores (n=3 vs 3)", r10_4, r10_8),
    ]

    print("| Comparison | Group A (n) | Group B (n) | U_min | Exact two-sided p | Cliff's delta |")
    print("| --- | :---: | :---: | :---: | :---: | :---: |")
    for label, a, b in tests:
        _, u_min, p_val, cd = exact_mann_whitney(a, b)
        print(
            "| {} | {} | {} | {:.1f} | {:.6f} | {:+.3f} |".format(
                label, len(a), len(b), u_min, p_val, cd
            )
        )


if __name__ == "__main__":
    main()
