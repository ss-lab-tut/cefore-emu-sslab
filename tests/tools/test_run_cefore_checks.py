"""Regression tests for the smoke checker's declarative validate_results.

The checker lives outside the package (a skill script), so it is loaded by
path; these tests pin the expectation semantics that smoke correctness
depends on — most importantly that expectations never pass vacuously.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / ".agents/skills/cefore-run-tests/scripts/run_cefore_checks.py"
)


def _load_checker():
    """Load the checker script as a module from its skill path."""
    spec = importlib.util.spec_from_file_location("run_cefore_checks", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # dataclass field-type resolution looks the module up in sys.modules;
    # exec'ing an unregistered module crashes at the first @dataclass.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def _event_row(event_type, outcome=None, success=False):
    """One results.json event record with an optional tri-state outcome."""
    row = {"op_type": "event", "event_type": event_type, "success": success}
    if outcome is not None:
        row["outcome"] = outcome
    return row


def test_event_outcomes_zero_matching_rows_fails():
    """2026-07-16 audit fix: an outcome expectation implies the event
    happened; zero matching rows must fail, not pass vacuously."""
    with pytest.raises(RuntimeError, match="at least 1 compute_call"):
        checker.validate_results(
            "case",
            [_event_row("link_down")],
            {"event_outcomes": {"compute_call": "skipped-no-result"}},
            Path("."),
        )


def test_event_outcomes_wrong_outcome_fails():
    """A mismatching outcome value must fail the expectation."""
    with pytest.raises(RuntimeError, match="skipped-no-result"):
        checker.validate_results(
            "case",
            [_event_row("compute_call", outcome="not-ok")],
            {"event_outcomes": {"compute_call": "skipped-no-result"}},
            Path("."),
        )


def test_event_outcomes_matching_outcome_passes():
    """The expectation passes when every matching record carries the outcome."""
    checker.validate_results(
        "case",
        [_event_row("compute_call", outcome="skipped-no-result")],
        {"event_outcomes": {"compute_call": "skipped-no-result"}},
        Path("."),
    )


# ── validate_host_app_markers ──
#
# Exact-match assertions per project convention (docs/runbooks/mutation-
# testing.md): substring/regex asserts let mutants through, so these compare
# the full raised message, not a `match=` pattern.


def _write_marker(run_dir: Path, idx: int, content: str) -> None:
    marker_dir = run_dir / "debug" / "node_dirs" / f"h{idx}"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / "host_app_marker").write_text(content)


def test_host_app_markers_missing_file_fails(tmp_path):
    _write_marker(tmp_path, 0, "h0 1700000000000")
    # h1's marker is never written.

    with pytest.raises(RuntimeError) as exc_info:
        checker.validate_host_app_markers("min_host_apps", tmp_path, (0, 1))

    assert str(exc_info.value) == "min_host_apps: host_app_marker missing for h1"


def test_host_app_markers_wrong_token_count_fails(tmp_path):
    _write_marker(tmp_path, 0, "h0 1700000000000 extra")

    with pytest.raises(RuntimeError) as exc_info:
        checker.validate_host_app_markers("min_host_apps", tmp_path, (0,))

    assert str(exc_info.value) == (
        "min_host_apps: h0 host_app_marker content "
        "'h0 1700000000000 extra' is not 'hN <ms>'"
    )


def test_host_app_markers_wrong_node_name_fails(tmp_path):
    # h1's marker holds h0's name -- the mix-up this check exists to catch.
    _write_marker(tmp_path, 1, "h0 1700000000000")

    with pytest.raises(RuntimeError) as exc_info:
        checker.validate_host_app_markers("min_host_apps", tmp_path, (1,))

    assert str(exc_info.value) == (
        "min_host_apps: h1 host_app_marker node is 'h0', expected 'h1'"
    )


def test_host_app_markers_non_numeric_t0_fails(tmp_path):
    _write_marker(tmp_path, 0, "h0 not-a-number")

    with pytest.raises(RuntimeError) as exc_info:
        checker.validate_host_app_markers("min_host_apps", tmp_path, (0,))

    assert str(exc_info.value) == (
        "min_host_apps: h0 host_app_marker t0 'not-a-number' is not numeric"
    )


def test_host_app_markers_mismatched_t0_fails(tmp_path):
    _write_marker(tmp_path, 0, "h0 1700000000000")
    _write_marker(tmp_path, 1, "h1 1700000000111")

    with pytest.raises(RuntimeError) as exc_info:
        checker.validate_host_app_markers("min_host_apps", tmp_path, (0, 1))

    assert str(exc_info.value) == (
        "min_host_apps: host_app_marker t0 values differ across hosts: "
        "['1700000000000', '1700000000111']"
    )


def test_host_app_markers_matching_t0_passes(tmp_path):
    _write_marker(tmp_path, 0, "h0 1700000000000")
    _write_marker(tmp_path, 1, "h1 1700000000000")
    _write_marker(tmp_path, 2, "h2 1700000000000")

    checker.validate_host_app_markers("min_host_apps", tmp_path, (0, 1, 2))
