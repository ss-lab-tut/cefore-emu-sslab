"""Thread-safe container for host flap state."""

import threading


class FlapState:
    """Thread-safe container for host flap state.

    This class provides a safe way to share flap state between the main thread
    and the worker thread that performs periodic host flapping. Uses a lock
    to prevent race conditions when reading or updating state.

    Attributes:
        _lock: Threading lock for synchronization.
        _down_hosts: List of currently down host IDs.
        _last_down_host: ID of the most recently downed host.
    """

    def __init__(self):
        """Initialize empty flap state with lock."""
        self._lock = threading.Lock()
        self._down_hosts = []
        self._last_down_host = None

    def update(self, down_hosts, last_down=None):
        """Update state (called from worker thread).

        Args:
            down_hosts: Iterable of currently down host IDs.
            last_down: Optional ID of the most recently downed host.
        """
        with self._lock:
            self._down_hosts = sorted(down_hosts)
            if last_down is not None:
                self._last_down_host = last_down

    def snapshot(self):
        """Get current state snapshot (called from main thread).

        Returns:
            List of currently down host IDs (copy).
        """
        with self._lock:
            return list(self._down_hosts)

    def get(self, key, default=None):
        """Dict-like get method for backward compatibility.

        Args:
            key: Key to retrieve ('down_hosts' or 'last_down_host').
            default: Default value if key not found.

        Returns:
            Value for the key, or default.
        """
        with self._lock:
            if key == "down_hosts":
                return list(self._down_hosts)
            elif key == "last_down_host":
                return self._last_down_host
            return default

    @property
    def down_hosts(self):
        """Get current down hosts list.

        Returns:
            List of currently down host IDs (copy).
        """
        with self._lock:
            return list(self._down_hosts)

    @property
    def last_down_host(self):
        """Get last down host.

        Returns:
            ID of the most recently downed host, or None.
        """
        with self._lock:
            return self._last_down_host
