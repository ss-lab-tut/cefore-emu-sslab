"""Read Cefore daemon configuration without importing Mininet runtime code."""

from pathlib import Path


def read_port_num(node_dir: str | Path, default: int = 9695) -> int:
    """Read cefnetd.conf PORT_NUM using cefnetd's default when absent."""
    conf_path = Path(node_dir) / "cefnetd.conf"
    if not conf_path.is_file():
        return default
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
    return default
