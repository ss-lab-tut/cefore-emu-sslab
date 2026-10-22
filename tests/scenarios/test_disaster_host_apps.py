"""Behavior tests for DisasterScenario's host_apps: wiring.

Covers: host apps start through build_host_app_fleet/start_all during
run_experiment(), {t0_ms} is derived from the exact same time.time()/
time.monotonic() capture point the EventScheduler's "at: 0" origin uses,
and host_app_fleet.stop_all() runs inside shutdown_runtime_resources()
(i.e. before teardown() stops cefnetd/csmgrd), with its failures
propagated like every other shutdown stage.
"""

from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest

from src.runtime.event_batch import EventBatchResult
from src.scenarios.disaster import DisasterScenario


def _make_args(**overrides):
    data = {
        "hosts": 3,
        "seed": 42,
        "events": [],
        "bridges": [],
        "bridge": [],
        "ext": [],
        "no_cli": False,
        "results_json": "",
        "addressing": {},
        # _run_normal_experiment() -> _start_failure_manager() reads these
        # unconditionally; 0/0 means "no flap" (see FailureManager in
        # CONTEXT.md) and keeps run_experiment() runnable without a real
        # Mininet net.
        "down_interval": 0,
        "down_duration": 0,
    }
    data.update(overrides)
    return Namespace(**data)


def _scenario_runnable_without_mininet(args, run_dir):
    """A DisasterScenario whose run_experiment() can run without build_topology().

    run_experiment() -> _run_normal_experiment()/_run_autotest_experiment()
    reads self.topo.mesh_links regardless of whether events are configured
    (it is a constructor field on EventBatchSpec, built before
    run_event_batch() is called). These tests exercise host_apps wiring
    only, never the mesh topology itself, so a MagicMock stands in for the
    topo that build_topology() would otherwise have produced.
    """
    scenario = DisasterScenario(args, run_dir=run_dir)
    scenario.topo = MagicMock()
    return scenario


def _stub_run_event_batch(captured_specs):
    def fake(net, spec):
        captured_specs.append(spec)
        return EventBatchResult(None, None, None, [])

    return fake


class TestHostAppsStartDuringRunExperiment:
    def test_no_host_apps_config_builds_no_fleet(self, tmp_path):
        scenario = _scenario_runnable_without_mininet(_make_args(), tmp_path)

        scenario.run_experiment(MagicMock())

        assert scenario.host_app_fleet is None

    def test_host_apps_config_builds_and_starts_a_fleet(self, tmp_path):
        host_apps_config = [{"hosts": [0], "argv": ["noop"]}]
        scenario = _scenario_runnable_without_mininet(
            _make_args(host_apps=host_apps_config), tmp_path
        )
        net = MagicMock()
        fake_fleet = MagicMock()

        with patch(
            "src.scenarios.disaster.build_host_app_fleet", return_value=fake_fleet
        ) as mock_build:
            scenario.run_experiment(net)

        # args, host_count, host_apps_config, t0_ms (t0_ms is checked by the
        # t0-sharing test below; here only the first three matter).
        called_net, called_host_count, called_config = mock_build.call_args[0][:3]
        assert called_net is net
        assert called_host_count == 3
        assert called_config == host_apps_config
        assert scenario.host_app_fleet is fake_fleet
        fake_fleet.start_all.assert_called_once()


class TestHostAppsT0SharesSchedulerOrigin:
    def test_t0_ms_and_scheduler_origin_come_from_the_same_capture_point(
        self, tmp_path
    ):
        host_apps_config = [{"hosts": [0], "argv": ["noop"]}]
        scenario = _scenario_runnable_without_mininet(
            _make_args(
                host_apps=host_apps_config,
                events=[{"at": 5, "type": "link_down", "nodes": [0, 1]}],
            ),
            tmp_path,
        )
        net = MagicMock()
        captured_specs = []
        fake_fleet = MagicMock()

        with patch(
            "src.scenarios.disaster.time.monotonic", return_value=1000.0
        ), patch(
            "src.scenarios.disaster.time.time", return_value=1700000000.5
        ), patch(
            "src.scenarios.disaster.run_event_batch",
            side_effect=_stub_run_event_batch(captured_specs),
        ), patch(
            "src.scenarios.disaster.build_host_app_fleet", return_value=fake_fleet
        ) as mock_build:
            scenario.run_experiment(net)

        # The scheduler's "at: 0" origin (EventBatchSpec.start_time) ...
        assert captured_specs[0].start_time == 1000.0
        # ... and the apps' {t0_ms} (int(time.time() * 1000)) are both
        # derived from the single time.monotonic()/time.time() pair taken
        # back-to-back at the top of run_experiment() -- not two
        # independently-chosen "now"s.
        t0_ms_arg = mock_build.call_args[0][3]
        assert t0_ms_arg == 1700000000500


class TestHostAppsStopBeforeTeardown:
    def _run_execute_with_stubbed_lifecycle(self, scenario, call_order, net=None):
        net = net or MagicMock()

        def fake_teardown(_net):
            call_order.append("teardown")

        with patch.object(scenario, "build_topology"):
            with patch.object(scenario, "create_mininet", return_value=net):
                with patch.object(scenario, "configure"):
                    with patch.object(scenario, "run_experiment"):
                        with patch.object(
                            scenario, "teardown", side_effect=fake_teardown
                        ):
                            with patch("src.scenarios.base.cleanup_all"):
                                scenario.execute()

    def test_host_app_fleet_stop_all_runs_before_teardown(self, tmp_path):
        # no_cli=True: run_main() would otherwise enter the real
        # mininet.cli.CLI(net), which crashes under pytest's stdin capture
        # (unrelated to what this test checks) before ever reaching
        # teardown. Pass-after/fail-before here is about call_order, not
        # the CLI.
        scenario = DisasterScenario(_make_args(no_cli=True), run_dir=tmp_path)
        call_order = []

        def stop_all():
            call_order.append("host_apps_stop_all")
            return []

        fleet = MagicMock()
        fleet.stop_all.side_effect = stop_all
        scenario.host_app_fleet = fleet

        self._run_execute_with_stubbed_lifecycle(scenario, call_order)

        assert call_order == ["host_apps_stop_all", "teardown"]
        fleet.stop_all.assert_called_once()

    def test_none_host_app_fleet_is_a_noop(self, tmp_path):
        scenario = DisasterScenario(_make_args(), run_dir=tmp_path)
        assert scenario.host_app_fleet is None
        assert scenario.shutdown_runtime_resources() == []

    def test_stop_all_failures_propagate(self, tmp_path):
        scenario = DisasterScenario(_make_args(no_cli=True), run_dir=tmp_path)
        boom = RuntimeError("host app vanished")
        fleet = MagicMock()
        fleet.stop_all.return_value = [("stop_host_app h1", boom)]
        scenario.host_app_fleet = fleet

        net = MagicMock()
        with patch.object(scenario, "build_topology"):
            with patch.object(scenario, "create_mininet", return_value=net):
                with patch.object(scenario, "configure"):
                    with patch.object(scenario, "run_experiment"):
                        with patch.object(scenario, "teardown"):
                            with patch("src.scenarios.base.cleanup_all"):
                                with pytest.raises(
                                    RuntimeError, match="host app vanished"
                                ):
                                    scenario.execute()
