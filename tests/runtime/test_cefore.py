"""Unit tests for cefore runtime command construction."""

import subprocess
from unittest.mock import MagicMock, patch

import src.runtime.cefore as cefore_mod
from src.runtime.cefore import (
    popen_capture,
    run_cefgetfile,
    run_cefpubfile,
    run_cefputfile,
    run_cefsubfile,
    run_csmgrstatus,
    start_cefsubfile,
)
from src.runtime.command_runner import FakeCommandRunner


def _make_net(host_count=3):
    """Create a mock Mininet network (for the net-based status wrappers)."""
    proc = MagicMock()
    proc.wait.return_value = 0

    host = MagicMock()
    host.popen.return_value = proc

    net = MagicMock()
    net.hosts = [host] * host_count
    net.get.return_value = host
    return net, host, proc


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
# popen_capture
# ---------------------------------------------------------------------------

class TestPopenCapture:
    def test_returns_decoded_stdout(self):
        node = MagicMock()
        proc = MagicMock()
        proc.communicate.return_value = (b"hello\n", None)
        node.popen.return_value = proc
        assert popen_capture(node, "cefstatus -d ./h1", timeout=5) == "hello\n"

    def test_popen_kwargs_no_shared_shell(self):
        node = MagicMock()
        proc = MagicMock()
        proc.communicate.return_value = (b"", None)
        node.popen.return_value = proc
        popen_capture(node, "cmd", timeout=3)
        kwargs = node.popen.call_args[1]
        assert kwargs["shell"] is True
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["stdout"] == subprocess.PIPE
        assert kwargs["stderr"] == subprocess.STDOUT
        proc.communicate.assert_called_once_with(timeout=3)

    def test_timeout_terminates_and_reports(self):
        node = MagicMock()
        proc = MagicMock()
        proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="cmd", timeout=2)
        node.popen.return_value = proc
        with patch.object(cefore_mod, "_terminate_process") as mock_term:
            result = popen_capture(node, "cmd", timeout=2)
        mock_term.assert_called_once_with(proc)
        assert result == "error: command timeout"


# ---------------------------------------------------------------------------
# run_csmgrstatus — quiet / use_popen
# ---------------------------------------------------------------------------

class TestRunCsmgrstatus:
    def test_default_uses_cmd_and_emits_output(self):
        net, host, _proc = _make_net()
        host.cmd.return_value = "status output"
        with patch.object(cefore_mod, "info") as mock_info:
            out = run_csmgrstatus(net, 1, uri="ccnx:/", host="127.0.0.1")
        assert out == "status output"
        host.cmd.assert_called_once()
        mock_info.assert_called_once_with("status output")

    def test_quiet_suppresses_print_and_info(self, capsys):
        net, host, _proc = _make_net()
        host.cmd.return_value = "status output"
        with patch.object(cefore_mod, "info") as mock_info:
            out = run_csmgrstatus(net, 1, uri="ccnx:/", host="127.0.0.1", quiet=True)
        assert out == "status output"
        mock_info.assert_not_called()
        assert "command:" not in capsys.readouterr().out

    def test_use_popen_routes_via_popen_capture(self):
        net, host, _proc = _make_net()
        with patch.object(
            cefore_mod, "popen_capture", return_value="popen out"
        ) as mock_cap:
            out = run_csmgrstatus(
                net, 1, uri="ccnx:/", host="127.0.0.1",
                quiet=True, use_popen=True, timeout=10,
            )
        assert out == "popen out"
        host.cmd.assert_not_called()
        mock_cap.assert_called_once()
        assert mock_cap.call_args[0][0] is net.hosts[1]
        assert mock_cap.call_args[1]["timeout"] == 10
