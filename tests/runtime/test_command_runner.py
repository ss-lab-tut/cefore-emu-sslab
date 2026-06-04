"""Contract tests for the CommandRunner seam.

The MininetCommandRunner tests use the root sentinel with real, deterministic
shell utilities (echo / sleep / printf) so the real adapter's wait, deadline,
cancellation, and redirect behaviour is exercised without Mininet or sudo.
"""

import threading
import time

from src.runtime.command_runner import (
    ROOT_SENTINEL,
    FakeCommandRunner,
    MininetCommandRunner,
)


# ---------------------------------------------------------------------------
# FakeCommandRunner
# ---------------------------------------------------------------------------


class TestFakeCommandRunner:
    def test_run_records_call_and_returns_default_success(self):
        fake = FakeCommandRunner()
        result = fake.run("h2", ["cefputfile", "ccnx:/x"], log_path="/tmp/a.log")
        assert result.returncode == 0
        assert result.log_path == "/tmp/a.log"
        assert fake.runs[0]["node"] == "h2"
        assert fake.runs[0]["argv"] == ["cefputfile", "ccnx:/x"]
        assert fake.runs[0]["log_path"] == "/tmp/a.log"

    def test_run_consumes_scripted_results_in_order(self):
        fake = FakeCommandRunner()
        fake.script_run(returncode=3)
        fake.script_run(returncode=0)
        assert fake.run("h0", ["a"]).returncode == 3
        assert fake.run("h0", ["b"]).returncode == 0
        # Exhausted script falls back to default success.
        assert fake.run("h0", ["c"]).returncode == 0

    def test_wait_uses_scripted_flags(self):
        fake = FakeCommandRunner()
        fake.script_wait(returncode=-15, timed_out=True)
        handle = fake.start("h1", ["cefsubfile", "ccnx:/s"], log_path="/tmp/s.log")
        result = fake.wait(handle)
        assert result.returncode == -15
        assert result.timed_out is True
        assert result.log_path == "/tmp/s.log"

    def test_on_start_hook_can_create_artifacts(self, tmp_path):
        fake = FakeCommandRunner()

        def make_artifact(handle):
            # output dir is the argument after -f in the argv
            out_dir = tmp_path
            (out_dir / "RNP0xabc.out").write_bytes(b"data")

        fake.on_start = make_artifact
        fake.start("h1", ["cefsubfile", "ccnx:/s", "-f", str(tmp_path)])
        assert (tmp_path / "RNP0xabc.out").read_bytes() == b"data"

    def test_terminate_and_kill_mark_handle(self):
        fake = FakeCommandRunner()
        handle = fake.start("h1", ["sleep", "5"])
        fake.terminate(handle)
        fake.kill(handle)
        assert handle.terminated is True
        assert handle.killed is True


# ---------------------------------------------------------------------------
# MininetCommandRunner via root sentinel (real subprocesses)
# ---------------------------------------------------------------------------


class TestMininetCommandRunnerRoot:
    def test_run_capture_returns_stdout(self):
        runner = MininetCommandRunner(net=None)
        result = runner.run(ROOT_SENTINEL, ["echo", "hello"])
        assert result.returncode == 0
        assert result.stdout.strip() == "hello"
        assert result.timed_out is False

    def test_run_redirects_to_log_file(self, tmp_path):
        log = tmp_path / "out.log"
        runner = MininetCommandRunner(net=None)
        result = runner.run(ROOT_SENTINEL, ["printf", "hi"], log_path=str(log))
        assert result.returncode == 0
        assert result.stdout == ""
        assert result.log_path == str(log)
        assert log.read_text() == "hi"

    def test_run_combines_stderr_into_log(self, tmp_path):
        log = tmp_path / "err.log"
        runner = MininetCommandRunner(net=None)
        # Write to stderr via sh; combined redirect must capture it.
        result = runner.run(
            ROOT_SENTINEL,
            ["sh", "-c", "echo oops 1>&2"],
            log_path=str(log),
        )
        assert result.returncode == 0
        assert "oops" in log.read_text()

    def test_run_timeout_sets_timed_out_and_terminates(self, tmp_path):
        log = tmp_path / "slow.log"
        runner = MininetCommandRunner(net=None)
        start = time.monotonic()
        result = runner.run(
            ROOT_SENTINEL, ["sleep", "10"], log_path=str(log), timeout=0.2
        )
        assert time.monotonic() - start < 5
        assert result.timed_out is True
        assert result.cancelled is False
        assert result.returncode != 0

    def test_start_wait_cancel_sets_cancelled(self, tmp_path):
        log = tmp_path / "cancel.log"
        runner = MininetCommandRunner(net=None)
        cancel = threading.Event()
        handle = runner.start(ROOT_SENTINEL, ["sleep", "10"], log_path=str(log))
        cancel.set()
        result = runner.wait(handle, cancel_event=cancel)
        assert result.cancelled is True
        assert result.timed_out is False

    def test_start_wait_completes_before_deadline(self, tmp_path):
        log = tmp_path / "fast.log"
        runner = MininetCommandRunner(net=None)
        handle = runner.start(ROOT_SENTINEL, ["true"], log_path=str(log))
        result = runner.wait(handle, deadline=time.monotonic() + 5)
        assert result.returncode == 0
        assert result.timed_out is False
        assert result.cancelled is False

    def test_poll_returns_none_then_code(self, tmp_path):
        log = tmp_path / "poll.log"
        runner = MininetCommandRunner(net=None)
        handle = runner.start(ROOT_SENTINEL, ["sleep", "0.3"], log_path=str(log))
        assert runner.poll(handle) is None
        runner.wait(handle, deadline=time.monotonic() + 5)
        assert runner.poll(handle) == 0
