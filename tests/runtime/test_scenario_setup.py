"""Order/structure contract for setup_scenario(net, spec) -> SetupResult.

Pins the canonical order the seam walks through the common setup recipe
for every scenario (disaster, connect, mesh). The pre-canonical drift
(connect's bw/ext-after-everything, mesh/connect ``time.sleep(1)``, mesh
debug print, PNG-after-status timing) was removed in slice 2 after a
behavior-preserving extraction slice proved by /cefore-run-tests smoke
that those variations carried no real semantic load.
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.runtime.cache_strategy import CacheContext, KCentersStrategy
from src.runtime.scenario_setup import (
    ScenarioSetupSpec,
    SetupResult,
    setup_scenario,
)


class _FakeCacheStrategy:
    """Lightweight stand-in: records calls + returns a fixed set."""

    def __init__(self, result: set[int]):
        self._result = result
        self.calls: list[CacheContext] = []

    def place(self, ctx: CacheContext) -> set[int]:
        self.calls.append(ctx)
        return self._result


@pytest.fixture
def patched_seam():
    """Patch every external function the seam calls and route them into a
    single ``calls`` list with named entries.

    Yields ``(calls, patches_dict)`` so individual tests can inspect call
    args via the named MagicMocks while the order assertion uses ``calls``.
    """
    calls: list[str] = []
    runner_instance = MagicMock(name="runner")
    runner_instance.run.return_value = MagicMock(stdout="ifconfig-output\n")

    def record(name):
        def _side_effect(*a, **kw):
            calls.append(name)
            if name == "build_fleet":
                fleet = MagicMock(name="daemon_fleet")
                fleet.start_all.side_effect = lambda *a, **k: calls.append("fleet.start_all")
                fleet.wait_ready.side_effect = lambda *a, **k: calls.append("fleet.wait_ready")
                return fleet
            if name == "apply_fib":
                return [("route", "stub")]
            if name == "parse_bw_args":
                return [(0, 1, 5)] if a and a[0] else []
            if name == "parse_ext_args":
                return [("h0", "eth0", "192.168.99.1", 1500)] if a and a[0] else []
            if name == "build_host_graph":
                return ({}, None)
            return None

        return _side_effect

    targets = {
        "apply_ip_addr": "src.runtime.scenario_setup.apply_ip_addr",
        "setup_bridges": "src.runtime.scenario_setup.setup_bridges",
        "parse_bw_args": "src.runtime.scenario_setup.parse_bw_args",
        "set_link_bandwidth": "src.runtime.scenario_setup.set_link_bandwidth",
        "parse_ext_args": "src.runtime.scenario_setup.parse_ext_args",
        "attach_external_interface": "src.runtime.scenario_setup.attach_external_interface",
        "render_topology_png": "src.runtime.scenario_setup.render_topology_png",
        "build_host_graph": "src.runtime.scenario_setup.build_host_graph",
        "build_fleet": "src.runtime.scenario_setup.build_fleet",
        "apply_fib": "src.runtime.scenario_setup.apply_fib",
        "run_cefstatus_all": "src.runtime.scenario_setup.run_cefstatus_all",
        "print_mesh_links": "src.runtime.scenario_setup.print_mesh_links",
        "MininetCommandRunner": "src.runtime.scenario_setup.MininetCommandRunner",
    }

    patchers = {}
    mocks = {}
    for name, target in targets.items():
        p = patch(target)
        m = p.start()
        patchers[name] = p
        mocks[name] = m
        if name == "MininetCommandRunner":
            m.return_value = runner_instance
            m.side_effect = lambda *a, **k: (calls.append("MininetCommandRunner"), runner_instance)[1]
        else:
            m.side_effect = record(name)

    # ifconfig per-host runs are routed into ``calls`` so order can be verified.
    def _runner_run(host, argv):
        calls.append(f"runner.run({host})")
        return MagicMock(stdout="ifconfig-output\n")

    runner_instance.run.side_effect = _runner_run

    try:
        yield calls, mocks, runner_instance
    finally:
        for p in patchers.values():
            p.stop()


# -- canonical order ---------------------------------------------------------

def test_seam_walks_canonical_setup_order(patched_seam):
    calls, mocks, _ = patched_seam
    strategy = _FakeCacheStrategy(result={0, 2})
    spec = ScenarioSetupSpec(
        mesh_links=[("h0", "h1", "s0")],
        scheme=MagicMock(name="scheme"),
        host_count=3,
        publisher_ids={2},
        cache_strategy=strategy,
        fleet_run_dir=Path("/tmp/run_dir"),
        fib_k=2,
        bridge_manager=MagicMock(),
        bridge_configs=[{"bridge": "br0"}],
        bw_args="0:1:5",
        ext_args="h0:eth0:192.168.99.1",
        topo_png_path="/tmp/topo.png",
        topo_seed=42,
        topo_layout="kamada_kawai",
        fleet_cefnetd_timeout=10,
        fleet_readiness_policy="raise",
        fib_strategy="dijkstra",
        fib_uri_publishers={"ccnx:/x": 2},
    )
    net = MagicMock(name="net")

    result = setup_scenario(net, spec)

    assert calls == [
        "apply_ip_addr",
        "setup_bridges",
        "MininetCommandRunner",
        "runner.run(h0)", "runner.run(h1)", "runner.run(h2)",
        "parse_bw_args",
        "set_link_bandwidth",
        "parse_ext_args",
        "attach_external_interface",
        "render_topology_png",
        "build_host_graph",
        "build_fleet",
        "fleet.start_all",
        "fleet.wait_ready",
        "apply_fib",
        "run_cefstatus_all",
        "print_mesh_links",
    ]
    assert strategy.calls and strategy.calls[0].host_count == 3
    assert strategy.calls[0].publisher_ids == {2}
    assert isinstance(result, SetupResult)
    assert result.cache_node_set == {0, 2}
    assert result.fib_routes == [("route", "stub")]


def test_seam_with_empty_bw_ext_still_calls_parsers(patched_seam):
    # Even with empty bw/ext args, the parse_* functions are invoked once
    # each (they yield empty lists). Pins that parsing is unconditional;
    # only the apply step is gated by the parse result.
    calls, _, _ = patched_seam
    spec = ScenarioSetupSpec(
        mesh_links=[("h0", "h1", "s0")],
        scheme=MagicMock(),
        host_count=2,
        publisher_ids=set(),
        cache_strategy=_FakeCacheStrategy(result=set()),
        fleet_run_dir=Path("/tmp/run_dir"),
        fib_k=1,
        bw_args="",
        ext_args="",
    )
    setup_scenario(MagicMock(), spec)
    # parse_bw_args called, set_link_bandwidth not (empty bw_args).
    assert "parse_bw_args" in calls
    assert "set_link_bandwidth" not in calls
    assert "parse_ext_args" in calls
    assert "attach_external_interface" not in calls


# -- defaults & flow-back ----------------------------------------------------

def test_setup_scenario_skips_bridges_when_no_configs(patched_seam):
    calls, _, _ = patched_seam
    spec = ScenarioSetupSpec(
        mesh_links=[("h0", "h1", "s0")],
        scheme=MagicMock(),
        host_count=1,
        publisher_ids=set(),
        cache_strategy=_FakeCacheStrategy(result=set()),
        fleet_run_dir=Path("/tmp/run_dir"),
        fib_k=1,
    )
    setup_scenario(MagicMock(), spec)
    assert "setup_bridges" not in calls


def test_setup_result_carries_cache_set_and_fib_routes(patched_seam):
    _, mocks, _ = patched_seam
    spec = ScenarioSetupSpec(
        mesh_links=[("h0", "h1", "s0")],
        scheme=MagicMock(),
        host_count=2,
        publisher_ids={0},
        cache_strategy=_FakeCacheStrategy(result={0, 1}),
        fleet_run_dir=Path("/tmp/run_dir"),
        fib_k=3,
    )
    result = setup_scenario(MagicMock(), spec)

    assert result.cache_node_set == {0, 1}
    assert result.fib_routes == [("route", "stub")]
    # daemon_fleet is whatever build_fleet returned (MagicMock instance).
    assert result.daemon_fleet is not None


def test_fleet_options_forwarded_to_build_fleet(patched_seam):
    _, mocks, _ = patched_seam
    spec = ScenarioSetupSpec(
        mesh_links=[("h0", "h1", "s0")],
        scheme=MagicMock(),
        host_count=2,
        publisher_ids=set(),
        cache_strategy=_FakeCacheStrategy(result={1}),
        fleet_run_dir=Path("/tmp/disaster_run"),
        fib_k=1,
        fleet_cefnetd_timeout=25,
        fleet_readiness_policy="raise",
    )
    setup_scenario(MagicMock(), spec)

    bf = mocks["build_fleet"]
    _, kwargs = bf.call_args
    assert kwargs["cefnetd_timeout"] == 25
    assert kwargs["readiness_policy"] == "raise"
    # csmgrd hosts come from the strategy's place() result.
    args, _ = bf.call_args
    assert {1} == set(args[2])
