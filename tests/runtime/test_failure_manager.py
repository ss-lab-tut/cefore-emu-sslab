"""Unit tests for failure manager."""

import threading
import time
from unittest.mock import MagicMock, patch, call

import pytest

from src.core.flap_state import FlapState
from src.runtime.failure_manager import FlexibleFailureManager, periodic_host_flap


def _make_net(host_count=5):
    net = MagicMock()
    host = MagicMock()
    host.cmd.return_value = ""
    net.hosts = [host] * host_count
    net.get.return_value = host
    return net


class TestPeriodicHostFlap:
    @patch("src.runtime.failure_manager.set_node_links_state")
    def test_empty_host_pool_returns_immediately(self, mock_links):
        net = _make_net(3)
        state = FlapState()
        stop = periodic_host_flap(
            net, 3, interval=1, down_time=1, rng=None,
            exclude=[0, 1, 2], state=state, down_count=1, stagger=0,
        )
        assert isinstance(stop, threading.Event)
        stop.set()
        time.sleep(0.1)
        mock_links.assert_not_called()

    @patch("src.runtime.failure_manager.set_node_links_state")
    def test_hosts_are_downed_and_restored(self, mock_links):
        net = _make_net(3)
        state = FlapState()
        stop = periodic_host_flap(
            net, 3, interval=0.05, down_time=0.05, rng=None,
            exclude=[], state=state, down_count=1, stagger=0, quiet=True,
        )
        time.sleep(0.3)
        stop.set()
        time.sleep(0.15)
        down_calls = [c for c in mock_links.call_args_list if c[0][2] == "down"]
        up_calls = [c for c in mock_links.call_args_list if c[0][2] == "up"]
        assert len(down_calls) > 0
        assert len(up_calls) > 0

    @patch("src.runtime.failure_manager.set_node_links_state")
    def test_exclude_ids_are_never_downed(self, mock_links):
        net = _make_net(4)
        state = FlapState()
        stop = periodic_host_flap(
            net, 4, interval=0.05, down_time=0.05, rng=None,
            exclude=[1], state=state, down_count=1, stagger=0, quiet=True,
        )
        time.sleep(0.3)
        stop.set()
        time.sleep(0.15)
        for c in mock_links.call_args_list:
            if c[0][2] == "down":
                assert c[0][1] != "h1"

    @patch("src.runtime.failure_manager.set_node_links_state")
    def test_on_host_up_callback_fires(self, mock_links):
        net = _make_net(3)
        state = FlapState()
        callback = MagicMock()
        stop = periodic_host_flap(
            net, 3, interval=0.05, down_time=0.05, rng=None,
            exclude=[], state=state, down_count=1, stagger=0,
            quiet=True, on_host_up=callback,
        )
        time.sleep(0.3)
        stop.set()
        time.sleep(0.15)
        assert callback.call_count > 0

    @patch("src.runtime.failure_manager.set_node_links_state")
    def test_stop_event_terminates_worker(self, mock_links):
        net = _make_net(3)
        state = FlapState()
        stop = periodic_host_flap(
            net, 3, interval=10, down_time=10, rng=None,
            exclude=[], state=state, down_count=1, stagger=0, quiet=True,
        )
        time.sleep(0.05)
        stop.set()
        time.sleep(0.2)


class TestFlexibleFailureManager:
    @patch("src.runtime.failure_manager.periodic_host_flap")
    def test_simple_strategy_dispatches(self, mock_flap):
        mock_flap.return_value = threading.Event()
        config = {
            "strategy": "simple",
            "simple": {"interval": 10, "duration": 5, "count": 1},
        }
        mgr = FlexibleFailureManager(config, 5, rng=None, publisher_ids={4})
        state = FlapState()
        stop, _ = mgr.start(MagicMock(), state, quiet=True)
        mock_flap.assert_called_once()

    @patch("src.runtime.failure_manager.set_node_links_state")
    def test_cyclic_strategy_processes_all_cycles(self, mock_links):
        config = {
            "strategy": "cyclic",
            "cycles": [
                {"interval": 0.05, "duration": 0.05, "count": 1},
                {"interval": 0.05, "duration": 0.05, "count": 1},
            ],
        }
        mgr = FlexibleFailureManager(config, 5, rng=None, publisher_ids={4})
        state = FlapState()
        stop, thread = mgr.start(_make_net(5), state, quiet=True)
        if thread:
            thread.join(timeout=3)
        down_calls = [c for c in mock_links.call_args_list if c[0][2] == "down"]
        assert len(down_calls) >= 2

    @patch("src.runtime.failure_manager.set_node_links_state")
    def test_manual_strategy_uses_target_list(self, mock_links):
        config = {
            "strategy": "manual",
            "cycles": [
                {"interval": 0.05, "duration": 0.05, "target": [2, 3]},
            ],
        }
        mgr = FlexibleFailureManager(config, 5, rng=None, publisher_ids=set())
        state = FlapState()
        stop, thread = mgr.start(_make_net(5), state, quiet=True)
        if thread:
            thread.join(timeout=3)
        down_hosts = set()
        for c in mock_links.call_args_list:
            if c[0][2] == "down":
                down_hosts.add(c[0][1])
        assert down_hosts == {"h2", "h3"}

    @patch("src.runtime.failure_manager.set_node_links_state")
    def test_random_strategy_uses_rng_sample(self, mock_links):
        rng = MagicMock()
        rng.sample.return_value = [2]
        config = {
            "strategy": "random",
            "cycles": [
                {"interval": 0.05, "duration": 0.05, "count": 1},
            ],
        }
        mgr = FlexibleFailureManager(config, 5, rng=rng, publisher_ids=set())
        state = FlapState()
        stop, thread = mgr.start(_make_net(5), state, quiet=True)
        if thread:
            thread.join(timeout=3)
        rng.sample.assert_called()

    def test_unknown_strategy_returns_noop(self):
        config = {"strategy": "bogus"}
        mgr = FlexibleFailureManager(config, 5, rng=None, publisher_ids=set())
        state = FlapState()
        stop, thread = mgr.start(MagicMock(), state)
        assert isinstance(stop, threading.Event)
        assert thread is None
