"""Tests for src.log.plotter.

Covers the two independent halves of the module (see CONTEXT.md Slice 5 of the
test-gap plan):

Section A -- pure helpers (extract_uri_prefix, _safe_float/_safe_int,
_get_metric, _known_success, _build_title, _color_for) plus the two "simple"
plotters that draw a single Axes without a cycle dimension: plot_cefputfile
and plot_cefpubfile.

Section B -- the grouped-bar-by-cycle path: _filter_eval, _group_by_prefix,
_cycles, _grouped_bar_by_cycle itself, and the three plotters that delegate
to it (plot_cefgetfile, plot_cefsubfile) plus the top-level dispatcher
plot_all.

Record field names (uri/success/phase/throughput_bps/goodput_bps/
jitter_ave_us/rate/seed/hosts/experiment_dir/label/publisher_down) are taken
from the real output of src/log/parser.py and src/log/summarizer.py so these
tests exercise plotter.py against realistic input shapes.

NOTE on `cycle`: the current summarizer (post R7-2) does not emit a `cycle`
column -- it was dropped from the CSV. plotter.py still reads it optionally
(`record.get("cycle")`), so the grouped-bar-by-cycle tests below *fabricate*
a `cycle` key on test records purely to exercise that optional code path. It
is not something real parser/summarizer output would ever contain today.
"""

from pathlib import Path

from src.log.plotter import (
    _build_title,
    _color_for,
    _cycles,
    _filter_eval,
    _get_metric,
    _group_by_prefix,
    _grouped_bar_by_cycle,
    _known_success,
    _safe_float,
    _safe_int,
    extract_uri_prefix,
    plot_all,
    plot_cefgetfile,
    plot_cefpubfile,
    plot_cefputfile,
    plot_cefsubfile,
)


def _assert_saved(paths: list[Path]) -> None:
    """Assert _save_fig's contract: one .png + one .pdf, both non-empty on disk.

    Shared by every test that reaches a plotter's happy path, since every
    plotter bottoms out in _save_fig (plotter.py:116) which always writes
    both extensions for a given base filename.
    """
    suffixes = sorted(p.suffix for p in paths)
    assert suffixes.count(".png") >= 1
    assert suffixes.count(".pdf") >= 1
    assert len(paths) == suffixes.count(".png") + suffixes.count(".pdf")
    for path in paths:
        assert path.exists()
        assert path.stat().st_size > 0


# ===========================================================================
# Section A: pure helpers + simple (non-cycle) plotters
# ===========================================================================


