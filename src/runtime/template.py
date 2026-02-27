"""Template management and configuration file operations for Cefore nodes.

Consolidates templates.py + config_io.py into a single module.
"""

import os
import shutil
import sys

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


def read_port_num(node_dir, default=9695):
    """Read PORT_NUM from cefnetd.conf."""
    conf_path = os.path.join(node_dir, "cefnetd.conf")
    if not os.path.isfile(conf_path):
        return default
    with open(conf_path, "r", encoding="utf-8") as conf_file:
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
    return default


def cleanup_cefnetd_socket(node_dir, idx):
    """Remove stale cefnetd socket file."""
    port = read_port_num(node_dir)
    sock_path = f"/tmp/cef_{port}.{idx}"
    if os.path.exists(sock_path):
        try:
            os.remove(sock_path)
            info(f"removed stale socket {sock_path}\n")
        except OSError:
            info(f"failed to remove stale socket {sock_path}\n")


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
