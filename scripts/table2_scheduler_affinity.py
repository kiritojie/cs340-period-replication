#!/usr/bin/env python3
"""Check a declared Linux CPU list against current affinity without changing it."""
from __future__ import print_function

import argparse
import json
import os
import re
import sys

# Bound parsing work for malformed CLI input; these are parser resource limits,
# not a benchmark CPU configuration or a reason to change an actual affinity.
MAX_CPU_INDEX = 1048575
MAX_CPU_COUNT = 65536


def parse_cpu_list(text):
    if not isinstance(text, str) or not re.match(r"^[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*$", text):
        raise ValueError("expected a nonempty Linux CPU list, e.g. 0-31 or 0-3,8")
    if any(character.isspace() for character in text):
        raise ValueError("CPU list must not contain whitespace")
    result = set()
    for token in text.split(","):
        endpoints = token.split("-")
        first, last = int(endpoints[0]), int(endpoints[-1])
        if first > last:
            raise ValueError("CPU range is reversed: " + token)
        if last > MAX_CPU_INDEX or last - first + 1 > MAX_CPU_COUNT:
            raise ValueError("CPU list exceeds parser resource limits")
        values = set(range(first, last + 1))
        if result.intersection(values):
            raise ValueError("CPU list repeats or overlaps CPU indices")
        result.update(values)
        if len(result) > MAX_CPU_COUNT:
            raise ValueError("CPU list exceeds parser resource limits")
    return frozenset(result)


def verify_affinity(expected_text, actual_cpus=None):
    expected = parse_cpu_list(expected_text)
    if actual_cpus is None:
        if not hasattr(os, "sched_getaffinity"):
            raise ValueError("current process affinity cannot be read on this platform")
        actual_cpus = os.sched_getaffinity(0)
    actual = frozenset(actual_cpus)
    if not actual or any(type(cpu) is not int or cpu < 0 for cpu in actual):
        raise ValueError("actual affinity is empty or invalid")
    if actual != expected:
        raise ValueError("actual CPU affinity {0} differs from declared {1}; no affinity was changed".format(
            sorted(actual), expected_text))
    return {"expected_cpu_list": expected_text, "expected_cpus": sorted(expected),
            "actual_cpus": sorted(actual), "status": "PASS", "affinity_changed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-cpus", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(verify_affinity(args.expected_cpus), sort_keys=True))
        return 0
    except (ValueError, OSError) as error:
        print("BLOCKED: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
