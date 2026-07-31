"""Unit tests for src/runtime/monitoring.py (Monitor class)."""

import csv
import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch


from src.runtime.command_runner import CommandResult, FakeCommandRunner
from src.runtime.monitoring import (
    DEFAULT_COMMAND_TIMEOUT,
    MONITOR_FIELDS,
    Monitor,
    _resolve_hosts,
    make_monitor_record,
)


def _ok_result(stdout="ok"):
    """Build a CommandResult that derive_monitor_outcome will classify as ok or not-ok
    depending on content.  Tests that only care about kwarg forwarding use this."""
    return CommandResult(returncode=0, stdout=stdout)


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
        def resolver(h):
            return f"192.168.1.{h + 1}"
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
        with patch("src.runtime.monitoring.run_csmgrstatus", return_value=_ok_result()) as mock_fn:
            monitor._collect_target("csmgrstatus", 2, {"type": "csmgrstatus"})
        resolver.assert_called_once_with(2)
        mock_fn.assert_called_once()
        _, kwargs = mock_fn.call_args
        assert kwargs.get("host") == "192.168.3.4"

    def test_resolver_ip_passed_to_run_csmgrstatus(self, tmp_path):
        def resolver(h):
            return f"172.20.{h}.1"
        monitor = self._make_monitor(tmp_path, resolver=resolver)
        with patch("src.runtime.monitoring.run_csmgrstatus", return_value=_ok_result()) as mock_fn:
            monitor._collect_target("csmgrstatus", 1, {"type": "csmgrstatus"})
        _, kwargs = mock_fn.call_args
        assert kwargs["host"] == "172.20.1.1"

    def test_target_host_override_takes_priority_over_resolver(self, tmp_path):
        resolver = MagicMock(return_value="192.168.1.1")
        monitor = self._make_monitor(tmp_path, resolver=resolver)
        with patch("src.runtime.monitoring.run_csmgrstatus", return_value=_ok_result()) as mock_fn:
            monitor._collect_target(
                "csmgrstatus", 0, {"type": "csmgrstatus", "target_host": "10.99.0.1"}
            )
        resolver.assert_not_called()
        _, kwargs = mock_fn.call_args
        assert kwargs["host"] == "10.99.0.1"

    def test_empty_target_host_falls_back_to_resolver(self, tmp_path):
        resolver = MagicMock(return_value="192.168.5.1")
        monitor = self._make_monitor(tmp_path, resolver=resolver)
        with patch("src.runtime.monitoring.run_csmgrstatus", return_value=_ok_result()) as mock_fn:
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
        with patch("src.runtime.monitoring.run_csmgrstatus", return_value=_ok_result()) as mock_fn:
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
        with patch("src.runtime.monitoring.run_csmgrstatus", return_value=_ok_result()) as mock_fn:
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
        with patch("src.runtime.monitoring.run_csmgrstatus", return_value=_ok_result()) as mock_fn:
            monitor._collect_target("csmgrstatus", 0, {"type": "csmgrstatus", "target_host": ""})
        _, kwargs = mock_fn.call_args
        assert kwargs.get("host") == "127.0.0.1"

    def test_uri_and_port_num_forwarded(self, tmp_path):
        def resolver(h):
            return "192.168.1.1"
        monitor = self._make_monitor(tmp_path, resolver=resolver)
        target = {"type": "csmgrstatus", "uri": "ccnx:/test", "port_num": 9696}
        with patch("src.runtime.monitoring.run_csmgrstatus", return_value=_ok_result()) as mock_fn:
            monitor._collect_target("csmgrstatus", 0, target)
        _, kwargs = mock_fn.call_args
        assert kwargs["uri"] == "ccnx:/test"
        assert kwargs["port_num"] == 9696


# ---------------------------------------------------------------------------
# cefstatus does not need resolver
# ---------------------------------------------------------------------------

