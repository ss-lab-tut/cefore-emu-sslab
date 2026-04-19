"""Unit tests for cefore runtime command construction."""

from unittest.mock import MagicMock, call, patch

import pytest

import src.runtime.cefore as cefore_mod
from src.runtime.cefore import (
    run_cefgetfile,
    run_cefpubfile,
    run_cefputfile,
    run_cefsubfile,
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
