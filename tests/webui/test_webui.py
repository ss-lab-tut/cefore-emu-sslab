"""Unit tests for WebUI state and server."""

import threading
import time

from src.webui.state import DashboardState, _cefnetd_is_up, _csmgrd_is_up


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
