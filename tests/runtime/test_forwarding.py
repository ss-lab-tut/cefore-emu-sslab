"""Tests for forwarding strategy config resolution and application."""

from src.runtime.forwarding import ForwardingConfigManager, resolve_forwarding_config


def test_resolve_forwarding_config_defaults_to_flooding():
    assert resolve_forwarding_config(None) == {"default": "flooding"}


def test_apply_configs_writes_default_and_node_overrides(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for idx in range(3):
        node_dir = tmp_path / f"h{idx}"
        node_dir.mkdir()
        (node_dir / "cefnetd.conf").write_text("FORWARDING_STRATEGY=default\n")

    config = {
        "default": "flooding",
        "nodes": [{"id": [1, 2], "strategy": "shortest_path"}],
    }
    ForwardingConfigManager(config).apply_configs(host_count=3)

    assert (
        "FORWARDING_STRATEGY=flooding" in (tmp_path / "h0" / "cefnetd.conf").read_text()
    )
    assert (
        "FORWARDING_STRATEGY=shortest_path"
        in (tmp_path / "h1" / "cefnetd.conf").read_text()
    )
    assert (
        "FORWARDING_STRATEGY=shortest_path"
        in (tmp_path / "h2" / "cefnetd.conf").read_text()
    )
