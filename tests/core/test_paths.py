"""Tests for src.core.paths."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.paths import ensure_within_run_dir, resolve_run_dir, resolve_run_path


# ── resolve_run_dir ──


def test_resolve_run_dir_legacy():
    args = SimpleNamespace(legacy_layout=True)
    assert resolve_run_dir(args) == Path(".")


def test_resolve_run_dir_no_num_no_output():
    args = SimpleNamespace(legacy_layout=False, num=None, output_dir=None)
    assert resolve_run_dir(args) == Path(".")


def test_resolve_run_dir_with_num_and_seed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = SimpleNamespace(
        legacy_layout=False, num=1, seed=42, output_dir=None, timestamp=False,
    )
    result = resolve_run_dir(args)
    assert result == Path("logs/ex1_seed42")
    assert result.exists()


def test_resolve_run_dir_custom_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = SimpleNamespace(
        legacy_layout=False, num=None, seed=10, output_dir=str(tmp_path / "results"),
        timestamp=False,
    )
    result = resolve_run_dir(args)
    assert "seed10" in str(result)
    assert result.exists()


# ── ensure_within_run_dir ──


def test_ensure_within_run_dir_valid(tmp_path):
    target = tmp_path / "subdir" / "file.txt"
    target.parent.mkdir(parents=True)
    result = ensure_within_run_dir(tmp_path, target)
    assert result == target.resolve()


def test_ensure_within_run_dir_escape(tmp_path):
    target = tmp_path / ".." / "outside"
    with pytest.raises(ValueError, match="escapes run directory"):
        ensure_within_run_dir(tmp_path, target)


# ── resolve_run_path ──


def test_resolve_run_path_relative(tmp_path):
    result = resolve_run_path(tmp_path, "output.json")
    assert result == (tmp_path / "output.json").resolve()


def test_resolve_run_path_default_name(tmp_path):
    result = resolve_run_path(tmp_path, None, default_name="default.csv")
    assert result == (tmp_path / "default.csv").resolve()


def test_resolve_run_path_no_path_no_default(tmp_path):
    with pytest.raises(ValueError, match="path is required"):
        resolve_run_path(tmp_path, None)
