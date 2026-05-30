"""Unit tests for cefore runtime command construction."""

import subprocess
import threading
from unittest.mock import MagicMock, call, patch

import pytest

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


def _make_net(host_count=3):
    """Create a mock Mininet network."""
    proc = MagicMock()
    proc.wait.return_value = 0

    host = MagicMock()
    host.popen.return_value = proc

    net = MagicMock()
    net.hosts = [host] * host_count
    net.get.return_value = host
    return net, host, proc


# ---------------------------------------------------------------------------
# run_cefputfile
# ---------------------------------------------------------------------------

class TestRunCefputfile:
    def test_redirects_stderr_to_log(self):
        net, host, _proc = _make_net()
        run_cefputfile(net, 2, "ccnx:/test/sample", log_name="/tmp/put.log")
        cmd = host.popen.call_args[0][0]
        assert "2>&1" in cmd
        assert "/tmp/put.log" in cmd

    def test_no_devnull(self):
        net, host, _proc = _make_net()
        run_cefputfile(net, 2, "ccnx:/test/sample", log_name="/tmp/put.log")
        kwargs = host.popen.call_args[1]
        assert kwargs.get("stderr") is None

    def test_default_log_name(self):
        net, host, _proc = _make_net()
        run_cefputfile(net, 2, "ccnx:/test/sample")
        cmd = host.popen.call_args[0][0]
        assert "cefputfile-h2.log" in cmd

    def test_cancellation_terminates_running_command(self):
        net, _host, proc = _make_net()
        proc.returncode = -15
        cancelled = threading.Event()
        cancelled.set()
        assert run_cefputfile(
            net, 2, "ccnx:/test/sample", cancel_event=cancelled
        ) == -15
        proc.terminate.assert_called_once()


# ---------------------------------------------------------------------------
# run_cefgetfile
# ---------------------------------------------------------------------------

class TestRunCefgetfile:
    def test_redirects_stderr_to_log(self):
        net, host, _proc = _make_net()
        run_cefgetfile(net, 0, "ccnx:/test/sample", "/tmp/recv", log_name="/tmp/get.log")
        cmd = host.popen.call_args[0][0]
        assert "2>&1" in cmd
        assert "/tmp/get.log" in cmd

    def test_default_log_name(self):
        net, host, _proc = _make_net()
        run_cefgetfile(net, 0, "ccnx:/test/sample", "/tmp/recv")
        cmd = host.popen.call_args[0][0]
        assert "cefgetfile-h0.log" in cmd

    def test_timeout_terminates_running_command(self):
        net, _host, proc = _make_net()
        proc.returncode = -15
        proc.wait.side_effect = [0]
        assert run_cefgetfile(
            net, 0, "ccnx:/test/sample", "/tmp/recv", timeout=0
        ) == -15
        proc.terminate.assert_called_once()


# ---------------------------------------------------------------------------
# run_cefsubfile
# ---------------------------------------------------------------------------

class TestRunCefsubfile:
    def test_redirects_stderr_to_log(self):
        net, host, _proc = _make_net()
        run_cefsubfile(net, 0, "ccnx:/test/stream", output_path="/tmp/recvdir", log_name="/tmp/sub.log")
        cmd = host.popen.call_args[0][0]
        assert "2>&1" in cmd
        assert "/tmp/sub.log" in cmd

    def test_passes_directory_with_f_flag(self):
        net, host, _proc = _make_net()
        run_cefsubfile(net, 0, "ccnx:/test/stream", output_path="/tmp/recvdir")
        cmd = host.popen.call_args[0][0]
        assert "-f /tmp/recvdir" in cmd

    def test_default_log_name(self):
        net, host, _proc = _make_net()
        run_cefsubfile(net, 0, "ccnx:/test/stream")
        cmd = host.popen.call_args[0][0]
        assert "cefsubfile-h0.log" in cmd


# ---------------------------------------------------------------------------
# start_cefsubfile
# ---------------------------------------------------------------------------

class TestStartCefsubfile:
    def test_redirects_stderr_to_log(self):
        net, host, _proc = _make_net()
        start_cefsubfile(net, 0, "ccnx:/test/stream", output_path="/tmp/recvdir", log_name="/tmp/sub.log")
        cmd = host.popen.call_args[0][0]
        assert "2>&1" in cmd
        assert "/tmp/sub.log" in cmd

    def test_returns_popen_process(self):
        net, host, proc = _make_net()
        result = start_cefsubfile(net, 0, "ccnx:/test/stream")
        assert result is proc


# ---------------------------------------------------------------------------
# run_cefpubfile
# ---------------------------------------------------------------------------

class TestRunCefpubfile:
    def test_redirects_stderr_to_log(self):
        net, host, _proc = _make_net()
        run_cefpubfile(net, 2, "ccnx:/test/stream", "/tmp/pub.bin", log_name="/tmp/pub.log")
        # run_cefpubfile uses net.get(node_name), not net.hosts[idx]
        host2 = net.get.return_value
        cmd = host2.popen.call_args[0][0]
        assert "2>&1" in cmd
        assert "/tmp/pub.log" in cmd

    def test_no_devnull_kwarg(self):
        net, host, _proc = _make_net()
        run_cefpubfile(net, 2, "ccnx:/test/stream", "/tmp/pub.bin", log_name="/tmp/pub.log")
        host2 = net.get.return_value
        kwargs = host2.popen.call_args[1]
        assert "stderr" not in kwargs

    def test_default_log_name(self):
        net, host, _proc = _make_net()
        run_cefpubfile(net, 2, "ccnx:/test/stream", "/tmp/pub.bin")
        host2 = net.get.return_value
        cmd = host2.popen.call_args[0][0]
        assert "cefpubfile-h2.log" in cmd


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
