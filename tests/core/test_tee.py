"""Behavior tests for src.core.tee.Tee (multi-stream fan-out writer).

Tee is used to duplicate stdout/stderr to a log file while still behaving
like a normal file object (fileno/isatty/encoding) for callers that probe
the stream before writing to it (e.g. subprocess redirection, readline).
Real files opened under tmp_path are used as the underlying streams so
fileno/isatty/encoding are exercised against real OS-backed behavior
instead of stubs.
"""

from src.core.tee import Tee


class TestTee:
    def test_write_fans_out_to_all_streams_and_flushes(self, tmp_path):
        path_a = tmp_path / "a.log"
        path_b = tmp_path / "b.log"
        with open(path_a, "w") as stream_a, open(path_b, "w") as stream_b:
            tee = Tee(stream_a, stream_b)
            written = tee.write("hello")
            # write() must flush internally so a reader of the file sees the
            # data immediately, without waiting for the writer to close.
            assert path_a.read_text() == "hello"
            assert path_b.read_text() == "hello"
            assert written == len("hello")

    def test_flush_delegates_to_every_stream(self, tmp_path):
        path_a = tmp_path / "a.log"
        path_b = tmp_path / "b.log"
        with open(path_a, "w") as stream_a, open(path_b, "w") as stream_b:
            tee = Tee(stream_a, stream_b)
            tee.write("data")
            tee.flush()
            assert path_a.read_text() == "data"
            assert path_b.read_text() == "data"

    def test_fileno_returns_first_stream_fileno(self, tmp_path):
        path_a = tmp_path / "a.log"
        path_b = tmp_path / "b.log"
        with open(path_a, "w") as stream_a, open(path_b, "w") as stream_b:
            tee = Tee(stream_a, stream_b)
            assert tee.fileno() == stream_a.fileno()

    def test_isatty_returns_first_stream_isatty(self, tmp_path):
        path_a = tmp_path / "a.log"
        path_b = tmp_path / "b.log"
        with open(path_a, "w") as stream_a, open(path_b, "w") as stream_b:
            tee = Tee(stream_a, stream_b)
            # A plain file is never a tty; this proves the call is delegated
            # to streams[0] rather than hardcoded to True/False.
            assert tee.isatty() == stream_a.isatty()
            assert tee.isatty() is False

    def test_encoding_returns_first_stream_encoding(self, tmp_path):
        path_a = tmp_path / "a.log"
        path_b = tmp_path / "b.log"
        with open(path_a, "w") as stream_a, open(path_b, "w") as stream_b:
            tee = Tee(stream_a, stream_b)
            assert tee.encoding == stream_a.encoding
