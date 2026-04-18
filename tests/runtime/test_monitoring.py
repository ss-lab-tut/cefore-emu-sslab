"""Unit tests for src/runtime/monitoring.py (Monitor class)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.runtime.monitoring import Monitor


def _make_net(host_count=3):
    """Return a fake Mininet-like object."""
    net = MagicMock()
    net.hosts = [MagicMock() for _ in range(host_count)]
    for h in net.hosts:
        h.cmd.return_value = "status output"
    return net


def _csmgrstatus_target(**kwargs):
    return {"type": "csmgrstatus", **kwargs}


def _cefstatus_target(**kwargs):
    return {"type": "cefstatus", **kwargs}


# ---------------------------------------------------------------------------
# Constructor — resolver is now optional (no ValueError for missing resolver)
# ---------------------------------------------------------------------------

class TestMonitorInitValidation:
    """Monitor.__init__ always succeeds; missing resolver defaults to 127.0.0.1."""

    def test_no_resolver_accepted_for_csmgrstatus(self, tmp_path):
        # Should not raise even without a resolver.
        Monitor(
            _make_net(),
            targets=[_csmgrstatus_target(hosts="all")],
            interval=1,
            output_dir=tmp_path,
            host_count=2,
            csmgr_host_resolver=None,
        )

    def test_resolver_not_required_when_all_csmgrstatus_have_explicit_target_host(self, tmp_path):
        Monitor(
            _make_net(),
            targets=[_csmgrstatus_target(target_host="192.168.1.1")],
            interval=1,
            output_dir=tmp_path,
            host_count=2,
            csmgr_host_resolver=None,
        )

    def test_cefstatus_only_resolver_not_required(self, tmp_path):
        Monitor(
            _make_net(),
            targets=[_cefstatus_target(hosts="all")],
            interval=1,
            output_dir=tmp_path,
            host_count=2,
            csmgr_host_resolver=None,
        )

    def test_empty_targets_resolver_not_required(self, tmp_path):
        Monitor(
            _make_net(),
            targets=[],
            interval=1,
            output_dir=tmp_path,
            csmgr_host_resolver=None,
        )

    def test_empty_string_target_host_accepted_without_resolver(self, tmp_path):
        # Empty target_host falls back to loopback, no ValueError.
        Monitor(
            _make_net(),
            targets=[_csmgrstatus_target(target_host="")],
            interval=1,
            output_dir=tmp_path,
            host_count=2,
            csmgr_host_resolver=None,
        )

    def test_non_string_target_host_accepted_without_resolver(self, tmp_path):
        # Non-string target_host falls back to loopback, no ValueError.
        Monitor(
            _make_net(),
            targets=[_csmgrstatus_target(target_host=12345)],
            interval=1,
            output_dir=tmp_path,
            host_count=2,
            csmgr_host_resolver=None,
        )

    def test_resolver_provided_is_accepted(self, tmp_path):
        resolver = lambda h: f"192.168.1.{h + 1}"
        Monitor(
            _make_net(),
            targets=[_csmgrstatus_target(hosts="all")],
            interval=1,
            output_dir=tmp_path,
            host_count=2,
            csmgr_host_resolver=resolver,
        )


# ---------------------------------------------------------------------------
# _collect_target — resolver-based IP
# ---------------------------------------------------------------------------

class TestCollectTargetCsmgrstatus:
    def _make_monitor(self, tmp_path, resolver, targets=None, host_count=3):
        if targets is None:
            targets = [_csmgrstatus_target(hosts="all")]
        return Monitor(
            _make_net(host_count),
            targets=targets,
            interval=1,
            output_dir=tmp_path,
            host_count=host_count,
            csmgr_host_resolver=resolver,
        )

    def test_resolver_called_with_host_idx(self, tmp_path):
        resolver = MagicMock(return_value="192.168.3.4")
        monitor = self._make_monitor(tmp_path, resolver=resolver)
        with patch("src.runtime.monitoring.run_csmgrstatus", return_value="ok") as mock_fn:
            monitor._collect_target("csmgrstatus", 2, {"type": "csmgrstatus"})
        resolver.assert_called_once_with(2)
        mock_fn.assert_called_once()
        _, kwargs = mock_fn.call_args
        assert kwargs.get("host") == "192.168.3.4"

    def test_resolver_ip_passed_to_run_csmgrstatus(self, tmp_path):
        resolver = lambda h: f"172.20.{h}.1"
        monitor = self._make_monitor(tmp_path, resolver=resolver)
        with patch("src.runtime.monitoring.run_csmgrstatus", return_value="ok") as mock_fn:
            monitor._collect_target("csmgrstatus", 1, {"type": "csmgrstatus"})
        _, kwargs = mock_fn.call_args
        assert kwargs["host"] == "172.20.1.1"

    def test_target_host_override_takes_priority_over_resolver(self, tmp_path):
        resolver = MagicMock(return_value="192.168.1.1")
        monitor = self._make_monitor(tmp_path, resolver=resolver)
        with patch("src.runtime.monitoring.run_csmgrstatus", return_value="ok") as mock_fn:
            monitor._collect_target(
                "csmgrstatus", 0, {"type": "csmgrstatus", "target_host": "10.99.0.1"}
            )
        resolver.assert_not_called()
        _, kwargs = mock_fn.call_args
        assert kwargs["host"] == "10.99.0.1"

    def test_empty_target_host_falls_back_to_resolver(self, tmp_path):
        resolver = MagicMock(return_value="192.168.5.1")
        monitor = self._make_monitor(tmp_path, resolver=resolver)
        with patch("src.runtime.monitoring.run_csmgrstatus", return_value="ok") as mock_fn:
            monitor._collect_target(
                "csmgrstatus", 0, {"type": "csmgrstatus", "target_host": ""}
            )
        resolver.assert_called_once_with(0)
        _, kwargs = mock_fn.call_args
        assert kwargs["host"] == "192.168.5.1"

    def test_non_string_target_host_falls_back_to_resolver(self, tmp_path):
        resolver = MagicMock(return_value="192.168.5.1")
        # A target_host=12345 passes init only if resolver is provided (validated above)
        # so we directly test the fallback path with a monkeypatched monitor.
        monitor = self._make_monitor(tmp_path, resolver=resolver)
        with patch("src.runtime.monitoring.run_csmgrstatus", return_value="ok") as mock_fn:
            monitor._collect_target(
                "csmgrstatus", 0, {"type": "csmgrstatus", "target_host": 12345}
            )
        resolver.assert_called_once_with(0)
        _, kwargs = mock_fn.call_args
        assert kwargs["host"] == "192.168.5.1"

    def test_no_resolver_falls_back_to_loopback(self, tmp_path):
        """When no resolver and no target_host, csmgrstatus must use 127.0.0.1."""
        monitor = Monitor(
            _make_net(3),
            targets=[_csmgrstatus_target(hosts="all")],
            interval=1,
            output_dir=tmp_path,
            host_count=3,
            csmgr_host_resolver=None,
        )
        with patch("src.runtime.monitoring.run_csmgrstatus", return_value="ok") as mock_fn:
            monitor._collect_target("csmgrstatus", 1, {"type": "csmgrstatus"})
        _, kwargs = mock_fn.call_args
        assert kwargs.get("host") == "127.0.0.1"

    def test_empty_target_host_no_resolver_falls_back_to_loopback(self, tmp_path):
        monitor = Monitor(
            _make_net(3),
            targets=[_csmgrstatus_target(target_host="")],
            interval=1,
            output_dir=tmp_path,
            host_count=3,
            csmgr_host_resolver=None,
        )
        with patch("src.runtime.monitoring.run_csmgrstatus", return_value="ok") as mock_fn:
            monitor._collect_target("csmgrstatus", 0, {"type": "csmgrstatus", "target_host": ""})
        _, kwargs = mock_fn.call_args
        assert kwargs.get("host") == "127.0.0.1"

    def test_uri_and_port_num_forwarded(self, tmp_path):
        resolver = lambda h: "192.168.1.1"
        monitor = self._make_monitor(tmp_path, resolver=resolver)
        target = {"type": "csmgrstatus", "uri": "ccnx:/test", "port_num": 9696}
        with patch("src.runtime.monitoring.run_csmgrstatus", return_value="ok") as mock_fn:
            monitor._collect_target("csmgrstatus", 0, target)
        _, kwargs = mock_fn.call_args
        assert kwargs["uri"] == "ccnx:/test"
        assert kwargs["port_num"] == 9696


# ---------------------------------------------------------------------------
# cefstatus does not need resolver
# ---------------------------------------------------------------------------

class TestCollectTargetCefstatus:
    def test_cefstatus_uses_net_cmd(self, tmp_path):
        net = _make_net(3)
        monitor = Monitor(
            net,
            targets=[_cefstatus_target(hosts="all")],
            interval=1,
            output_dir=tmp_path,
            host_count=3,
        )
        monitor._collect_target("cefstatus", 0, {"type": "cefstatus"})
        net.hosts[0].cmd.assert_called_once_with("cefstatus -d ./h0")
