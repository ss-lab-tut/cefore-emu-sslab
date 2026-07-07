"""Shared fixtures for cefore-emu tests."""

import pytest


@pytest.fixture
def triangle_graph():
    """3-node triangle: every node connected to every other."""
    return {0: {1, 2}, 1: {0, 2}, 2: {0, 1}}


@pytest.fixture
def linear_graph():
    """5-node chain: 0-1-2-3-4."""
    return {0: {1}, 1: {0, 2}, 2: {1, 3}, 3: {2, 4}, 4: {3}}


@pytest.fixture
def diamond_graph():
    """4-node diamond: 0→1→3, 0→2→3 (two paths from 0 to 3)."""
    return {0: {1, 2}, 1: {0, 3}, 2: {0, 3}, 3: {1, 2}}


@pytest.fixture
def disconnected_graph():
    """Two disconnected components: {0,1} and {2,3}."""
    return {0: {1}, 1: {0}, 2: {3}, 3: {2}}


@pytest.fixture
def sample_mesh_links():
    """Mesh links for FIB tests (triangle: 0-1-2)."""
    return [
        {"host_a": 0, "host_b": 1, "subnet": 0},
        {"host_a": 1, "host_b": 2, "subnet": 1},
        {"host_a": 0, "host_b": 2, "subnet": 2},
    ]


@pytest.fixture
def sample_putfile_log():
    """Realistic cefputfile log text."""
    return (
        "2024-01-15 10:30:45.123456 [cefputfile] Start\n"
        "[cefputfile] URI = ccnx:/test/example1\n"
        "[cefputfile] File = ./sample-putfile\n"
        "[cefputfile] Rate = 10 Mbps\n"
        "[cefputfile] Block Size = 1024 Bytes\n"
        "[cefputfile] Cache Time = 3000 sec\n"
        "[cefputfile] Expiration = 5000 sec\n"
        "[cefputfile] Tx Frames = 100\n"
        "[cefputfile] Tx Bytes = 51200 Bytes\n"
        "[cefputfile] Duration = 5.123 sec\n"
        "[cefputfile] Throughput = 80000 bps\n"
    )


@pytest.fixture
def sample_getfile_log():
    """Realistic cefgetfile log text for a completed retrieval."""
    return (
        "2024-01-15 10:31:00.654321 [cefgetfile] Start\n"
        "[cefgetfile] URI = ccnx:/test/example1\n"
        "Completed to get all the chunks.\n"
        "[cefgetfile] Rx Frames (All) = 120\n"
        "[cefgetfile] Rx Frames (ContentObject) = 100\n"
        "[cefgetfile] Rx Bytes (All) = 61440 Bytes\n"
        "[cefgetfile] Rx Bytes (ContentObject) = 51200 Bytes\n"
        "[cefgetfile] Duration = 4.567 sec\n"
        "[cefgetfile] Throughput = 90000 bps\n"
        "[cefgetfile] Goodput = 85000 bps\n"
        "[cefgetfile] Jitter (Ave) = 150 us\n"
        "[cefgetfile] Jitter (Max) = 500 us\n"
        "[cefgetfile] Jitter (Var) = 75 us\n"
    )
