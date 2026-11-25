"""Offline generator/controller checks; never launch an instrumented benchmark.

The oracles assign distinguishable per-thread events to monotonically increasing
periods, independently of PERIOD's recursive pattern/schedule enumeration.  For
Parallel, only one thread already present before the last period may also occur
in that last period: the other last-period threads are the neglected threads in
the paper's chosen-thread model.  This is narrower than arbitrary parallelism.

Run from the repository root: python -B -m unittest discover -s tests -v
"""

import ast
import contextlib
import copy
import ctypes
import importlib.util
import io
import itertools
from collections import Counter, OrderedDict
from pathlib import Path
import sys
import subprocess
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "scripts" / "run_scheduler_comparison.py"
VENDOR = ROOT / "scripts" / "vendor" / "period_b6f72a7"


def freeze(schedule):
    """Period ordering matters; order inside a parallel period does not."""
    return tuple(tuple(sorted(period)) for period in schedule)


def exact(schedule):
    """Raw printed order, including the last period, for strict regression."""
    return tuple(tuple(period) for period in schedule)


def serial_oracle(kps, periods):
    """All multiset event permutations, compressed into nonempty runs."""
    remaining = list(kps)
    answers = set()

    def walk(events):
        if not any(remaining):
            runs = []
            for thread in events:
                if not runs or runs[-1][0] != thread:
                    runs.append([thread])
                else:
                    runs[-1].append(thread)
            if len(runs) == periods:
                answers.add(freeze(runs))
            return
        for thread, count in enumerate(remaining):
            if count:
                remaining[thread] -= 1
                walk(events + (thread,))
                remaining[thread] += 1

    walk(())
    return answers


def parallel_oracle(kps, periods):
    """Independent event-to-period assignment oracle for chosen-thread mode."""
    assignments = [
        itertools.combinations_with_replacement(range(periods), count)
        for count in kps
    ]
    answers = set()
    for allocation in itertools.product(*assignments):
        schedule = [[] for _ in range(periods)]
        for thread, event_periods in enumerate(allocation):
            for period in event_periods:
                schedule[period].append(thread)
        if any(not period for period in schedule):
            continue
        if any(len(set(period)) != 1 for period in schedule[:-1]):
            continue
        if any(schedule[i][0] == schedule[i + 1][0]
               for i in range(periods - 2)):
            continue
        if schedule[-2][0] in schedule[-1]:
            continue
        previously_chosen = set(itertools.chain.from_iterable(schedule[:-1]))
        if len(previously_chosen.intersection(schedule[-1])) > 1:
            continue
        answers.add(freeze(schedule))
    return answers


def prefix_oracle(schedule, prefix):
    """Complete earlier periods and a lower bound on the final prefix period."""
    if not prefix:
        return True
    if len(prefix) > len(schedule):
        return False
    if freeze(schedule[:len(prefix) - 1]) != freeze(prefix[:-1]):
        return False
    last = tuple(prefix[-1])
    candidate = tuple(schedule[len(prefix) - 1])
    return len(candidate) >= len(last) and candidate[:len(last)] == last


class AdapterImportMixin:
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("comparison_under_test", DRIVER)
        cls.sut = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.sut
        spec.loader.exec_module(cls.sut)


