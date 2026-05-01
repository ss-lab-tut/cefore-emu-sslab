"""Template management and configuration file operations for Cefore nodes.

Consolidates templates.py + config_io.py into a single module.
"""

import os
import re
import shutil
import sys
from pathlib import Path

from mininet.log import info

from ..core.paths import TEMPLATE_ROOT
from ..core.roles import assign_roles

# Marker file written inside every hN directory created by ensure_node_dirs().
# cleanup_node_dirs() only removes directories that carry this stamp,
# preventing accidental deletion of manually created directories.
STAMP_FILENAME = ".ceforeemu-node-dir"


def update_local_sock_id(node_dir, idx):
    """Update LOCAL_SOCK_ID in cefnetd.conf and csmgrd.conf."""
    for conf_name in ("cefnetd.conf", "csmgrd.conf"):
        conf_path = os.path.join(node_dir, conf_name)
        if not os.path.isfile(conf_path):
            continue
        with open(conf_path, "r", encoding="utf-8") as conf_file:
            lines = conf_file.readlines()
        updated = False
        new_lines = []
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith("LOCAL_SOCK_ID=") or stripped.startswith(
                "#LOCAL_SOCK_ID="
            ):
                leading = line[: len(line) - len(stripped)]
                new_lines.append(f"{leading}LOCAL_SOCK_ID={idx}\n")
                updated = True
            else:
                new_lines.append(line)
        if not updated:
            new_lines.append(f"LOCAL_SOCK_ID={idx}\n")
        with open(conf_path, "w", encoding="utf-8") as conf_file:
            conf_file.writelines(new_lines)


def update_node_name(node_dir, idx, base_uri="example.com/xxx/router-"):
    """Update NODE_NAME in cefnetd.conf."""
    conf_path = os.path.join(node_dir, "cefnetd.conf")
    if not os.path.isfile(conf_path):
        return
    with open(conf_path, "r", encoding="utf-8") as conf_file:
        lines = conf_file.readlines()
    updated = False
    new_lines = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("NODE_NAME=") or stripped.startswith("#NODE_NAME="):
            leading = line[: len(line) - len(stripped)]
            new_lines.append(f'{leading}#NODE_NAME="{base_uri}{idx}"\n')
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f'#NODE_NAME="{base_uri}{idx}"\n')
    with open(conf_path, "w", encoding="utf-8") as conf_file:
        conf_file.writelines(new_lines)


from .cefore import cleanup_cefnetd_socket, read_port_num  # noqa: F401 (re-export)


def ensure_node_dirs(host_num, rng, publishers=None) -> list[Path]:
    """Create node directories from templates based on assigned roles.

    Each created directory receives a stamp file (STAMP_FILENAME) so that
    cleanup_node_dirs() can safely identify generated directories.

    If a directory already exists without the stamp, the function exits with
    an error to avoid destroying unmanaged content.

    Args:
        host_num: Total number of hosts.
        rng: Random number generator.
        publishers: Set of host IDs designated as publishers.

    Returns:
        List of Path objects for every directory that was created or refreshed.
    """
    roles = assign_roles(host_num, rng, publishers)
    generated: list[Path] = []
    for idx in range(host_num):
        node_dir = Path(f"h{idx}")
        template = TEMPLATE_ROOT / roles[idx].template
        if not template.exists():
            sys.exit(f"missing template directory: {template}")
        if node_dir.is_dir():
            stamp = node_dir / STAMP_FILENAME
            if not stamp.exists():
                sys.exit(
                    f"{node_dir} exists but was not created by ceforeemu "
                    f"(no {STAMP_FILENAME} stamp). Remove it manually before running."
                )
            shutil.rmtree(node_dir)
        shutil.copytree(template, node_dir)
        (node_dir / STAMP_FILENAME).touch()
        update_local_sock_id(str(node_dir), idx)
        generated.append(node_dir)
    return generated


