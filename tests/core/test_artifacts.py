"""Artifact naming helpers preserve the experiment output schema."""

import re

from src.core.artifacts import (
    content_log_name,
    experiment_dir_name,
    parse_content_log_name,
    safe_uri_label,
    topo_png_default_name,
)


def test_experiment_dir_name_includes_experiment_number_and_seed():
    assert experiment_dir_name(1, 42) == "ex1_seed42"


def test_experiment_dir_name_without_experiment_number_uses_seed_prefix():
    assert experiment_dir_name(None, 7) == "seed7"


def test_experiment_dir_name_labels_missing_seed_as_none():
    assert experiment_dir_name(3, None) == "ex3_seednone"


def test_experiment_dir_name_timestamp_suffix_matches_existing_schema():
    assert re.match(
        r"^ex2_seed9_\d{8}-\d{4}$", experiment_dir_name(2, 9, timestamp=True)
    )


def test_topo_png_default_name_without_experiment_number_keeps_seed_identity():
    assert topo_png_default_name(None, 7, 5) == "seed7_h5.png"


def test_topo_png_default_name_includes_experiment_number_seed_and_hosts():
    assert topo_png_default_name(1, 42, 13) == "ex1_seed42_h13.png"


def test_safe_uri_label_matches_runtime_log_label_schema():
    assert safe_uri_label("ccnx:/test/example4/test.py") == "test_example4_test.py"


def test_content_log_name_round_trips_representative_uri():
    name = content_log_name("cefgetfile", "eval", 4, "ccnx:/test/example4/test.py")
    assert name == "cefgetfile_eval_h4_test_example4_test.py.log"
    assert parse_content_log_name(name) == (
        parse_content_log_name("cefgetfile_eval_h4_test_example4_test.py.log")
    )
    meta = parse_content_log_name(name)
    assert meta is not None
    assert meta.command == "cefgetfile"
    assert meta.phase == "eval"
    assert meta.host == 4
    assert meta.label == "test_example4_test.py"


def test_parse_content_log_name_rejects_legacy_shapes():
    assert parse_content_log_name("cefputfile_h9.log") is None
    assert parse_content_log_name("cefgetfile-h0.log") is None
    assert (
        parse_content_log_name(
            "cefgetfile_seed100_downhosts0,2_phaseeval_cycle1_idx0_h0.log"
        )
        is None
    )
