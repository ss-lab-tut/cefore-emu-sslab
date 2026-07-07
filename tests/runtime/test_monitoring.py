"""Unit tests for src/runtime/monitoring.py (Monitor class)."""

import csv
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.runtime.command_runner import FakeCommandRunner
from src.runtime.monitoring import Monitor, _resolve_hosts


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
    def test_cefstatus_runs_via_runner(self, tmp_path):
        fake = FakeCommandRunner()
        fake.script_run(stdout="cef out")
        monitor = Monitor(
            MagicMock(),
            targets=[_cefstatus_target(hosts="all")],
            interval=1,
            output_dir=tmp_path,
            host_count=3,
        )
        with patch("src.runtime.monitoring.MininetCommandRunner", return_value=fake):
            out = monitor._collect_target("cefstatus", 0, {"type": "cefstatus"})
        assert out == "cef out"
        assert fake.runs[0]["node"] == "h0"
        assert fake.runs[0]["argv"] == ["cefstatus", "-d", "./h0"]
        # Non-background: no command timeout.
        assert fake.runs[0]["timeout"] is None


# ---------------------------------------------------------------------------
# Background mode — quiet + popen, no shared-shell contention
# ---------------------------------------------------------------------------

class TestBackgroundMode:
    def _bg_monitor(self, tmp_path, net=None, **kwargs):
        return Monitor(
            net or _make_net(3),
            targets=[_cefstatus_target(hosts="all")],
            interval=1,
            output_dir=tmp_path,
            host_count=3,
            background=True,
            **kwargs,
        )

    def test_background_flag_set_on_construction(self, tmp_path):
        monitor = self._bg_monitor(tmp_path)
        assert monitor._background.is_set()

    def test_enter_background_sets_flag(self, tmp_path):
        monitor = Monitor(
            _make_net(3),
            targets=[_cefstatus_target(hosts="all")],
            interval=1,
            output_dir=tmp_path,
            host_count=3,
        )
        assert not monitor._background.is_set()
        monitor.enter_background()
        assert monitor._background.is_set()

    def test_background_cefstatus_passes_command_timeout(self, tmp_path):
        fake = FakeCommandRunner()
        fake.script_run(stdout="cef out")
        monitor = self._bg_monitor(tmp_path, net=MagicMock(), command_timeout=7)
        with patch("src.runtime.monitoring.MininetCommandRunner", return_value=fake):
            out = monitor._collect_target("cefstatus", 1, {"type": "cefstatus"})
        assert out == "cef out"
        assert fake.runs[0]["node"] == "h1"
        assert fake.runs[0]["argv"] == ["cefstatus", "-d", "./h1"]
        # Background mode applies the command timeout.
        assert fake.runs[0]["timeout"] == 7

    def test_background_csmgrstatus_quiet_and_timeout(self, tmp_path):
        monitor = self._bg_monitor(tmp_path)  # default command_timeout=10
        with patch(
            "src.runtime.monitoring.run_csmgrstatus", return_value="ok"
        ) as mock_fn:
            monitor._collect_target("csmgrstatus", 0, {"type": "csmgrstatus"})
        _, kwargs = mock_fn.call_args
        assert kwargs["quiet"] is True
        assert kwargs["timeout"] == 10
        assert "use_popen" not in kwargs

    def test_background_down_host_skip_is_silent(self, tmp_path):
        monitor = self._bg_monitor(tmp_path)
        monitor._down_hosts_getter = lambda: [0]
        with patch("src.runtime.monitoring.info") as mock_info:
            out = monitor._collect_target("csmgrstatus", 0, {"type": "csmgrstatus"})
        assert out == "skipped: host down"
        mock_info.assert_not_called()

    def test_non_background_csmgrstatus_not_quiet(self, tmp_path):
        monitor = Monitor(
            _make_net(3),
            targets=[_csmgrstatus_target(hosts="all")],
            interval=1,
            output_dir=tmp_path,
            host_count=3,
        )
        with patch(
            "src.runtime.monitoring.run_csmgrstatus", return_value="ok"
        ) as mock_fn:
            monitor._collect_target("csmgrstatus", 0, {"type": "csmgrstatus"})
        _, kwargs = mock_fn.call_args
        assert kwargs["quiet"] is False
        # Foreground: unbounded, like the cefstatus foreground path.
        assert kwargs["timeout"] is None
        assert "use_popen" not in kwargs


