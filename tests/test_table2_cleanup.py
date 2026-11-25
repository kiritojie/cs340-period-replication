"""Cleanup regressions; Linux cases use real harmless subprocesses and pipes.

No PERIOD target or SCHED_DEADLINE operation is started by these tests. Linux
cases intentionally remain skipped on Windows instead of certifying that path.
"""
import ctypes
import importlib.util
import io
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "table2_cleanup_permissions_test", ROOT / "scripts/table2_scheduler_permissions.py")
PERMISSIONS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PERMISSIONS)


class FinishedProcess:
    """A concrete Popen stand-in whose drained pipes forbid communicate again."""
    pid = 7654321
    returncode = 0

    def __init__(self):
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.stdout.close()
        self.stderr.close()
        self.stdin = None
        self.communicate = mock.Mock(side_effect=AssertionError("closed pipes must not be communicated again"))
        self.wait = mock.Mock(return_value=0)

    def poll(self):
        return self.returncode


class CleanupRegressionTests(unittest.TestCase):
    def test_closed_pipes_skip_communicate_but_still_signal_exited_leader_group(self):
        process = FinishedProcess()
        with mock.patch.object(PERMISSIONS, "kill_process_group", return_value=False) as kill:
            first = PERMISSIONS.cleanup_owned_process(process)
            second = PERMISSIONS.cleanup_owned_process(process)
        process.communicate.assert_not_called()
        self.assertEqual(first["returncode"], 0)
        self.assertEqual(second["returncode"], 0)
        self.assertEqual(first["output"], second["output"])
        kill.assert_any_call(process.pid, PERMISSIONS.SIGKILL)
        self.assertTrue(all(call == mock.call(process.pid, PERMISSIONS.SIGKILL)
                            for call in kill.call_args_list))

    def test_no_pipe_process_is_reaped_without_communicate(self):
        process = FinishedProcess()
        process.stdout = process.stderr = None
        result = PERMISSIONS.cleanup_owned_process(process, own_group=False)
        self.assertEqual(result["returncode"], 0)
        process.communicate.assert_not_called()
        self.assertTrue(process.wait.called)

    def test_probe_retains_kernel_result_raw_output_and_exit_when_cleanup_fails(self):
        for child_status, child_exit, kernel_return in (("PASS", 0, 0), ("BLOCKED", 1, -1)):
            with self.subTest(child_status=child_status):
                raw = json.dumps({"status": child_status,
                                  "sched_setattr": {"return": kernel_return, "errno": 0 if kernel_return == 0 else 1},
                                  "readback": {"policy": 6 if kernel_return == 0 else 0}}) + "\n"
                process = FinishedProcess()
                process.returncode = child_exit
                process.communicate = mock.Mock(return_value=(raw, "native diagnostic\n"))
                with mock.patch.object(PERMISSIONS, "_popen", return_value=process), \
                        mock.patch.object(PERMISSIONS, "cleanup_owned_process",
                                          side_effect=RuntimeError("later cleanup failed")):
                    record = PERMISSIONS._run_probe("sched_deadline")
                self.assertEqual(record["status"], "BLOCKED")
                self.assertEqual(record["probe_status"], child_status)
                self.assertEqual(record["exit_code"], child_exit)
                self.assertEqual(record["child_exit_code"], child_exit)
                self.assertEqual(record["sched_setattr"]["return"], kernel_return)
                self.assertEqual(record["stdout"], raw)
                self.assertEqual(record["stderr"], "native diagnostic\n")
                detail = record["cleanup_errors"][0]
                self.assertIn("later cleanup failed", detail["error"])
                self.assertIn("Traceback (most recent call last)", detail["traceback"])
                self.assertIn("_run_probe", detail["traceback"])

    def test_probe_success_is_not_replaced_by_finally_recommunicating_closed_pipes(self):
        process = FinishedProcess()
        raw = json.dumps({"status": "PASS", "sched_setattr": {"return": 0}})
        process.stdout = io.StringIO()
        process.stderr = io.StringIO()
        def communicate(timeout=None):
            if process.stdout.closed or process.stderr.closed:
                raise ValueError("Invalid file object: closed probe pipe")
            process.stdout.close()
            process.stderr.close()
            return raw, ""
        process.communicate = mock.Mock(side_effect=communicate)
        with mock.patch.object(PERMISSIONS, "_popen", return_value=process), \
                mock.patch.object(PERMISSIONS, "kill_process_group", return_value=False):
            record = PERMISSIONS._run_probe("sched_deadline")
        self.assertEqual(record["status"], "PASS")
        self.assertEqual(record["exit_code"], 0)
        self.assertEqual(record["sched_setattr"]["return"], 0)
        self.assertEqual(process.communicate.call_count, 1)


