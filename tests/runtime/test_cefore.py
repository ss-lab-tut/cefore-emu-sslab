"""Unit tests for cefore runtime command construction."""

from unittest.mock import MagicMock, patch

import src.runtime.cefore as cefore_mod
from src.runtime.cefore import (
    run_cefgetfile,
    run_cefpubfile,
    run_cefputfile,
    run_cefsubfile,
    run_csmgrstatus,
    start_cefsubfile,
)
from src.runtime.command_runner import FakeCommandRunner


def _argv_str(argv):
    return " ".join(str(a) for a in argv)


# ---------------------------------------------------------------------------
# run_cefputfile — now argv + CommandRunner based
# ---------------------------------------------------------------------------

class TestRunCefputfile:
    def test_log_path_owns_redirect_not_argv(self):
        fake = FakeCommandRunner()
        run_cefputfile(fake, 2, "ccnx:/test/sample", log_name="/tmp/put.log")
        rec = fake.runs[0]
        assert rec["node"] == "h2"
        assert rec["log_path"] == "/tmp/put.log"
        # Redirection is owned by the seam, never present in argv.
        assert "2>&1" not in _argv_str(rec["argv"])
        assert ">" not in _argv_str(rec["argv"])

    def test_builds_expected_argv(self):
        fake = FakeCommandRunner()
        run_cefputfile(fake, 2, "ccnx:/test/sample", "/data/in.bin")
        argv = fake.runs[0]["argv"]
        assert argv[:4] == ["cefputfile", "ccnx:/test/sample", "-f", "/data/in.bin"]
        assert argv[-2:] == ["-d", "./h2"]

    def test_default_log_name(self):
        fake = FakeCommandRunner()
        run_cefputfile(fake, 2, "ccnx:/test/sample")
        assert fake.runs[0]["log_path"] == "cefputfile-h2.log"

    def test_returns_returncode(self):
        fake = FakeCommandRunner()
        fake.script_run(returncode=-15, cancelled=True)
        assert run_cefputfile(fake, 2, "ccnx:/test/sample") == -15

    def test_passes_timeout_and_cancel_event(self):
        fake = FakeCommandRunner()
        sentinel = object()
        run_cefputfile(
            fake, 2, "ccnx:/test/sample", timeout=7, cancel_event=sentinel
        )
        assert fake.runs[0]["timeout"] == 7
        assert fake.runs[0]["cancel_event"] is sentinel


# ---------------------------------------------------------------------------
# run_cefgetfile
# ---------------------------------------------------------------------------

class TestRunCefgetfile:
    def test_builds_expected_argv_and_log(self):
        fake = FakeCommandRunner()
        run_cefgetfile(
            fake, 0, "ccnx:/test/sample", "/tmp/recv", log_name="/tmp/get.log"
        )
        rec = fake.runs[0]
        assert rec["node"] == "h0"
        assert rec["argv"][:4] == ["cefgetfile", "ccnx:/test/sample", "-f", "/tmp/recv"]
        assert rec["log_path"] == "/tmp/get.log"
        assert "2>&1" not in _argv_str(rec["argv"])

    def test_default_log_name(self):
        fake = FakeCommandRunner()
        run_cefgetfile(fake, 0, "ccnx:/test/sample", "/tmp/recv")
        assert fake.runs[0]["log_path"] == "cefgetfile-h0.log"

    def test_timeout_returncode(self):
        fake = FakeCommandRunner()
        fake.script_run(returncode=-15, timed_out=True)
        assert run_cefgetfile(
            fake, 0, "ccnx:/test/sample", "/tmp/recv", timeout=0
        ) == -15
        assert fake.runs[0]["timeout"] == 0


# ---------------------------------------------------------------------------
# run_cefsubfile (blocking)
# ---------------------------------------------------------------------------

class TestRunCefsubfile:
    def test_builds_expected_argv_and_log(self):
        fake = FakeCommandRunner()
        run_cefsubfile(
            fake, 0, "ccnx:/test/stream",
            output_path="/tmp/recvdir", log_name="/tmp/sub.log",
        )
        rec = fake.runs[0]
        assert rec["argv"][argv_index(rec["argv"], "-f") + 1] == "/tmp/recvdir"
        assert rec["log_path"] == "/tmp/sub.log"
        assert "2>&1" not in _argv_str(rec["argv"])

    def test_default_log_name(self):
        fake = FakeCommandRunner()
        run_cefsubfile(fake, 0, "ccnx:/test/stream")
        assert fake.runs[0]["log_path"] == "cefsubfile-h0.log"

    def test_returns_returncode(self):
        fake = FakeCommandRunner()
        fake.script_run(returncode=0)
        assert run_cefsubfile(fake, 0, "ccnx:/test/stream") == 0


# ---------------------------------------------------------------------------
# start_cefsubfile — non-blocking, returns a CommandHandle
# ---------------------------------------------------------------------------

