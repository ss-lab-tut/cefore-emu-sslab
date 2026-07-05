"""Unit tests for WebUI state and server."""

import json
import threading
import time
import urllib.request
from urllib.error import URLError

import pytest

from src.webui.state import DashboardState, _cefnetd_is_up, _csmgrd_is_up
from src.webui.server import WebUIServer


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def make_dashboard():
    return DashboardState(
        host_count=3,
        cache_nodes={1},
        seed=42,
        started_at=time.time(),
        flap_state_getter=lambda: [],
    )


# ------------------------------------------------------------------ #
# _csmgrd_is_up()                                                     #
# ------------------------------------------------------------------ #

def test_csmgrd_is_up_empty():
    assert _csmgrd_is_up("") is False


def test_csmgrd_is_up_skipped():
    assert _csmgrd_is_up("skipped: host down") is False


def test_csmgrd_is_up_connection_refused():
    assert _csmgrd_is_up("connection refused") is False


def test_csmgrd_is_up_error():
    assert _csmgrd_is_up("error: cannot connect") is False


def test_csmgrd_is_up_positive():
    output = "Connect to 127.0.0.1 9799\nAll Connection Num = 0\n"
    assert _csmgrd_is_up(output) is True


def test_csmgrd_is_up_no_positive_markers():
    assert _csmgrd_is_up("some unknown output without markers") is False


# ------------------------------------------------------------------ #
# _cefnetd_is_up()                                                    #
# ------------------------------------------------------------------ #

def test_cefnetd_is_up_empty():
    assert _cefnetd_is_up("") is False


def test_cefnetd_is_up_connection_refused():
    assert _cefnetd_is_up("connection refused") is False


def test_cefnetd_is_up_error():
    assert _cefnetd_is_up("error: no such file") is False


def test_cefnetd_is_up_positive_faces():
    assert _cefnetd_is_up("Faces: 2\nFIB entries: 3\n") is True


def test_cefnetd_is_up_positive_fib_only():
    assert _cefnetd_is_up("fib entries: 0\n") is True


def test_cefnetd_is_up_no_positive_markers():
    assert _cefnetd_is_up("some unknown output without markers") is False


# ------------------------------------------------------------------ #
# auto-monitor config generation logic                                #
# ------------------------------------------------------------------ #

def _run_auto_monitor_logic(monitoring_raw, dashboard):
    """Simulate the disaster.py auto-monitor setup."""
    monitoring_config = dict(monitoring_raw or {})
    if dashboard is not None and not monitoring_config.get("targets"):
        monitoring_config["targets"] = [
            {"type": "cefstatus",   "hosts": "all"},
            {"type": "csmgrstatus", "hosts": "cache"},
        ]
        monitoring_config.setdefault("interval", 5)
    return monitoring_config


def test_auto_monitor_adds_targets_when_no_config():
    ds = make_dashboard()
    result = _run_auto_monitor_logic({}, ds)
    assert len(result["targets"]) == 2
    assert result["interval"] == 5


def test_auto_monitor_preserves_user_interval():
    ds = make_dashboard()
    result = _run_auto_monitor_logic({"interval": 1, "output_json": "m.json"}, ds)
    assert result["interval"] == 1
    assert result["output_json"] == "m.json"
    assert len(result["targets"]) > 0


def test_auto_monitor_does_not_overwrite_user_targets():
    ds = make_dashboard()
    original = [{"type": "cefstatus", "hosts": [0]}]
    result = _run_auto_monitor_logic({"targets": original}, ds)
    assert result["targets"] == original


def test_auto_monitor_no_dashboard_means_no_targets():
    result = _run_auto_monitor_logic({}, None)
    assert "targets" not in result


# ------------------------------------------------------------------ #
# SSE endpoint smoke test                                             #
# ------------------------------------------------------------------ #

def test_sse_endpoint_responds():
    from src.webui.server import create_app

    stop = threading.Event()
    ds = make_dashboard()
    app = create_app(ds, stop)
    app.config["TESTING"] = True

    with app.test_client() as client:
        resp = client.get("/events", buffered=False)
        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type
        first = next(resp.response)
        assert first == b": connected\n\n"
        resp.close()

    stop.set()