class TestCollectTargetCefstatus:
    def test_cefstatus_runs_via_run_cefstatus(self, tmp_path):
        net = MagicMock()
        monitor = Monitor(
            net,
            targets=[_cefstatus_target(hosts="all")],
            interval=1,
            output_dir=tmp_path,
            host_count=3,
        )
        with patch(
            "src.runtime.monitoring.run_cefstatus", return_value=_ok_result("cef out")
        ) as mock_fn:
            out, outcome = monitor._collect_target("cefstatus", 0, {"type": "cefstatus"})
        assert out == "cef out"
        assert outcome == "not-ok"  # "cef out" has no positive markers
        mock_fn.assert_called_once_with(net, 0, quiet=False, timeout=None)


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
        net = MagicMock()
        monitor = self._bg_monitor(tmp_path, net=net, command_timeout=7)
        with patch(
            "src.runtime.monitoring.run_cefstatus", return_value=_ok_result("cef out")
        ) as mock_fn:
            out, outcome = monitor._collect_target("cefstatus", 1, {"type": "cefstatus"})
        assert out == "cef out"
        assert outcome == "not-ok"
        mock_fn.assert_called_once_with(net, 1, quiet=True, timeout=7)

    def test_background_csmgrstatus_quiet_and_timeout(self, tmp_path):
        monitor = self._bg_monitor(tmp_path)  # default command_timeout=10
        with patch(
            "src.runtime.monitoring.run_csmgrstatus", return_value=_ok_result()
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
            out, outcome = monitor._collect_target("csmgrstatus", 0, {"type": "csmgrstatus"})
        assert out == "skipped: host down"
        assert outcome == "skipped"
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
            "src.runtime.monitoring.run_csmgrstatus", return_value=_ok_result()
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
            monitor, "_collect_target",
            lambda t, host_idx, tgt: (f"out-{host_idx}", "ok"),
        )
        monitor._collect_once(1.234)
        assert len(monitor._records) == 2
        assert monitor._records[0] == {
            "elapsed_sec": 1.2,
            "type": "cefstatus",
            "host": 0,
            "output": "out-0",
            "outcome": "ok",
        }
        assert monitor._records[1]["host"] == 1
        assert monitor._records[1]["output"] == "out-1"
        assert monitor._records[1]["outcome"] == "ok"

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
        assert len(monitor._records) == 1
        assert monitor._records[0]["output"] == "error: boom"
        assert monitor._records[0]["outcome"] == "not-ok"

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
            return f"out-{host_idx}", "ok"

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
        monkeypatch.setattr(monitor, "_collect_target", lambda t, h, tgt: ("ok", "ok"))
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
        monkeypatch.setattr(monitor, "_collect_target", lambda t, h, tgt: ("ok", "ok"))
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
        monkeypatch.setattr(monitor, "_collect_target", lambda t, h, tgt: ("ok", "ok"))
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
        monitor._collect_target = lambda target_type, host_idx, target: ("ok", "ok")
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
            {"elapsed_sec": 0.0, "type": "cefstatus", "host": 0, "output": "seed", "outcome": "ok"}
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
            {"elapsed_sec": 0.0, "type": "cefstatus", "host": 0, "output": "a", "outcome": "not-ok"},
            {"elapsed_sec": 1.5, "type": "csmgrstatus", "host": 1, "output": "b", "outcome": "not-ok"},
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
        monitor._records = [{"elapsed_sec": 0.0, "type": "cefstatus", "host": 0, "output": "a", "outcome": "not-ok"}]
        monitor._write_outputs()
        assert (tmp_path / "monitor.json").exists()
        assert not (tmp_path / "monitor.csv").exists()

    def test_writes_csv_only_when_json_path_is_not_configured(self, tmp_path):
        monitor = self._monitor(tmp_path, output_csv="monitor.csv")
        monitor._records = [{"elapsed_sec": 0.0, "type": "cefstatus", "host": 0, "output": "a", "outcome": "not-ok"}]
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
        monitor._records = [{"elapsed_sec": 0.0, "type": "cefstatus", "host": 0, "output": "a", "outcome": "not-ok"}]
        with patch("src.runtime.monitoring.info") as mock_info:
            monitor._write_outputs()
        assert mock_info.call_count == 2


# ---------------------------------------------------------------------------
# make_monitor_record — the single owner of the monitor-record dict shape,
# shared by monitor.json/monitor.csv (via Monitor._collect_once) and by the
# disaster-scenario webui pre-populate path (DashboardState.record_monitor).
# ---------------------------------------------------------------------------

