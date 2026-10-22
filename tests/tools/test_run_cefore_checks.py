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


def _get_row(uri, success):
    """One results.json get-content record for the given uri."""
    return {"op_type": "get", "uri": uri, "success": success}


def test_event_outcomes_zero_matching_rows_fails():
    """2026-07-16 audit fix: an outcome expectation implies the event
    happened; zero matching rows must fail, not pass vacuously.

    2026-10-22 fix: exact-match the raised message instead of a substring
    -- mutation testing showed a substring match lets a mutant that drops
    or reorders words in the message through undetected.
    """
    with pytest.raises(RuntimeError) as exc_info:
        checker.validate_results(
            "case",
            [_event_row("link_down")],
            {"event_outcomes": {"compute_call": "skipped-no-result"}},
            Path("."),
        )
    assert (
        str(exc_info.value)
        == "case: expected at least 1 compute_call record to check outcome"
    )


def test_event_outcomes_wrong_outcome_fails():
    """A mismatching outcome value must fail the expectation.

    2026-10-22 fix: exact-match the raised message (see
    test_event_outcomes_zero_matching_rows_fails for why).
    """
    with pytest.raises(RuntimeError) as exc_info:
        checker.validate_results(
            "case",
            [_event_row("compute_call", outcome="not-ok")],
            {"event_outcomes": {"compute_call": "skipped-no-result"}},
            Path("."),
        )
    assert str(exc_info.value) == (
        "case: compute_call record outcome is 'not-ok', expected 'skipped-no-result'"
    )


def test_event_outcomes_matching_outcome_passes():
    """The expectation passes when every matching record carries the outcome."""
    checker.validate_results(
        "case",
        [_event_row("compute_call", outcome="skipped-no-result")],
        {"event_outcomes": {"compute_call": "skipped-no-result"}},
        Path("."),
    )


# ── get_outcomes (per-uri success, not a blanket all_success) ──


def test_get_outcomes_zero_matching_rows_fails():
    """A get_outcomes expectation implies that uri was actually fetched;
    zero matching rows must fail, not pass vacuously.

    2026-10-22 fix: exact-match the raised message instead of a substring
    -- mutation testing showed a substring match lets a mutant that drops
    or reorders words in the message through undetected.
    """
    with pytest.raises(RuntimeError) as exc_info:
        checker.validate_results(
            "case",
            [_get_row("ccnx:/other", True)],
            {"get_outcomes": {"ccnx:/test/during": False}},
            Path("."),
        )
    assert str(exc_info.value) == (
        "case: expected at least 1 get result for uri='ccnx:/test/during'"
    )


def test_get_outcomes_unexpected_success_fails():
    """A get that was expected to fail (e.g. during a link outage) but
    actually succeeded must fail the expectation -- this is the case a
    blanket all_success could never express.

    2026-10-22 fix: exact-match the raised message (see
    test_get_outcomes_zero_matching_rows_fails for why).
    """
    with pytest.raises(RuntimeError) as exc_info:
        checker.validate_results(
            "case",
            [_get_row("ccnx:/test/during", True)],
            {"get_outcomes": {"ccnx:/test/during": False}},
            Path("."),
        )
    assert str(exc_info.value) == (
        "case: get row for uri='ccnx:/test/during' has success=True "
        "(type bool), expected exactly False"
    )


def test_get_outcomes_unexpected_failure_fails():
    """A get that was expected to succeed (e.g. after restoration) but
    actually failed must fail the expectation.

    2026-10-22 fix: exact-match the raised message (see
    test_get_outcomes_zero_matching_rows_fails for why).
    """
    with pytest.raises(RuntimeError) as exc_info:
        checker.validate_results(
            "case",
            [_get_row("ccnx:/test/after", False)],
            {"get_outcomes": {"ccnx:/test/after": True}},
            Path("."),
        )
    assert str(exc_info.value) == (
        "case: get row for uri='ccnx:/test/after' has success=False "
        "(type bool), expected exactly True"
    )


def test_get_outcomes_matching_success_passes():
    """The expectation passes when every matching row's success matches."""
    checker.validate_results(
        "case",
        [_get_row("ccnx:/test/before", True), _get_row("ccnx:/test/during", False)],
        {
            "get_outcomes": {
                "ccnx:/test/before": True,
                "ccnx:/test/during": False,
            }
        },
        Path("."),
    )
