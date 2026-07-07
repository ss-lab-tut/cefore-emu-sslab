"""Tests for src.core.debug: build_debug_config branch combinations.

CONTEXT.md test-gap slice 10: build_debug_config() was previously exercised
only end-to-end via bootstrap (a single combined path), so its CLI/YAML
union logic and edge-case filtering had no direct branch coverage.
"""

from types import SimpleNamespace

from src.core.debug import DEBUG_ARTIFACT_CHOICES, DebugConfig, build_debug_config


def _args(**overrides):
    """Return a bare argparse-like namespace with no debug attributes set,
    unless overridden. build_debug_config() reads args via getattr(...,
    default), so an empty namespace exercises the "nothing set" defaults.
    """
    return SimpleNamespace(**overrides)


class TestBuildDebugConfigCliOnly:
    """CLI-sourced flags: --debug (master) and --debug-artifact (individual)."""

    def test_no_flags_and_no_raw_debug_yields_all_disabled(self):
        config = build_debug_config(_args())
        assert config == DebugConfig()
        assert config.enabled() is False
        assert config.output_subdir == "debug"

    def test_debug_master_flag_enables_all_artifacts(self):
        config = build_debug_config(_args(debug=True))
        assert config.node_dirs is True
        assert config.fib_dump is True
        assert config.enabled() is True

    def test_debug_artifact_list_enables_only_named_artifacts(self):
        config = build_debug_config(_args(debug_artifact=["fib_dump"]))
        assert config.fib_dump is True
        assert config.node_dirs is False


class TestBuildDebugConfigYamlOnly:
    """YAML/JSON `debug:` block passed as raw_debug."""

    def test_raw_debug_bare_true_enables_all_artifacts(self):
        config = build_debug_config(_args(), raw_debug=True)
        assert config.node_dirs is True
        assert config.fib_dump is True

    def test_raw_debug_bare_false_leaves_all_disabled(self):
        config = build_debug_config(_args(), raw_debug=False)
        assert config.enabled() is False

    def test_raw_debug_dict_filters_out_non_string_artifacts(self):
        # Malformed config entries (e.g. from a mistyped YAML list) must be
        # silently dropped rather than raising or being treated as valid names.
        raw_debug = {"artifacts": ["fib_dump", 123, None, "unknown"]}
        config = build_debug_config(_args(), raw_debug=raw_debug)
        assert config.fib_dump is True
        assert config.node_dirs is False

    def test_raw_debug_dict_output_subdir_override(self):
        config = build_debug_config(
            _args(), raw_debug={"artifacts": [], "output_subdir": "custom_debug"}
        )
        assert config.output_subdir == "custom_debug"

    def test_raw_debug_dict_empty_output_subdir_keeps_default(self):
        # An empty string is falsy, so it must not override the "debug" default.
        config = build_debug_config(
            _args(), raw_debug={"artifacts": [], "output_subdir": ""}
        )
        assert config.output_subdir == "debug"


class TestBuildDebugConfigCliYamlUnion:
    """CLI and YAML sources must union, not override one another."""

    def test_cli_debug_artifact_and_yaml_artifacts_union(self):
        config = build_debug_config(
            _args(debug_artifact=["node_dirs"]),
            raw_debug={"artifacts": ["fib_dump"]},
        )
        assert config.node_dirs is True
        assert config.fib_dump is True

    def test_cli_debug_master_flag_unions_with_yaml_subdir_override(self):
        config = build_debug_config(
            _args(debug=True),
            raw_debug={"artifacts": [], "output_subdir": "custom"},
        )
        # --debug enables all artifacts regardless of the YAML artifacts list.
        for choice in DEBUG_ARTIFACT_CHOICES:
            assert getattr(config, choice) is True
        assert config.output_subdir == "custom"


class TestDebugConfigEnabled:
    """DebugConfig.enabled() directly: True iff any artifact flag is set."""

    def test_enabled_false_when_all_artifacts_off(self):
        assert DebugConfig().enabled() is False

    def test_enabled_true_when_any_single_artifact_on(self):
        assert DebugConfig(node_dirs=True).enabled() is True
        assert DebugConfig(fib_dump=True).enabled() is True
