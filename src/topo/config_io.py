"""Configuration file operations for Cefore nodes."""

import os

from mininet.log import info


def update_local_sock_id(node_dir, idx):
    """Update LOCAL_SOCK_ID in daemon config files.

    Args:
        node_dir: Path to node configuration directory.
        idx: Host index to set as LOCAL_SOCK_ID.
    """
    for conf_name in ("cefnetd.conf", "csmgrd.conf", "conpubd.conf"):
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
    """Update NODE_NAME in cefnetd.conf.

    Args:
        node_dir: Path to node configuration directory.
        idx: Host index to append to base_uri.
        base_uri: Base URI prefix for the node name.
    """
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
    """Read PORT_NUM from cefnetd.conf.

    Args:
        node_dir: Path to node configuration directory.
        default: Default port if not found.

    Returns:
        Port number as integer.
    """
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
    """Remove stale cefnetd socket file.

    Args:
        node_dir: Path to node configuration directory.
        idx: Host index used in socket filename.
    """
    port = read_port_num(node_dir)
    sock_path = f"/tmp/cef_{port}.{idx}"
    if os.path.exists(sock_path):
        try:
            os.remove(sock_path)
            info(f"removed stale socket {sock_path}\n")
        except OSError:
            info(f"failed to remove stale socket {sock_path}\n")