class TestPureHelpers:
    """extract_uri_prefix, _safe_float/_safe_int, _get_metric, _known_success,
    _build_title, _color_for: leaf helpers with no plotting side effects."""

    def test_extracts_prefix_from_well_formed_uri(self):
        assert extract_uri_prefix("ccnx:/video/stream1") == "video"

    def test_returns_unknown_for_none(self):
        assert extract_uri_prefix(None) == "unknown"

    def test_returns_unknown_for_empty_string(self):
        assert extract_uri_prefix("") == "unknown"

    def test_returns_unknown_for_non_ccnx_uri(self):
        # No "ccnx:/" prefix at all -> regex fails to match.
        assert extract_uri_prefix("http://example.com/foo") == "unknown"

    def test_safe_float_parses_valid_numeric_string(self):
        assert _safe_float("3.14") == 3.14

    def test_safe_float_returns_none_for_invalid_string(self):
        assert _safe_float("not-a-number") is None

    def test_safe_float_returns_none_for_none(self):
        assert _safe_float(None) is None

    def test_safe_float_returns_none_for_empty_string(self):
        assert _safe_float("") is None

    def test_safe_int_parses_valid_numeric_string(self):
        assert _safe_int("42") == 42

    def test_safe_int_returns_none_for_invalid_string(self):
        assert _safe_int("nope") is None

    def test_safe_int_returns_none_for_none(self):
        assert _safe_int(None) is None

    def test_safe_int_returns_none_for_empty_string(self):
        assert _safe_int("") is None

    def test_get_metric_returns_first_present_key_in_fallback_chain(self):
        # cefsubfile records may carry either the generic "throughput" key
        # or the "throughput_bps" alias depending on the log's unit label;
        # _get_metric tries keys left-to-right and returns the first hit.
        record = {"throughput": None, "throughput_bps": "5000000"}
        assert _get_metric(record, "throughput", "throughput_bps") == 5000000.0

    def test_get_metric_returns_none_when_no_key_present(self):
        record = {"other_field": "1"}
        assert _get_metric(record, "throughput", "throughput_bps") is None

    def test_known_success_lowercases_and_keeps_true_false_only(self):
        records = [
            {"success": "True"},
            {"success": "FALSE"},
            {"success": ""},  # unknown verdict, tri-state -- excluded
            {"success": None},  # missing field -- excluded
        ]
        assert _known_success(records) == ["true", "false"]

    def test_known_success_returns_empty_list_when_all_unknown(self):
        records = [{"success": ""}, {"success": None}]
        assert _known_success(records) == []

    def test_build_title_includes_experiment_hosts_and_seed_when_present(self):
        records = [{"experiment_dir": "exp1", "hosts": 5, "seed": 42}]
        title = _build_title(records, "cefputfile Throughput")
        assert title == "cefputfile Throughput - exp1 - hosts=5 - seed=42"

    def test_build_title_omits_missing_fields(self):
        # No seed/hosts/experiment_dir in the record -> title is chart_name alone.
        title = _build_title([{}], "cefputfile Throughput")
        assert title == "cefputfile Throughput"

    def test_build_title_handles_empty_records_list(self):
        title = _build_title([], "cefputfile Throughput")
        assert title == "cefputfile Throughput"

    def test_color_for_known_prefix_returns_mapped_color(self):
        assert _color_for("video") == "#0077BB"

    def test_color_for_unknown_prefix_returns_default_color(self):
        assert _color_for("mystery-prefix") == "#BBBBBB"


class TestPlotCefputfile:
    """plot_cefputfile: single bar chart, one bar per URI, mean throughput."""

    def test_happy_path_writes_png_and_pdf(self, tmp_path):
        records = [
            {"uri": "ccnx:/video/a", "throughput_bps": "1000000"},
            {"uri": "ccnx:/test/b", "throughput_bps": "2000000"},
        ]
        paths = plot_cefputfile(records, tmp_path)
        _assert_saved(paths)
        names = {p.stem for p in paths}
        assert names == {"cefputfile_throughput"}

    def test_empty_records_returns_no_paths(self, tmp_path):
        assert plot_cefputfile([], tmp_path) == []

    def test_records_with_no_usable_metric_values_returns_no_paths(self, tmp_path):
        # uri present but throughput_bps missing/unparsable on every record
        # -> by_uri stays empty -> plotter bails before drawing anything.
        records = [{"uri": "ccnx:/video/a", "throughput_bps": None}]
        assert plot_cefputfile(records, tmp_path) == []


class TestPlotCefpubfile:
    """plot_cefpubfile: two-axis figure (rate, success%) grouped by URI."""

    def test_happy_path_writes_png_and_pdf(self, tmp_path):
        records = [
            {"uri": "ccnx:/video/a", "rate_mbps": "10", "success": "true"},
            {"uri": "ccnx:/video/a", "rate_mbps": "20", "success": "false"},
            {"uri": "ccnx:/test/b", "rate_mbps": "5", "success": "true"},
        ]
        paths = plot_cefpubfile(records, tmp_path)
        _assert_saved(paths)
        names = {p.stem for p in paths}
        assert names == {"cefpubfile_summary"}

    def test_empty_records_returns_no_paths(self, tmp_path):
        assert plot_cefpubfile([], tmp_path) == []

    def test_reads_rate_from_canonical_schema_key(self, tmp_path, monkeypatch):
        import src.log.plotter as plotter_module

        observed_rate_heights: list[float] = []

        def capture_rates(fig, output_dir, name):
            observed_rate_heights.extend(
                patch.get_height() for patch in fig.axes[0].patches
            )
            return []

        monkeypatch.setattr(plotter_module, "_save_fig", capture_rates)
        plotter_module.plot_cefpubfile(
            [{"uri": "ccnx:/video/a", "rate_mbps": "15", "success": "true"}],
            tmp_path,
        )

        assert observed_rate_heights == [15.0]


