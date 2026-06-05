"""External compute API client for cache/edge nodes."""

from pathlib import Path

from mininet.log import info

from ..core.paths import resolve_run_path
from .command_runner import MininetCommandRunner


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
        (exit_code, stdout) tuple. exit_code is curl's exit code; stdout is the
        decoded combined output text from the CommandRunner.
    """
    host_name = f"h{host_idx}"
    runner = MininetCommandRunner(net)

    argv = ["curl", "-s", "-S", "--max-time", str(timeout)]
    if method == "POST":
        argv.extend(["-X", "POST"])
        if payload:
            argv.extend(["-d", payload])

    out_path = None
    if output_file and run_dir:
        out_path = resolve_run_path(Path(run_dir), output_file)
        argv.extend(["-o", str(out_path)])

    argv.append(endpoint)

    info(f"[compute] {host_name}: {argv}\n")

    result = runner.run(host_name, argv)
    exit_code = result.returncode
    stdout = result.stdout

    if exit_code != 0:
        info(f"[compute] {host_name}: curl failed (exit={exit_code})\n")
        return exit_code, stdout

    info(f"[compute] {host_name}: success (exit=0)\n")

    if publish_uri and out_path and out_path.exists():
        pub_argv = [
            "cefputfile", publish_uri, "-f", str(out_path),
            "-t", "3000", "-e", "3000", "-d", f"./{host_name}",
        ]
        info(f"[compute] {host_name}: publishing {publish_uri}\n")
        runner.run(host_name, pub_argv)

    return exit_code, stdout


def check_external_connectivity(net, host_idx, endpoint):
    """Check if host can reach the external endpoint.

    Uses curl HEAD request with 5s timeout to verify connectivity.

    Returns:
        True if reachable (HTTP 2xx/3xx), False otherwise.
    """
    host_name = f"h{host_idx}"
    argv = [
        "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
        "--max-time", "5", endpoint,
    ]
    output = MininetCommandRunner(net).run(host_name, argv).stdout.strip()
    return output.startswith("2") or output.startswith("3")
