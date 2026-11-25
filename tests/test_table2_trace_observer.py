"""Pure Python fixtures for the yield observer; never start a PERIOD target."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


OBSERVER = Path(__file__).resolve().parents[1] / "scripts/trace_period_driver.py"


class YieldObserverTests(unittest.TestCase):
    def run_fixture(self, source, adapted=False):
        with tempfile.TemporaryDirectory(prefix="period-trace-fixture-") as directory:
            root = Path(directory)
            official = root / "run_PDS.py"
            official.write_text(source, encoding="utf-8")
            driver = official
            if adapted:
                driver = root / "adapter_fixture.py"
                driver.write_text(
                    "from pathlib import Path\n"
                    "official = Path(" + repr(str(official)) + ")\n"
                    "namespace = {'__name__':'__main__', '__file__':str(official)}\n"
                    "exec(compile(official.read_text(),str(official)+' [comparison]','exec'),namespace)\n",
                    encoding="utf-8")
            trace = root / "trace.jsonl"
            environment = dict(os.environ)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            process = subprocess.Popen(
                [sys.executable, str(OBSERVER), "--trace", str(trace),
                 "--expected-source", str(official), "--", str(driver)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, env=environment)
            stdout, stderr = process.communicate(timeout=15)
            rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
            return process.returncode, stdout, stderr, rows

    @staticmethod
    def exploration_source():
        return (
            "def memmove_pattern_list(PatternList):\n"
            "    values = [item for row in PatternList for item in row]\n"
            "rounds = 0\nTaskReproduce = 0\n"
            "ZeroPattern = [[0,0],[1,0],[2,0]]\n"
            "memmove_pattern_list(ZeroPattern)\n"
            "DBDS_stage = 1\n"
            "for rounds in (1,2):\n"
            "    iterPeriod = rounds+1\n"
            "    inter = [[0,0],[1,1,2]] if rounds == 1 else [[0],[1,1],[0,2]]\n"
            "    pattern = [[0,0],[rounds,0],[rounds,0]]\n"
            "    memmove_pattern_list(pattern)\n"
            "    pattern[0][0] = 99\n"
            "print('End Testing!')\n"
            "print('Round 0 2')\n"
            "raise SystemExit(0)\n")

    def test_initialization_then_actual_writes(self):
        code, stdout, stderr, rows = self.run_fixture(self.exploration_source())
        self.assertEqual((code, stderr), (0, ""))
        self.assertIn("End Testing!\nRound 0 2", stdout)
        writes = [row for row in rows if row["event"] == "yield_write"]
        self.assertEqual([row["ordinal"] for row in writes], [1, 2])
        self.assertEqual([row["period"] for row in writes], [2, 3])
        self.assertEqual(writes[0]["yield_pattern"], [[0, 0], [1, 0], [1, 0]])
        self.assertEqual(writes[1]["yield_pattern"], [[0, 0], [2, 0], [2, 0]])
        self.assertEqual(rows[-1]["yield_writes"], 2)
        self.assertEqual(rows[-1]["ignored_initialization_writes"], 1)
        self.assertEqual(rows[-1]["ignored_replay_writes"], 0)
        self.assertIsNone(rows[-1]["observation_error"])

    def test_adapted_comparison_filename(self):
        code, stdout, stderr, rows = self.run_fixture(self.exploration_source(), adapted=True)
        self.assertEqual((code, stderr), (0, ""))
        writes = [row for row in rows if row["event"] == "yield_write"]
        self.assertEqual([row["ordinal"] for row in writes], [1, 2])
        self.assertTrue(all(row["code_filename"].endswith(" [comparison]") for row in writes))
        self.assertEqual(rows[-1]["ignored_initialization_writes"], 1)

    def test_replay_is_not_an_exploration_write(self):
        code, stdout, stderr, rows = self.run_fixture(
            "def memmove_pattern_list(PatternList):\n    result = len(PatternList)\n"
            "rounds=0\nTaskReproduce=1\npattern_list=[[0],[1]]\n"
            "memmove_pattern_list(pattern_list)\nraise SystemExit(0)\n")
        self.assertEqual((code, stderr), (0, ""))
        self.assertFalse(any(row["event"] == "yield_write" for row in rows))
        self.assertEqual(rows[-1]["ignored_replay_writes"], 1)

    def test_positive_round_missing_context_is_not_ignored(self):
        code, stdout, stderr, rows = self.run_fixture(
            "def memmove_pattern_list(PatternList):\n    result = len(PatternList)\n"
            "rounds=1\nTaskReproduce=0\nZeroPattern=[[0],[1]]\n"
            "memmove_pattern_list(ZeroPattern)\nprint('must not continue')\n")
        self.assertEqual(code, 2)
        self.assertNotIn("must not continue", stdout)
        self.assertFalse(any(row["event"] == "yield_write" for row in rows))
        self.assertIsNotNone(rows[-1]["observation_error"])
        self.assertEqual(rows[-1]["ignored_initialization_writes"], 0)

    def test_round_zero_unknown_write_is_not_ignored(self):
        code, stdout, stderr, rows = self.run_fixture(
            "def memmove_pattern_list(PatternList):\n    result = len(PatternList)\n"
            "rounds=0\nTaskReproduce=0\nZeroPattern=[[0],[1]]\n"
            "memmove_pattern_list([[0],[1]])\n")
        self.assertEqual(code, 2)
        self.assertIsNotNone(rows[-1]["observation_error"])

    def test_failed_initialization_write_is_not_claimed_complete(self):
        code, stdout, stderr, rows = self.run_fixture(
            "def memmove_pattern_list(PatternList):\n    raise ValueError('write failed')\n"
            "rounds=0\nTaskReproduce=0\nZeroPattern=[[0],[1]]\n"
            "memmove_pattern_list(ZeroPattern)\n")
        self.assertEqual(code, 2)
        self.assertEqual(rows[-1]["ignored_initialization_writes"], 0)
        self.assertIsNotNone(rows[-1]["observation_error"])


if __name__ == "__main__":
    unittest.main()