class ControllerTests(AdapterImportMixin, unittest.TestCase):
    def test_small_three_thread_counts_follow_from_oracle_not_a_benchmark_run(self):
        self.assertEqual([len(serial_oracle([2, 2, 1], p)) for p in (3, 4, 5)],
                         [6, 12, 12])
        self.assertEqual([len(parallel_oracle([2, 2, 1], p)) for p in (2, 3, 4)],
                         [3, 10, 14])

    def test_period_ranges_and_depth_mapping(self):
        for n in (2, 3, 4, 10):
            for depth in (1, 2, 3):
                for mode in ("parallel", "serial"):
                    first, last = self.sut.period_bounds(mode, depth, n)
                    self.assertEqual(first, 2 if mode == "parallel" else n)
                    self.assertEqual(last, depth + 1 if mode == "parallel" else depth + n - 1)
                    self.assertEqual([self.sut.logical_depth(mode, p, n)
                                      for p in range(first, last + 1)],
                                     list(range(1, depth + 1)))

    def test_budget_distinguishes_generated_started_completed_and_retests(self):
        budget = self.sut.Budget(1)
        budget.note_generated()
        budget.note_generated()
        self.assertEqual((budget.generated, budget.executed, budget.completed), (2, 0, 0))
        budget.before_start()
        budget.start(process_id=101)
        self.assertEqual((budget.generated, budget.executed, budget.completed), (2, 1, 0))
        # A repeated launch belongs to the same explored schedule and must be
        # separately observable, even when that schedule consumed the last slot.
        budget.before_start(retest=True)
        budget.start(process_id=102, retest=True)
        budget.complete(process_id=102, retest=True)
        self.assertEqual(budget.retests, 1)
        budget.complete(process_id=101)
        self.assertEqual((budget.executed, budget.completed), (1, 1))
        self.assertFalse(budget.can_start())
        self.assertIsInstance(budget.snapshot(), dict)

    def test_zero_budget_preserves_upstream_unlimited_semantics(self):
        budget = self.sut.Budget(0)
        for _ in range(8):
            budget.note_generated()
            budget.before_start()
            budget.start()
            budget.complete()
        self.assertTrue(budget.can_start())
        self.assertEqual((budget.generated, budget.executed, budget.completed), (8, 8, 8))

    def test_prepared_driver_compiles_and_retains_true_period_index(self):
        source = (VENDOR / "run_PDS.py").read_text(encoding="utf-8")
        for mode in ("parallel", "serial"):
            with self.subTest(mode=mode):
                prepared = self.sut.prepare_driver_source(source, mode)
                compile(prepared, "adapted_run_PDS.py", "exec")
                tree = ast.parse(prepared)
                # Runtime's T field is the last true period index; it must never
                # receive the serial logical-depth expression p-N+1 instead.
                runtime_period_writes = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                        if node.func.id == "c_uint" and node.args:
                            arg = node.args[0]
                            if isinstance(arg, ast.BinOp) and isinstance(arg.left, ast.Name):
                                if arg.left.id == "iterPeriod":
                                    runtime_period_writes.append(arg)
                self.assertTrue(runtime_period_writes)
                self.assertTrue(all(isinstance(x.op, ast.Sub)
                                    and ast.literal_eval(x.right) == 1
                                    for x in runtime_period_writes))

    def test_normal_footer_reaches_success_marker_without_executing_target(self):
        source = (VENDOR / "run_PDS.py").read_text(encoding="utf-8")
        for mode in ("parallel", "serial"):
            with self.subTest(mode=mode):
                prepared = self.sut.prepare_driver_source(source, mode)
                footer = prepared[prepared.index('print("\\033[4;36mEnd Testing!'):]
                namespace = {
                    "total_errors_interleavings": [0],
                    "total_timeouts_interleavings": [0],
                    "statusL": [], "rlts": [], "lastRound": 0, "rounds": 0,
                    "lastTime": 0, "startTime": 0,
                    "time": types.SimpleNamespace(time=lambda: 0),
                    "formateTime": lambda unused: "00:00:00",
                }
                with contextlib.redirect_stdout(io.StringIO()):
                    exec(compile(footer, "<footer-only-no-target>", "exec"), namespace)
                self.assertTrue(namespace.get("_comparison_finished"))


