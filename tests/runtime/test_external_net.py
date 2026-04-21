"""Unit tests for external network content operation resolution."""

from argparse import Namespace

from src.runtime.external_net import (
    _resolve_connect_content_ops,
    _warn_if_no_content_operations,
)


def _make_args(**overrides):
    data = {
        "hosts": 3,
        "seed": 42,
        "puts": [],
        "gets": [],
        "auto": None,
    }
    data.update(overrides)
    return Namespace(**data)


def test_resolve_connect_content_ops_keeps_empty_ops_without_auto(tmp_path):
    ops_put, ops_get = _resolve_connect_content_ops(_make_args(), tmp_path)
    assert ops_put == []
    assert ops_get == []


def test_resolve_connect_content_ops_uses_auto_when_no_explicit_ops(tmp_path):
    args = _make_args(
        auto={
            "publishers": [2],
            "consumers": [0],
            "content_count": 1,
            "uri_prefix": "ccnx:/test",
            "consumer_per_content": 1,
        }
    )
    ops_put, ops_get = _resolve_connect_content_ops(args, tmp_path)
    assert len(ops_put) == 1
    assert len(ops_get) == 1


def test_warn_if_no_content_operations(capsys):
    warned = _warn_if_no_content_operations([], [])
    captured = capsys.readouterr()
    assert warned is True
    assert "no content operations configured" in captured.out