def cleanup_node_dirs(generated_dirs: list[Path]) -> None:
    """Remove generated node directories identified by their stamp file.

    Only directories that contain the STAMP_FILENAME marker are removed.
    Directories without the stamp are silently skipped.

    Args:
        generated_dirs: List of Path objects returned by ensure_node_dirs().
    """
    for node_dir in generated_dirs:
        if not node_dir.is_dir():
            continue
        stamp = node_dir / STAMP_FILENAME
        if stamp.exists():
            shutil.rmtree(node_dir)


def _read_config_value(path: Path, key: str) -> str | None:
    """Read the current value of KEY from a config file.

    Returns the value string if found, or None if the key is not present
    or is commented out.
    """
    if not path.exists():
        return None
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.*)$")
    for line in path.read_text(encoding="utf-8").splitlines():
        m = pattern.match(line)
        if m:
            return m.group(1).strip()
    return None


def _set_config_value(path: Path, key: str, value: str) -> None:
    """Set KEY=VALUE in a config file, replacing commented/default lines."""
    if not path.exists():
        return

    pattern = re.compile(rf"^\s*#?\s*{re.escape(key)}\s*=.*$")
    lines = path.read_text(encoding="utf-8").splitlines()
    replaced = False
    new_lines = []
    for line in lines:
        if pattern.match(line):
            if not replaced:
                new_lines.append(f"{key}={value}")
                replaced = True
            continue
        new_lines.append(line)

    if not replaced:
        new_lines.append(f"{key}={value}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def apply_cache_node_settings(
    host_num: int,
    cache_nodes: set[int],
    cache_default_rct_ms: int | None = None,
    cache_capacity: int | None = None,
    cache_algorithm: str | None = None,
    cache_type: str | None = None,
    publishers: set[int] | None = None,
) -> None:
    """Apply cache-related runtime overrides to generated host configs.

    - Cache nodes: force ``CS_MODE=2`` (external CS via csmgrd).
    - Publisher nodes (non-cache): force ``CS_MODE=1`` (local CS for content serving).
    - Other non-cache nodes: preserve template CS_MODE (0 or 1).
      If the template set CS_MODE=2 but the node is not a cache node,
      downgrade to CS_MODE=0 to prevent csmgrd-wait hang.

    Args:
        host_num: Total number of hosts.
        cache_nodes: Set of host indices designated as cache nodes.
        cache_default_rct_ms: CACHE_DEFAULT_RCT value in milliseconds.
        cache_capacity: CACHE_CAPACITY value in bytes.
        cache_algorithm: CACHE_ALGORITHM value (e.g. LRU, LFU, FIFO).
        cache_type: CACHE_TYPE value (e.g. memory, filesystem).
        publishers: Set of host indices designated as publishers.
    """
    publishers = publishers or set()

    for idx in sorted(cache_nodes):
        if idx < 0 or idx >= host_num:
            continue
        node_dir = Path(f"h{idx}")
        conf_path = node_dir / "csmgrd.conf"
        _set_config_value(node_dir / "cefnetd.conf", "CS_MODE", "2")
        if cache_default_rct_ms is not None:
            _set_config_value(conf_path, "CACHE_DEFAULT_RCT", str(cache_default_rct_ms))
        if cache_capacity is not None:
            _set_config_value(conf_path, "CACHE_CAPACITY", str(cache_capacity))
        if cache_algorithm is not None:
            _set_config_value(conf_path, "CACHE_ALGORITHM", str(cache_algorithm))
        if cache_type is not None:
            _set_config_value(conf_path, "CACHE_TYPE", str(cache_type))

    for idx in range(host_num):
        if idx in cache_nodes:
            continue
        node_dir = Path(f"h{idx}")
        cefnetd_conf = node_dir / "cefnetd.conf"
        if not cefnetd_conf.exists():
            continue
        if idx in publishers:
            _set_config_value(cefnetd_conf, "CS_MODE", "1")
        else:
            # Preserve template CS_MODE (0 or 1) from assign_roles.
            # Only downgrade CS_MODE=2 → 0 to prevent csmgrd-wait hang
            # on nodes that are not cache nodes.
            current = _read_config_value(cefnetd_conf, "CS_MODE")
            if current == "2":
                _set_config_value(cefnetd_conf, "CS_MODE", "0")
