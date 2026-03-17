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


def ensure_node_dirs(host_num, rng, publishers=None):
    """Create node directories from templates based on assigned roles.

    Args:
        host_num: Total number of hosts.
        rng: Random number generator.
        publishers: Set of host IDs designated as publishers.
    """
    roles = assign_roles(host_num, rng, publishers)
    for idx in range(host_num):
        node_dir = f"h{idx}"
        template = TEMPLATE_ROOT / roles[idx].template
        if not template.exists():
            sys.exit(f"missing template directory: {template}")
        if node_dir != str(template):
            if os.path.isdir(node_dir):
                shutil.rmtree(node_dir)
            shutil.copytree(template, node_dir)
        update_local_sock_id(node_dir, idx)


def cleanup_node_dirs():
    """Remove dynamically created node directories (h3 and above)."""
    for name in os.listdir("."):
        if not name.startswith("h"):
            continue
        suffix = name[1:]
        if not suffix.isdigit():
            continue
        idx = int(suffix)
        if idx >= 3 and os.path.isdir(name):
            shutil.rmtree(name)


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
    - Other non-cache nodes: force ``CS_MODE=0`` to prevent csmgrd-wait hang.

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
            _set_config_value(cefnetd_conf, "CS_MODE", "0")