# ---------------------------------------------------------------------------
# _resolve_hosts — pure translation of a target's "hosts" spec to indices
# ---------------------------------------------------------------------------

class TestResolveHosts:
    """_resolve_hosts turns a target's "hosts" spec into concrete host indices.

    Four branches: "all" (full range), "cache" (sorted cache node set),
    an explicit list (int-coerced, order preserved), and anything else
    (defensive empty list — e.g. a typo'd spec should not crash collection).
    """

    def test_all_spec_returns_the_full_host_range(self):
        assert _resolve_hosts("all", 4) == [0, 1, 2, 3]

    def test_cache_spec_returns_cache_nodes_sorted(self):
        assert _resolve_hosts("cache", 5, cache_nodes={3, 1}) == [1, 3]

    def test_cache_spec_with_no_cache_nodes_returns_empty_list(self):
        # cache_nodes=None must not raise (sorted(None or set()) path).
        assert _resolve_hosts("cache", 5, cache_nodes=None) == []

    def test_explicit_list_spec_coerces_entries_to_int_preserving_order(self):
        assert _resolve_hosts(["2", "0", 1], 5) == [2, 0, 1]

    def test_unknown_spec_returns_empty_list(self):
        # Neither "all", "cache", nor a list — defensive fallback.
        assert _resolve_hosts("bogus", 4) == []
        assert _resolve_hosts(None, 4) == []


# ---------------------------------------------------------------------------
# _collect_once — target/host iteration, error wrapping, stop-event
# short-circuit, and on_record dispatch. _collect_target itself is
# monkeypatched throughout so these tests never touch real collection
# (that is already covered by TestCollectTargetCsmgrstatus/Cefstatus above).
# ---------------------------------------------------------------------------

