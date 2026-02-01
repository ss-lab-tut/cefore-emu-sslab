"""Template management for Cefore node directories."""

import os
import shutil
import sys

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
        Path to template directory (h0, h1, or h2).
    """
    # パブリッシャーとして指定されている場合は h2 テンプレートを使用
    if publishers and idx in publishers:
        return TEMPLATE_ROOT / "h2"
    if idx < 3:
        return TEMPLATE_ROOT / f"h{idx}"
    if idx % 2 == 1:
        return TEMPLATE_ROOT / "h1"
    if idx == host_num - 1:
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
