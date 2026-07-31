"""Contract tests for the ccninfo stdout parser (src/core/ccninfo_parse.py).

Two evidence sources, per the tracer-bullet plan:

1. REAL captured fixtures under tests/fixtures/ccninfo/ (see that directory's
   README.md for provenance: real-machine ccninfo 0.12.0 stdout+stderr,
   captured 2026-07-27 against the disaster scenario's 3-host mesh). These
   pin the parser against the actual grammar Cefore emits, not a guess at it.
2. Synthetic strings for cases the fixture set cannot exercise directly
   (multi-hop routes, corrupted numeric fields, mid-write truncation,
   interleaved unknown lines) — the tolerance contract's edges.

The absolute invariant under test everywhere here: parse_ccninfo() must
never raise, for any str input, and must degrade unparseable fields to None
rather than guess at them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.ccninfo_parse import CcninfoHop, CcninfoReply, parse_ccninfo

# Fixture directory lives at <repo root>/tests/fixtures/ccninfo/. This test
# file is at <repo root>/tests/core/test_ccninfo_parse.py, so parents[2] from
# __file__ is the repo root — same resolution pattern used by
# tests/runtime/test_command_seam_guard.py and
# tests/synthetic/test_external_bridge_synthetic.py.
FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "ccninfo"


def _load_fixture(name: str) -> str:
    """Read a captured ccninfo fixture file verbatim (no stripping) — the
    parser must handle exactly the bytes a real capture script produced,
    trailing EXIT=/ELAPSED_MS= metadata line included."""
    return (FIXTURES_DIR / name).read_text()


# ---------------------------------------------------------------------------
# Fixture-driven: real captured ccninfo output
# ---------------------------------------------------------------------------


class TestRealFixtures:
    def test_reply_basic(self):
        """IP-form responder/node, one route hop, no cache block."""
        reply = parse_ccninfo(_load_fixture("reply_basic.out"))
        assert reply.reply_received is True
        assert reply.responder == "192.168.1.2"
        assert reply.result == "NO_ERROR"
        assert reply.rtt_ms == pytest.approx(3.456)
        assert len(reply.route) == 1
        assert reply.route[0] == CcninfoHop(
            index=1, node="192.168.1.2", delay_ms=pytest.approx(3.342)
        )
        assert reply.cache_lines == ()

    def test_reply_cache_info(self):
        """-c adds a cache block; its column-header line must NOT become a
        cache_line, only the numbered entry line(s) that follow it."""
        reply = parse_ccninfo(_load_fixture("reply_cache_info.out"))
        assert reply.reply_received is True
        assert len(reply.route) == 1
        assert len(reply.cache_lines) == 1
        # Pins the "header line itself is excluded" rule explicitly — an
        # off-by-one that captured the header too would still pass a bare
        # len()==1 check if it dropped the real entry instead, so check
        # content, not just count.
        assert "cache information:" not in reply.cache_lines[0]
        assert reply.cache_lines[0].startswith(" 1 c ")
        assert "423 KB" in reply.cache_lines[0]
        # "verbatim" (v1 does not structure-parse the cache columns) means
        # the tab column separator survives too, not just the visible text.
        assert "\t" in reply.cache_lines[0]

    def test_reply_named_cache(self):
        """NODE_NAME configured -> responder/node render as a name ('h1'),
        not an IP. Node tokens are opaque strings; both forms must parse."""
        reply = parse_ccninfo(_load_fixture("reply_named_cache.out"))
        assert reply.reply_received is True
        assert reply.responder == "h1"
        assert len(reply.route) == 1
        assert reply.route[0].node == "h1"
        assert len(reply.cache_lines) == 1

    def test_reply_multihop(self):
        """Real 2-hop capture (h0 -> h2, originator CS_MODE=0 to dodge the
        cefnetd_external_cache_seek pkt_len byte-order bug — see
        tests/fixtures/ccninfo/README.md). Pins that a real route block with
        multiple entries preserves hop order and per-hop delays."""
        reply = parse_ccninfo(_load_fixture("reply_multihop.out"))
        assert reply.reply_received is True
        assert reply.responder == "h2"
        assert reply.result == "NO_ERROR"
        assert [(h.index, h.node) for h in reply.route] == [(1, "h0"), (2, "h2")]
        assert reply.route[0].delay_ms == 0.397
        assert reply.route[1].delay_ms == 0.519
        assert reply.cache_lines == ()

    def test_no_reply_timeout(self):
        """Header-only capture (request timed out) -> no response/route/cache
        block ever appeared; the header line itself carries no field in the
        frozen API and must be ignored like any unknown line."""
        reply = parse_ccninfo(_load_fixture("no_reply_timeout.out"))
        assert reply == CcninfoReply(
            reply_received=False,
            responder=None,
            result=None,
            rtt_ms=None,
            route=(),
            cache_lines=(),
        )

    def test_s0_rejected(self):
        """[ccninfo] ERROR: ... + usage text, exit 0, no reply — must not
        crash and must not be mistaken for a reply."""
        reply = parse_ccninfo(_load_fixture("s0_rejected.out"))
        assert reply.reply_received is False
        assert reply.route == ()
        assert reply.cache_lines == ()

    def test_skip_ge_hop(self):
        """Same usage-rejection shape as s0_rejected, different message."""
        reply = parse_ccninfo(_load_fixture("skip_ge_hop.out"))
        assert reply.reply_received is False
        assert reply.route == ()
        assert reply.cache_lines == ()


# ---------------------------------------------------------------------------
# Synthetic: tolerance-contract edges the real fixtures can't exercise
# ---------------------------------------------------------------------------


class TestToleranceContract:
    def test_empty_string(self):
        assert parse_ccninfo("") == CcninfoReply(
            reply_received=False,
            responder=None,
            result=None,
            rtt_ms=None,
            route=(),
            cache_lines=(),
        )

    def test_pure_garbage(self):
        """No known line shape at all — every line is ignored, no crash."""
        garbage = "asdkjh asdkjh\n!!!! #### ????\n\t\t\n"
        assert parse_ccninfo(garbage) == CcninfoReply(
            reply_received=False,
            responder=None,
            result=None,
            rtt_ms=None,
            route=(),
            cache_lines=(),
        )

    def test_header_only(self):
        """A header line with no blank-line terminator and nothing after it
        — must still parse cleanly to an unreceived reply."""
        header = (
            "ccninfo to ccnx:/no/such/prefix with HopLimit=32, "
            "SkipHopCount=0, Flag=0x0000, Request ID=59853 and "
            "node ID=192.168.2.1"
        )
        reply = parse_ccninfo(header)
        assert reply.reply_received is False
        assert reply.route == ()
        assert reply.cache_lines == ()

    def test_multi_hop_route_order_preserved(self):
        """2+ synthetic route lines in the observed grammar — tuple order
        must match file order (not e.g. sorted by index)."""
        text = "route information:\n 1 h1: 1.1 ms\n 2 h2: 2.2 ms\n 3 h3: 3.3 ms\n"
        reply = parse_ccninfo(text)
        assert tuple(hop.node for hop in reply.route) == ("h1", "h2", "h3")
        assert tuple(hop.index for hop in reply.route) == (1, 2, 3)
        assert reply.route[0].delay_ms == pytest.approx(1.1)
        assert reply.route[1].delay_ms == pytest.approx(2.2)
        assert reply.route[2].delay_ms == pytest.approx(3.3)

    def test_route_line_corrupt_delay_degrades_to_none(self):
        """Delay text present but not a float -> delay_ms None, index+node
        still kept (never drop the whole hop over one bad field)."""
        text = "route information:\n 1 h1: notanumber ms\n"
        reply = parse_ccninfo(text)
        assert len(reply.route) == 1
        assert reply.route[0] == CcninfoHop(index=1, node="h1", delay_ms=None)

    def test_truncated_route_block_mid_line(self):
        """Simulates a capture stream cut off before the trailing ' ms' of
        the last line was flushed (e.g. process killed mid-write). The
        completed hop before it must still parse; the truncated hop keeps
        its index+node with delay_ms degraded to None — not dropped
        entirely, and no exception."""
        text = (
            "response from h1: NO_ERROR, time=1.0 ms\n"
            "\n"
            "route information:\n"
            " 1 h1: 1.0 ms\n"
            " 2 h2: 4.1"  # no trailing " ms" — mid-write cutoff
        )
        reply = parse_ccninfo(text)
        assert reply.reply_received is True
        assert len(reply.route) == 2
        assert reply.route[0] == CcninfoHop(
            index=1, node="h1", delay_ms=pytest.approx(1.0)
        )
        assert reply.route[1] == CcninfoHop(index=2, node="h2", delay_ms=None)

    def test_response_line_corrupt_time_degrades_to_none(self):
        """rtt_ms degrades to None on a corrupt time value, but the line was
        still recognized as a response -> reply_received stays True and
        responder/result are still captured."""
        reply = parse_ccninfo("response from h1: NO_ERROR, time=abc ms\n")
        assert reply.reply_received is True
        assert reply.responder == "h1"
        assert reply.result == "NO_ERROR"
        assert reply.rtt_ms is None

    def test_nan_rtt_degrades_to_none(self):
        """Non-finite rtt_ms (nan) must degrade to None, not propagate."""
        reply = parse_ccninfo("response from h1: NO_ERROR, time=nan ms\n")
        assert reply.reply_received is True
        assert reply.responder == "h1"
        assert reply.rtt_ms is None

    def test_inf_delay_degrades_to_none(self):
        """Non-finite route delay (inf) must degrade to None."""
        text = "route information:\n 1 h1: inf ms\n"
        reply = parse_ccninfo(text)
        assert len(reply.route) == 1
        assert reply.route[0].delay_ms is None

    def test_5000_digit_hop_index_degrades_to_none(self):
        """CPython int-conversion digit limit (4300 digits) must not raise;
        the hop should be silently dropped (None from _try_parse_route_line)."""
        huge = "9" * 5000
        text = f"route information:\n {huge} h1: 1.0 ms\n"
        reply = parse_ccninfo(text)
        # The absurd-index line is dropped; no crash.
        assert reply.route == ()

    def test_interleaved_unknown_lines_everywhere(self):
        """Unknown lines scattered before, between, and inside every block
        must not break parsing of the surrounding valid content. Garbage
        lines here are deliberately NOT route-entry-shaped ('<digits>
        <token>:' would legitimately parse as an opaque-token hop) and kept
        outside the (nonexistent) cache block, whose raw-capture rule would
        otherwise swallow them as fake cache_lines."""
        text = (
            "some noise before anything else\n"
            "ccninfo to ccnx:/x with HopLimit=32, SkipHopCount=0, "
            "Flag=0x0000, Request ID=1 and node ID=h1\n"
            "!!! random junk !!!\n"
            "\n"
            "response from h1: NO_ERROR, time=2.0 ms\n"
            "another random line with no recognized shape\n"
            "\n"
            "route information:\n"
            "*** not a route line ***\n"
            " 1 h1: 1.0 ms\n"
            "trailing junk without colon or digits\n"
            " 2 h2: 2.0 ms\n"
            "\n"
            "EXIT=0 ELAPSED_MS=10\n"
        )
        reply = parse_ccninfo(text)
        assert reply.reply_received is True
        assert reply.responder == "h1"
        assert reply.rtt_ms == pytest.approx(2.0)
        assert tuple(hop.node for hop in reply.route) == ("h1", "h2")
