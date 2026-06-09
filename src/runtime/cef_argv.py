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
    sg: Optional[int] = None,
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
            ("-z", sg),
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