class TestMakeMonitorRecord:
    def test_returns_exactly_monitor_fields_keys_with_given_values(self):
        record = make_monitor_record(1.5, "cefstatus", 2, "faces: 1", "ok")
        assert set(record.keys()) == set(MONITOR_FIELDS)
        assert record["elapsed_sec"] == 1.5
        assert record["type"] == "cefstatus"
        assert record["host"] == 2
        assert record["output"] == "faces: 1"
        assert record["outcome"] == "ok"

    def test_key_order_matches_monitor_fields(self):
        record = make_monitor_record(0.0, "csmgrstatus", 0, "ok", "not-ok")
        assert tuple(record.keys()) == MONITOR_FIELDS


class TestCollectOnceUsesFactory:
    """_collect_once must build every record through make_monitor_record,
    not a hand-rolled dict literal, so CSV/JSON output and the webui feed
    cannot silently drift from MONITOR_FIELDS.
    """

    def test_collect_once_record_shape_matches_monitor_fields(
        self, tmp_path, monkeypatch
    ):
        monitor = Monitor(
            _make_net(2),
            targets=[_cefstatus_target(hosts=[0])],
            interval=1,
            output_dir=tmp_path,
            host_count=2,
        )
        monkeypatch.setattr(monitor, "_collect_target", lambda t, h, tgt: ("out", "ok"))
        monitor._collect_once(0.5)
        assert tuple(monitor._records[0].keys()) == MONITOR_FIELDS


# ---------------------------------------------------------------------------
# Fixture loading — reuses the same directory as test_ccninfo_parse.py
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ccninfo"


def _load_fixture(name: str) -> str:
    """Read a ccninfo fixture verbatim (no stripping)."""
    return (_FIXTURES_DIR / name).read_text()


def _ccninfo_target(**kwargs):
    return {"type": "ccninfo", "uri": "ccnx:/test/mon", **kwargs}


# ---------------------------------------------------------------------------
# _collect_target — ccninfo branch
# ---------------------------------------------------------------------------

