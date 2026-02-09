"""Template management for Cefore node directories."""

import os
import re
import shutil
import sys
from pathlib import Path

from .config_io import update_local_sock_id
from .paths import TEMPLATE_ROOT


def select_template(idx, host_num, rng, publishers=None):
    """Select template directory based on host index and role.

    Args:
        idx: Host index.
        host_num: Total number of hosts.
        rng: Random number generator.
        publishers: Set of host IDs designated as publishers.

    Returns:
        Path to template directory (h0 or h2).
    """
    # パブリッシャーとして指定されている場合は h2 テンプレートを使用
    if publishers and idx in publishers:
        return TEMPLATE_ROOT / "h2"
    return rng.choice([TEMPLATE_ROOT / "h0", TEMPLATE_ROOT / "h2"])


def ensure_node_dirs(host_num, rng, publishers=None):
    """Create node directories from templates.

    Args:
        host_num: Total number of hosts.
        rng: Random number generator.
        publishers: Set of host IDs designated as publishers.
    """
    for idx in range(host_num):
        node_dir = f"h{idx}"
        template = select_template(idx, host_num, rng, publishers)
        if not template.exists():
            sys.exit(f"missing template directory: {template}")
        if node_dir != str(template):
            if os.path.isdir(node_dir):
                shutil.rmtree(node_dir)
            shutil.copytree(template, node_dir)
        update_local_sock_id(node_dir, idx)


def cleanup_node_dirs():
    """Remove dynamically created node directories (hN)."""
    template_root = TEMPLATE_ROOT.resolve()
    for name in os.listdir("."):
        if not name.startswith("h"):
            continue
        suffix = name[1:]
        if not suffix.isdigit():
            continue
        path = Path(name)
        if not path.is_dir():
            continue
        try:
            resolved = path.resolve()
        except FileNotFoundError:
            continue
        if resolved == template_root or template_root in resolved.parents:
            continue
        shutil.rmtree(path)


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
) -> None:
    """Apply cache-related runtime overrides to generated host configs.

    - Cache nodes only: replace with ``h1`` template (external CS via csmgrd).
    - Optional RCT override applies only to cache nodes.
    """
    template = TEMPLATE_ROOT / "h1"
    if not template.exists():
        sys.exit(f"missing template directory: {template}")
    for idx in sorted(cache_nodes):
        if idx < 0 or idx >= host_num:
            continue
        node_dir = Path(f"h{idx}")
        if node_dir.exists():
            shutil.rmtree(node_dir)
        shutil.copytree(template, node_dir)
        update_local_sock_id(str(node_dir), idx)
        if cache_default_rct_ms is not None:
            _set_config_value(
                node_dir / "csmgrd.conf",
                "CACHE_DEFAULT_RCT",
                str(cache_default_rct_ms),
            )


def apply_pubsub_node_settings(host_num: int, pubsub_hosts: set[int]) -> None:
    """Apply pub/sub runtime overrides to generated host configs.

    Pub/sub publishers must use CS_MODE=3 and provide a usable conpubd config.
    """
    for idx in sorted(pubsub_hosts):
        if idx < 0 or idx >= host_num:
            continue
        node_dir = Path(f"h{idx}")
        if not node_dir.exists():
            continue
        _set_config_value(node_dir / "cefnetd.conf", "CS_MODE", "3")
        _set_config_value(node_dir / "conpubd.conf", "CEF_LOG_LEVEL", "2")
        _set_config_value(node_dir / "conpubd.conf", "CACHE_TYPE", "memory")
        update_local_sock_id(str(node_dir), idx)
