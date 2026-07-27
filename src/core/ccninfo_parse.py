"""Parse `ccninfo` stdout into a structured reply.

Fixture provenance: the grammar below is pinned against REAL captured
stdout+stderr from `/usr/local/bin/ccninfo`, Cefore 0.12.0, captured
2026-07-27 against this repo's disaster scenario (3-host mesh, k=1). See
tests/fixtures/ccninfo/README.md for the exact capture commands and the
NODE_NAME quirk (responder/route node tokens render as an IP when
NODE_NAME is unset, or as that name otherwise — both forms are opaque
strings to this parser).

Not covered — deliberately excluded from this slice:
- `-f` full-discovery mode. Cefore's default (hop-limited) discovery, which
  every fixture here uses, emits exactly one response + one route block per
  run. `-f` walks the full cache-holder graph and is expected to emit
  multiple blocks per run with a grammar this slice has not characterized
  against a real capture; wiring it in without real fixtures would mean
  guessing at a format instead of pinning it, so it is left for a future
  slice.
- Structured cache-column parsing. The `cache information:` block's entry
  lines (size/cobs/interests/start-end/cachetime/lifetime, tab- and
  space-padded in a way that isn't documented anywhere Cefore-side) are
  captured verbatim as `cache_lines` rather than field-split. Guessing at
  column boundaries now would bake in an assumption this slice has no
  fixture evidence for; a future slice can structure them once a caller
  actually needs individual fields instead of the raw line.

Why the tolerance contract is absolute (parse_ccninfo never raises, on any
str input, and degrades unparseable fields to None rather than guessing):
ccninfo's stdout format is not specified by RFC 9344 (which defines the
CCNInfo wire protocol, not any particular CLI's text rendering) and has
already been observed to vary with the client's NODE_NAME configuration.
It is exactly the kind of format that drifts silently across Cefore
versions. A parser that raises on an unrecognized line would turn a stdout
wording change into a crashed experiment run; degrading to
`reply_received=False` (or a None field) lets the caller treat "couldn't
parse a reply" the same as "no reply arrived" and keep the run going.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Literal prefixes that switch parsing mode. Matched with str.startswith()
# rather than a full-line equality/regex: the "cache information:" line
# in particular carries a variable column-header tail after the colon
# (see module docstring) that this parser has no reason to validate.
_ROUTE_HEADER_PREFIX = "route information:"
_CACHE_HEADER_PREFIX = "cache information:"
_RESPONSE_LINE_PREFIX = "response from "


@dataclass(frozen=True)
class CcninfoHop:
    """One entry from a `route information:` block.

    `node` is an opaque string — fixtures show both an IP form
    ('192.168.1.2') and a NODE_NAME form ('h1'); this parser does not
    interpret or validate it either way, it only extracts the token as
    ccninfo printed it.
    """

    index: int
    node: str
    delay_ms: float | None


@dataclass(frozen=True)
class CcninfoReply:
    """Structured result of one `ccninfo` invocation's stdout.

    `reply_received` is the single ground-truth signal for "did a reply
    line show up at all" — it is True iff a `response from` line was
    recognized, independent of whether its own fields (result/rtt_ms)
    parsed cleanly. Callers that only care about reachability should check
    this field alone rather than inferring it from `responder is not None`.
    """

    reply_received: bool
    responder: str | None
    result: str | None
    rtt_ms: float | None
    route: tuple[CcninfoHop, ...]
    cache_lines: tuple[str, ...]


def _parse_ms_value(text: str) -> float | None:
    """Parse a trailing '<float> ms' value; degrade to None on any mismatch.

    Covers both a genuinely corrupt number ('notanumber ms') and a stream
    truncated before the ' ms' suffix was ever written (see
    test_truncated_route_block_mid_line) — both are "delay unknown", not a
    crash.
    """
    text = text.strip()
    if not text.endswith("ms"):
        return None
    number = text[: -len("ms")].strip()
    try:
        val = float(number)
    except ValueError:
        return None
    # Reject non-finite results (nan, inf) — "time=nan ms" or "inf ms"
    # should degrade to None (delay unknown), not propagate a sentinel.
    if not math.isfinite(val):
        return None
    return val


def _try_parse_route_line(line: str) -> CcninfoHop | None:
    """Parse one ' <idx> <node>: <delay> ms' route-block entry line.

    Returns None if the line doesn't even have the minimal '<idx> <node>:'
    shape — the caller treats that as an unknown/ignored line per the
    tolerance contract, not a fatal error for the whole route block.
    """
    parts = line.strip().split(None, 1)
    if len(parts) < 2:
        return None
    idx_str, remainder = parts
    # str.isdigit() + isascii() filters most non-integer input, but
    # CPython's int-conversion digit limit (4300 digits, Python 3.11+)
    # can still raise ValueError on absurd digit runs. The try/except
    # below handles that edge case per the never-raises contract.
    if not (idx_str.isascii() and idx_str.isdigit()):
        return None
    if ":" not in remainder:
        return None
    node, _, rest = remainder.partition(":")
    node = node.strip()
    if not node:
        return None
    try:
        index = int(idx_str)
    except ValueError:
        return None
    return CcninfoHop(index=index, node=node, delay_ms=_parse_ms_value(rest))


def _split_response_rest(rest: str) -> tuple[str | None, float | None]:
    """Split the '<RESULT>, time=<float> ms' tail of a response line.

    Once a line has already matched the 'response from <responder>:'
    shape (see _try_parse_response_line), this always returns a result
    (falling back to the raw rest text if the ', time=... ms' suffix is
    missing/garbled) — reply_received is already decided by that point, so
    this function's only job is to degrade result/rtt_ms independently,
    never to re-decide whether a reply was received.
    """
    if "," in rest:
        result_part, _, time_part = rest.partition(",")
    else:
        result_part, time_part = rest, ""
    result = result_part.strip() or None

    rtt_ms = None
    time_part = time_part.strip()
    if time_part.startswith("time=") and time_part.endswith("ms"):
        time_str = time_part[len("time=") : -len("ms")].strip()
        try:
            val = float(time_str)
        except ValueError:
            val = None
        # Reject non-finite rtt (nan, inf) — degrade to None.
        if val is not None and not math.isfinite(val):
            val = None
        rtt_ms = val
    return result, rtt_ms


def _try_parse_response_line(line: str) -> tuple[str, str | None, float | None] | None:
    """Parse a 'response from <responder>: <RESULT>, time=<float> ms' line.

    Returns None only when the line doesn't even have the minimal
    'response from <responder>:' shape — that's the sole condition under
    which the caller should treat no reply as received. Once the shape IS
    recognized, this never returns None; RESULT/time degrade to None
    individually via _split_response_rest instead.
    """
    if not line.startswith(_RESPONSE_LINE_PREFIX):
        return None
    remainder = line[len(_RESPONSE_LINE_PREFIX) :]
    if ":" not in remainder:
        return None
    responder, _, rest = remainder.partition(":")
    responder = responder.strip()
    if not responder:
        return None
    result, rtt_ms = _split_response_rest(rest.strip())
    return responder, result, rtt_ms


def parse_ccninfo(text: str) -> CcninfoReply:
    """Parse `ccninfo` stdout (+ any interleaved stderr/trailer text) into a
    CcninfoReply. Never raises — see module docstring for why.

    Implemented as a single-pass line-by-line state machine rather than
    block-boundary regexes: ccninfo's grammar is "header, blank line,
    optional response line, blank line, optional route block, blank line,
    optional cache block" but real captures interleave unrelated lines
    (the header itself, and the capture script's own EXIT=/ELAPSED_MS=
    trailer) that carry no field in this API and must simply be skipped
    without disturbing block recognition around them.

    Mode transitions:
    - DEFAULT (start state): recognizes 'response from ...', or a
      'route information:'/'cache information:' header that switches mode.
      Anything else (the request header line, EXIT=... trailer, usage/
      error text) is an unknown line and is ignored.
    - ROUTE: a blank line ends the block (back to DEFAULT). A line matching
      the route-entry shape becomes a CcninfoHop; anything else is ignored
      but does NOT end the block, so a stray unknown line inside the route
      section doesn't truncate the hops after it.
    - CACHE: a blank line ends the block. Every other line is captured
      verbatim into cache_lines with no filtering at all — per the plan,
      these are raw, un-structure-parsed entries (see module docstring).
    """
    # 2026-07-27 tolerance-contract robustness: a str-typed caller should
    # never pass None, but `text or ""` costs one line and makes an
    # accidental None a no-op empty parse instead of an AttributeError on
    # the first .splitlines() call, matching parse_ccninfo's "never raises"
    # contract at essentially zero cost.
    text = text or ""

    reply_received = False
    responder: str | None = None
    result: str | None = None
    rtt_ms: float | None = None
    route: list[CcninfoHop] = []
    cache_lines: list[str] = []

    mode = "default"  # "default" | "route" | "cache"

    for line in text.splitlines():
        if mode == "route":
            if line.strip() == "":
                mode = "default"
                continue
            hop = _try_parse_route_line(line)
            if hop is not None:
                route.append(hop)
            continue  # unrecognized line inside the block: ignored, stay in "route"

        if mode == "cache":
            if line.strip() == "":
                mode = "default"
                continue
            cache_lines.append(line)
            continue  # raw capture: every non-blank line, no filtering

        # mode == "default"
        if line.strip() == "":
            continue
        if line.startswith(_ROUTE_HEADER_PREFIX):
            mode = "route"
            continue
        if line.startswith(_CACHE_HEADER_PREFIX):
            mode = "cache"
            continue
        parsed_response = _try_parse_response_line(line)
        if parsed_response is not None:
            reply_received = True
            responder, result, rtt_ms = parsed_response
            continue
        # Unknown line (request header, EXIT=... trailer, [ccninfo] ERROR/
        # usage text, ...): ignored per the tolerance contract.

    return CcninfoReply(
        reply_received=reply_received,
        responder=responder,
        result=result,
        rtt_ms=rtt_ms,
        route=tuple(route),
        cache_lines=tuple(cache_lines),
    )