class OfflineSchedulerTests(AdapterImportMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sut.load_official_modules(VENDOR)

    def enumerate_checked(self, mode, kps, periods, prefix=None):
        scheduler = self.sut.make_scheduler(mode, len(kps), list(kps), periods,
                                            prefix=prefix)
        seen = []
        for schedule in scheduler:
            self.assertEqual(len(schedule), periods)
            self.assertTrue(all(schedule), "An empty period is not a schedule")
            self.assertEqual(Counter(itertools.chain.from_iterable(schedule)),
                             Counter({t: count for t, count in enumerate(kps)}))
            self.assertTrue(all(0 <= t < len(kps)
                                for t in itertools.chain.from_iterable(schedule)))
            pure = schedule if mode == "serial" else schedule[:-1]
            self.assertTrue(all(len(set(period)) == 1 for period in pure))
            for left, right in zip(pure, pure[1:]):
                self.assertNotEqual(left[0], right[0])
            if mode == "parallel":
                self.assertNotIn(schedule[-2][0], schedule[-1])
            self.assertEqual(freeze(scheduler.get_schedule()), freeze(schedule))
            self.assertTrue(prefix_oracle(schedule, prefix))

            # An event's accumulated yield count is its true period index.  Each
            # thread's kth event must occur after its (k-1)th event; no benchmark
            # operation is executed while checking this encoding.
            yields = scheduler.get_yield_pattern()
            self.assertEqual(len(yields), len(kps))
            decoded = [[] for _ in range(periods)]
            for thread, deltas in enumerate(yields):
                self.assertEqual(len(deltas), kps[thread])
                clock = 0
                event_ordinals = []
                for ordinal, delta in enumerate(deltas):
                    self.assertIsInstance(delta, int)
                    self.assertGreaterEqual(delta, 0)
                    clock += delta
                    self.assertLess(clock, periods)
                    decoded[clock].append(thread)
                    event_ordinals.append((clock, ordinal))
                self.assertEqual(event_ordinals, sorted(event_ordinals))
            self.assertEqual(freeze(decoded), freeze(schedule))
            seen.append(freeze(schedule))
        self.assertEqual(len(seen), len(set(seen)), "Duplicate generated schedules")
        return seen

    def test_serial_exhaustive_against_independent_multiset_oracle(self):
        for kps in ([1, 1], [2, 1], [2, 2], [1, 1, 1], [2, 1, 1], [2, 2, 1]):
            for periods in range(len(kps), sum(kps) + 1):
                with self.subTest(kps=kps, periods=periods):
                    self.assertEqual(set(self.enumerate_checked("serial", kps, periods)),
                                     serial_oracle(kps, periods))

    def test_parallel_exhaustive_against_event_assignment_oracle(self):
        for kps in ([1, 1], [2, 1], [2, 2], [1, 1, 1], [2, 1, 1], [2, 2, 1]):
            for periods in range(2, min(sum(kps), 4) + 1):
                with self.subTest(kps=kps, periods=periods):
                    self.assertEqual(set(self.enumerate_checked("parallel", kps, periods)),
                                     parallel_oracle(kps, periods))

    def test_no_prefix_parallel_sequence_and_yields_are_unmodified_upstream(self):
        # Set equality alone would fail to catch a change in search order.
        for kps in ([2, 1], [2, 2, 1], [2, 1, 1, 1]):
            for periods in range(2, min(sum(kps), 4) + 1):
                with self.subTest(kps=kps, periods=periods):
                    upstream = self.sut.SBPMESched(len(kps), list(kps), periods)
                    adapted = self.sut.make_scheduler("parallel", len(kps), list(kps), periods)
                    original_rows = []
                    candidate_rows = []
                    for schedule in upstream:
                        original_rows.append((exact(schedule), upstream.get_yield_pattern()))
                    for schedule in adapted:
                        candidate_rows.append((exact(schedule), adapted.get_yield_pattern()))
                    self.assertEqual(candidate_rows, original_rows)

    def test_serial_prefix_complete_legal_subset_without_loss_or_duplicates(self):
        kps = [3, 2, 1]
        for periods in (3, 4, 5):
            universe = serial_oracle(kps, periods)
            prefixes = set()
            for schedule in universe:
                for size in (1, min(2, periods - 1)):
                    prefix = list(schedule[:size])
                    prefix[-1] = prefix[-1][:1]
                    prefixes.add(tuple(prefix))
            for frozen_prefix in sorted(prefixes):
                prefix = [list(x) for x in frozen_prefix]
                expected = {row for row in universe if prefix_oracle(row, prefix)}
                with self.subTest(periods=periods, prefix=prefix):
                    actual = self.enumerate_checked("serial", kps, periods, prefix)
                    self.assertEqual(set(actual), expected)

    def test_parallel_prefix_constraints_and_upstream_order(self):
        # Parallel's prefix implementation must remain precisely the upstream
        # fix_prefix=True implementation; no extra local search filter is used.
        for kps, periods, prefix in (
            ([3, 2], 4, [[0], [1]]),
            ([3, 2, 1], 4, [[0], [1]]),
            ([3, 2, 1], 4, [[1], [0]]),
            ([3, 2, 1], 5, [[0], [1], [0]]),
        ):
            with self.subTest(kps=kps, periods=periods, prefix=prefix):
                upstream = self.sut.SBPMESched(len(kps), list(kps), periods,
                                               sched=prefix, fix_prefix=True)
                expected = []
                for schedule in upstream:
                    self.assertTrue(prefix_oracle(schedule, prefix))
                    expected.append(freeze(schedule))
                self.assertEqual(self.enumerate_checked("parallel", kps, periods, prefix),
                                 expected)
                raw_upstream = self.sut.SBPMESched(len(kps), list(kps), periods,
                                                   sched=prefix, fix_prefix=True)
                raw_adapted = self.sut.make_scheduler("parallel", len(kps), list(kps),
                                                       periods, prefix=prefix)
                self.assertEqual([exact(row) for row in raw_adapted],
                                 [exact(row) for row in raw_upstream])

    def test_invalid_prefix_is_rejected_instead_of_silently_changing_slice(self):
        for mode in ("parallel", "serial"):
            for prefix in ([[]], [[3]], [[0, 1]], [[0, 0, 0]], [[0], [0]]):
                with self.subTest(mode=mode, prefix=prefix):
                    with self.assertRaises(ValueError):
                        self.sut.make_scheduler(mode, 3, [2, 2, 1], 4, prefix=prefix)

    def test_global_budget_stops_both_modes_before_an_extra_target_start(self):
        for mode in ("parallel", "serial"):
            for limit in (1, 2, 5):
                with self.subTest(mode=mode, limit=limit):
                    budget = self.sut.Budget(limit)
                    target_calls = []
                    first, last = self.sut.period_bounds(mode, 3, 3)
                    try:
                        # Independent outer jobs deliberately remain available
                        # after exhaustion, like the driver's stage/prefix jobs.
                        for unused_job in range(3):
                            for periods in range(first, last + 1):
                                for schedule in self.sut.make_scheduler(mode, 3, [2, 2, 1], periods):
                                    budget.note_generated()
                                    budget.before_start()
                                    target_calls.append(freeze(schedule))
                                    budget.start()
                                    budget.complete()
                    except self.sut.BudgetExhausted:
                        pass
                    self.assertEqual(len(target_calls), limit)
                    self.assertEqual(budget.executed, limit)
                    self.assertEqual(budget.completed, limit)
                    self.assertGreaterEqual(budget.generated, budget.executed)
                    self.assertFalse(budget.can_start())
                    with self.assertRaises(self.sut.BudgetExhausted):
                        budget.before_start()
                    self.assertEqual(budget.executed, limit)

    def test_actual_adapted_exploration_stops_global_budget_across_prefix_stage(self):
        """Run real adapted control flow, real generators, and fake target I/O.

        This is not a benchmark result: no Popen, native shared-memory function,
        or instrumented program is invoked.  One synthetic coverage job forces
        the real driver into its prefix stage before the budget runs out.
        """
        source = (VENDOR / "run_PDS.py").read_text(encoding="utf-8")
        module_tree = ast.parse(DRIVER.read_text(encoding="utf-8"))
        main_function = next(node for node in module_tree.body
                             if isinstance(node, ast.FunctionDef) and node.name == "main")
        launch_function = next(node for node in ast.walk(main_function)
                               if isinstance(node, ast.FunctionDef) and node.name == "launch")
        launch_tree = ast.Module(body=[launch_function], type_ignores=[])
        launch_code = compile(ast.fix_missing_locations(launch_tree), "<actual-launch-no-target>", "exec")

        for mode, limit in (("parallel", 14), ("serial", 19)):
            with self.subTest(mode=mode, limit=limit):
                budget = self.sut.Budget(limit)
                launch_namespace = {"budget": budget, "processes": [], "_Process": self.sut._Process}
                exec(launch_code, launch_namespace)
                target_calls = []
                ns = {
                    "COMPARISON_MODE": mode, "N": 3, "M": 2, "bugDepth": 3,
                    "zero_in_KP": 0, "kpMaxNumArray": [2, 2, 1] + [0] * 97,
                    "VarModeFlag": 0, "DBDS_stage": 1, "full_deep_run": 0,
                    "no_prefix_run": 0, "prefix": [], "rounds": 0, "runs_limit": limit,
                    "waited_to_explore": OrderedDict(), "waited_to_explore_save": OrderedDict(),
                    "parentArray": [0] * 100, "parentArrayCopy": [0] * 100,
                    "SHARE_THREAD_NUM": 100, "SHARE_ARRAY_SIZE": 1990,
                    "kpNumArray": [2, 2, 1] + [0] * 97,
                    "kpYieldArray": [], "kpLocArray": [], "kpOrderArray": [],
                    "A": ctypes.c_uint(3), "B": ctypes.c_uint(2), "T": ctypes.c_uint(0),
                    "ADDR": 0, "sizeof": ctypes.sizeof, "byref": ctypes.byref,
                    "c_uint": ctypes.c_uint, "c_ulonglong": ctypes.c_ulonglong,
                    "memmove": lambda *unused: None, "memmove_pattern_list": lambda *unused: None,
                    "get_info_from_share_memory": lambda *unused: None,
                    "check_and_update_kpNumMaxArray": lambda *unused: None,
                    "new_max_kpNumArray": lambda *unused: False,
                    "calculate_coverage_hashID": lambda *unused: 0,
                    "default_coverage_hashID": 0,
                    "is_redundant_with_prefix": lambda *unused: False,
                    "recordERR": 1, "check_STDOUT": 1, "check_STDERR": 1,
                    "DebugInfo": False, "folder_name": "<offline-fixture>", "subprocessTimeout": 5,
                    "copy": copy, "subprocess": subprocess,
                    "period_bounds": self.sut.period_bounds,
                    "logical_depth": self.sut.logical_depth,
                    "NoScheduleError": self.sut.NoScheduleError,
                    "BudgetExhausted": self.sut.BudgetExhausted,
                    "_comparison_budget": budget,
                    "_comparison_launch": launch_namespace["launch"],
                }

                class FakeCompletedTarget:
                    returncode = 0

                    def __init__(self, pid):
                        self.pid = pid

                    def communicate(self, timeout=None):
                        return b"", b""

                    def poll(self):
                        return 0

                def fake_factory(*unused):
                    target_calls.append({"schedule": exact(ns["scheduler"].get_schedule()),
                                         "stage": ns["DBDS_stage"]})
                    return FakeCompletedTarget(len(target_calls))

                def record_synthetic_feedback(*unused):
                    if ns["DBDS_stage"] == 1 and ns["iterPeriod"] > ns["first_period"]:
                        ns["waited_to_explore"][1] = [None, None, 3, 2, [2, 2, 1], [[0]]]

                def fill_with_zero(pattern, width):
                    for row in pattern:
                        row.extend([0] * (width - len(row)))

                ns.update({
                    "create_DBDS_subprocess": fake_factory,
                    "record_error_message": record_synthetic_feedback,
                    "filled_with_zero": fill_with_zero,
                    "_comparison_scheduler": lambda n, kps, p, prefix=None:
                        self.sut.make_scheduler(mode, n, kps, p, prefix, budget.note_generated),
                })
                prepared = self.sut.prepare_driver_source(source, mode)
                start = prepared.index("N_after_DryRun = N")
                end = prepared.index('print("\\033[4;36mEnd Testing!')
                with contextlib.redirect_stdout(io.StringIO()):
                    exec(compile(prepared[start:end], "<actual-exploration-no-target>", "exec"), ns)
                self.assertEqual(len(target_calls), limit)
                self.assertEqual((budget.executed, budget.completed), (limit, limit))
                self.assertEqual(ns["rounds"], limit)
                self.assertTrue(budget.budget_hit)
                self.assertTrue(any(call["stage"] == 2 for call in target_calls))
                self.assertEqual(budget.snapshot()["in_flight"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