# ===========================================================================
# Section B: grouped-bar-by-cycle path
# ===========================================================================


class TestFilterEval:
    """_filter_eval: keep phase-less records (linear/mesh) and phase=='eval'."""

    def test_records_without_phase_field_are_treated_as_eval(self):
        records = [{"uri": "ccnx:/a"}]
        assert _filter_eval(records) == records

    def test_records_with_eval_phase_case_insensitive_are_kept(self):
        records = [{"phase": "EVAL"}, {"phase": "eval"}]
        assert _filter_eval(records) == records

    def test_records_with_other_phase_are_dropped(self):
        records = [{"phase": "warmup"}, {"phase": "eval"}]
        assert _filter_eval(records) == [{"phase": "eval"}]


class TestGroupByPrefix:
    """_group_by_prefix: bucket records by URI prefix, sorted by prefix name."""

    def test_groups_records_by_uri_prefix_sorted(self):
        records = [
            {"uri": "ccnx:/video/a"},
            {"uri": "ccnx:/emergency/b"},
            {"uri": "ccnx:/video/c"},
        ]
        groups = _group_by_prefix(records)
        # Sorted alphabetically: emergency before video.
        assert list(groups.keys()) == ["emergency", "video"]
        assert len(groups["video"]) == 2
        assert len(groups["emergency"]) == 1

    def test_missing_uri_groups_under_unknown(self):
        groups = _group_by_prefix([{"uri": None}])
        assert list(groups.keys()) == ["unknown"]


class TestCycles:
    """_cycles: distinct sorted cycle numbers, defaulting missing/bad to 0.

    `cycle` is fabricated here -- see module docstring note: the real
    summarizer output does not carry this field, plotter.py just reads it
    optionally.
    """

    def test_records_without_cycle_field_default_to_cycle_zero(self):
        assert _cycles([{"uri": "a"}, {"uri": "b"}]) == [0]

    def test_records_with_integer_cycle_strings_are_parsed_and_sorted(self):
        records = [{"cycle": "2"}, {"cycle": "0"}, {"cycle": "1"}]
        assert _cycles(records) == [0, 1, 2]

    def test_malformed_cycle_value_falls_back_to_zero(self):
        records = [{"cycle": "not-a-number"}, {"cycle": "3"}]
        assert _cycles(records) == [0, 3]


class TestGroupedBarByCycle:
    """_grouped_bar_by_cycle: shared engine behind get/sub plotters."""

    def test_no_eval_records_returns_no_paths(self, tmp_path):
        # Every record filtered out by phase -> _filter_eval yields [] -> bail.
        records = [{"phase": "warmup", "uri": "ccnx:/a"}]
        paths = _grouped_bar_by_cycle(
            records,
            metric_keys=("throughput_bps",),
            ylabel="Throughput (Mbps)",
            chart_name="test",
            filename="test_chart",
            output_dir=tmp_path,
            divisor=1e6,
        )
        assert paths == []

    def test_no_cycles_returns_no_paths(self, tmp_path, monkeypatch):
        # Force _cycles to report no cycles even though eval_records is
        # non-empty, exercising the "if not cycles: return []" guard
        # (plotter.py:144-145) which is otherwise unreachable since _cycles
        # always yields at least [0] for any non-empty record list.
        import src.log.plotter as plotter_module

        monkeypatch.setattr(plotter_module, "_cycles", lambda records: [])
        records = [{"uri": "ccnx:/a", "throughput_bps": "1000000"}]
        paths = plotter_module._grouped_bar_by_cycle(
            records,
            metric_keys=("throughput_bps",),
            ylabel="Throughput (Mbps)",
            chart_name="test",
            filename="test_chart",
            output_dir=tmp_path,
            divisor=1e6,
        )
        assert paths == []

    def test_success_rate_branch_computes_percentage_per_cycle(self, tmp_path):
        records = [
            {"uri": "ccnx:/video/a", "cycle": "0", "success": "true"},
            {"uri": "ccnx:/video/a", "cycle": "0", "success": "false"},
            {"uri": "ccnx:/video/a", "cycle": "1", "success": "true"},
        ]
        paths = _grouped_bar_by_cycle(
            records,
            metric_keys=(),
            ylabel="Success Rate (%)",
            chart_name="test Success Rate",
            filename="test_success_rate",
            output_dir=tmp_path,
            is_success_rate=True,
        )
        _assert_saved(paths)

    def test_metric_average_branch_computes_mean_per_cycle(self, tmp_path):
        records = [
            {"uri": "ccnx:/video/a", "cycle": "0", "throughput_bps": "1000000"},
            {"uri": "ccnx:/video/a", "cycle": "0", "throughput_bps": "3000000"},
            {"uri": "ccnx:/video/a", "cycle": "1", "throughput_bps": "2000000"},
        ]
        paths = _grouped_bar_by_cycle(
            records,
            metric_keys=("throughput_bps",),
            ylabel="Throughput (Mbps)",
            chart_name="test Throughput",
            filename="test_throughput",
            output_dir=tmp_path,
            divisor=1e6,
        )
        _assert_saved(paths)


