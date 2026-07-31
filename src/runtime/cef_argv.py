"""Pure argv builders for cefore content commands.

These functions only assemble argv lists; they never execute anything, never
add shell redirection, and never apply ``shlex.quote``. The CommandRunner seam
owns execution and output redirection (see ``command_runner.py``), so an argv
element is always the raw, unquoted value. Keeping construction pure lets the
flag-mapping be unit-tested without a network.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple


def _build_argv(
    command: str,
    head: Sequence[str],
    opts: Sequence[Tuple[str, object]],
    node_name: str,
) -> List[str]:
    """Assemble a cefore argv from its parts.

    ``head`` holds the command and its mandatory/positional args, already
    ordered. ``opts`` is a sequence of ``(flag, value)`` pairs for value-taking
    options: each pair is appended as ``[flag, str(value)]`` only when
    ``value is not None`` — mirroring the explicit ``if x is not None`` idiom
    the builders used, so output stays byte-exact for every value (including
    ``0``). Bare boolean flags (e.g. ``-o``) are intentionally not handled here;
    the caller puts them in ``head`` to preserve their original truthiness.
    The trailing ``-d ./<node_name>`` is always appended last.
    """
    argv: List[str] = [command, *head]
    for flag, value in opts:
        if value is not None:
            argv += [flag, str(value)]
    argv += ["-d", f"./{node_name}"]
    return argv


def build_cefputfile_argv(
    uri: str,
    file_path: str = "./sample-putfile",
    *,
    node_name: str,
    rate: Optional[float] = None,
    block_size: Optional[int] = None,
    expiry: Optional[float] = None,
    cache_time: Optional[float] = None,
    valid_algo: Optional[str] = None,
    port_num: Optional[int] = None,
) -> List[str]:
    """Build the argv for ``cefputfile``."""
    return _build_argv(
        "cefputfile",
        [uri, "-f", file_path],
        [
            ("-r", rate),
            ("-b", block_size),
            ("-e", expiry),
            ("-t", cache_time),
            ("-v", valid_algo),
            ("-p", port_num),
        ],
        node_name,
    )


def build_cefgetfile_argv(
    uri: str,
    output_path: str,
    *,
    node_name: str,
    owner_only: bool = False,
    chunk: Optional[int] = None,
    pipeline: Optional[int] = None,
    valid_algo: Optional[str] = None,
    port_num: Optional[int] = None,
    sg: bool = False,
) -> List[str]:
    """Build the argv for ``cefgetfile``."""
    head = [uri, "-f", output_path]
    if owner_only:
        head.append("-o")
    return _build_argv(
        "cefgetfile",
        head,
        [
            ("-m", chunk),
            ("-s", pipeline),
            ("-v", valid_algo),
            ("-p", port_num),
            ("-z", "sg" if sg else None),
        ],
        node_name,
    )


def build_cefsubfile_argv(
    uri: str,
    *,
    node_name: str,
    output_path: Optional[str] = None,
    pipeline: Optional[int] = None,
    ri_valid_algo: Optional[str] = None,
    td_valid_algo: Optional[str] = None,
    port_num: Optional[int] = None,
) -> List[str]:
    """Build the argv for ``cefsubfile``."""
    return _build_argv(
        "cefsubfile",
        [uri],
        [
            ("-f", output_path),
            ("-s", pipeline),
            ("-v_RI", ri_valid_algo),
            ("-v_TD", td_valid_algo),
            ("-p", port_num),
        ],
        node_name,
    )


def build_ccninfo_argv(
    uri: str,
    *,
    node_name: str,
    cache_info: bool = False,
    owner_only: bool = False,
    hop_count: Optional[int] = None,
    skip_hop: Optional[int] = None,
    valid_algo: Optional[str] = None,
    port_num: Optional[int] = None,
) -> List[str]:
    """Build the argv for ``ccninfo`` (network cache/path discovery).

    This builder is intentionally a pure passthrough: it does not validate
    ``hop_count``/``skip_hop`` against the real binary's constraints even
    though the binary is picky about them:
      - an explicit ``-s`` rejects the value 0 (0 is the *default* when ``-s``
        is omitted, but passing "-s 0" on the command line is itself rejected);
      - ``-s`` (skip_hop) must be strictly less than ``-r`` (hop_count) when
        both are given;
      - on any argument error the binary prints a usage message and exits 0,
        not a nonzero code, so a caller cannot detect a bad invocation from
        the exit status alone.
    Why not validate here: the config validator (upstream of this call) is
    the single place that owns "is this ccninfo invocation well-formed";
    duplicating that logic in the builder would let the two drift apart
    silently. The builder's only job is byte-exact argv assembly.

    Args:
        uri: Content name prefix to query.
        node_name: Cefore node directory name (e.g. "h0"); becomes the
            ``-d ./<node_name>`` config-dir argument.
        cache_info: If True, add the bare ``-c`` flag (request cache
            information/RTT from the content forwarder).
        owner_only: If True, add the bare ``-o`` flag (owner-only query).
        hop_count: Max number of routers to trace (``-r``). The builder
            passes 0 through verbatim, but the validator (and the real
            binary) reject explicit 0 — only the implicit default when
            ``-r`` is omitted is valid as 0.
        skip_hop: Number of upstream routers to skip (``-s``). Same
            0-vs-omitted distinction as ``hop_count``.
        valid_algo: Validation algorithm (crc32c or rsa-sha256).
        port_num: Port number. Note: ``-p`` is ineffective in Cefore 0.12.0
            due to the client parse-order bug (cef_client_init reads
            cefnetd.conf before ``-p`` is parsed — same upstream Bug1 that
            affects all cef_client tools). Kept in the pure builder for
            argv completeness; callers should NOT pass it (the config
            validator rejects ``port_num`` on ccninfo events and monitor
            targets).
    """
    head = []
    # Bare flags belong in head (not opts) so their truthiness maps directly
    # to presence/absence, mirroring cefgetfile's "-o" handling; cache_info is
    # checked before owner_only to keep -c ahead of -o, matching cefinfo's own
    # documented option order.
    if cache_info:
        head.append("-c")
    if owner_only:
        head.append("-o")
    return _build_argv(
        "ccninfo",
        [uri, *head],
        [
            ("-r", hop_count),
            ("-s", skip_hop),
            ("-v", valid_algo),
            ("-p", port_num),
        ],
        node_name,
    )


def build_cefpubfile_argv(
    uri: str,
    file_path: str,
    *,
    node_name: str,
    rate: Optional[float] = None,
    block_size: Optional[int] = None,
    expiry: Optional[float] = None,
    cache_time: Optional[float] = None,
    lifetime: Optional[float] = None,
    retry_limit: Optional[int] = None,
    target: Optional[str] = None,
    ti_valid_algo: Optional[str] = None,
    rd_valid_algo: Optional[str] = None,
    port_num: Optional[int] = None,
) -> List[str]:
    """Build the argv for ``cefpubfile``."""
    return _build_argv(
        "cefpubfile",
        [uri, "-f", file_path],
        [
            ("-r", rate),
            ("-b", block_size),
            ("-e", expiry),
            ("-t", cache_time),
            ("-l", lifetime),
            ("-m", retry_limit),
            ("-z", target),
            ("-v_TI", ti_valid_algo),
            ("-v_RD", rd_valid_algo),
            ("-p", port_num),
        ],
        node_name,
    )