class TestCollectTargetCcninfo:
    """ccninfo branch of _collect_target: builds argv via build_ccninfo_argv,
    prepends CEFORE_DIR, runs via MininetCommandRunner, and parses stdout
    into a structured dict with uri/raw/parsed/elapsed_ms/timed_out.

    Like every other branch, it returns an ``(output, outcome)`` pair. The
    outcome is derived from the parsed reply rather than from
    derive_monitor_outcome, which has no ccninfo marker table and would
    fail-closed to "not-ok" on a healthy reply.
    """

    def _make_monitor(self, tmp_path, **kwargs):
        return Monitor(
            _make_net(2),
            targets=[_ccninfo_target()],
            interval=1,
            output_dir=tmp_path,
            host_count=2,
            background=True,
            **kwargs,
        )

    def test_ccninfo_success_produces_structured_dict_output(self, tmp_path):
        """A successful ccninfo run returns a 4-field dict with uri, raw,
        parsed (structured reply fields including route as list of dicts),
        elapsed_ms, and timed_out=False.
        """
        fixture_text = _load_fixture("reply_named_cache.out")
        fake = FakeCommandRunner()
        fake.script_run(stdout=fixture_text)
        monitor = self._make_monitor(tmp_path, command_timeout=5)
        target = _ccninfo_target()
        with patch("src.runtime.monitoring.MininetCommandRunner", return_value=fake):
            out, outcome = monitor._collect_target("ccninfo", 1, target)

        # a parsed reply that did not time out is the "ok" evidence
        assert outcome == "ok"
        # output is a dict, not a string
        assert isinstance(out, dict)
        assert out["uri"] == "ccnx:/test/mon"
        assert out["raw"] == fixture_text
        assert isinstance(out["elapsed_ms"], int)
        assert out["elapsed_ms"] >= 0
        assert out["timed_out"] is False

        # parsed sub-dict carries the ccninfo reply fields
        parsed = out["parsed"]
        assert parsed["reply_received"] is True
        assert parsed["responder"] == "h1"
        assert parsed["result"] == "NO_ERROR"
        assert parsed["rtt_ms"] == 5.562

        # route is a list of plain dicts (JSON-primitive contract), not
        # dataclass objects or tuples
        assert isinstance(parsed["route"], list)
        assert len(parsed["route"]) == 1
        hop = parsed["route"][0]
        assert isinstance(hop, dict)
        assert hop == {"index": 1, "node": "h1", "delay_ms": 5.463}

        # cache_lines is a list of strings
        assert isinstance(parsed["cache_lines"], list)
        assert len(parsed["cache_lines"]) == 1

    def test_ccninfo_timeout_produces_dict_with_timed_out_true(self, tmp_path):
        """A timed-out ccninfo run returns a dict with timed_out=True and
        parsed.reply_received=False (empty stdout).
        """
        fake = FakeCommandRunner()
        fake.script_run(stdout="", timed_out=True)
        monitor = self._make_monitor(tmp_path, command_timeout=5)
        target = _ccninfo_target()
        with patch("src.runtime.monitoring.MininetCommandRunner", return_value=fake):
            out, outcome = monitor._collect_target("ccninfo", 0, target)

        assert isinstance(out, dict)
        assert out["timed_out"] is True
        assert out["parsed"]["reply_received"] is False
        # a timeout is a genuine failure, distinct from the "skipped" a
        # downed host produces
        assert outcome == "not-ok"

    def test_ccninfo_host_down_returns_skip_string(self, tmp_path):
        """A ccninfo target on a downed host returns the plain-string
        'skipped: host down', same as cefstatus/csmgrstatus.
        """
        monitor = self._make_monitor(tmp_path)
        monitor._down_hosts_getter = lambda: [0]
        target = _ccninfo_target()
        out, outcome = monitor._collect_target("ccninfo", 0, target)
        assert out == "skipped: host down"
        # the shared host-down early return already carries the third
        # tri-state value; ccninfo needs no special casing for it
        assert outcome == "skipped"

    def test_ccninfo_always_passes_timeout(self, tmp_path):
        """Unlike fg cefstatus (which passes timeout=None), ccninfo always
        passes command_timeout — in both fg and bg modes — because a
        reply-less ccninfo blocks ~5s per host and would stall the monitor.
        """
        # Background mode
        fake_bg = FakeCommandRunner()
        fake_bg.script_run(stdout="")
        monitor_bg = self._make_monitor(tmp_path, command_timeout=7)
        target = _ccninfo_target()
        with patch("src.runtime.monitoring.MininetCommandRunner", return_value=fake_bg):
            monitor_bg._collect_target("ccninfo", 0, target)
        assert fake_bg.runs[0]["timeout"] == 7

        # Foreground mode
        fake_fg = FakeCommandRunner()
        fake_fg.script_run(stdout="")
        monitor_fg = Monitor(
            _make_net(2),
            targets=[_ccninfo_target()],
            interval=1,
            output_dir=tmp_path,
            host_count=2,
            command_timeout=7,
        )
        with patch("src.runtime.monitoring.MininetCommandRunner", return_value=fake_fg):
            monitor_fg._collect_target("ccninfo", 0, target)
        # ccninfo fg timeout is NOT None (unlike cefstatus fg which is None)
        assert fake_fg.runs[0]["timeout"] == 7

    def test_cefstatus_fg_still_passes_timeout_none(self, tmp_path):
        """Complementary pin: cefstatus in foreground mode still passes
        timeout=None. This test documents the intentional asymmetry between
        cefstatus (timeout=None in fg) and ccninfo (always bounded).

        cefstatus reaches the runner through cefore.run_cefstatus, which
        builds its own MininetCommandRunner, so the patch target is the one
        in cefore — patching monitoring's would miss it entirely. ccninfo
        still constructs the runner in monitoring itself.
        """
        fake = FakeCommandRunner()
        fake.script_run(stdout="cef out")
        monitor = Monitor(
            MagicMock(),
            targets=[_cefstatus_target(hosts="all")],
            interval=1,
            output_dir=tmp_path,
            host_count=3,
        )
        with patch("src.runtime.cefore.MininetCommandRunner", return_value=fake):
            monitor._collect_target("cefstatus", 0, {"type": "cefstatus"})
        assert fake.runs[0]["timeout"] is None

    def test_ccninfo_argv_carries_cefore_dir_prefix(self, tmp_path):
        """The ccninfo argv must be prefixed with env CEFORE_DIR=... so
        cef_client_init reads the correct node's cefnetd.conf socket ID.
        """
        fake = FakeCommandRunner()
        fake.script_run(stdout="")
        monitor = self._make_monitor(tmp_path)
        target = _ccninfo_target()
        with patch("src.runtime.monitoring.MininetCommandRunner", return_value=fake):
            monitor._collect_target("ccninfo", 0, target)
        argv = fake.runs[0]["argv"]
        assert argv[0] == "env"
        assert "CEFORE_DIR=" in argv[1]
        assert ".cefore_env" in argv[1]
        # The actual ccninfo command follows the env prefix
        assert argv[2] == "ccninfo"

    def test_unknown_type_fallback_unchanged_with_ccninfo_present(self, tmp_path):
        """The unknown-type fallback must still work now that ccninfo is
        wired as an elif branch before the else.
        """
        monitor = self._make_monitor(tmp_path)
        out, outcome = monitor._collect_target("bogus", 0, {"type": "bogus"})
        assert out == "unknown monitor type: bogus"
        assert outcome == "not-ok"

    def test_ccninfo_passthrough_options_forwarded(self, tmp_path):
        """Optional ccninfo flags (cache_info, hop_count, etc.) from the
        target dict are forwarded to build_ccninfo_argv.
        """
        fake = FakeCommandRunner()
        fake.script_run(stdout="")
        monitor = self._make_monitor(tmp_path)
        target = _ccninfo_target(
            cache_info=True,
            owner_only=True,
            hop_count=5,
            skip_hop=2,
            valid_algo="crc32c",
            port_num=9876,
        )
        with patch("src.runtime.monitoring.MininetCommandRunner", return_value=fake):
            monitor._collect_target("ccninfo", 0, target)
        argv = fake.runs[0]["argv"]
        # After the env prefix, the ccninfo argv should contain the flags
        ccninfo_argv = argv[2:]  # skip ["env", "CEFORE_DIR=..."]
        assert "-c" in ccninfo_argv
        assert "-o" in ccninfo_argv
        assert "-r" in ccninfo_argv
        idx_r = ccninfo_argv.index("-r")
        assert ccninfo_argv[idx_r + 1] == "5"
        idx_s = ccninfo_argv.index("-s")
        assert ccninfo_argv[idx_s + 1] == "2"