class TestPlotCefgetfile:
    """plot_cefgetfile: 4 grouped-bar charts (success rate, throughput, goodput, jitter)."""

    def test_happy_path_writes_all_four_charts(self, tmp_path):
        records = [
            {
                "uri": "ccnx:/video/a",
                "cycle": "0",
                "success": "true",
                "throughput_bps": "1000000",
                "goodput_bps": "900000",
                "jitter_ave_us": "150",
            },
            {
                "uri": "ccnx:/video/a",
                "cycle": "1",
                "success": "false",
                "throughput_bps": "1200000",
                "goodput_bps": "1000000",
                "jitter_ave_us": "200",
            },
        ]
        paths = plot_cefgetfile(records, tmp_path)
        _assert_saved(paths)
        names = {p.stem for p in paths}
        assert names == {
            "cefgetfile_success_rate",
            "cefgetfile_throughput",
            "cefgetfile_goodput",
            "cefgetfile_jitter",
        }

    def test_empty_records_returns_no_paths(self, tmp_path):
        assert plot_cefgetfile([], tmp_path) == []


class TestPlotCefsubfile:
    """plot_cefsubfile: same 4-chart shape as cefgetfile."""

    def test_happy_path_writes_all_four_charts(self, tmp_path):
        records = [
            {
                "uri": "ccnx:/emergency/a",
                "cycle": "0",
                "success": "true",
                "throughput_bps": "1000000",
                "goodput_bps": "900000",
                "jitter_ave_us": "150",
            },
        ]
        paths = plot_cefsubfile(records, tmp_path)
        _assert_saved(paths)
        names = {p.stem for p in paths}
        assert names == {
            "cefsubfile_success_rate",
            "cefsubfile_throughput",
            "cefsubfile_goodput",
            "cefsubfile_jitter",
        }

    def test_empty_records_returns_no_paths(self, tmp_path):
        assert plot_cefsubfile([], tmp_path) == []


class TestPlotAll:
    """plot_all: dispatch table over sorted command names."""

    def test_dispatches_to_registered_plotters_for_each_command(self, tmp_path):
        records_by_command = {
            "cefputfile": [
                {"uri": "ccnx:/video/a", "throughput_bps": "1000000"},
            ],
            "cefgetfile": [
                {
                    "uri": "ccnx:/video/a",
                    "cycle": "0",
                    "success": "true",
                    "throughput_bps": "1000000",
                },
            ],
        }
        paths = plot_all(records_by_command, tmp_path)
        _assert_saved(paths)
        stems = {p.stem for p in paths}
        assert "cefputfile_throughput" in stems
        assert "cefgetfile_success_rate" in stems

    def test_unknown_command_is_silently_skipped(self, tmp_path):
        records_by_command = {"cefunknownfile": [{"uri": "ccnx:/a"}]}
        paths = plot_all(records_by_command, tmp_path)
        assert paths == []