def test_index_uses_local_assets_only():
    from src.webui.server import create_app

    stop = threading.Event()
    app = create_app(make_dashboard(), stop)
    app.config["TESTING"] = True

    with app.test_client() as client:
        resp = client.get("/")
        html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "cdn.jsdelivr.net" not in html
    assert "unpkg.com" not in html
    assert "cdnjs.cloudflare.com" not in html
    assert "/assets/vendor/chart.umd.min.js" in html
    assert "/assets/vendor/vis-network.min.js" in html
    assert "/assets/vendor/vis-network.min.css" in html
    stop.set()


def test_vendor_assets_are_served():
    from src.webui.server import create_app

    stop = threading.Event()
    app = create_app(make_dashboard(), stop)
    app.config["TESTING"] = True

    with app.test_client() as client:
        chart = client.get("/assets/vendor/chart.umd.min.js")
        vis_js = client.get("/assets/vendor/vis-network.min.js")
        vis_css = client.get("/assets/vendor/vis-network.min.css")

    assert chart.status_code == 200
    assert "window.Chart" in chart.get_data(as_text=True)
    assert vis_js.status_code == 200
    assert "window.vis" in vis_js.get_data(as_text=True)
    assert vis_css.status_code == 200
    assert "#topology-canvas" in vis_css.get_data(as_text=True)
    stop.set()


def test_favicon_does_not_404():
    from src.webui.server import create_app

    stop = threading.Event()
    app = create_app(make_dashboard(), stop)
    app.config["TESTING"] = True

    with app.test_client() as client:
        resp = client.get("/favicon.ico")

    assert resp.status_code == 204
    stop.set()


# ------------------------------------------------------------------ #
# DashboardState.set_topology()                                        #
# ------------------------------------------------------------------ #

class TestDashboardStateTopology:
    """set_topology converts MeshTopo.mesh_links into vis-network nodes/edges."""

    def test_set_topology_creates_a_node_per_host(self):
        ds = DashboardState(host_count=3, cache_nodes=set(), seed=0, started_at=time.time())
        ds.set_topology([])
        assert ds._topology["nodes"] == [
            {"id": 0, "label": "h0"},
            {"id": 1, "label": "h1"},
            {"id": 2, "label": "h2"},
        ]
        # empty mesh_links must not fabricate edges
        assert ds._topology["edges"] == []

    def test_set_topology_builds_edges_from_a_shared_switch_link(self):
        ds = DashboardState(host_count=3, cache_nodes=set(), seed=0, started_at=time.time())
        # One canonical multi-host link: all three hosts share switch s0,
        # so every pair among them becomes an edge (TopologyModel.edges()).
        mesh_links = [{"switch": "s0", "subnet": 0, "hosts": [0, 1, 2], "host_eth": {}}]
        ds.set_topology(mesh_links)
        edges = ds._topology["edges"]
        assert len(edges) == 3
        assert {"from": 0, "to": 1} in edges
        assert {"from": 0, "to": 2} in edges
        assert {"from": 1, "to": 2} in edges

    def test_set_topology_dedupes_reversed_pair_across_link_entries(self):
        ds = DashboardState(host_count=2, cache_nodes=set(), seed=0, started_at=time.time())
        # Two legacy point-to-point entries describe the same host pair with
        # host_a/host_b swapped. TopologyModel._normalize() sorts each link's
        # hosts independently, so both entries yield the edge (0, 1) — the
        # `seen` set in set_topology() must collapse them into a single edge
        # instead of emitting a duplicate.
        mesh_links = [
            {"host_a": 0, "host_b": 1, "subnet": 0},
            {"host_a": 1, "host_b": 0, "subnet": 1},
        ]
        ds.set_topology(mesh_links)
        assert ds._topology["edges"] == [{"from": 0, "to": 1}]


# ------------------------------------------------------------------ #
# DashboardState.record_monitor()                                      #
# ------------------------------------------------------------------ #