# ---------------------------------------------------------------------------
# CSV round-trip: dict outputs get json.dumps'd, string outputs stay plain
# ---------------------------------------------------------------------------

class TestCsvDictSerialization:
    """CSV rows with dict-valued outputs must be JSON-serialized so they
    round-trip through json.loads; string outputs stay untouched.
    """

    def _monitor(self, tmp_path, **kwargs):
        return Monitor(
            _make_net(1),
            targets=[],
            interval=1,
            output_dir=tmp_path,
            host_count=1,
            **kwargs,
        )

    def test_dict_output_csv_roundtrips_via_json(self, tmp_path):
        """A record whose output is a dict must be written as JSON in CSV
        so json.loads on the cell round-trips to the original dict.
        """
        dict_output = {
            "uri": "ccnx:/test",
            "raw": "some output",
            "parsed": {
                "reply_received": True,
                "responder": "h1",
                "result": "NO_ERROR",
                "rtt_ms": 5.0,
                "route": [{"index": 1, "node": "h1", "delay_ms": 3.0}],
                "cache_lines": [],
            },
            "elapsed_ms": 42,
            "timed_out": False,
        }
        monitor = self._monitor(
            tmp_path, output_csv="monitor.csv", output_json="monitor.json"
        )
        monitor._records = [
            {"elapsed_sec": 0.0, "type": "ccninfo", "host": 0, "output": dict_output},
        ]
        monitor._write_outputs()

        # CSV round-trip: json.loads on the output cell recovers the dict
        with open(tmp_path / "monitor.csv", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        recovered = json.loads(rows[0]["output"])
        assert recovered == dict_output

        # JSON file keeps the nested dict as-is (not double-encoded)
        json_data = json.loads((tmp_path / "monitor.json").read_text(encoding="utf-8"))
        assert json_data[0]["output"] == dict_output

    def test_string_output_csv_stays_plain(self, tmp_path):
        """A record whose output is a plain string (e.g. cefstatus output)
        must NOT be json.dumps'd — it stays as the raw string in CSV.
        """
        monitor = self._monitor(tmp_path, output_csv="monitor.csv")
        monitor._records = [
            {"elapsed_sec": 0.0, "type": "cefstatus", "host": 0, "output": "faces: 1"},
        ]
        monitor._write_outputs()
        with open(tmp_path / "monitor.csv", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["output"] == "faces: 1"

    def test_mixed_string_and_dict_outputs_serialize_correctly(self, tmp_path):
        """A CSV with both string and dict output rows serializes each
        independently: dicts get JSON, strings stay plain.
        """
        dict_output = {"uri": "ccnx:/x", "raw": "", "parsed": {}, "elapsed_ms": 0, "timed_out": False}
        monitor = self._monitor(tmp_path, output_csv="monitor.csv")
        monitor._records = [
            {"elapsed_sec": 0.0, "type": "cefstatus", "host": 0, "output": "plain text"},
            {"elapsed_sec": 1.0, "type": "ccninfo", "host": 1, "output": dict_output},
        ]
        monitor._write_outputs()
        with open(tmp_path / "monitor.csv", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["output"] == "plain text"
        assert json.loads(rows[1]["output"]) == dict_output


# ---------------------------------------------------------------------------
# stop() — join budget and late-thread safety
# ---------------------------------------------------------------------------

class TestStopContract:
    """stop() join budget is computed from command_timeout, not a fixed 10s.
    A blocking fake runner pins the contract: the worker thread blocks on
    a ccninfo run for exactly its timeout duration, and stop() returns
    with the thread dead within the budget.
    """

    def test_stop_returns_with_thread_dead_after_blocking_ccninfo(self, tmp_path):
        """A fake runner that blocks until its timeout elapses simulates a
        worst-case ccninfo cycle. stop() must join within the budget and
        the thread must be dead.
        """
        # command_timeout=1 -> budget = 1 + 2 + 3 = 6s
        # Use an Event to synchronize instead of a fixed sleep: the fake
        # signals when it has entered its blocking run, and the test waits
        # on that before calling stop().
        entered = threading.Event()
        fake = FakeCommandRunner()

        def blocking_run(node, argv, *, log_path=None, cwd=None, timeout=None,
                         cancel_event=None, capture=True, capture_stderr=False):
            entered.set()
            if timeout is not None:
                time.sleep(timeout)
            return CommandResult(0, "", "")
        fake.run = blocking_run

        monitor = Monitor(
            _make_net(2),
            targets=[_ccninfo_target()],
            interval=60,  # long interval so only one cycle runs
            output_dir=tmp_path,
            host_count=2,
            background=True,
            command_timeout=1,
        )
        with patch("src.runtime.monitoring.MininetCommandRunner", return_value=fake):
            monitor.start()
            assert entered.wait(timeout=5), "fake never entered blocking_run"
            t0 = time.monotonic()
            monitor.stop()
            elapsed = time.monotonic() - t0

        assert not monitor._thread.is_alive()
        # Budget is 1+2+3=6s; the actual wait should be well under that
        # (the thread sleeps for ~1s per host then the join is near-instant).
        # With hosts=[0,1] (default "all" for ccninfo), worst case is ~2s.
        assert elapsed < 8

    def test_stop_join_budget_scales_with_command_timeout(self, tmp_path):
        """The join timeout must be command_timeout + 5, not a fixed 10s.
        Directly asserts the _join_budget() formula.
        """
        monitor = Monitor(
            _make_net(2),
            targets=[_ccninfo_target()],
            interval=1,
            output_dir=tmp_path,
            host_count=2,
            command_timeout=20,
        )
        assert monitor._join_budget() == 20 + 2 + 3  # 25, not 10

    def test_join_budget_uses_default_when_command_timeout_is_default(self, tmp_path):
        """_join_budget with the default command_timeout (10) yields 15."""
        monitor = Monitor(
            _make_net(2),
            targets=[_ccninfo_target()],
            interval=1,
            output_dir=tmp_path,
            host_count=2,
        )
        assert monitor._join_budget() == DEFAULT_COMMAND_TIMEOUT + 2 + 3  # 15

    def test_stop_joins_with_budget_and_warns_when_thread_survives(self, tmp_path):
        """When the thread is still alive after the join budget, stop() must:
        (1) pass _join_budget() as the join timeout,
        (2) warn about the surviving thread,
        (3) still write outputs from the locked snapshot.
        Uses command_timeout=4 so the budget (4+2+3=9) is distinguishable
        from the old fixed 10.
        """

        class SurvivingThread:
            """Fake thread that never dies — always reports is_alive()=True."""

            def __init__(self):
                self.join_timeout = None

            def join(self, timeout=None):
                self.join_timeout = timeout

            def is_alive(self):
                return True

        monitor = Monitor(
            _make_net(2),
            targets=[_ccninfo_target()],
            interval=1,
            output_dir=tmp_path,
            host_count=2,
            command_timeout=4,
            output_json="monitor.json",
        )
        monitor._records.append(
            {"elapsed_sec": 0.0, "type": "ccninfo", "host": 0, "output": "seed"}
        )
        surviving = SurvivingThread()
        monitor._thread = surviving

        with patch("src.runtime.monitoring.warn") as mock_warn:
            monitor.stop()

        # (1) stop() must pass _join_budget() to join(), not a fixed 10
        assert surviving.join_timeout == monitor._join_budget()  # 9
        assert surviving.join_timeout == 4 + 2 + 3  # explicit arithmetic pin

        # (2) a warning must be logged
        mock_warn.assert_called_once()
        assert "join budget" in mock_warn.call_args[0][0]

        # (3) outputs must still be written despite the surviving thread
        assert (tmp_path / "monitor.json").exists()


# ---------------------------------------------------------------------------
# Lock-protected snapshot — deterministic test (no threads, no timing)
# ---------------------------------------------------------------------------

class TestRecordsLock:
    """The _records_lock protects append in _collect_once and snapshot in
    _write_outputs so a late-returning thread cannot race _write_outputs.
    """

    def test_append_and_snapshot_hold_records_lock(self, tmp_path, monkeypatch):
        """Instrument _records with a list subclass that records whether
        _records_lock was held during append and list() snapshot.
        """

        class InstrumentedList(list):
            def __init__(self, *args, lock=None, **kwargs):
                super().__init__(*args, **kwargs)
                self._lock = lock
                self.append_locked = []
                self.iter_locked = []

            def append(self, item):
                self.append_locked.append(self._lock.locked())
                super().append(item)

            def __iter__(self):
                self.iter_locked.append(self._lock.locked())
                return super().__iter__()

        monitor = Monitor(
            _make_net(2),
            targets=[_cefstatus_target(hosts=[0])],
            interval=1,
            output_dir=tmp_path,
            host_count=2,
            output_json="monitor.json",
        )
        # Must be a pair: a bare "ok" would unpack into ('o', 'k') and pass by
        # accident, hiding a contract break in _collect_target.
        monkeypatch.setattr(monitor, "_collect_target", lambda t, h, tgt: ("ok", "ok"))

        instrumented = InstrumentedList(lock=monitor._records_lock)
        monitor._records = instrumented

        # Trigger an append via _collect_once
        monitor._collect_once(0.0)
        assert len(instrumented.append_locked) == 1
        assert instrumented.append_locked[0] is True, (
            "_records.append must be called with _records_lock held"
        )

        # Trigger a snapshot via _write_outputs
        monitor._write_outputs()
        assert len(instrumented.iter_locked) >= 1
        assert instrumented.iter_locked[0] is True, (
            "list(self._records) snapshot must be called with _records_lock held"
        )