@unittest.skipUnless(sys.platform == "linux", "requires real Linux subprocess and process-group semantics")
class LinuxCleanupRegressionTests(unittest.TestCase):
    def spawn(self, program):
        process = subprocess.Popen([sys.executable, "-u", "-c", program],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        self.addCleanup(self.force_cleanup, process)
        return process

    @staticmethod
    def force_cleanup(process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)
        for stream in (process.stdout, process.stderr, process.stdin):
            if stream is not None and not stream.closed:
                stream.close()

    @staticmethod
    def read_line(stream, timeout=3):
        deadline = time.monotonic() + timeout
        data = b""
        while not data.endswith(b"\n"):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([stream], [], [], remaining)[0]:
                raise AssertionError("harmless child did not become ready")
            chunk = os.read(stream.fileno(), 1)
            if not chunk:
                raise AssertionError("harmless child exited before readiness")
            data += chunk
        return data.strip()

    def test_real_completed_communicate_then_repeated_cleanup_never_reopens_pipes(self):
        process = self.spawn("import sys; print('out'); print('err', file=sys.stderr)")
        self.assertEqual(process.communicate(timeout=3), (b"out\n", b"err\n"))
        self.assertTrue(process.stdout.closed and process.stderr.closed)
        with mock.patch.object(process, "communicate", side_effect=AssertionError("drained pipes reused")):
            self.assertEqual(PERMISSIONS.cleanup_owned_process(process)["returncode"], 0)
            self.assertEqual(PERMISSIONS.cleanup_owned_process(process)["returncode"], 0)

    def test_real_timeout_kill_and_repeated_cleanup_preserve_collected_output(self):
        process = self.spawn("import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                             "print('ready',flush=True); time.sleep(30)")
        self.assertEqual(self.read_line(process.stdout), b"ready")
        os.killpg(process.pid, signal.SIGTERM)
        with self.assertRaises(subprocess.TimeoutExpired):
            process.communicate(timeout=0.1)
        first = PERMISSIONS.cleanup_owned_process(process)
        self.assertEqual(first["returncode"], -signal.SIGKILL)
        with mock.patch.object(process, "communicate", side_effect=AssertionError("cleanup drained twice")):
            second = PERMISSIONS.cleanup_owned_process(process)
        self.assertEqual(second["returncode"], -signal.SIGKILL)
        self.assertEqual(second["output"], first["output"])

    def test_real_one_closed_pipe_drains_other_pipe_without_communicate(self):
        process = self.spawn("import sys,time; print('kept',file=sys.stderr,flush=True); "
                             "print('ready',flush=True); time.sleep(30)")
        self.assertEqual(self.read_line(process.stdout), b"ready")
        process.stdout.close()
        with mock.patch.object(process, "communicate", side_effect=AssertionError("partly closed pipes reused")):
            first = PERMISSIONS.cleanup_owned_process(process)
            second = PERMISSIONS.cleanup_owned_process(process)
        self.assertEqual(first["returncode"], -signal.SIGKILL)
        self.assertIn(b"kept", first["output"][1])
        self.assertEqual(first["output"], second["output"])
        self.assertTrue(process.stderr.closed)

    def test_real_exited_leader_still_has_descendant_killed_and_reaped(self):
        libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        self.assertEqual(libc.prctl(37, ctypes.byref(previous), 0, 0, 0), 0)
        self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)
        descendant = None
        try:
            program = ("import os,time\n"
                       "child=os.fork()\n"
                       "if child:\n"
                       " print(child,flush=True)\n"
                       " os._exit(0)\n"
                       "time.sleep(30)\n")
            process = self.spawn(program)
            descendant = int(self.read_line(process.stdout))
            self.assertEqual(process.wait(timeout=3), 0)
            self.assertTrue(Path("/proc/" + str(descendant)).exists())
            PERMISSIONS.cleanup_owned_process(process)
            deadline = time.monotonic() + 3
            while True:
                reaped, status = os.waitpid(descendant, os.WNOHANG)
                if reaped:
                    break
                if time.monotonic() >= deadline:
                    self.fail("adopted descendant did not exit after group cleanup")
                time.sleep(0.01)
            self.assertTrue(os.WIFSIGNALED(status))
            self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)
            self.assertFalse(Path("/proc/" + str(descendant)).exists())
            descendant = None
            PERMISSIONS.cleanup_owned_process(process)
        finally:
            try:
                if descendant is not None:
                    try:
                        os.kill(descendant, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    deadline = time.monotonic() + 3
                    while True:
                        try:
                            reaped, _ = os.waitpid(descendant, os.WNOHANG)
                        except ChildProcessError:
                            break
                        if reaped:
                            break
                        if time.monotonic() >= deadline:
                            self.fail("failed-test descendant did not exit within cleanup bound")
                        time.sleep(0.01)
            finally:
                self.assertEqual(libc.prctl(36, previous.value, 0, 0, 0), 0)


if __name__ == "__main__":
    unittest.main()