class TestCollectOnce:
    def test_records_accumulate_once_per_target_host(self, tmp_path, monkeypatch):
        monitor = Monitor(
            _make_net(3),
            targets=[_cefstatus_target(hosts=[0, 1])],
            interval=1,
            output_dir=tmp_path,
            host_count=3,
        )
        monkeypatch.setattr(
            monitor, "_collect_target", lambda t, host_idx, tgt: f"out-{host_idx}"
        )
        monitor._collect_once(1.234)
        assert len(monitor._records) == 2
        # elapsed_sec is rounded to 1 decimal place by _collect_once.
        assert monitor._records[0] == {
            "elapsed_sec": 1.2,
            "type": "cefstatus",
            "host": 0,
            "output": "out-0",
        }
        assert monitor._records[1]["host"] == 1
        assert monitor._records[1]["output"] == "out-1"

    def test_exception_from_collect_target_becomes_an_error_string_record(
        self, tmp_path, monkeypatch
    ):
        monitor = Monitor(
            _make_net(2),
            targets=[_cefstatus_target(hosts=[0])],
            interval=1,
            output_dir=tmp_path,
            host_count=2,
        )

        def _raise(target_type, host_idx, target):
            raise ValueError("boom")

        monkeypatch.setattr(monitor, "_collect_target", _raise)
        monitor._collect_once(0.0)
        # The loop must not propagate the exception — it degrades to a record.
        assert len(monitor._records) == 1
        assert monitor._records[0]["output"] == "error: boom"

    def test_stop_event_set_mid_loop_ends_collection_early(self, tmp_path, monkeypatch):
        monitor = Monitor(
            _make_net(3),
            targets=[_cefstatus_target(hosts=[0, 1, 2])],
            interval=1,
            output_dir=tmp_path,
            host_count=3,
        )

        def _collect(target_type, host_idx, target):
            if host_idx == 0:
                # Simulate Monitor.stop() being called from another thread
                # mid-cycle; the next host-loop iteration must observe it.
                monitor._stop_event.set()
            return f"out-{host_idx}"

        monkeypatch.setattr(monitor, "_collect_target", _collect)
        monitor._collect_once(0.0)
        # host 0 is collected before the stop check re-fires; hosts 1/2 are
        # never reached because _collect_once returns immediately.
        assert len(monitor._records) == 1
        assert monitor._records[0]["host"] == 0

    def test_on_record_callback_fires_with_the_new_record_on_success(
        self, tmp_path, monkeypatch
    ):
        received = []
        monitor = Monitor(
            _make_net(2),
            targets=[_cefstatus_target(hosts=[0])],
            interval=1,
            output_dir=tmp_path,
            host_count=2,
            on_record=received.append,
        )
        monkeypatch.setattr(monitor, "_collect_target", lambda t, h, tgt: "ok")
        monitor._collect_once(2.0)
        assert len(received) == 1
        assert received[0]["output"] == "ok"
        assert received[0] is monitor._records[0]

    def test_on_record_exception_is_swallowed_and_warns_in_foreground(
        self, tmp_path, monkeypatch
    ):
        def _raising_callback(record):
            raise RuntimeError("cb broke")

        monitor = Monitor(
            _make_net(2),
            targets=[_cefstatus_target(hosts=[0])],
            interval=1,
            output_dir=tmp_path,
            host_count=2,
            on_record=_raising_callback,
        )
        monkeypatch.setattr(monitor, "_collect_target", lambda t, h, tgt: "ok")
        assert not monitor._background.is_set()
        with patch("src.runtime.monitoring.info") as mock_info:
            monitor._collect_once(0.0)
        # The record itself is preserved even though the callback failed.
        assert len(monitor._records) == 1
        mock_info.assert_called_once()
        assert "on_record callback failed" in mock_info.call_args[0][0]

    def test_on_record_exception_is_swallowed_silently_in_background(
        self, tmp_path, monkeypatch
    ):
        def _raising_callback(record):
            raise RuntimeError("cb broke")

        monitor = Monitor(
            _make_net(2),
            targets=[_cefstatus_target(hosts=[0])],
            interval=1,
            output_dir=tmp_path,
            host_count=2,
            background=True,
            on_record=_raising_callback,
        )
        monkeypatch.setattr(monitor, "_collect_target", lambda t, h, tgt: "ok")
        with patch("src.runtime.monitoring.info") as mock_info:
            monitor._collect_once(0.0)
        assert len(monitor._records) == 1
        mock_info.assert_not_called()


# ---------------------------------------------------------------------------
# start()/stop() — real threading.Thread lifecycle. _collect_target is
# monkeypatched to a trivial stub so these tests exercise thread start/join
# and output-writing, never real Mininet/command collection. Synchronization
# is via the Monitor's own _stop_event (Event.wait returns immediately once
# set) plus Thread.join(timeout=...) — no fixed sleeps.
# ---------------------------------------------------------------------------