class TestDashboardStateRecordMonitor:
    """record_monitor is invoked from the Monitor background thread per sample."""

    def test_record_monitor_updates_last_status_fields_for_known_host(self):
        ds = make_dashboard()
        ds.record_monitor({"host": 1, "type": "cefstatus", "output": "faces: 2"})
        ds.record_monitor({"host": 1, "type": "csmgrstatus", "output": "Connect to 127.0.0.1"})
        assert ds._hosts[1]["last_cefstatus"] == "faces: 2"
        assert ds._hosts[1]["last_csmgrstatus"] == "Connect to 127.0.0.1"

    def test_record_monitor_ignores_records_for_unknown_host(self):
        ds = make_dashboard()  # host_count=3 -> known hosts are 0,1,2
        ds.record_monitor({"host": 99, "type": "cefstatus", "output": "faces: 1"})
        assert 99 not in ds._hosts
        # the raw record is still appended to _monitor_records for audit/history purposes
        assert ds._monitor_records[-1]["host"] == 99

    def test_record_monitor_evicts_oldest_record_at_max_monitor_capacity(self):
        ds = make_dashboard()
        # Instance-attribute override keeps the test fast instead of inserting
        # MAX_MONITOR=500 real records; self.MAX_MONITOR resolves to this
        # instance value before the class default.
        ds.MAX_MONITOR = 2
        ds.record_monitor({"host": 0, "type": "cefstatus", "output": "first"})
        ds.record_monitor({"host": 0, "type": "cefstatus", "output": "second"})
        ds.record_monitor({"host": 0, "type": "cefstatus", "output": "third"})
        assert len(ds._monitor_records) == 2
        assert [r["output"] for r in ds._monitor_records] == ["second", "third"]


# ------------------------------------------------------------------ #
# DashboardState.record_operation()                                    #
# ------------------------------------------------------------------ #

class TestDashboardStateRecordOperation:
    """record_operation feeds both _operations and the success_history trend line.

    state.py:130 -- a success_history sample is appended for EVERY op_type,
    but only get/sub operations are counted toward the total/success/rate
    aggregation. This is a deliberate asymmetry (Codex-verified) and the
    single easiest place to write a test that asserts the wrong thing.
    """

    def test_record_operation_always_appends_a_history_sample_for_every_op_type(self):
        ds = make_dashboard()
        ds.record_operation({"op_type": "put", "success": True})
        ds.record_operation({"op_type": "pub", "success": True})
        # both calls appended a sample even though neither op_type counts
        # toward the rate computation
        assert len(ds._success_history) == 2
        last = ds._success_history[-1]
        assert last["total"] == 0
        assert last["success"] == 0
        assert last["rate"] == 0.0

    def test_record_operation_rate_reflects_get_and_sub_only(self):
        ds = make_dashboard()
        ds.record_operation({"op_type": "put", "success": False})   # ignored by rate
        ds.record_operation({"op_type": "get", "success": True})
        ds.record_operation({"op_type": "sub", "success": False})
        ds.record_operation({"op_type": "pub", "success": True})    # ignored by rate
        last = ds._success_history[-1]
        assert last["total"] == 2      # only the get + sub samples
        assert last["success"] == 1    # only the get succeeded
        assert last["rate"] == 0.5
        # yet a sample was appended for every one of the 4 calls
        assert len(ds._success_history) == 4

    def test_record_operation_evicts_oldest_operation_at_max_operations_capacity(self):
        ds = make_dashboard()
        ds.MAX_OPERATIONS = 2  # avoid inserting 1000 real records to hit the class default
        ds.record_operation({"op_type": "get", "uri": "a", "success": True})
        ds.record_operation({"op_type": "get", "uri": "b", "success": True})
        ds.record_operation({"op_type": "get", "uri": "c", "success": True})
        assert len(ds._operations) == 2
        assert [op["uri"] for op in ds._operations] == ["b", "c"]

    def test_record_operation_evicts_oldest_history_sample_at_max_history_capacity(self):
        ds = make_dashboard()
        ds.MAX_HISTORY = 2  # avoid inserting 300 real samples to hit the class default
        for _ in range(3):
            ds.record_operation({"op_type": "get", "success": True})
        assert len(ds._success_history) == 2


# ------------------------------------------------------------------ #
# DashboardState.record_launch()                                       #
# ------------------------------------------------------------------ #

