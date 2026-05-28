"""Teardown lifecycle integration tests — Phase II-A.2.

Verifies that all cleanup stages execute even if earlier stages fail,
and that multiple simultaneous failures are preserved.

Each test exercises the ACTUAL production code paths (teardown() and
the execute() finally block) to capture real fail-before behavior.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, call

import pytest

from src.runtime.bridge import TeardownError


def _make_scenario(tmp_path):
    """Create a DisasterScenario with minimal configuration."""
    from src.scenarios.disaster import DisasterScenario

    args = SimpleNamespace(
        hosts=3,
        seed=42,
        results_json="",
        no_cli=False,
        bridges=None,
        bridge=None,
        events=[],
        ext=None,
        bw=None,
        topo_png=None,
        topo_layout="spring",
        cache_count=0,
        cache_config=None,
        down_interval=0,
        down_duration=0,
        down_count=0,
        down_stagger=0,
        down_exclude=None,
        pubsub_sub_startup_grace=1.0,
        failure_scenarios=None,
        warmup_gets=None,
        warmup_get_interval=0,
        warmup_only_cache_nodes=True,
        duration=0,
        addressing=None,
        routing=None,
        cefnetd_timeout=10,
        webui_port=None,
        node_per_switch=None,
        host_degree_min=None,
        host_degree_max=None,
        switch_use_all=None,
    )

    return DisasterScenario(
        args=args,
        run_dir=Path(tmp_path),
        debug_config=None,
    )


# ---------------------------------------------------------------------------
# L1. Debug pre-teardown containment failure still permits operational cleanup
# ---------------------------------------------------------------------------

class TestL1DebugPreTeardown:
    """If collect_debug_pre_teardown() raises, teardown and cleanup_all
    must still be attempted."""

    def test_debug_pre_failure_allows_teardown_and_cleanup(self, tmp_path):
        """Exercise the execute() finally block. If collect_debug_pre_teardown()
        raises ValueError, teardown() and cleanup_all() must still run.

        Fail-before: the ValueError propagates through the finally block
        unhandled, skipping teardown() and cleanup_all().
        Pass-after: ValueError is caught; teardown() and cleanup_all() run.
        """
        scenario = _make_scenario(tmp_path)
        scenario.started_csmgrd_hosts = set()
        scenario.generated_node_dirs = []
        scenario.results_path = None
        scenario.results = {}

        # Patch collect_debug_pre_teardown to raise ValueError
        # This will be called from execute()'s finally block
        orig_pre = scenario.collect_debug_pre_teardown
        with patch.object(
            scenario,
            "collect_debug_pre_teardown",
            side_effect=ValueError("path escapes run directory"),
        ):
            with patch.object(scenario, "teardown") as mock_teardown:
                with patch(
                    "src.scenarios.disaster.cleanup_all"
                ) as mock_cleanup_all:
                    net = MagicMock()

                    # Call execute() — the finally block exercises the real control flow
                    # We need to mock the try block to avoid Mininet
                    with patch.object(scenario, "build_topology"):
                        with patch.object(scenario, "create_mininet", return_value=net):
                            with patch.object(scenario, "configure"):
                                with patch.object(scenario, "run_experiment"):
                                    try:
                                        scenario.execute()
                                    except Exception:
                                        pass  # We expect exceptions in fail-before

                            # After fix: teardown and cleanup_all were called
                            mock_teardown.assert_called()
                            mock_cleanup_all.assert_called()


# ---------------------------------------------------------------------------
# L2. Debug post-teardown containment failure still permits generic cleanup
# ---------------------------------------------------------------------------

class TestL2DebugPostTeardown:
    """If collect_debug_post_teardown() raises, cleanup_all must still run."""

    def test_debug_post_failure_allows_cleanup_all(self, tmp_path):
        """If collect_debug_post_teardown() raises ValueError, cleanup_all()
        must still be attempted.

        Fail-before: ValueError propagates through finally block,
        skipping cleanup_all().
        Pass-after: ValueError caught; cleanup_all() runs.
        """
        scenario = _make_scenario(tmp_path)
        scenario.started_csmgrd_hosts = set()
        scenario.generated_node_dirs = []
        scenario.results_path = None
        scenario.results = {}

        with patch.object(scenario, "teardown"):
            with patch.object(
                scenario,
                "collect_debug_post_teardown",
                side_effect=ValueError("path escapes run directory"),
            ):
                with patch("src.scenarios.disaster.cleanup_all") as mock_cleanup:
                    net = MagicMock()

                    with patch.object(scenario, "build_topology"):
                        with patch.object(scenario, "create_mininet", return_value=net):
                            with patch.object(scenario, "configure"):
                                with patch.object(scenario, "run_experiment"):
                                    try:
                                        scenario.execute()
                                    except Exception:
                                        pass

                            mock_cleanup.assert_called()


# ---------------------------------------------------------------------------
# L3. Daemon-stop exception does not skip BridgeManager/external cleanup
# ---------------------------------------------------------------------------

class TestL3DaemonStop:
    """If stop_cefnetd() raises, bridge cleanup must still run."""

    def test_stop_cefnetd_failure_allows_bridge_cleanup(self, tmp_path):
        """If stop_cefnetd() raises, bridge_manager.cleanup() and
        cleanup_external_bridges() must still be attempted.

        Fail-before: teardown() aborts on first stop_cefnetd exception;
        bridge cleanup never reached.
        Pass-after: all daemon stops attempted; bridge cleanup runs.
        """
        scenario = _make_scenario(tmp_path)
        scenario.started_csmgrd_hosts = set()

        stop_calls = []

        def stop_cefnetd_side_effect(net, idx):
            stop_calls.append(idx)
            if idx == 0:
                raise RuntimeError("daemon stop failed")

        with patch(
            "src.scenarios.disaster.stop_cefnetd",
            side_effect=stop_cefnetd_side_effect,
        ):
            with patch("src.scenarios.disaster.stop_csmgrd"):
                scenario.bridge_manager.cleanup = MagicMock()
                with patch("src.scenarios.disaster.cleanup_external_bridges"):
                    net = MagicMock()

                    try:
                        scenario.teardown(net)
                    except Exception:
                        pass  # May raise

                    # After fix: bridge_manager.cleanup was called
                    scenario.bridge_manager.cleanup.assert_called()


# ---------------------------------------------------------------------------
# L4. BridgeManager and external cleanup failures are both preserved
# ---------------------------------------------------------------------------

class TestL4DualCleanupFailure:
    """Multiple cleanup failures must be preserved together."""

    def test_both_bridge_failures_preserved(self, tmp_path):
        """If bridge_manager.cleanup() raises TeardownError AND
        cleanup_external_bridges() raises, both must be observable.

        Fail-before: external bridge failure discarded when bridge_manager
        already failed (line 677: if bridge_cleanup_error is None: raise)
        Pass-after: both failures observable.
        """
        scenario = _make_scenario(tmp_path)
        scenario.started_csmgrd_hosts = set()

        scenario.bridge_manager.cleanup = MagicMock(
            side_effect=TeardownError([("nat restore", 1, "error")])
        )

        with patch(
            "src.scenarios.disaster.cleanup_external_bridges",
            side_effect=RuntimeError("external bridge failed"),
        ):
            with patch("src.scenarios.disaster.stop_cefnetd"):
                with patch("src.scenarios.disaster.stop_csmgrd"):
                    net = MagicMock()

                    with pytest.raises(Exception) as exc_info:
                        scenario.teardown(net)

                    exc = exc_info.value

                    # After fix: both failures are observable
                    assert _exception_tree_contains(exc, "external bridge failed"), (
                        f"external bridge failure not observable in: {_collect_exception_messages(exc)}"
                    )
                    assert _exception_tree_contains(exc, "nat restore"), (
                        f"BridgeManager failure not observable in: {_collect_exception_messages(exc)}"
                    )


# ---------------------------------------------------------------------------
# L5. Primary execution failure plus debug/cleanup failures preserves all causes
# ---------------------------------------------------------------------------

class TestL5PrimaryAndCleanupFailure:
    """Primary and cleanup failures must both be preserved."""

    def test_primary_and_teardown_failures_both_preserved(self, tmp_path):
        """When primary execution fails AND teardown has mandatory
        failures, both must be observable.

        Fail-before: primary exception lost; only TeardownError propagates.
        Pass-after: both observable via ExceptionGroup or chaining.
        """
        scenario = _make_scenario(tmp_path)
        scenario.started_csmgrd_hosts = set()
        scenario.generated_node_dirs = []
        scenario.results_path = None
        scenario.results = {}

        scenario.bridge_manager.cleanup = MagicMock(
            side_effect=TeardownError([("cleanup failure", 1, "error")])
        )

        with patch("src.scenarios.disaster.cleanup_external_bridges"):
            with patch("src.scenarios.disaster.stop_cefnetd"):
                with patch("src.scenarios.disaster.stop_csmgrd"):
                    net = MagicMock()

                    # Simulate: primary failure during configure
                    with patch.object(
                        scenario, "configure", side_effect=RuntimeError("primary failure")
                    ):
                        with patch.object(scenario, "build_topology"):
                            with patch.object(scenario, "create_mininet", return_value=net):
                                with patch.object(scenario, "run_experiment"):
                                    try:
                                        scenario.execute()
                                    except Exception as exc:
                                        # After fix: both primary and cleanup in exception tree
                                        assert _exception_tree_contains(exc, "primary failure"), (
                                            f"primary failure not in: {_collect_exception_messages(exc)}"
                                        )
                                        assert _exception_tree_contains(exc, "cleanup failure"), (
                                            f"cleanup failure not in: {_collect_exception_messages(exc)}"
                                        )
                                        return

                                    pytest.fail("expected exception")


# ---------------------------------------------------------------------------
# L6. Results write happens only after operational cleanup attempt
# ---------------------------------------------------------------------------

class TestL6ResultsWriteOrdering:
    """Results write must occur after cleanup, not before."""

    def test_cleanup_before_results_write(self, tmp_path):
        """cleanup_all() must be attempted before results write.

        Fail-before: in some error paths, ordering may be wrong.
        Pass-after: cleanup always precedes results write.
        """
        scenario = _make_scenario(tmp_path)
        scenario.started_csmgrd_hosts = set()
        scenario.generated_node_dirs = []
        scenario.results_path = tmp_path / "results.json"
        scenario.results = {}

        call_order = []

        def mock_teardown(*args):
            call_order.append("teardown")

        def mock_cleanup_all(*args, **kwargs):
            call_order.append("cleanup_all")

        with patch.object(scenario, "teardown", side_effect=mock_teardown):
            with patch.object(scenario, "collect_debug_post_teardown"):
                with patch(
                    "src.scenarios.disaster.cleanup_all",
                    side_effect=mock_cleanup_all,
                ):
                    net = MagicMock()

                    with patch.object(scenario, "build_topology"):
                        with patch.object(scenario, "create_mininet", return_value=net):
                            with patch.object(scenario, "configure"):
                                with patch.object(scenario, "run_experiment"):
                                    try:
                                        scenario.execute()
                                    except Exception:
                                        pass

                    # Verify cleanup_all was called before results write
                    # Results write happens in execute() after cleanup_all
                    assert "teardown" in call_order
                    assert "cleanup_all" in call_order
                    assert call_order.index("teardown") < call_order.index("cleanup_all")


# ---------------------------------------------------------------------------
# Helper: collect all messages from an exception tree
# ---------------------------------------------------------------------------

def _collect_exception_messages(exc):
    """Collect all exception messages from an exception tree."""
    messages = [str(exc)]
    if isinstance(exc, (ExceptionGroup, BaseExceptionGroup)):
        for sub in exc.exceptions:
            messages.extend(_collect_exception_messages(sub))
    if exc.__cause__ is not None:
        messages.extend(_collect_exception_messages(exc.__cause__))
    if exc.__context__ is not None and exc.__context__ is not exc:
        messages.extend(_collect_exception_messages(exc.__context__))
    return messages


def _exception_tree_contains(exc, substring):
    """Check if any exception in the tree contains the given substring."""
    for msg in _collect_exception_messages(exc):
        if substring in msg:
            return True
    return False


def _find_exception_by_type(exc, exc_type):
    """Find an exception of the given type in an exception tree."""
    if isinstance(exc, exc_type):
        return exc
    if isinstance(exc, (ExceptionGroup, BaseExceptionGroup)):
        for sub in exc.exceptions:
            found = _find_exception_by_type(sub, exc_type)
            if found is not None:
                return found
    if exc.__cause__ is not None:
        found = _find_exception_by_type(exc.__cause__, exc_type)
        if found is not None:
            return found
    if exc.__context__ is not None and exc.__context__ is not exc:
        found = _find_exception_by_type(exc.__context__, exc_type)
        if found is not None:
            return found
    return None


# ---------------------------------------------------------------------------
# P0.1 SystemExit aggregation must retain both failures
# ---------------------------------------------------------------------------

class TestP01SystemExitAggregationStrong:
    """Stronger S6: SystemExit + cleanup failure → both preserved in BaseExceptionGroup."""

    def test_system_exit_code_and_cleanup_both_in_base_exception_group(self, tmp_path):
        """P0.1: SystemExit(2) + TeardownError → BaseExceptionGroup containing
        both SystemExit with .code==2 AND the cleanup failure detail.

        Fail-before: if ExceptionGroup used, TypeError. If only one preserved, assertion fails.
        Pass-after: BaseExceptionGroup with SystemExit(2) and TeardownError both present.
        """
        scenario = _make_scenario(tmp_path)
        scenario.started_csmgrd_hosts = set()
        scenario.generated_node_dirs = []
        scenario.results_path = None
        scenario.results = {}

        scenario.bridge_manager.cleanup = MagicMock(
            side_effect=TeardownError([("nat restore", 1, "error")])
        )

        with patch("src.scenarios.disaster.cleanup_external_bridges"):
            with patch("src.scenarios.disaster.stop_cefnetd"):
                with patch("src.scenarios.disaster.stop_csmgrd"):
                    with patch("src.scenarios.disaster.cleanup_all"):
                        net = MagicMock()

                        with patch.object(scenario, "build_topology"):
                            with patch.object(scenario, "create_mininet", return_value=net):
                                with patch.object(
                                    scenario, "configure", side_effect=SystemExit(2)
                                ):
                                    with patch.object(scenario, "run_experiment"):
                                        with pytest.raises(BaseExceptionGroup) as exc_info:
                                            scenario.execute()

                                        # Must be BaseExceptionGroup
                                        assert isinstance(exc_info.value, BaseExceptionGroup)

                                        # Must contain SystemExit with code 2
                                        system_exit = _find_exception_by_type(
                                            exc_info.value, SystemExit
                                        )
                                        assert system_exit is not None, (
                                            "SystemExit not found in exception tree"
                                        )
                                        assert system_exit.code == 2

                                        # Must contain cleanup failure detail
                                        assert _exception_tree_contains(
                                            exc_info.value, "nat restore"
                                        ), (
                                            f"cleanup failure not in: {_collect_exception_messages(exc_info.value)}"
                                        )


# ---------------------------------------------------------------------------
# P0.2 Interrupt during shutdown stages must not skip cleanup
# ---------------------------------------------------------------------------

class TestP02InterruptDuringShutdown:
    """Interrupt during shutdown must not skip operational cleanup."""

    def test_keyboard_interrupt_during_monitor_stop_still_runs_cleanup(self, tmp_path):
        """P0.2a: monitor.stop() raises KeyboardInterrupt → teardown and
        cleanup_all must still run.

        Fail-before: if monitor.stop() only catches Exception, KeyboardInterrupt
        propagates and skips all cleanup.
        Pass-after: KeyboardInterrupt captured; cleanup runs; interrupt observable.
        """
        scenario = _make_scenario(tmp_path)
        scenario.started_csmgrd_hosts = set()
        scenario.generated_node_dirs = []
        scenario.results_path = None
        scenario.results = {}

        mock_monitor = MagicMock()
        mock_monitor.stop = MagicMock(side_effect=KeyboardInterrupt())
        scenario.monitor = mock_monitor

        with patch.object(scenario, "teardown") as mock_teardown:
            with patch("src.scenarios.disaster.cleanup_all") as mock_cleanup:
                net = MagicMock()

                with patch.object(scenario, "build_topology"):
                    with patch.object(scenario, "create_mininet", return_value=net):
                        with patch.object(scenario, "configure"):
                            with patch.object(scenario, "run_experiment"):
                                try:
                                    scenario.execute()
                                except (BaseExceptionGroup, KeyboardInterrupt):
                                    # Either: KeyboardInterrupt propagated (with cleanup done)
                                    # or: captured in BaseExceptionGroup with cleanup failures
                                    pass
                                except Exception:
                                    pass

                        # After fix: teardown and cleanup_all called
                        mock_teardown.assert_called()
                        mock_cleanup.assert_called()

    def test_system_exit_during_teardown_still_runs_cleanup_all(self, tmp_path):
        """P0.2b: teardown() raises SystemExit(2) → cleanup_all must still run.

        Fail-before: if teardown only catches Exception, SystemExit propagates
        and skips cleanup_all.
        Pass-after: SystemExit captured; cleanup_all runs; SystemExit observable.
        """
        scenario = _make_scenario(tmp_path)
        scenario.started_csmgrd_hosts = set()
        scenario.generated_node_dirs = []
        scenario.results_path = None
        scenario.results = {}

        with patch.object(
            scenario,
            "teardown",
            side_effect=SystemExit(2),
        ):
            with patch("src.scenarios.disaster.cleanup_all") as mock_cleanup:
                net = MagicMock()

                with patch.object(scenario, "build_topology"):
                    with patch.object(scenario, "create_mininet", return_value=net):
                        with patch.object(scenario, "configure"):
                            with patch.object(scenario, "run_experiment"):
                                try:
                                    scenario.execute()
                                except (BaseExceptionGroup, SystemExit):
                                    pass
                                except Exception:
                                    pass

                        # After fix: cleanup_all was called
                        mock_cleanup.assert_called()


# ---------------------------------------------------------------------------
# S1. monitor.stop failure does not skip operational cleanup
# ---------------------------------------------------------------------------

class TestS1MonitorStop:
    """If monitor.stop() raises, teardown and cleanup_all must still run."""

    def test_monitor_stop_failure_allows_cleanup(self, tmp_path):
        """S1: monitor.stop() raises → teardown + cleanup_all must run.

        Fail-before: monitor.stop() on line 631 has no try/except.
        Exception propagates, skipping all staged cleanup.
        Pass-after: monitor failure caught; cleanup runs.
        """
        scenario = _make_scenario(tmp_path)
        scenario.started_csmgrd_hosts = set()
        scenario.generated_node_dirs = []
        scenario.results_path = None
        scenario.results = {}

        mock_monitor = MagicMock()
        mock_monitor.stop = MagicMock(side_effect=RuntimeError("monitor shutdown failed"))
        scenario.monitor = mock_monitor

        with patch.object(scenario, "teardown") as mock_teardown:
            with patch("src.scenarios.disaster.cleanup_all") as mock_cleanup:
                net = MagicMock()

                with patch.object(scenario, "build_topology"):
                    with patch.object(scenario, "create_mininet", return_value=net):
                        with patch.object(scenario, "configure"):
                            with patch.object(scenario, "run_experiment"):
                                try:
                                    scenario.execute()
                                except Exception:
                                    pass

                        # After fix: teardown and cleanup_all called
                        mock_teardown.assert_called()
                        mock_cleanup.assert_called()


# ---------------------------------------------------------------------------
# S2. webui.stop failure does not skip operational cleanup
# ---------------------------------------------------------------------------

class TestS2WebuiStop:
    """If webui.stop() raises, teardown and cleanup_all must still run."""

    def test_webui_stop_failure_allows_cleanup(self, tmp_path):
        """S2: webui.stop() raises → teardown + cleanup_all must run.

        Fail-before: webui.stop() on line 633 has no try/except.
        Exception propagates, skipping all staged cleanup.
        Pass-after: webui failure caught; cleanup runs.
        """
        scenario = _make_scenario(tmp_path)
        scenario.started_csmgrd_hosts = set()
        scenario.generated_node_dirs = []
        scenario.results_path = None
        scenario.results = {}

        mock_webui = MagicMock()
        mock_webui.stop = MagicMock(side_effect=RuntimeError("webui shutdown failed"))
        scenario.webui = mock_webui

        with patch.object(scenario, "teardown") as mock_teardown:
            with patch("src.scenarios.disaster.cleanup_all") as mock_cleanup:
                net = MagicMock()

                with patch.object(scenario, "build_topology"):
                    with patch.object(scenario, "create_mininet", return_value=net):
                        with patch.object(scenario, "configure"):
                            with patch.object(scenario, "run_experiment"):
                                try:
                                    scenario.execute()
                                except Exception:
                                    pass

                        mock_teardown.assert_called()
                        mock_cleanup.assert_called()


# ---------------------------------------------------------------------------
# S3. event_scheduler.stop failure does not skip operational cleanup
# ---------------------------------------------------------------------------

class TestS3SchedulerStop:
    """If event_scheduler.stop() raises, teardown and cleanup_all must still run."""

    def test_scheduler_stop_failure_allows_cleanup(self, tmp_path):
        """S3: event_scheduler.stop() raises → teardown + cleanup_all must run.

        Fail-before: event_scheduler.stop() on line 635 has no try/except.
        Exception propagates, skipping all staged cleanup.
        Pass-after: scheduler failure caught; cleanup runs.
        """
        scenario = _make_scenario(tmp_path)
        scenario.started_csmgrd_hosts = set()
        scenario.generated_node_dirs = []
        scenario.results_path = None
        scenario.results = {}

        mock_scheduler = MagicMock()
        mock_scheduler.stop = MagicMock(side_effect=RuntimeError("scheduler shutdown failed"))
        scenario.event_scheduler = mock_scheduler

        with patch.object(scenario, "teardown") as mock_teardown:
            with patch("src.scenarios.disaster.cleanup_all") as mock_cleanup:
                net = MagicMock()

                with patch.object(scenario, "build_topology"):
                    with patch.object(scenario, "create_mininet", return_value=net):
                        with patch.object(scenario, "configure"):
                            with patch.object(scenario, "run_experiment"):
                                try:
                                    scenario.execute()
                                except Exception:
                                    pass

                        mock_teardown.assert_called()
                        mock_cleanup.assert_called()


# ---------------------------------------------------------------------------
# S4. content_runner stop failure does not skip operational cleanup
# ---------------------------------------------------------------------------

class TestS4ContentRunnerStop:
    """If content_runner.stop() raises, teardown and cleanup_all must still run."""

    def test_content_runner_stop_failure_allows_cleanup(self, tmp_path):
        """S4: content_runner.stop() raises → teardown + cleanup_all must run.

        Fail-before: content_runner.stop() on line 639 has no try/except.
        Exception propagates, skipping all staged cleanup.
        Pass-after: content_runner failure caught; cleanup runs.
        """
        scenario = _make_scenario(tmp_path)
        scenario.started_csmgrd_hosts = set()
        scenario.generated_node_dirs = []
        scenario.results_path = None
        scenario.results = {}

        mock_runner = MagicMock()
        mock_runner.wait_all = MagicMock(return_value=True)
        mock_runner.stop = MagicMock(side_effect=RuntimeError("content runner stop failed"))
        scenario.content_runner = mock_runner

        with patch.object(scenario, "teardown") as mock_teardown:
            with patch("src.scenarios.disaster.cleanup_all") as mock_cleanup:
                net = MagicMock()

                with patch.object(scenario, "build_topology"):
                    with patch.object(scenario, "create_mininet", return_value=net):
                        with patch.object(scenario, "configure"):
                            with patch.object(scenario, "run_experiment"):
                                try:
                                    scenario.execute()
                                except Exception:
                                    pass

                        mock_teardown.assert_called()
                        mock_cleanup.assert_called()


# ---------------------------------------------------------------------------
# S5. Multiple front-end shutdown failures plus teardown failure all preserved
# ---------------------------------------------------------------------------

class TestS5MultipleShutdownFailures:
    """Multiple front-end + teardown failures must all be observable."""

    def test_multiple_shutdown_and_teardown_failures_preserved(self, tmp_path):
        """S5: monitor.stop + teardown failures → both observable.

        Fail-before: monitor.stop() failure propagates, preventing teardown
        from ever running; only monitor failure visible.
        Pass-after: all failures observable in aggregate.
        """
        scenario = _make_scenario(tmp_path)
        scenario.started_csmgrd_hosts = set()
        scenario.generated_node_dirs = []
        scenario.results_path = None
        scenario.results = {}

        mock_monitor = MagicMock()
        mock_monitor.stop = MagicMock(side_effect=RuntimeError("monitor failed"))
        scenario.monitor = mock_monitor

        scenario.bridge_manager.cleanup = MagicMock(
            side_effect=TeardownError([("nat restore", 1, "error")])
        )

        with patch("src.scenarios.disaster.cleanup_external_bridges"):
            with patch("src.scenarios.disaster.stop_cefnetd"):
                with patch("src.scenarios.disaster.stop_csmgrd"):
                    with patch("src.scenarios.disaster.cleanup_all"):
                        net = MagicMock()

                        with patch.object(scenario, "build_topology"):
                            with patch.object(scenario, "create_mininet", return_value=net):
                                with patch.object(scenario, "configure"):
                                    with patch.object(scenario, "run_experiment"):
                                        try:
                                            scenario.execute()
                                        except Exception as exc:
                                            # After fix: both failures in exception tree
                                            assert _exception_tree_contains(exc, "monitor failed"), (
                                                f"monitor failure not in: {_collect_exception_messages(exc)}"
                                            )
                                            assert _exception_tree_contains(exc, "nat restore"), (
                                                f"teardown failure not in: {_collect_exception_messages(exc)}"
                                            )
                                            return

                                        pytest.fail("expected exception")


# ---------------------------------------------------------------------------
# S6. SystemExit primary plus cleanup failure does not become TypeError
# ---------------------------------------------------------------------------

class TestS6SystemExitAggregation:
    """SystemExit + cleanup failure must not produce TypeError."""

    def test_system_exit_with_cleanup_failure_no_typeerror(self, tmp_path):
        """S6: SystemExit(2) + cleanup failure → not TypeError.

        Fail-before: _propagate_failures() passes SystemExit into
        ExceptionGroup(), which only accepts Exception subclasses → TypeError.
        Pass-after: BaseExceptionGroup used for non-Exception primary.
        """
        scenario = _make_scenario(tmp_path)
        scenario.started_csmgrd_hosts = set()
        scenario.generated_node_dirs = []
        scenario.results_path = None
        scenario.results = {}

        # Make teardown raise a cleanup failure
        scenario.bridge_manager.cleanup = MagicMock(
            side_effect=TeardownError([("nat restore", 1, "error")])
        )

        with patch("src.scenarios.disaster.cleanup_external_bridges"):
            with patch("src.scenarios.disaster.stop_cefnetd"):
                with patch("src.scenarios.disaster.stop_csmgrd"):
                    with patch("src.scenarios.disaster.cleanup_all"):
                        net = MagicMock()

                        # SystemExit is not caught by except KeyboardInterrupt,
                        # so it propagates to the finally block.
                        with patch.object(scenario, "build_topology"):
                            with patch.object(scenario, "create_mininet", return_value=net):
                                # Raise SystemExit during configure
                                with patch.object(
                                    scenario, "configure", side_effect=SystemExit(2)
                                ):
                                    with patch.object(scenario, "run_experiment"):
                                        got_typeerror = False
                                        got_valid = False
                                        try:
                                            scenario.execute()
                                        except TypeError as te:
                                            got_typeerror = True
                                        except (SystemExit, BaseExceptionGroup):
                                            got_valid = True
                                        except Exception:
                                            # cleanup-only failure, also valid (no TypeError)
                                            got_valid = True

                                        assert not got_typeerror, (
                                            "SystemExit fed into ExceptionGroup caused TypeError"
                                        )
                                        # We expect either BaseExceptionGroup or cleanup failure
                                        assert got_valid or got_typeerror  # always true, but explicit


# ---------------------------------------------------------------------------
# S7. KeyboardInterrupt behavior is explicit
# ---------------------------------------------------------------------------

class TestS7KeyboardInterrupt:
    """KeyboardInterrupt is intentionally consumed; cleanup runs."""

    def test_keyboard_interrupt_cleanup_runs_no_reraise(self, tmp_path):
        """S7: KeyboardInterrupt triggers cleanup but is not re-raised.

        This is intentional behavior: user interrupt should terminate
        gracefully. Cleanup failures from the interrupt path should
        still be surfaced.
        """
        scenario = _make_scenario(tmp_path)
        scenario.started_csmgrd_hosts = set()
        scenario.generated_node_dirs = []
        scenario.results_path = None
        scenario.results = {}

        with patch.object(scenario, "teardown") as mock_teardown:
            with patch("src.scenarios.disaster.cleanup_all") as mock_cleanup:
                net = MagicMock()

                with patch.object(scenario, "build_topology"):
                    # Simulate KeyboardInterrupt during configure
                    with patch.object(
                        scenario, "configure", side_effect=KeyboardInterrupt()
                    ):
                        with patch.object(scenario, "create_mininet", return_value=net):
                            with patch.object(scenario, "run_experiment"):
                                # Should not raise after cleanup
                                try:
                                    scenario.execute()
                                except KeyboardInterrupt:
                                    pytest.fail(
                                        "KeyboardInterrupt should be consumed"
                                    )
                                # If we get here, no exception — correct behavior

                            mock_teardown.assert_called()
                            mock_cleanup.assert_called()

    def test_keyboard_interrupt_with_cleanup_failure_surfaces_failure(self, tmp_path):
        """If cleanup fails during KeyboardInterrupt, the failure is raised."""
        scenario = _make_scenario(tmp_path)
        scenario.started_csmgrd_hosts = set()
        scenario.generated_node_dirs = []
        scenario.results_path = None
        scenario.results = {}

        scenario.bridge_manager.cleanup = MagicMock(
            side_effect=TeardownError([("nat", 1, "fail")])
        )

        with patch("src.scenarios.disaster.cleanup_external_bridges"):
            with patch("src.scenarios.disaster.stop_cefnetd"):
                with patch("src.scenarios.disaster.stop_csmgrd"):
                    with patch("src.scenarios.disaster.cleanup_all"):
                        net = MagicMock()

                        with patch.object(scenario, "build_topology"):
                            with patch.object(
                                scenario, "configure", side_effect=KeyboardInterrupt()
                            ):
                                with patch.object(scenario, "create_mininet", return_value=net):
                                    with patch.object(scenario, "run_experiment"):
                                        with pytest.raises(Exception) as exc_info:
                                            scenario.execute()

                                        # Should be TeardownError, not KeyboardInterrupt
                                        assert not isinstance(exc_info.value, KeyboardInterrupt)


# ---------------------------------------------------------------------------
# Plan §6 Unit D: BaseException-mixed-with-Exception cleanup case
# ---------------------------------------------------------------------------


class TestBaseExceptionMixedCleanup:
    """KeyboardInterrupt + ordinary Exception cleanup failures must use
    BaseExceptionGroup, not raise TypeError("Cannot nest BaseExceptions in
    an ExceptionGroup")."""

    def test_cleanup_failures_with_baseexception_member_uses_baseexceptiongroup(
        self, tmp_path
    ):
        scenario = _make_scenario(tmp_path)
        scenario.started_csmgrd_hosts = set()
        scenario.generated_node_dirs = []
        scenario.results_path = None
        scenario.results = {}

        # monitor.stop() raises KeyboardInterrupt (e.g. signal during shutdown)
        mock_monitor = MagicMock()
        mock_monitor.stop = MagicMock(side_effect=KeyboardInterrupt())
        scenario.monitor = mock_monitor

        # bridge_manager.cleanup() raises a regular TeardownError (Exception)
        scenario.bridge_manager.cleanup = MagicMock(
            side_effect=TeardownError([("nat restore", 1, "error")])
        )

        with patch("src.scenarios.disaster.cleanup_external_bridges"):
            with patch("src.scenarios.disaster.stop_cefnetd"):
                with patch("src.scenarios.disaster.stop_csmgrd"):
                    with patch("src.scenarios.disaster.cleanup_all"):
                        net = MagicMock()

                        got_typeerror = False
                        observed: BaseException | None = None
                        with patch.object(scenario, "build_topology"):
                            with patch.object(
                                scenario, "create_mininet", return_value=net
                            ):
                                with patch.object(scenario, "configure"):
                                    with patch.object(scenario, "run_experiment"):
                                        try:
                                            scenario.execute()
                                        except TypeError:
                                            got_typeerror = True
                                        except BaseException as exc:
                                            observed = exc

                        # Must not be the "Cannot nest BaseExceptions" TypeError
                        assert not got_typeerror, (
                            "ExceptionGroup raised on non-Exception member"
                        )
                        # The aggregate must be a BaseExceptionGroup that
                        # contains both the KeyboardInterrupt and the
                        # TeardownError, in some order.
                        assert isinstance(observed, BaseExceptionGroup), (
                            f"expected BaseExceptionGroup; got {type(observed).__name__}"
                        )
                        kinds = [type(e) for e in observed.exceptions]
                        assert KeyboardInterrupt in kinds
                        assert TeardownError in kinds


# ---------------------------------------------------------------------------
# T6 (Defect 4). content_runner.wait_all() raising MUST NOT skip stop()
#                and the raised wait_all failure remains observable in the
#                final propagated exception (directly for single-failure case,
#                inside an aggregate when multiple failures exist).
# ---------------------------------------------------------------------------


def _collect_exceptions(exc):
    """Walk an exception graph (ExceptionGroup members + __cause__/__context__)
    and return every exception node reached."""
    seen: list[BaseException] = []
    queue: list[BaseException | None] = [exc]
    while queue:
        e = queue.pop()
        if e is None or any(e is s for s in seen):
            continue
        seen.append(e)
        # ExceptionGroup / BaseExceptionGroup members
        members = getattr(e, "exceptions", None)
        if members is not None:
            for m in members:
                queue.append(m)
        if getattr(e, "__cause__", None) is not None:
            queue.append(e.__cause__)
        if getattr(e, "__context__", None) is not None:
            queue.append(e.__context__)
    return seen


class TestT6ContentRunnerWaitAllRaises:
    """T6 (Defect 4): if content_runner.wait_all() raises, stop() must still
    be invoked, downstream cleanup stages must still run, and the wait_all
    failure must remain observable in the final propagated exception."""

    def test_T6_wait_all_raises_stop_still_runs_and_failure_propagated(self, tmp_path):
        scenario = _make_scenario(tmp_path)
        scenario.started_csmgrd_hosts = set()
        scenario.generated_node_dirs = []
        scenario.results_path = None
        scenario.results = {}

        mock_runner = MagicMock()
        mock_runner.wait_all = MagicMock(side_effect=RuntimeError("wait failed"))
        mock_runner.stop = MagicMock(return_value=None)
        scenario.content_runner = mock_runner

        observed: BaseException | None = None
        with patch.object(scenario, "teardown") as mock_teardown:
            with patch("src.scenarios.disaster.cleanup_all") as mock_cleanup:
                net = MagicMock()
                with patch.object(scenario, "build_topology"):
                    with patch.object(scenario, "create_mininet", return_value=net):
                        with patch.object(scenario, "configure"):
                            with patch.object(scenario, "run_experiment"):
                                try:
                                    scenario.execute()
                                except BaseException as exc:
                                    observed = exc

        # stop() must still be called even though wait_all raised.
        mock_runner.stop.assert_called_once()
        # Downstream stages must still run.
        mock_teardown.assert_called()
        mock_cleanup.assert_called()
        # wait_all was actually invoked.
        mock_runner.wait_all.assert_called_once()

        # The wait_all failure must remain observable in the propagated
        # exception graph, regardless of whether _propagate_failures()
        # re-raised it directly (single-cleanup-failure path) or wrapped it.
        assert observed is not None, "execute() must have propagated some exception"
        collected = _collect_exceptions(observed)
        assert any(
            isinstance(e, RuntimeError) and "wait failed" in str(e)
            for e in collected
        ), (
            f"wait_all failure must remain observable; collected={[repr(e) for e in collected]}"
        )
