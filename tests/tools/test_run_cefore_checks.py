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


# ── fib_dump (FIB section scraped from a real cefstatus dump) ──
#
# Synthetic dumps below follow the real four-section cefstatus layout
# (FIB(App) : / FIB : <count> / PIT(App) : / PIT :), confirmed against a
# live capture under debug/fib/fib_h1.txt from a min_prefix_routes smoke
# run: a "FIB : <count>" header, then per entry a two-space-indented
# "  <uri>" line followed by a four-space-indented "    Faces : ..." line,
# up to the next top-level header.


def _fib_dump_text(entries, trailing_app_pit_line="  Entry is empty"):
    """Build a synthetic cefstatus FIB dump matching the real layout.

    ``entries`` is an iterable of (prefix, faces_text) pairs rendered under
    the ``FIB : <count>`` header. ``trailing_app_pit_line`` is the line
    placed right after the ``PIT(App) :`` header -- the real dump always
    has ``  Entry is empty`` there, but a test can swap in a line that
    mimics a FIB entry's two-space indent to prove it is never read as one.
    """
    lines = ["FIB(App) :", "  Entry is empty", f"FIB : {len(entries)}"]
    for prefix, faces in entries:
        lines.append(f"  {prefix}")
        lines.append(f"    Faces : {faces}")
    lines += ["PIT(App) :", trailing_app_pit_line, "PIT :", "  Entry is empty"]
    return "\n".join(lines) + "\n"


def _write_fib_dump(run_dir: Path, host_label: str, text: str) -> None:
    """Write one host's FIB dump where run_single_smoke's cefstatus capture
    would (debug/fib/fib_<host>.txt), found by validate_results via rglob."""
    fib_dir = run_dir / "debug" / "fib"
    fib_dir.mkdir(parents=True, exist_ok=True)
    (fib_dir / f"fib_{host_label}.txt").write_text(text)


def test_fib_dump_require_missing_prefix_fails(tmp_path):
    """A `require` prefix absent from the host's FIB section must fail by
    name -- fib_dump exists to pin which route got installed, not just that
    some FIB section is present.
    """
    text = _fib_dump_text([("ccnx:/test/putget", "34 (-s-) RtCost=0 ")])
    _write_fib_dump(tmp_path, "h0", text)

    with pytest.raises(RuntimeError) as exc_info:
        checker.validate_results(
            "case",
            [],
            {"fib_dump": {"require": {"h0": ["ccnx:/test/to-h2"]}}},
            tmp_path,
        )
    assert str(exc_info.value) == (
        "case: fib_h0.txt FIB section is missing prefix 'ccnx:/test/to-h2'"
    )


def test_fib_dump_forbid_present_prefix_fails(tmp_path):
    """2026-10-22 fix: an inverted `forbid` check (treating "present" as
    passing) survived the suite with zero unit coverage of this branch --
    only a live smoke run against real host data would have caught it. A
    `forbid` prefix found in the host's FIB section must fail -- e.g. a
    prefix_routes target must never carry a route back to itself.
    """
    text = _fib_dump_text([("ccnx:/test/to-h2", "34 (-s-) RtCost=0 ")])
    _write_fib_dump(tmp_path, "h2", text)

    with pytest.raises(RuntimeError) as exc_info:
        checker.validate_results(
            "case",
            [],
            {"fib_dump": {"forbid": {"h2": ["ccnx:/test/to-h2"]}}},
            tmp_path,
        )
    assert str(exc_info.value) == (
        "case: fib_h2.txt FIB section unexpectedly has prefix "
        "'ccnx:/test/to-h2' (a route announcement must not route to itself)"
    )


