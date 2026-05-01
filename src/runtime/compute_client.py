"""External compute API client for cache/edge nodes."""

import shlex
from pathlib import Path

from mininet.log import info

from ..core.paths import resolve_run_path


def compute_call(net, host_idx, endpoint, method="GET", payload=None,
                 output_file=None, publish_uri=None, run_dir=None,
                 timeout=30):
    """Execute an HTTP API call from a Mininet host.

    Args:
        net: Mininet network instance.
        host_idx: Host index to execute from.
        endpoint: URL to call.
        method: HTTP method (GET or POST).
        payload: Request body (for POST).
        output_file: Path to save response (relative to run_dir).
        publish_uri: If set, publish result via cefputfile on success.
        run_dir: Experiment run directory (Path).
        timeout: Request timeout in seconds.

    Returns:
        (exit_code, stdout) tuple. exit_code is curl's exit code.
    """
    host = net.hosts[host_idx]
    host_name = f"h{host_idx}"

    cmd_parts = ["curl", "-s", "-S", "--max-time", str(timeout)]
    if method == "POST":
        cmd_parts.extend(["-X", "POST"])
        if payload:
            cmd_parts.extend(["-d", shlex.quote(payload)])

    out_path = None
    if output_file and run_dir:
        out_path = resolve_run_path(Path(run_dir), output_file)
        cmd_parts.extend(["-o", shlex.quote(str(out_path))])

    cmd_parts.append(shlex.quote(endpoint))
    cmd_str = " ".join(cmd_parts)

    info(f"[compute] {host_name}: {cmd_str}\n")

    proc = host.popen(cmd_str, shell=True)
    stdout, _ = proc.communicate()
    exit_code = proc.wait()

    if exit_code != 0:
        info(f"[compute] {host_name}: curl failed (exit={exit_code})\n")
        return exit_code, stdout

    info(f"[compute] {host_name}: success (exit=0)\n")

    if publish_uri and out_path and out_path.exists():
        pub_cmd = (
            f"cefputfile {shlex.quote(publish_uri)} "
            f"-f {shlex.quote(str(out_path))} "
            f"-t 3000 -e 3000 -d ./{host_name}"
        )
        info(f"[compute] {host_name}: publishing {publish_uri}\n")
        host.cmd(pub_cmd)

    return exit_code, stdout


def check_external_connectivity(net, host_idx, endpoint):
    """Check if host can reach the external endpoint.

    Uses curl HEAD request with 5s timeout to verify connectivity.

    Returns:
        True if reachable (HTTP 2xx/3xx), False otherwise.
    """
    host = net.hosts[host_idx]
    result = host.cmd(
        f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 5 "
        f"{shlex.quote(endpoint)}"
    )
    return result.strip().startswith("2") or result.strip().startswith("3")
