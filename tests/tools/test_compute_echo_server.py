"""Unit tests for the compute endpoint stand-in used by the ok-path tests.

The echo server is the reference "compute service" that the compute_call
ok-path tests point at, so its wire behaviour (status, Content-Type, exact
bytes) is the contract those tests trust. It lives in ``tools/`` which is not
an importable package, so it is loaded by path the same way
``tests/tools/test_run_cefore_checks.py`` loads the smoke checker.
"""

import http.client
import importlib.util
import json
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "tools/compute_echo_server.py"


def _load_server_module():
    """Load the echo server script as a module from its tools/ path."""
    spec = importlib.util.spec_from_file_location("compute_echo_server", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


echo = _load_server_module()


@pytest.fixture
def serve():
    """Start the echo server on an ephemeral port; yield its base URL.

    Port 0 lets the kernel pick a free port, so concurrent test runs never
    collide on the 18080 default. shutdown() must be called from this thread,
    not from the serving thread, or serve_forever() deadlocks.
    """
    servers = []

    def _start(payload_file=None):
        server = echo.make_server("127.0.0.1", 0, payload_file)
        servers.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield _start
    for server in servers:
        server.shutdown()
        server.server_close()


def test_post_echoes_method_path_body_and_headers(serve):
    base = serve()
    request = urllib.request.Request(
        f"{base}/compute", data=b"hello", headers={"Foo": "bar"}
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 200
        assert response.headers["Content-Type"] == "application/json"
        body = json.loads(response.read())
    assert body["method"] == "POST"
    assert body["path"] == "/compute"
    assert body["body"] == "hello"
    # urllib capitalizes header names it sends ("Foo" stays "Foo"); the server
    # echoes them exactly as received rather than normalizing.
    assert body["headers"]["Foo"] == "bar"


def test_get_returns_method_and_path(serve):
    base = serve()
    with urllib.request.urlopen(f"{base}/ping", timeout=5) as response:
        assert response.status == 200
        assert response.headers["Content-Type"] == "application/json"
        body = json.loads(response.read())
    assert body == {"method": "GET", "path": "/ping"}


@pytest.fixture
def payload(tmp_path):
    """A payload with a NUL and a non-UTF-8 byte, so "exact bytes" means it."""
    path = tmp_path / "payload.bin"
    path.write_bytes(b"compute-result\x00\xff\n")
    return path


def test_payload_file_get_returns_exact_bytes(serve, payload):
    base = serve(payload)
    with urllib.request.urlopen(f"{base}/result", timeout=5) as response:
        assert response.status == 200
        assert response.headers["Content-Type"] == "application/octet-stream"
        assert response.headers["Content-Length"] == str(len(payload.read_bytes()))
        assert response.read() == payload.read_bytes()


def test_payload_file_post_returns_exact_bytes(serve, payload):
    base = serve(payload)
    request = urllib.request.Request(f"{base}/result", data=b"ignored request body")
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 200
        assert response.headers["Content-Type"] == "application/octet-stream"
        assert response.read() == payload.read_bytes()


def test_argument_defaults_are_localhost_and_18080():
    args = echo.build_parser().parse_args([])
    assert args.bind == "127.0.0.1"
    assert args.port == 18080
    assert args.payload_file is None


def test_arguments_parse_bind_port_and_payload_file():
    args = echo.build_parser().parse_args(
        ["--bind", "0.0.0.0", "--port", "9", "--payload-file", "/tmp/p.bin"]
    )
    assert args.bind == "0.0.0.0"
    assert args.port == 9
    assert args.payload_file == Path("/tmp/p.bin")


def test_malformed_content_length_is_rejected_with_400(serve):
    """A broken header must not become a 500 or a hung read.

    urllib refuses to send a non-integer Content-Length, so the raw header is
    written through http.client instead.
    """
    base = serve()
    conn = http.client.HTTPConnection(
        "127.0.0.1", int(base.rsplit(":", 1)[1]), timeout=5
    )
    try:
        conn.putrequest("POST", "/compute", skip_accept_encoding=True)
        conn.putheader("Content-Length", "not-a-number")
        conn.endheaders()
        response = conn.getresponse()
        assert response.status == 400
        assert response.read() == b"bad Content-Length\n"
    finally:
        conn.close()


def _readline_with_timeout(stream, timeout=10.0):
    """Return one line from `stream`, or None if it does not arrive in time.

    A plain readline() on a child that neither prints nor exits would hang the
    whole test session, and pytest cannot interrupt it.
    """
    lines = []
    reader = threading.Thread(
        target=lambda: lines.append(stream.readline()), daemon=True
    )
    reader.start()
    reader.join(timeout)
    return lines[0] if lines else None


def _stop_and_read_stderr(proc):
    """Stop `proc` if needed and return its stderr text, for diagnostics only.

    stderr can only be drained once the child is gone, so failure messages
    that want it have to stop the child first.
    """
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=5)
    try:
        return proc.stderr.read()
    except ValueError:
        return "<stderr already closed>"


def test_startup_line_reports_bound_port_and_sigterm_exits_zero():
    """The one stdout line is how a supervisor learns the server is up.

    Port 0 proves the line carries the *bound* port rather than the argument;
    the ok-path tests keep the real port fixed but still poll for this line.
    """
    proc = subprocess.Popen(
        [sys.executable, str(_SCRIPT), "--port", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = _readline_with_timeout(proc.stdout)
        assert line is not None, (
            f"no startup line; stderr={_stop_and_read_stderr(proc)!r}"
        )
        prefix, _, port = line.rstrip("\n").rpartition(":")
        assert prefix == "listening on 127.0.0.1", (
            f"startup line {line!r}; stderr={_stop_and_read_stderr(proc)!r}"
        )
        assert port.isdigit() is True, f"startup line {line!r}"
        proc.terminate()
        try:
            status = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            raise AssertionError(
                f"SIGTERM did not stop the server; stderr={_stop_and_read_stderr(proc)!r}"
            ) from None
        assert status == 0, f"exit status {status}; stderr={proc.stderr.read()!r}"
    finally:
        # Cleanup only — an assertion here would replace whatever the test was
        # actually failing on with its own message.
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        proc.stdout.close()
        proc.stderr.close()
