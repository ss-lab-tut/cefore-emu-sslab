"""Shared cleanup helpers for Mininet/Cefore scenario shutdown."""

from mininet.clean import cleanup as mn_cleanup
from mininet.log import info

from .template import cleanup_node_dirs

_CEF_PATTERNS = (
    "cefnetd",
    "csmgrd",
    "cefsubfile",
    "cefpubfile",
    "cefputfile",
    "cefgetfile",
    "cefroute",
    "cefstatus",
    "conpubd",
)


def kill_cef_processes(net) -> None:
    """Force-kill remaining Cefore commands while host namespaces still exist."""
    info("*** Killing remaining Cefore processes\n")
    for host in net.hosts:
        for pattern in _CEF_PATTERNS:
            host.cmd(f'pkill -9 -f "{pattern}" || true')


def cleanup_all(net, generated_dirs) -> None:
    """Run the common scenario cleanup sequence."""
    kill_cef_processes(net)
    net.stop()
    mn_cleanup()
    cleanup_node_dirs(generated_dirs)
