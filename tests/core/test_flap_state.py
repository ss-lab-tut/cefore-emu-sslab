"""Tests for src.core.flap_state."""

import threading

from src.core.flap_state import FlapState


def test_initial_state_empty():
    fs = FlapState()
    assert fs.snapshot() == []
    assert fs.last_down_host is None


def test_update_and_snapshot():
    fs = FlapState()
    fs.update([3, 1, 2])
    assert fs.snapshot() == [1, 2, 3]


def test_last_down_host_property():
    fs = FlapState()
    fs.update([1, 2], last_down=2)
    assert fs.last_down_host == 2


def test_get_dict_api():
    fs = FlapState()
    fs.update([5, 3], last_down=5)
    assert fs.get("down_hosts") == [3, 5]
    assert fs.get("last_down_host") == 5


def test_get_unknown_key_default():
    fs = FlapState()
    assert fs.get("unknown") is None
    assert fs.get("unknown", "fallback") == "fallback"


def test_update_last_down_none_preserves_previous():
    """update(last_down=None) should NOT reset last_down_host."""
    fs = FlapState()
    fs.update([1], last_down=1)
    assert fs.last_down_host == 1
    fs.update([2], last_down=None)
    assert fs.last_down_host == 1


def test_thread_safety():
    fs = FlapState()
    barrier = threading.Barrier(10)
    errors = []

    def worker(idx):
        try:
            barrier.wait()
            fs.update([idx], last_down=idx)
            _ = fs.snapshot()
            _ = fs.down_hosts
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    snap = fs.snapshot()
    assert len(snap) == 1
    assert isinstance(snap[0], int)
