"""Locate, collect, and clean up Cefore daemon logs from shared /tmp."""

import shutil
from dataclasses import dataclass
from pathlib import Path

from src.core.paths import ensure_within_run_dir

from .cefore_conf import read_port_num

_TMP_DIR = Path("/tmp")


@dataclass(frozen=True)
class HostLogScope:
    """Facts needed to derive daemon log names for one emulated host."""

    idx: int
    node_dir: Path
    has_csmgrd: bool


def read_local_sock_id(node_dir: Path, conf_name: str) -> str:
    """Read the daemon-specific LOCAL_SOCK_ID used in Cefore /tmp log names."""
    conf_path = node_dir / conf_name
    if not conf_path.is_file():
        return "0"
    with conf_path.open(encoding="utf-8") as conf_file:
        for line in conf_file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("LOCAL_SOCK_ID="):
                return stripped.split("=", 1)[1].strip().split()[0]
    return "0"


def read_csmgr_port_num(node_dir: Path) -> int:
    """Read csmgrd.conf PORT_NUM, whose default differs from cefnetd."""
    conf_path = node_dir / "csmgrd.conf"
    if not conf_path.is_file():
        return 9799
    with conf_path.open(encoding="utf-8") as conf_file:
        for line in conf_file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("PORT_NUM="):
                value = stripped.split("=", 1)[1].strip().split()[0]
                try:
                    return int(value)
                except ValueError:
                    break
    return 9799


def tmp_daemon_log_paths(scope: HostLogScope) -> list[Path]:
    """Return the /tmp daemon log paths Cefore will use for a host scope."""
    cef_port = read_port_num(scope.node_dir)
    cef_sockid = read_local_sock_id(scope.node_dir, "cefnetd.conf")
    paths = [_TMP_DIR / f"cefnetd_{cef_port}_{cef_sockid}.log"]
    if scope.has_csmgrd:
        csmgr_port = read_csmgr_port_num(scope.node_dir)
        csmgr_sockid = read_local_sock_id(scope.node_dir, "csmgrd.conf")
        paths.append(_TMP_DIR / f"csmgrd_{csmgr_port}_{csmgr_sockid}.log")
    return paths


def collect_daemon_logs(run_dir: Path, scopes: list[HostLogScope]) -> list[str]:
    """Copy existing daemon logs into run_dir without failing the scenario."""
    warnings = []
    for scope in scopes:
        try:
            sources = tmp_daemon_log_paths(scope)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"failed to collect daemon log for h{scope.idx}: {exc}")
            continue
        for source in sources:
            try:
                if not source.is_file():
                    continue
                dest = ensure_within_run_dir(run_dir, run_dir / source.name)
                shutil.copy2(source, dest)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"failed to collect daemon log {source}: {exc}")
    return warnings


def cleanup_stale_daemon_logs(scope: HostLogScope) -> None:
    """Remove old /tmp daemon logs that Cefore would otherwise append to."""
    cleanup_stale_cefnetd_log(scope.node_dir, scope.idx)
    if scope.has_csmgrd:
        cleanup_stale_csmgrd_log(scope.node_dir, scope.idx)


def cleanup_stale_cefnetd_log(node_dir: str | Path, idx: int) -> None:
    """Remove the stale cefnetd /tmp log for a host before cefnetd starts."""
    node_path = Path(node_dir)
    port = read_port_num(node_path)
    sockid = read_local_sock_id(node_path, "cefnetd.conf")
    _unlink_stale_paths([_TMP_DIR / f"cefnetd_{port}_{sockid}.log"])


def cleanup_stale_csmgrd_log(node_dir: str | Path, idx: int) -> None:
    """Remove stale csmgrd /tmp logs for both bootstrap and configured ports."""
    node_path = Path(node_dir)
    sockid = read_local_sock_id(node_path, "csmgrd.conf")
    port = read_csmgr_port_num(node_path)
    _unlink_stale_paths(
        [
            _TMP_DIR / f"csmgrd_9799_{sockid}.log",
            _TMP_DIR / f"csmgrd_{port}_{sockid}.log",
        ]
    )


def _unlink_stale_paths(paths: list[Path]) -> None:
    for path in set(paths):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