class TestDashboardStateRecordLaunch:
    """record_launch logs a fire-and-forget put/pub launch (result unknown yet)."""

    def test_record_launch_appends_launch_shaped_operation_with_success_none(self):
        ds = make_dashboard()
        ds.record_launch("put", host=1, uri="ccnx:/test/example")
        op = ds._operations[-1]
        assert op["op_type"] == "put"
        assert op["host"] == 1
        assert op["uri"] == "ccnx:/test/example"
        # success is unknown at launch time -- distinct from a completed
        # operation's True/False, and must not be counted by the rate calc
        assert op["success"] is None
        assert op["ts"] is None
        assert op["exit_code"] is None
        assert op["down_hosts"] == []
        assert op["phase"] is None

    def test_record_launch_evicts_oldest_operation_at_max_operations_capacity(self):
        ds = make_dashboard()
        ds.MAX_OPERATIONS = 1  # avoid inserting 1000 real launches to hit the class default
        ds.record_launch("put", host=0, uri="a")
        ds.record_launch("pub", host=1, uri="b")
        assert len(ds._operations) == 1
        assert ds._operations[0]["uri"] == "b"


# ------------------------------------------------------------------ #
# DashboardState.snapshot()                                            #
# ------------------------------------------------------------------ #

class TestDashboardStateSnapshot:
    """snapshot() assembles the full JSON-serializable dashboard payload."""

    def test_snapshot_assembles_all_expected_keys_and_host_entries(self):
        ds = make_dashboard()  # host_count=3, cache_nodes={1}, seed=42
        snap = ds.snapshot()
        assert set(snap.keys()) == {
            "elapsed_sec", "meta", "hosts", "operations",
            "topology", "success_history", "down_hosts",
        }
        assert snap["meta"] == {"seed": 42, "host_count": 3, "cache_nodes": [1]}
        assert set(snap["hosts"].keys()) == {"0", "1", "2"}
        assert snap["hosts"]["1"]["is_cache"] is True
        assert snap["hosts"]["0"]["is_cache"] is False

    def test_snapshot_reflects_down_hosts_from_flap_state_getter(self):
        ds = DashboardState(
            host_count=2, cache_nodes=set(), seed=1, started_at=time.time(),
            flap_state_getter=lambda: [1],
        )
        snap = ds.snapshot()
        assert snap["down_hosts"] == [1]
        assert snap["hosts"]["1"]["up"] is False
        assert snap["hosts"]["0"]["up"] is True

    def test_snapshot_slices_operations_to_last_200(self):
        ds = make_dashboard()
        ds.MAX_OPERATIONS = 10_000  # keep every sample; only the snapshot slice is under test
        for i in range(250):
            ds.record_launch("put", host=0, uri=f"u{i}")
        snap = ds.snapshot()
        assert len(snap["operations"]) == 200
        assert snap["operations"][0]["uri"] == "u50"
        assert snap["operations"][-1]["uri"] == "u249"

    def test_snapshot_slices_success_history_to_last_300(self):
        ds = make_dashboard()
        ds.MAX_HISTORY = 10_000  # keep every sample; only the snapshot slice is under test
        for _ in range(320):
            ds.record_operation({"op_type": "get", "success": True})
        snap = ds.snapshot()
        assert len(snap["success_history"]) == 300

    def test_snapshot_calls_flap_state_getter_and_uses_its_result(self):
        calls = []

        def getter():
            calls.append(True)
            return [0]

        ds = DashboardState(
            host_count=2, cache_nodes=set(), seed=0, started_at=time.time(),
            flap_state_getter=getter,
        )
        snap = ds.snapshot()
        assert calls == [True]
        assert snap["down_hosts"] == [0]

    def test_snapshot_getter_can_reenter_snapshot_without_deadlock(self):
        """Proxy for "flap_state_getter runs outside the lock".

        threading.Lock is not reentrant: if the getter were called while
        holding the state lock, a getter that calls snapshot() again would
        deadlock the calling thread forever. Running this in a background
        thread with a bounded join() lets the test fail fast (thread still
        alive) instead of hanging the whole suite if that invariant regresses.
        """
        calls = {"n": 0}
        ds_holder = {}

        def getter():
            calls["n"] += 1
            if calls["n"] == 1:
                ds_holder["ds"].snapshot()  # recursive call -- must not deadlock
            return []

        ds = DashboardState(
            host_count=1, cache_nodes=set(), seed=0, started_at=time.time(),
            flap_state_getter=getter,
        )
        ds_holder["ds"] = ds

        result = {}

        def run():
            result["snap"] = ds.snapshot()

        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(timeout=3)
        assert not t.is_alive()  # still alive here would mean a deadlock occurred
        assert "snap" in result


