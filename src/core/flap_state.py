"""Thread-safe container for host flap state."""

import threading


class FlapState:
    """Thread-safe container for host flap state.

    Provides a safe way to share flap state between the main thread
    and the worker thread that performs periodic host flapping.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._down_hosts = []
        self._last_down_host = None

    def update(self, down_hosts, last_down=None):
        """Update state (called from worker thread)."""
        with self._lock:
            self._down_hosts = sorted(down_hosts)
            if last_down is not None:
                self._last_down_host = last_down

    def snapshot(self):
        """Get current state snapshot (called from main thread)."""
        with self._lock:
            return list(self._down_hosts)

    def get(self, key, default=None):
        """Dict-like get method for backward compatibility."""
        with self._lock:
            if key == "down_hosts":
                return list(self._down_hosts)
            elif key == "last_down_host":
                return self._last_down_host
            return default

    @property
    def down_hosts(self):
        with self._lock:
            return list(self._down_hosts)

    @property
    def last_down_host(self):
        with self._lock:
            return self._last_down_host
