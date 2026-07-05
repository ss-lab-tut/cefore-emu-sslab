"""Tests for src.scenarios.base residual paths: run_main() hook chain and
the net-is-None early-failure cleanup branch.

CONTEXT.md test-gap slice 10: tests/scenarios/test_teardown_lifecycle.py
covers execute()'s finally-block cleanup staging extensively (24 tests) but
never exercises run_main()/should_run_cli()/before_cli()/after_cli(), nor
the branch where build_topology() fails before create_mininet() ever runs
(net stays None, so cleanup_node_dirs() is used instead of cleanup_all()).

Reuses the minimal-concrete-subclass pattern from
tests/core/test_path_containment.py's `_TestScenario`.

CRITICAL: `CLI` is imported into src/scenarios/base.py's module namespace
(base.py:6, `from mininet.cli import CLI`), so it must be patched at
"src.scenarios.base.CLI". Patching "mininet.cli.CLI" has no effect on the
already-bound name and would let the real interactive CLI start, hanging
the test run (Codex-verified).
"""

from unittest.mock import patch

import pytest

from src.scenarios.base import BaseScenario


class _TestScenario(BaseScenario):
    """Minimal concrete scenario for exercising BaseScenario's hook methods."""

    def build_topology(self):
        pass

    def configure(self, net):
        pass

    def run_experiment(self, net):
        pass

    def teardown(self, net):
        pass


class TestRunMainHookOrder:
    """run_main() gates the CLI hook chain on should_run_cli()."""

    def test_should_run_cli_true_invokes_hooks_in_order(self):
        scenario = _TestScenario()
        net = object()
        call_order = []
        scenario.before_cli = lambda n: call_order.append(("before_cli", n))
        scenario.run_cli = lambda n: call_order.append(("run_cli", n))
        scenario.after_cli = lambda n: call_order.append(("after_cli", n))

        scenario.run_main(net)

        assert call_order == [
            ("before_cli", net),
            ("run_cli", net),
            ("after_cli", net),
        ]

    def test_should_run_cli_false_skips_all_hooks(self):
        scenario = _TestScenario()
        scenario.should_run_cli = lambda: False
        scenario.before_cli = lambda n: pytest.fail("before_cli must not run")
        scenario.run_cli = lambda n: pytest.fail("run_cli must not run")
        scenario.after_cli = lambda n: pytest.fail("after_cli must not run")

        # No assertion needed beyond "did not raise" -- the lambdas above
        # fail the test immediately if run_main() invokes them.
        scenario.run_main(object())

    def test_default_should_run_cli_is_true(self):
        assert _TestScenario().should_run_cli() is True

    def test_default_run_cli_enters_mininet_cli(self):
        scenario = _TestScenario()
        net = object()

        with patch("src.scenarios.base.CLI") as mock_cli:
            scenario.run_cli(net)

        mock_cli.assert_called_once_with(net)


class TestExecuteNetNoneEarlyFailure:
    """If build_topology() raises before create_mininet() runs, net stays
    None and execute()'s finally block must fall back to cleanup_node_dirs()
    instead of cleanup_all() (base.py:229-237)."""

    def test_build_topology_failure_uses_cleanup_node_dirs_not_cleanup_all(self):
        scenario = _TestScenario()
        scenario.generated_node_dirs = ["h0", "h1"]
        boom = RuntimeError("topology construction failed")
        scenario.build_topology = lambda: (_ for _ in ()).throw(boom)

        with (
            patch("src.scenarios.base.cleanup_node_dirs") as mock_cleanup_node_dirs,
            patch("src.scenarios.base.cleanup_all") as mock_cleanup_all,
        ):
            # No cleanup-stage failures occur (net is None so teardown/
            # collect_debug_* never run), so the primary exception is
            # re-raised as-is by _propagate_failures().
            with pytest.raises(RuntimeError, match="topology construction failed"):
                scenario.execute()

        mock_cleanup_node_dirs.assert_called_once_with(["h0", "h1"])
        mock_cleanup_all.assert_not_called()