# ------------------------------------------------------------------ #
# server.py -- /api/snapshot route                                     #
# ------------------------------------------------------------------ #

class TestApiSnapshotRoute:
    """The /api/snapshot Flask route serializes DashboardState.snapshot()."""

    def test_api_snapshot_returns_200_json_matching_state_snapshot(self):
        from src.webui.server import create_app

        stop = threading.Event()
        ds = make_dashboard()
        app = create_app(ds, stop)
        app.config["TESTING"] = True

        with app.test_client() as client:
            resp = client.get("/api/snapshot")
        stop.set()

        assert resp.status_code == 200
        assert resp.content_type == "application/json"
        body = json.loads(resp.get_data(as_text=True))
        expected = ds.snapshot()
        # elapsed_sec is wall-clock-derived and re-evaluated by this second
        # call, so compare it with tolerance instead of exact equality --
        # everything else must match byte-for-byte.
        assert body["meta"] == expected["meta"]
        assert body["hosts"] == expected["hosts"]
        assert body["operations"] == expected["operations"]
        assert body["topology"] == expected["topology"]
        assert body["success_history"] == expected["success_history"]
        assert body["down_hosts"] == expected["down_hosts"]
        assert body["elapsed_sec"] == pytest.approx(expected["elapsed_sec"], abs=0.5)


# ------------------------------------------------------------------ #
# server.py -- WebUIServer lifecycle (real socket, no root required)    #
# ------------------------------------------------------------------ #

@pytest.fixture
def running_webui_server():
    """A real WebUIServer bound to an OS-assigned port (port=0), started.

    Some sandboxes block raw socket creation (seccomp/no_new_privs); that is
    an environment constraint, not a defect under test, so PermissionError
    on start() is a skip rather than a failure.
    """
    ds = make_dashboard()
    srv = WebUIServer(ds, port=0)
    try:
        srv.start()
    except PermissionError:
        pytest.skip("socket creation blocked in sandbox")
    yield srv
    srv.stop()


def _wait_for_json(url: str, attempts: int = 20, delay: float = 0.05) -> dict:
    """Bounded retry loop for the server thread to finish binding/accepting.

    No fixed sleep before the first attempt -- only a short, bounded backoff
    between retries so the test fails fast instead of ever hanging.
    """
    last_error = None
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                assert resp.status == 200
                return json.loads(resp.read().decode())
        except URLError as exc:
            last_error = exc
            time.sleep(delay)
    raise AssertionError(f"server never became reachable at {url}: {last_error}")


class TestWebUIServerLifecycle:
    """start()/stop() run Flask on a real daemon thread bound to a real socket."""

    def test_start_binds_os_assigned_port_and_serves_real_snapshot(self, running_webui_server):
        srv = running_webui_server
        port = srv._server.server_address[1]
        assert port != 0  # OS assigned a concrete port for the port=0 request

        body = _wait_for_json(f"http://127.0.0.1:{port}/api/snapshot")
        assert "hosts" in body
        assert "meta" in body

    def test_after_stop_the_thread_is_dead_and_connections_are_refused(self, running_webui_server):
        srv = running_webui_server
        port = srv._server.server_address[1]
        _wait_for_json(f"http://127.0.0.1:{port}/api/snapshot")  # confirm it's actually up first

        srv.stop()

        assert srv._thread is not None
        assert not srv._thread.is_alive()
        with pytest.raises(URLError):
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/snapshot", timeout=1)

    def test_stop_is_idempotent_when_called_twice(self):
        ds = make_dashboard()
        srv = WebUIServer(ds, port=0)
        try:
            srv.start()
        except PermissionError:
            pytest.skip("socket creation blocked in sandbox")
        srv.stop()
        srv.stop()  # calling stop() again after shutdown must not raise
        assert not srv._thread.is_alive()

    def test_stop_without_start_is_safe(self):
        ds = make_dashboard()
        srv = WebUIServer(ds, port=0)
        # never started -- _server/_thread are still None; stop() must be a no-op
        srv.stop()
