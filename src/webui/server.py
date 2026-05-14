"""Flask WebUI server for CeforeEmu live dashboard."""

import json
import os
import threading
from pathlib import Path

from flask import Flask, Response, send_from_directory

from .state import DashboardState

_ASSETS_DIR = Path(__file__).parent / "assets"


def create_app(state: DashboardState, stop_event: threading.Event) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["SECRET_KEY"] = os.urandom(16)

    @app.route("/")
    def index():
        return send_from_directory(str(_ASSETS_DIR), "index.html")

    @app.route("/assets/<path:filename>")
    def assets(filename):
        return send_from_directory(str(_ASSETS_DIR), filename)

    @app.route("/favicon.ico")
    def favicon():
        return Response(status=204)

    @app.route("/api/snapshot")
    def api_snapshot():
        return Response(
            json.dumps(state.snapshot(), ensure_ascii=False),
            content_type="application/json",
        )

    @app.route("/events")
    def events():
        def generate():
            yield ": connected\n\n"  # SSE comment — triggers onopen and flushes buffer
            while not stop_event.is_set():
                try:
                    data = json.dumps(state.snapshot(), ensure_ascii=False)
                    yield f"data: {data}\n\n"
                except Exception as exc:
                    yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"
                if stop_event.wait(timeout=2.0):
                    break
        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


class WebUIServer:
    """Runs Flask on a daemon thread. Use start()/stop() for lifecycle."""

    def __init__(self, state: DashboardState, port: int = 5080):
        self._state = state
        self._port = port
        self._server = None
        self._thread = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        from werkzeug.serving import make_server

        app = create_app(self._state, self._stop_event)
        self._server = make_server("0.0.0.0", self._port, app, threaded=True)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="WebUIServer",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._server is not None:
            self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=5)
