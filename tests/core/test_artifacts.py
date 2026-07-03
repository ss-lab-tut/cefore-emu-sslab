"""Artifact naming helpers preserve the experiment output schema."""

import re

from src.core.artifacts import experiment_dir_name, topo_png_default_name


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
