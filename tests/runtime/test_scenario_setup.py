"""Order/structure contract for setup_scenario(net, spec) -> SetupResult.

Pins the canonical order the seam walks through the common setup recipe
for every scenario (disaster, connect, mesh). The pre-canonical drift
(connect's bw/ext-after-everything, mesh/connect ``time.sleep(1)``, mesh
debug print, PNG-after-status timing) was removed in slice 2 after a
behavior-preserving extraction slice proved by /cefore-run-tests smoke
that those variations carried no real semantic load.
"""

import random
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch, MagicMock

import pytest

from src.core.roles import PUBLISHER, assign_roles
from src.runtime.cache_strategy import CacheContext
from src.runtime.scenario_setup import (
    MeshBuildSpec,
    ScenarioSetupSpec,
    SetupResult,
    TeardownResult,
    TeardownSpec,
    build_mesh_scenario,
    create_tclink_mininet,
    setup_scenario,
    teardown_scenario,
)
from src.runtime.topo import MeshTopo


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
                fleet.start_all.side_effect = lambda *a, **k: calls.append(
                    "fleet.start_all"
                )
                fleet.wait_ready.side_effect = lambda *a, **k: calls.append(
                    "fleet.wait_ready"
                )
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
        "ForwardingConfigManager": "src.runtime.scenario_setup.ForwardingConfigManager",
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
            m.side_effect = lambda *a, **k: (
                calls.append("MininetCommandRunner"),
                runner_instance,
            )[1]
        elif name == "ForwardingConfigManager":
            manager = MagicMock(name="forwarding_manager")
            manager.apply_configs.side_effect = lambda *a, **k: calls.append(
                "forwarding.apply_configs"
            )
            m.return_value = manager
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
        forwarding_config={
            "default": "flooding",
            "nodes": [{"id": [1], "strategy": "shortest_path"}],
        },
    )
    net = MagicMock(name="net")

    result = setup_scenario(net, spec)

    assert calls == [
        "apply_ip_addr",
        "setup_bridges",
        "MininetCommandRunner",
        "runner.run(h0)",
        "runner.run(h1)",
        "runner.run(h2)",
        "parse_bw_args",
        "set_link_bandwidth",
        "parse_ext_args",
        "attach_external_interface",
        "render_topology_png",
        "build_host_graph",
        "forwarding.apply_configs",
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


# -- teardown seam ----------------------------------------------------------


def test_teardown_uses_supplied_daemon_fleet_without_building():
    fleet = MagicMock(name="daemon_fleet")
    fleet.stop_all.return_value = []
    spec = TeardownSpec(
        host_count=3,
        csmgrd_host_ids={1},
        fleet_run_dir=Path("/tmp/run_dir"),
        daemon_fleet=fleet,
    )

    with patch("src.runtime.scenario_setup.build_fleet") as build:
        result = teardown_scenario(MagicMock(name="net"), spec)

    build.assert_not_called()
    fleet.stop_all.assert_called_once_with()
    assert result == TeardownResult(failures=[])


def test_teardown_fallback_forwards_fleet_shape_to_build_fleet():
    fleet = MagicMock(name="daemon_fleet")
    fleet.stop_all.return_value = []
    net = MagicMock(name="net")
    run_dir = Path("/tmp/disaster_run")
    spec = TeardownSpec(
        host_count=4,
        csmgrd_host_ids={1, 3},
        fleet_run_dir=run_dir,
        fleet_cefnetd_timeout=25,
        fleet_readiness_policy="raise",
    )

    with patch("src.runtime.scenario_setup.build_fleet", return_value=fleet) as build:
        teardown_scenario(net, spec)

    build.assert_called_once_with(
        net,
        4,
        {1, 3},
        run_dir,
        cefnetd_timeout=25,
        readiness_policy="raise",
    )


def test_teardown_order_is_fleet_then_bridge_manager_then_external_bridges():
    calls: list[str] = []
    fleet = MagicMock(name="daemon_fleet")
    fleet.stop_all.side_effect = lambda: calls.append("fleet.stop_all") or []
    bridge_manager = MagicMock(name="bridge_manager")
    bridge_manager.cleanup.side_effect = lambda: calls.append("bridge_manager.cleanup")
    spec = TeardownSpec(
        host_count=2,
        csmgrd_host_ids=set(),
        fleet_run_dir=Path("/tmp/run_dir"),
        daemon_fleet=fleet,
        bridge_manager=bridge_manager,
        cleanup_external_bridges=True,
    )

    with patch("src.runtime.scenario_setup.cleanup_external_bridges") as cleanup:
        cleanup.side_effect = lambda: calls.append("cleanup_external_bridges")
        teardown_scenario(MagicMock(name="net"), spec)

    assert calls == [
        "fleet.stop_all",
        "bridge_manager.cleanup",
        "cleanup_external_bridges",
    ]


def test_teardown_runs_bridge_cleanup_when_stop_all_returns_failures():
    stop_error = RuntimeError("cefnetd stop failed")
    fleet = MagicMock(name="daemon_fleet")
    fleet.stop_all.return_value = [("stop_cefnetd h0", stop_error)]
    bridge_manager = MagicMock(name="bridge_manager")
    spec = TeardownSpec(
        host_count=1,
        csmgrd_host_ids=set(),
        fleet_run_dir=Path("/tmp/run_dir"),
        daemon_fleet=fleet,
        bridge_manager=bridge_manager,
    )

    result = teardown_scenario(MagicMock(name="net"), spec)

    bridge_manager.cleanup.assert_called_once_with()
    assert result.failures == [("stop_cefnetd h0", stop_error)]


def test_teardown_external_bridge_cleanup_is_opt_in():
    fleet = MagicMock(name="daemon_fleet")
    fleet.stop_all.return_value = []
    spec = TeardownSpec(
        host_count=1,
        csmgrd_host_ids=set(),
        fleet_run_dir=Path("/tmp/run_dir"),
        daemon_fleet=fleet,
        cleanup_external_bridges=False,
    )

    with patch("src.runtime.scenario_setup.cleanup_external_bridges") as cleanup:
        teardown_scenario(MagicMock(name="net"), spec)

    cleanup.assert_not_called()


def test_teardown_skips_missing_bridge_manager():
    fleet = MagicMock(name="daemon_fleet")
    fleet.stop_all.return_value = []
    spec = TeardownSpec(
        host_count=1,
        csmgrd_host_ids=set(),
        fleet_run_dir=Path("/tmp/run_dir"),
        daemon_fleet=fleet,
        bridge_manager=None,
    )

    result = teardown_scenario(MagicMock(name="net"), spec)

    assert result == TeardownResult(failures=[])


def test_teardown_accumulates_failures_from_all_stages():
    stop_error = RuntimeError("stop failed")
    bridge_error = RuntimeError("bridge failed")
    external_error = RuntimeError("external failed")
    fleet = MagicMock(name="daemon_fleet")
    fleet.stop_all.return_value = [("stop_cefnetd h0", stop_error)]
    bridge_manager = MagicMock(name="bridge_manager")
    bridge_manager.cleanup.side_effect = bridge_error
    spec = TeardownSpec(
        host_count=1,
        csmgrd_host_ids=set(),
        fleet_run_dir=Path("/tmp/run_dir"),
        daemon_fleet=fleet,
        bridge_manager=bridge_manager,
        cleanup_external_bridges=True,
    )

    with patch(
        "src.runtime.scenario_setup.cleanup_external_bridges",
        side_effect=external_error,
    ):
        result = teardown_scenario(MagicMock(name="net"), spec)

    assert result.failures == [
        ("stop_cefnetd h0", stop_error),
        ("bridge_manager.cleanup", bridge_error),
        ("cleanup_external_bridges", external_error),
    ]


def test_teardown_all_success_returns_empty_result():
    fleet = MagicMock(name="daemon_fleet")
    fleet.stop_all.return_value = []
    bridge_manager = MagicMock(name="bridge_manager")
    spec = TeardownSpec(
        host_count=2,
        csmgrd_host_ids={0},
        fleet_run_dir=Path("/tmp/run_dir"),
        daemon_fleet=fleet,
        bridge_manager=bridge_manager,
        cleanup_external_bridges=True,
    )

    with patch("src.runtime.scenario_setup.cleanup_external_bridges"):
        result = teardown_scenario(MagicMock(name="net"), spec)

    assert result == TeardownResult(failures=[])


# -- mesh construction seam -------------------------------------------------


def _mesh_spec(seed: int | None = 42, **overrides) -> MeshBuildSpec:
    values = {
        "host_count": 3,
        "switch_limit": 3,
        "node_per_switch": 2,
        "host_degree_min": 1,
        "host_degree_max": 2,
        "switch_use_all": False,
        "rng": random.Random(seed) if seed is not None else None,
        "publisher_ids": frozenset(),
    }
    values.update(overrides)
    return MeshBuildSpec(**values)


def test_build_mesh_scenario_same_seed_repeats_roles_and_links(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    first = build_mesh_scenario(_mesh_spec(seed=123))
    second = build_mesh_scenario(_mesh_spec(seed=123))

    assert first.roles == second.roles
    assert first.topo.mesh_links == second.topo.mesh_links


def test_build_mesh_scenario_matches_inline_shared_rng_sequence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    seed = 77
    spec = _mesh_spec(seed=seed)
    expected_rng = random.Random(seed)
    expected_roles = assign_roles(spec.host_count, expected_rng, spec.publisher_ids)
    expected_topo = MeshTopo(
        hosts=spec.host_count,
        swhich_num=spec.switch_limit,
        rng=expected_rng,
        node_per_switch=spec.node_per_switch,
        host_degree_min=spec.host_degree_min,
        host_degree_max=spec.host_degree_max,
        switch_use_all=spec.switch_use_all,
    )

    result = build_mesh_scenario(spec)

    assert result.roles == expected_roles
    assert result.topo.mesh_links == expected_topo.mesh_links


def test_build_mesh_scenario_honors_explicit_publisher_ids(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = build_mesh_scenario(_mesh_spec(seed=5, publisher_ids=frozenset({1})))

    assert result.roles[1] is PUBLISHER


def test_build_mesh_scenario_empty_publishers_match_assign_roles_none(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    seed = 17
    expected_roles = assign_roles(3, random.Random(seed), publishers=None)

    result = build_mesh_scenario(_mesh_spec(seed=seed, publisher_ids=frozenset()))

    assert result.roles == expected_roles


def test_build_mesh_scenario_accepts_missing_rng(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    # rng=None draws degrees from a fresh unseeded Random. With degree range
    # 1..2 and 3 hosts, all-ones (probability 1/8) exhausts the spanning-tree
    # degree budget and raises ValueError, so pin degree_min=2: the budget is
    # then 6 >= 4 for every draw and the emergent switch count is always 3.
    result = build_mesh_scenario(_mesh_spec(seed=None, host_degree_min=2))

    assert set(result.roles) == {0, 1, 2}
    assert result.topo.mesh_links


def test_build_mesh_scenario_provisions_node_dirs_from_roles(monkeypatch):
    calls = []
    node_dirs = [Path("h0"), Path("h1"), Path("h2")]

    def fake_provision(roles):
        calls.append(roles)
        return node_dirs

    monkeypatch.setattr(
        "src.runtime.scenario_setup.provision_node_dirs", fake_provision
    )

    result = build_mesh_scenario(_mesh_spec(seed=9))

    assert calls == [result.roles]
    assert result.node_dirs is node_dirs


def test_build_mesh_scenario_cleans_node_dirs_when_topology_build_fails(monkeypatch):
    node_dirs = [Path("h0"), Path("h1"), Path("h2")]
    cleanup_calls = []
    boom = RuntimeError("switch count exceeds limit")

    monkeypatch.setattr(
        "src.runtime.scenario_setup.provision_node_dirs",
        lambda roles: node_dirs,
    )
    monkeypatch.setattr(
        "src.runtime.scenario_setup.MeshTopo",
        MagicMock(side_effect=boom),
    )
    monkeypatch.setattr(
        "src.runtime.scenario_setup.cleanup_node_dirs",
        lambda dirs: cleanup_calls.append(dirs),
    )

    with pytest.raises(RuntimeError) as excinfo:
        build_mesh_scenario(_mesh_spec(seed=9))

    assert excinfo.value is boom
    assert cleanup_calls == [node_dirs]


def test_create_tclink_mininet_uses_lazy_mininet_import(monkeypatch):
    mininet_pkg = ModuleType("mininet")
    mininet_net = ModuleType("mininet.net")
    mininet_link = ModuleType("mininet.link")
    mininet_pkg.net = mininet_net
    mininet_pkg.link = mininet_link

    class FakeTCLink:
        pass

    class FakeMininet:
        calls = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls.append(kwargs)

    mininet_net.Mininet = FakeMininet
    mininet_link.TCLink = FakeTCLink
    monkeypatch.setitem(sys.modules, "mininet", mininet_pkg)
    monkeypatch.setitem(sys.modules, "mininet.net", mininet_net)
    monkeypatch.setitem(sys.modules, "mininet.link", mininet_link)

    topo = MagicMock(name="topo")
    result = create_tclink_mininet(topo, autoSetMacs=True)

    assert isinstance(result, FakeMininet)
    assert FakeMininet.calls == [
        {
            "topo": topo,
            "link": FakeTCLink,
            "waitConnected": True,
            "autoSetMacs": True,
        }
    ]