class TestThreadLifecycle:
    def _monitor(self, tmp_path, targets=None, **kwargs):
        if targets is None:
            targets = [_cefstatus_target(hosts=[0])]
        monitor = Monitor(
            _make_net(2),
            targets=targets,
            interval=1,
            output_dir=tmp_path,
            host_count=2,
            **kwargs,
        )
        monitor._collect_target = lambda target_type, host_idx, target: "ok"
        return monitor

    def test_start_then_stop_terminates_the_background_thread(self, tmp_path):
        monitor = self._monitor(tmp_path)
        monitor.start()
        assert monitor._thread is not None
        monitor.stop()
        assert not monitor._thread.is_alive()

    def test_stop_writes_output_file_from_records_present_at_stop_time(self, tmp_path):
        monitor = self._monitor(tmp_path, output_json="monitor.json")
        # Seed a record directly so the write is deterministic regardless of
        # whether the background thread actually got scheduled a collection
        # cycle before stop() fires (real thread scheduling is not under our
        # control here, and the plan forbids relying on fixed sleeps).
        monitor._records.append(
            {"elapsed_sec": 0.0, "type": "cefstatus", "host": 0, "output": "seed"}
        )
        monitor.start()
        monitor.stop()
        assert (tmp_path / "monitor.json").exists()

    def test_stop_invokes_write_outputs_exactly_once(self, tmp_path):
        monitor = self._monitor(tmp_path)
        write_spy = MagicMock(wraps=monitor._write_outputs)
        monitor._write_outputs = write_spy
        monitor.start()
        monitor.stop()
        write_spy.assert_called_once()

    def test_stop_is_safe_when_start_was_never_called(self, tmp_path):
        monitor = self._monitor(tmp_path)
        assert monitor._thread is None
        monitor.stop()  # must not raise despite _thread being None
        assert monitor._thread is None

    def test_start_is_a_noop_when_there_are_no_targets(self, tmp_path):
        monitor = self._monitor(tmp_path, targets=[])
        monitor.start()
        assert monitor._thread is None


# ---------------------------------------------------------------------------
# _write_outputs — called directly with _records populated manually to
# exercise its four write-mode branches without going through collection.
# ---------------------------------------------------------------------------

class TestWriteOutputs:
    def _monitor(self, tmp_path, **kwargs):
        return Monitor(
            _make_net(1),
            targets=[],
            interval=1,
            output_dir=tmp_path,
            host_count=1,
            **kwargs,
        )

    def test_writes_both_json_and_csv_when_both_paths_are_configured(self, tmp_path):
        monitor = self._monitor(tmp_path, output_json="monitor.json", output_csv="monitor.csv")
        monitor._records = [
            {"elapsed_sec": 0.0, "type": "cefstatus", "host": 0, "output": "a"},
            {"elapsed_sec": 1.5, "type": "csmgrstatus", "host": 1, "output": "b"},
        ]
        monitor._write_outputs()

        json_path = tmp_path / "monitor.json"
        csv_path = tmp_path / "monitor.csv"
        assert json.loads(json_path.read_text(encoding="utf-8")) == monitor._records

        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2
        assert rows[0]["type"] == "cefstatus"
        assert rows[0]["host"] == "0"
        assert rows[1]["output"] == "b"

    def test_writes_json_only_when_csv_path_is_not_configured(self, tmp_path):
        monitor = self._monitor(tmp_path, output_json="monitor.json")
        monitor._records = [{"elapsed_sec": 0.0, "type": "cefstatus", "host": 0, "output": "a"}]
        monitor._write_outputs()
        assert (tmp_path / "monitor.json").exists()
        assert not (tmp_path / "monitor.csv").exists()

    def test_writes_csv_only_when_json_path_is_not_configured(self, tmp_path):
        monitor = self._monitor(tmp_path, output_csv="monitor.csv")
        monitor._records = [{"elapsed_sec": 0.0, "type": "cefstatus", "host": 0, "output": "a"}]
        monitor._write_outputs()
        assert not (tmp_path / "monitor.json").exists()
        assert (tmp_path / "monitor.csv").exists()

    def test_empty_records_skips_both_writes(self, tmp_path):
        monitor = self._monitor(tmp_path, output_json="monitor.json", output_csv="monitor.csv")
        assert monitor._records == []
        monitor._write_outputs()
        assert not (tmp_path / "monitor.json").exists()
        assert not (tmp_path / "monitor.csv").exists()

    def test_info_logs_one_line_per_file_actually_written(self, tmp_path):
        monitor = self._monitor(tmp_path, output_json="monitor.json", output_csv="monitor.csv")
        monitor._records = [{"elapsed_sec": 0.0, "type": "cefstatus", "host": 0, "output": "a"}]
        with patch("src.runtime.monitoring.info") as mock_info:
            monitor._write_outputs()
        assert mock_info.call_count == 2
