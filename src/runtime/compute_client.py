"""External compute API client for cache/edge nodes.

Emulates edge-compute offload: a host (edge node) sends an HTTP request to a
compute resource (a Jetson-class box on the LAN, or any HTTP API), optionally
saves the response under the run directory, and optionally re-publishes the
result into the ICN via ``cefputfile`` so other nodes can ``get`` it.

Success is strict by design: curl must exit 0 AND the HTTP status must be
2xx AND, when a publish is requested, cefputfile must exit 0. A transport
that "worked" at the TCP level but returned 4xx/5xx is an experiment
failure, not a success — publishing an error body into the ICN would poison
downstream consumers.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from mininet.log import info

from ..core.paths import resolve_run_path
from .cef_argv import build_cefputfile_argv

# curl exit codes that mean "the endpoint could not be reached at all":
# 5 = proxy resolve, 6 = DNS resolve, 7 = connect refused/unreachable,
# 28 = timed out. These are environment failures (ext/bridges not set up,
# compute box down) — the scheduler records them as skipped, not failed,
# so experiment analysis can separate "compute was wrong" from "compute
# was unreachable". Anything else fails closed (failure).
_ENV_FAILURE_EXITS = frozenset({5, 6, 7, 28})

# Margin added to the CommandRunner deadline on top of curl's --max-time:
# curl's own timeout should always win, the runner deadline only guards a
# hung netns exec that never reaches curl.
_RUNNER_TIMEOUT_MARGIN = 5

# 2026-07-16 audit fix: the publish deadline must be independent of the HTTP
# timeout — at cefputfile's minimum rate (0.001 Mbps) even a few-KB result
# outlives timeout+margin, so reusing it killed valid slow publications.
# The default still bounds a hung cefputfile; slow transfers override it via
# the event's publish_timeout.
_PUBLISH_TIMEOUT_DEFAULT = 120


@dataclass(frozen=True)
class ComputeResult:
    """Typed outcome of one compute_call.

    ``publish_ok`` is None when no publish was requested or the request never
    reached the publish stage (HTTP already failed); True/False report the
    actual cefputfile outcome. ``env_failure`` marks unreachable-endpoint
    curl exits so callers can classify skipped-vs-failed.
    """

    ok: bool
    http_status: Optional[int]
    curl_exit: Optional[int]
    publish_ok: Optional[bool]
    output_file: Optional[str]
    stdout: str
    env_failure: bool


def _split_status(stdout: str):
    """Split curl output produced with ``-w '\\n%{http_code}'``.

    Returns (body, status) where status is None when the trailing line is not
    an integer (e.g. curl died before writing it).
    """
    body, sep, status_line = stdout.rpartition("\n")
    if not sep:
        body, status_line = "", stdout
    try:
        return body, int(status_line.strip())
    except ValueError:
        # No status line: the whole output is body, status unknown.
        return stdout, None


def compute_call(runner, host_idx, endpoint, method="GET", payload=None,
                 headers=None, output_file=None, publish_uri=None,
                 pub_opts=None, run_dir=None, timeout=30,
                 publish_timeout=None):
    """Execute an HTTP API call from a Mininet host and report a ComputeResult.

    Args:
        runner: CommandRunner to execute through (injected; the caller owns
            adapter choice so tests use FakeCommandRunner without patching).
        host_idx: Host index to execute from.
        endpoint: URL to call.
        method: HTTP method (GET or POST).
        payload: Request body (for POST).
        headers: Optional dict of HTTP headers (each becomes ``-H "k: v"``).
        output_file: Path to save response (relative to run_dir).
        publish_uri: If set, publish the saved output via cefputfile.
        pub_opts: Optional dict of cefputfile options (rate, block_size,
            expiry, cache_time, valid_algo, port_num). expiry/cache_time
            default to 3000 (the values this client always used).
        run_dir: Experiment run directory (Path).
        timeout: Request timeout in seconds (curl --max-time; the runner
            deadline is armed with a margin on top).
        publish_timeout: Deadline in seconds for the cefputfile run
            (default 120). Independent of ``timeout``: publishing speed is
            governed by pub_opts rate, not by the HTTP request.

    Returns:
        ComputeResult.
    """
    host_name = f"h{host_idx}"

    argv = ["curl", "-s", "-S", "--max-time", str(timeout)]
    if method == "POST":
        argv.extend(["-X", "POST"])
        if payload:
            argv.extend(["-d", payload])
    for key, value in (headers or {}).items():
        argv.extend(["-H", f"{key}: {value}"])

    out_path = None
    if output_file and run_dir:
        out_path = resolve_run_path(Path(run_dir), output_file)
        argv.extend(["-o", str(out_path)])

    # Trailing status line: with -o the body goes to the file and stdout is
    # just the status; without -o the status is split off the captured body.
    argv.extend(["-w", "\n%{http_code}"])
    argv.append(endpoint)

    info(f"[compute] {host_name}: {argv}\n")

    result = runner.run(
        host_name, argv, timeout=timeout + _RUNNER_TIMEOUT_MARGIN
    )
    curl_exit = result.returncode
    body, http_status = _split_status(result.stdout)

    # timed_out/cancelled are the CommandResult's authoritative deadline /
    # shutdown channel (never a sentinel returncode) — they veto success even
    # when curl managed to emit a status line before termination. Both count
    # as environment: the compute endpoint was never given a fair chance.
    interrupted = result.timed_out or result.cancelled
    env_failure = interrupted or curl_exit in _ENV_FAILURE_EXITS
    http_ok = (
        not interrupted
        and curl_exit == 0
        and http_status is not None
        and 200 <= http_status < 300
    )

    publish_ok: Optional[bool] = None
    if http_ok and publish_uri:
        if out_path is not None and out_path.exists():
            opts = pub_opts or {}
            pub_argv = build_cefputfile_argv(
                publish_uri,
                str(out_path),
                node_name=host_name,
                rate=opts.get("rate"),
                block_size=opts.get("block_size"),
                expiry=opts.get("expiry", 3000),
                cache_time=opts.get("cache_time", 3000),
                valid_algo=opts.get("valid_algo"),
                port_num=opts.get("port_num"),
            )
            info(f"[compute] {host_name}: publishing {publish_uri}\n")
            # 2026-07-16 audit fix: cefputfile's timed_out/cancelled flags are
            # as authoritative as curl's, and without a runner deadline a hung
            # cefputfile would stall the single-threaded scheduler forever.
            pub_result = runner.run(
                host_name,
                pub_argv,
                timeout=publish_timeout or _PUBLISH_TIMEOUT_DEFAULT,
            )
            publish_ok = (
                pub_result.returncode == 0
                and not pub_result.timed_out
                and not pub_result.cancelled
            )
        else:
            # Publish was requested but there is nothing to publish — a
            # config/runtime mismatch that must be visible, not skipped.
            info(
                f"[compute] {host_name}: publish requested but output "
                f"file is missing ({out_path})\n"
            )
            publish_ok = False

    ok = http_ok and publish_ok is not False
    status_note = http_status if http_status is not None else "?"
    info(
        f"[compute] {host_name}: exit={curl_exit} http={status_note} "
        f"publish={publish_ok} → {'ok' if ok else 'failed'}\n"
    )

    return ComputeResult(
        ok=ok,
        http_status=http_status,
        curl_exit=curl_exit,
        publish_ok=publish_ok,
        output_file=str(out_path) if out_path is not None else None,
        stdout=body,
        env_failure=env_failure,
    )
