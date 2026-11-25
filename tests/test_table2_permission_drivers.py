"""Permission boundary tests; no instrumented target or live deadline change."""
import ast
import importlib.util
import os
from pathlib import Path
import signal
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DriverPermissionBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_path = list(sys.path)
        sys.path.insert(0, str(ROOT / "scripts"))
        cls.driver = load("permission_driver_boundary", ROOT / "scripts/run_scheduler_comparison.py")
        cls.reference = load("permission_reference_boundary", ROOT / "scripts/run_abi_parallel_reference.py")
        import table2_scheduler_permissions
        cls.permissions = table2_scheduler_permissions

    @classmethod
    def tearDownClass(cls):
        sys.path[:] = cls.original_path

    def setUp(self):
        # Windows only exercises the launch boundary; live process-group calls
        # are verified by the mandatory Linux helper before a benchmark starts.
        patcher = mock.patch.object(os, "setpgrp", create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_reference_and_unified_use_identical_supervisor(self):
        import run_scheduler_comparison
        self.assertIs(self.reference.ProcessSupervisor, run_scheduler_comparison.ProcessSupervisor)
        for filename in ("run_abi_parallel_reference.py", "run_scheduler_comparison.py"):
            tree = ast.parse((ROOT / "scripts" / filename).read_text(encoding="utf-8"))
            main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
            calls = [n for n in ast.walk(main) if isinstance(n, ast.Call)]
            self.assertTrue(any(isinstance(n.func, ast.Name) and n.func.id == "validate_permission_proof"
                                for n in calls), filename)

    def test_root_launch_preserves_finalized_official_memoryleak_assignments(self):
        source = (ROOT / "scripts/vendor/period_b6f72a7/run_PDS.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        assignment = next(n for n in tree.body if isinstance(n, ast.Assign) and
                          any(isinstance(t, ast.Name) and t.id == "DBDS_Command" for t in n.targets))
        command = ast.literal_eval(assignment.value)
        command[3] = command[3].replace("detect_leaks=0", "detect_leaks=1")
        command.append("./reorder_3_bad")
        original = list(command)
        popen = mock.Mock(return_value=mock.Mock(pid=456))
        supervisor = self.driver.ProcessSupervisor(popen)
        with mock.patch.object(self.permissions.os, "geteuid", return_value=0, create=True):
            supervisor(command, stdout=-1, stderr=-1)
        argv, = popen.call_args[0]
        options = popen.call_args[1]
        self.assertEqual(argv, ["./reorder_3_bad"])
        self.assertIn("detect_leaks=1", options["env"]["ASAN_OPTIONS"])
        self.assertEqual(options["env"]["DBDS_Run"], "1")
        self.assertTrue(options["start_new_session"])
        self.assertEqual(command, original)

    def test_all_preparation_and_exploration_launches_are_owned(self):
        popen = mock.Mock(side_effect=[mock.Mock(pid=201), mock.Mock(pid=202)])
        supervisor = self.driver.ProcessSupervisor(popen)
        with mock.patch.object(self.permissions.os, "geteuid", return_value=0, create=True):
            supervisor(["sudo", "Dry_Run=1", "./reorder_3_bad"])
            # The official exploration factory already sets its process group.
            with mock.patch.object(os, "setpgrp", create=True) as group_setup:
                supervisor(["sudo", "DBDS_Run=1", "./reorder_3_bad"], preexec_fn=group_setup)
        self.assertEqual(len(supervisor.processes), 2)
        self.assertTrue(all(owned for _, owned in supervisor.processes))
        self.assertTrue(popen.call_args_list[0][1]["start_new_session"])
        self.assertNotIn("start_new_session", popen.call_args_list[1][1])

    def test_exited_leaders_still_get_group_cleanup_and_errors_are_not_hidden(self):
        processes = [mock.Mock(pid=301), mock.Mock(pid=302)]
        for process in processes:
            process.poll.return_value = 0
        supervisor = self.driver.ProcessSupervisor(mock.Mock())
        supervisor.processes = [(process, True) for process in processes]
        with mock.patch.object(self.permissions, "cleanup_owned_process", side_effect=[PermissionError("denied"), None]) as cleanup:
            with self.assertRaisesRegex(RuntimeError, "denied"):
                supervisor.cleanup()
        self.assertEqual(cleanup.call_count, 2)
        self.assertEqual(cleanup.call_args_list[1], mock.call(processes[1], own_group=True))

    def test_signal_during_launch_is_delivered_after_child_registration(self):
        process = mock.Mock(pid=401)
        supervisor = self.driver.ProcessSupervisor(None)
        def launch(*args, **kwargs):
            self.assertTrue(supervisor.defer_signal(signal.SIGTERM))
            return process
        def interrupted(signum, frame):
            self.assertEqual(supervisor.processes, [(process, True)])
            self.assertFalse(supervisor.launching)
            raise InterruptedError("deferred TERM")
        supervisor.popen = launch
        with mock.patch.object(self.driver.signal, "getsignal", return_value=interrupted):
            with self.assertRaisesRegex(InterruptedError, "deferred TERM"):
                supervisor(["./harmless-placeholder"])


if __name__ == "__main__":
    unittest.main()