def test_fib_dump_pit_app_indented_line_not_read_as_prefix():
    """2026-10-22 fix: removing the `break` on the PIT(App) : header
    survived the suite -- nothing exercised a line past that header, so a
    parser that kept scanning would still pass. A line under PIT(App) :
    can share a FIB entry's two-space indent (FIB(App) : uses the same
    indent too, per _fib_section_prefixes' docstring); this pins that the
    parser stops at the PIT(App) : header and never reads past it, rather
    than merely happening to produce the right set for dumps that only
    ever say "Entry is empty" there.
    """
    text = _fib_dump_text(
        [("ccnx:/test/to-h2", "34 (-s-) RtCost=0 ")],
        trailing_app_pit_line="  ccnx:/test/trap",
    )
    assert checker._fib_section_prefixes(text) == {"ccnx:/test/to-h2"}


# ── validate_host_app_markers ──
#
# Exact-match assertions per project convention (docs/runbooks/mutation-
# testing.md): substring/regex asserts let mutants through, so these compare
# the full raised message, not a `match=` pattern.


def _write_marker(run_dir: Path, idx: int, content: str) -> None:
    """Write one host's host_app_marker file under run_dir, as the real
    min_host_apps.yaml command (echo {node} {t0_ms} > ...) would."""
    marker_dir = run_dir / "debug" / "node_dirs" / f"h{idx}"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / "host_app_marker").write_text(content)


def test_host_app_markers_missing_file_fails(tmp_path):
    """A host that never wrote its marker must fail by name, not vacuously."""
    _write_marker(tmp_path, 0, "h0 1700000000000")
    # h1's marker is never written.

    with pytest.raises(RuntimeError) as exc_info:
        checker.validate_host_app_markers("min_host_apps", tmp_path, (0, 1))

    assert str(exc_info.value) == "min_host_apps: host_app_marker missing for h1"


def test_host_app_markers_wrong_token_count_fails(tmp_path):
    """The marker must be exactly two whitespace-separated tokens."""
    _write_marker(tmp_path, 0, "h0 1700000000000 extra")

    with pytest.raises(RuntimeError) as exc_info:
        checker.validate_host_app_markers("min_host_apps", tmp_path, (0,))

    assert str(exc_info.value) == (
        "min_host_apps: h0 host_app_marker content "
        "'h0 1700000000000 extra' is not 'hN <ms>'"
    )


def test_host_app_markers_wrong_node_name_fails(tmp_path):
    """h1's marker holds h0's name -- the mix-up this check exists to catch."""
    _write_marker(tmp_path, 1, "h0 1700000000000")

    with pytest.raises(RuntimeError) as exc_info:
        checker.validate_host_app_markers("min_host_apps", tmp_path, (1,))

    assert str(exc_info.value) == (
        "min_host_apps: h1 host_app_marker node is 'h0', expected 'h1'"
    )


def test_host_app_markers_non_numeric_t0_fails(tmp_path):
    """The second token must be the numeric t0_ms, not arbitrary text."""
    _write_marker(tmp_path, 0, "h0 not-a-number")

    with pytest.raises(RuntimeError) as exc_info:
        checker.validate_host_app_markers("min_host_apps", tmp_path, (0,))

    assert str(exc_info.value) == (
        "min_host_apps: h0 host_app_marker t0 'not-a-number' is not numeric"
    )


def test_host_app_markers_mismatched_t0_fails(tmp_path):
    """Differing t0_ms across hosts means they did not share one capture point."""
    _write_marker(tmp_path, 0, "h0 1700000000000")
    _write_marker(tmp_path, 1, "h1 1700000000111")

    with pytest.raises(RuntimeError) as exc_info:
        checker.validate_host_app_markers("min_host_apps", tmp_path, (0, 1))

    assert str(exc_info.value) == (
        "min_host_apps: host_app_marker t0 values differ across hosts: "
        "['1700000000000', '1700000000111']"
    )


def test_host_app_markers_matching_t0_passes(tmp_path):
    """Three markers, each with its own node name and the same t0_ms, pass."""
    _write_marker(tmp_path, 0, "h0 1700000000000")
    _write_marker(tmp_path, 1, "h1 1700000000000")
    _write_marker(tmp_path, 2, "h2 1700000000000")

    checker.validate_host_app_markers("min_host_apps", tmp_path, (0, 1, 2))
