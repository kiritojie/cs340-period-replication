#!/usr/bin/env python3
"""Summarize existing PERIOD exploration logs; no experiments are executed."""

import argparse
import hashlib
import re
import statistics
from pathlib import Path


ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TEST = re.compile(r"^\s*test (\d+):")
ERROR = re.compile(r"^\s*\[Error Found\]:")
FOOTERS = {
    "total": re.compile(r"^\s*Round\s+\d+\s+(\d+)\s*$"),
    "errors": re.compile(r"^\s*Total Error Interleavings:\s*(\d+)\s*$"),
    "timeouts": re.compile(r"^\s*Total Timeouts Interleavings:\s*(\d+)\s*$"),
}


def parse(raw):
    lines = ANSI.sub("", raw.decode("utf-8", errors="replace")).splitlines()
    tests, errors, footer = [], [], {}
    ended = False
    for lineno, line in enumerate(lines, 1):
        if line.strip() == "End Testing!":
            if ended:
                raise ValueError("more than one test run in this file")
            ended = True
        test = TEST.match(line)
        if test:
            if ended:
                raise ValueError(f"line {lineno}: another run after End Testing")
            tests.append((int(test[1]), lineno))
        if ERROR.match(line):
            if not tests or ended:
                raise ValueError(f"line {lineno}: error marker outside a test")
            errors.append((tests[-1][0], lineno))
        for key, pattern in FOOTERS.items():
            if match := pattern.match(line):
                if not ended or key in footer:
                    raise ValueError(f"line {lineno}: unexpected or duplicate {key} summary")
                footer[key] = (int(match[1]), lineno)

    if not ended or footer.keys() != FOOTERS.keys():
        raise ValueError("incomplete or unsupported log: missing End Testing or summary")
    total, error_count = footer["total"][0], footer["errors"][0]
    if [n for n, _ in tests] != list(range(1, len(tests) + 1)) or total != len(tests):
        raise ValueError("test sequence or final round count does not match")
    if error_count != len({n for n, _ in errors}):
        raise ValueError("error summary does not match the distinct reported tests")
    if footer["timeouts"][0] > total:
        raise ValueError("timeout count exceeds total schedules")
    first = (errors[0][0], tests[errors[0][0] - 1][1], errors[0][1]) if errors else None
    return footer, first


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="+", type=Path, help="one exploration log per independent run")
    args = parser.parse_args()
    runs, rejected, seen = [], [], set()
    for path in args.logs:
        try:
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest in seen:
                raise ValueError("duplicate log contents; do not reuse the same run")
            footer, first = parse(raw)
            seen.add(digest)
            runs.append((path, digest, footer, first))
        except (OSError, ValueError) as exc:
            rejected.append((path, str(exc)))

    print("| 日志 | 总调度数 | 首次报错调度 | 报错调度数 | 超时数 |")
    print("| --- | ---: | ---: | ---: | ---: |")
    for path, _, footer, first in runs:
        first_text = str(first[0]) if first is not None else "未发现"
        print(f"| {path.name} | {footer['total'][0]} | {first_text} | "
              f"{footer['errors'][0]} | {footer['timeouts'][0]} |")
    print()
    for path, digest, footer, first in runs:
        evidence = f"L{footer['total'][1]} 总数，L{footer['errors'][1]} 错误数，L{footer['timeouts'][1]} 超时数"
        if first is not None:
            evidence += f"，L{first[1]}–L{first[2]} 首次报错"
        print(f"- `{path}`：{evidence}；SHA-256 `{digest}`。")
    for path, reason in rejected:
        print(f"- 未纳入：`{path}` — {reason}")

    if len(runs) >= 3 and not rejected and not any(r[2]["timeouts"][0] for r in runs):
        print(f"\n均值 ± 样本标准差（n={len(runs)}；仅汇总同设置的独立运行）：")
        metrics = {
            "总调度数": [r[2]["total"][0] for r in runs],
            "首次报错调度": [r[3][0] for r in runs if r[3] is not None],
            "报错调度数": [r[2]["errors"][0] for r in runs],
        }
        for label, values in metrics.items():
            if len(values) != len(runs):
                print(f"- {label}：不可直接比较（{len(runs) - len(values)} 轮未发现错误）。")
            else:
                print(f"- {label}：{statistics.mean(values):.2f} ± {statistics.stdev(values):.2f}")
    else:
        print("\n不生成汇总统计：需要至少 3 份独立完整日志，且本批次无拒读或超时。")
    return 1 if rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
