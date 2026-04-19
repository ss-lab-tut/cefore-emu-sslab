"""Unit tests for pub/sub helpers in disaster scenario."""

from pathlib import Path

import pytest

from src.scenarios.disaster import _detect_sub_success


# ---------------------------------------------------------------------------
# _detect_sub_success
# ---------------------------------------------------------------------------

class TestDetectSubSuccess:
    def test_empty_directory_is_failure(self, tmp_path):
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        result = _detect_sub_success(0, output_dir, tmp_path / "sub.log")
        assert result["success"] is False
        assert result["has_output_file"] is False
        assert result["artifact_path"] is None

    def test_nonempty_out_file_is_success(self, tmp_path):
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        artifact = output_dir / "RNP0x0a1b2c.out"
        artifact.write_bytes(b"content data")
        result = _detect_sub_success(0, output_dir, tmp_path / "sub.log")
        assert result["success"] is True
        assert result["has_output_file"] is True
        assert result["artifact_path"] == str(artifact)

    def test_nonzero_exit_code_is_failure_even_with_file(self, tmp_path):
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        artifact = output_dir / "RNP0xdeadbeef.out"
        artifact.write_bytes(b"content data")
        result = _detect_sub_success(1, output_dir, tmp_path / "sub.log")
        assert result["success"] is False
        assert result["has_output_file"] is True

    def test_zero_byte_file_is_failure(self, tmp_path):
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        (output_dir / "RNP0xempty.out").write_bytes(b"")
        result = _detect_sub_success(0, output_dir, tmp_path / "sub.log")
        assert result["success"] is False
        assert result["has_output_file"] is False

    def test_nonexistent_directory_is_failure(self, tmp_path):
        output_dir = tmp_path / "does_not_exist"
        result = _detect_sub_success(0, output_dir, tmp_path / "sub.log")
        assert result["success"] is False
        assert result["has_output_file"] is False

    def test_returns_first_artifact_path(self, tmp_path):
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        a1 = output_dir / "RNP0x0001.out"
        a2 = output_dir / "RNP0x0002.out"
        a1.write_bytes(b"a")
        a2.write_bytes(b"b")
        result = _detect_sub_success(0, output_dir, tmp_path / "sub.log")
        assert result["artifact_path"] in (str(a1), str(a2))

    def test_has_completed_log_always_false(self, tmp_path):
        output_dir = tmp_path / "recvdir"
        output_dir.mkdir()
        (output_dir / "RNP0xabc.out").write_bytes(b"data")
        result = _detect_sub_success(0, output_dir, tmp_path / "sub.log")
        assert result["has_completed_log"] is False
