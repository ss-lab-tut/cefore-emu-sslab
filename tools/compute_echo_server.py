#!/usr/bin/env python3
"""Deterministic HTTP stand-in for a compute endpoint.

The compute_call ok-path tests need an endpoint whose reply is byte-for-byte
predictable: the same file the test wrote must come back over HTTP, land in
compute_call's output_file, and survive cefputfile/cefgetfile unchanged. Any
real service would make that three-way byte comparison untestable. This script
is deliberately dependency-free (stdlib only) because it runs in two places
where nothing can be installed: inside a Mininet host namespace on this
machine, and on the lab HPC over ssh/scp.

Why not `python -m http.server`: it answers POST with 501, and compute_call
issues POST. It also cannot echo the request back, which is what the non
payload-file mode is for.
"""

import argparse
import json
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def make_handler(payload):
    """Build the request handler class, closing over the fixed payload.

    payload is None (echo mode) or the bytes every request must answer with.
    The bytes are captured once at startup so every reply is identical even if
    the file is rewritten mid-run — the ok-path test compares three copies of
    them and a changing source would make a mismatch unexplainable.
    """

    class EchoHandler(BaseHTTPRequestHandler):
        # Per-request log lines: BaseHTTPRequestHandler.log_message already
        # writes one line to stderr, which keeps stdout free for the single
        # startup line the tests poll for.

        def do_GET(self):
            if payload is not None:
                self._send_bytes(payload, "application/octet-stream")
                return
            self._send_json({"method": "GET", "path": self.path})

        def do_POST(self):
            # A hostile or broken client must not take the endpoint down: a
            # non-integer header would raise out of the handler (500 plus a
            # traceback in the log) and a negative one would make read(-1)
            # block until the peer closed. Both become a plain 400.
            raw_length = self.headers.get("Content-Length", "0")
            try:
                length = int(raw_length)
            except ValueError:
                length = -1
            if length < 0:
                self._send_bytes(
                    b"bad Content-Length\n", "text/plain; charset=utf-8", status=400
                )
                return
            # Read the body even in payload mode: replying while request bytes
            # sit unread makes the close an RST, which the client sees as a
            # ConnectionResetError instead of the response.
            body = self.rfile.read(length)
            if payload is not None:
                self._send_bytes(payload, "application/octet-stream")
                return
            self._send_json(
                {
                    "method": "POST",
                    "path": self.path,
                    "headers": dict(self.headers.items()),
                    # compute_call may post binary; errors="replace" keeps a
                    # stray byte from turning into a 500 from json.dumps.
                    "body": body.decode("utf-8", errors="replace"),
                }
            )

        def _send_bytes(self, data, content_type, status=200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, document):
            self._send_bytes(json.dumps(document).encode("utf-8"), "application/json")

    return EchoHandler


def make_server(bind, port, payload_file=None):
    """Create (but do not serve) the echo server bound to bind:port.

    Returning the server instead of serving it lets callers read the actually
    bound port (port 0 picks a free one) before any request is made.
    Reading payload_file here is deliberate: a missing file must fail at
    startup, not as a mid-run 500 that the ok-path test would misread.
    """
    payload = None if payload_file is None else Path(payload_file).read_bytes()
    return ThreadingHTTPServer((bind, port), make_handler(payload))


def build_parser():
    """Command line of the stand-in.

    The default port is 18080, not 80: the lab HPC already serves on 80, and
    binding 80 also needs root, which the endpoint side must not require.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument(
        "--payload-file",
        type=Path,
        default=None,
        help="answer every request with this file's exact bytes",
    )
    return parser


def _raise_keyboard_interrupt(signum, frame):
    """Turn SIGTERM into the same exception Ctrl-C raises.

    Calling server.shutdown() from a signal handler would deadlock: the
    handler runs on the thread that is inside serve_forever(), and shutdown()
    waits for that loop to finish. Unwinding out of serve_forever() instead
    lets main() close the socket and exit 0, so a supervisor that terminates
    the stand-in never sees a failure status.
    """
    raise KeyboardInterrupt


def main(argv=None):
    args = build_parser().parse_args(argv)
    server = make_server(args.bind, args.port, args.payload_file)
    try:
        # Registration and the startup line live inside the try because a
        # supervisor may send SIGTERM the moment it reads that line — or even
        # before serve_forever() is entered. Outside the try, such a signal
        # would escape as an uncaught KeyboardInterrupt and exit non-zero.
        signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
        # Exactly one stdout line, and the bound port rather than args.port, so
        # a caller that passed 0 still learns where to connect. Everything else
        # the server says goes to stderr, so this line is unambiguous.
        print(f"listening on {args.bind}:{server.server_address[1]}", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    main()