class TestStartCefsubfile:
    def test_starts_and_records_handle(self):
        fake = FakeCommandRunner()
        handle = start_cefsubfile(
            fake, 0, "ccnx:/test/stream",
            output_path="/tmp/recvdir", log_name="/tmp/sub.log",
        )
        assert handle is fake.starts[0]
        assert handle.node == "h0"
        assert handle.log_path == "/tmp/sub.log"
        assert "2>&1" not in _argv_str(handle.argv)

    def test_default_log_name(self):
        fake = FakeCommandRunner()
        start_cefsubfile(fake, 0, "ccnx:/test/stream")
        assert fake.starts[0].log_path == "cefsubfile-h0.log"


# ---------------------------------------------------------------------------
# run_cefpubfile — non-blocking, returns a CommandHandle
# ---------------------------------------------------------------------------

class TestRunCefpubfile:
    def test_starts_and_records_handle(self):
        fake = FakeCommandRunner()
        handle = run_cefpubfile(
            fake, 2, "ccnx:/test/stream", "/tmp/pub.bin", log_name="/tmp/pub.log"
        )
        assert handle is fake.starts[0]
        assert handle.node == "h2"
        assert handle.argv[:4] == ["cefpubfile", "ccnx:/test/stream", "-f", "/tmp/pub.bin"]
        assert handle.log_path == "/tmp/pub.log"

    def test_default_log_name(self):
        fake = FakeCommandRunner()
        run_cefpubfile(fake, 2, "ccnx:/test/stream", "/tmp/pub.bin")
        assert fake.starts[0].log_path == "cefpubfile-h2.log"


def argv_index(argv, flag):
    return argv.index(flag)


# ---------------------------------------------------------------------------
# run_csmgrstatus — now argv + CommandRunner based
# ---------------------------------------------------------------------------

class TestRunCsmgrstatus:
    def test_default_runs_argv_and_emits_output(self):
        fake = FakeCommandRunner()
        fake.script_run(stdout="status output")
        with patch.object(cefore_mod, "MininetCommandRunner", return_value=fake), \
                patch.object(cefore_mod, "info") as mock_info:
            out = run_csmgrstatus(MagicMock(), 1, uri="ccnx:/", host="127.0.0.1")
        assert out == "status output"
        rec = fake.runs[0]
        assert rec["node"] == "h1"
        assert rec["argv"] == ["csmgrstatus", "ccnx:/", "-h", "127.0.0.1"]
        # Redirection is owned by the seam, never present in argv.
        assert ">" not in _argv_str(rec["argv"])
        mock_info.assert_called_once_with("status output")

    def test_quiet_suppresses_print_and_info(self, capsys):
        fake = FakeCommandRunner()
        fake.script_run(stdout="status output")
        with patch.object(cefore_mod, "MininetCommandRunner", return_value=fake), \
                patch.object(cefore_mod, "info") as mock_info:
            out = run_csmgrstatus(
                MagicMock(), 1, uri="ccnx:/", host="127.0.0.1", quiet=True
            )
        assert out == "status output"
        mock_info.assert_not_called()
        assert "command:" not in capsys.readouterr().out

    def test_log_name_redirects_stdout_only(self):
        fake = FakeCommandRunner()
        with patch.object(cefore_mod, "MininetCommandRunner", return_value=fake):
            run_csmgrstatus(
                MagicMock(), 1, host="127.0.0.1", log_name="/tmp/c.log", quiet=True
            )
        rec = fake.runs[0]
        assert rec["log_path"] == "/tmp/c.log"
        # stdout-only-to-log: stderr kept separate so the log stays stdout-only.
        assert rec["capture_stderr"] is True

    def test_timeout_forwarded(self):
        fake = FakeCommandRunner()
        with patch.object(cefore_mod, "MininetCommandRunner", return_value=fake):
            run_csmgrstatus(MagicMock(), 1, host="127.0.0.1", quiet=True, timeout=10)
        assert fake.runs[0]["timeout"] == 10

    def test_port_num_builds_two_token_argv(self):
        fake = FakeCommandRunner()
        with patch.object(cefore_mod, "MininetCommandRunner", return_value=fake):
            run_csmgrstatus(MagicMock(), 1, port_num=9799, host="127.0.0.1", quiet=True)
        argv = fake.runs[0]["argv"]
        assert argv == ["csmgrstatus", "-p", "9799", "-h", "127.0.0.1"]

    def test_timeout_returns_diagnostic_string(self):
        fake = FakeCommandRunner()
        fake.script_run(timed_out=True)
        with patch.object(cefore_mod, "MininetCommandRunner", return_value=fake):
            out = run_csmgrstatus(MagicMock(), 1, host="127.0.0.1", quiet=True)
        assert out == "error: command timeout"
