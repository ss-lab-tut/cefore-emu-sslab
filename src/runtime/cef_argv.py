"""Pure argv builders for cefore content commands.

These functions only assemble argv lists; they never execute anything, never
add shell redirection, and never apply ``shlex.quote``. The CommandRunner seam
owns execution and output redirection (see ``command_runner.py``), so an argv
element is always the raw, unquoted value. Keeping construction pure lets the
flag-mapping be unit-tested without a network.
"""

from __future__ import annotations

from typing import List, Optional


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
    argv = ["cefputfile", uri, "-f", file_path]
    if rate is not None:
        argv += ["-r", str(rate)]
    if block_size is not None:
        argv += ["-b", str(block_size)]
    if expiry is not None:
        argv += ["-e", str(expiry)]
    if cache_time is not None:
        argv += ["-t", str(cache_time)]
    if valid_algo is not None:
        argv += ["-v", valid_algo]
    if port_num is not None:
        argv += ["-p", str(port_num)]
    argv += ["-d", f"./{node_name}"]
    return argv


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
    argv = ["cefgetfile", uri, "-f", output_path]
    if owner_only:
        argv += ["-o"]
    if chunk is not None:
        argv += ["-m", str(chunk)]
    if pipeline is not None:
        argv += ["-s", str(pipeline)]
    if valid_algo is not None:
        argv += ["-v", valid_algo]
    if port_num is not None:
        argv += ["-p", str(port_num)]
    if sg is not None:
        argv += ["-z", str(sg)]
    argv += ["-d", f"./{node_name}"]
    return argv


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
    argv = ["cefsubfile", uri]
    if output_path is not None:
        argv += ["-f", output_path]
    if pipeline is not None:
        argv += ["-s", str(pipeline)]
    if ri_valid_algo is not None:
        argv += ["-v_RI", ri_valid_algo]
    if td_valid_algo is not None:
        argv += ["-v_TD", td_valid_algo]
    if port_num is not None:
        argv += ["-p", str(port_num)]
    argv += ["-d", f"./{node_name}"]
    return argv


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
    argv = ["cefpubfile", uri, "-f", file_path]
    if rate is not None:
        argv += ["-r", str(rate)]
    if block_size is not None:
        argv += ["-b", str(block_size)]
    if expiry is not None:
        argv += ["-e", str(expiry)]
    if cache_time is not None:
        argv += ["-t", str(cache_time)]
    if lifetime is not None:
        argv += ["-l", str(lifetime)]
    if retry_limit is not None:
        argv += ["-m", str(retry_limit)]
    if target is not None:
        argv += ["-z", target]
    if ti_valid_algo is not None:
        argv += ["-v_TI", ti_valid_algo]
    if rd_valid_algo is not None:
        argv += ["-v_RD", rd_valid_algo]
    if port_num is not None:
        argv += ["-p", str(port_num)]
    argv += ["-d", f"./{node_name}"]
    return argv
