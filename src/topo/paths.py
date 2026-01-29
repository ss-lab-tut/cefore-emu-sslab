"""Common path constants for the topo package."""

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATE_ROOT = ROOT_DIR / "configs" / "templates"
