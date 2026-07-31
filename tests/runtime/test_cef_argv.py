"""Unit tests for pure cefore argv builders.

These guard the two invariants the CommandRunner seam relies on: argv elements
carry no shell redirection (``>``/``2>&1``) and no ``shlex.quote`` artifacts
(values are raw, even with shell-special characters).
"""

from src.runtime.cef_argv import (
    build_ccninfo_argv,
    build_cefgetfile_argv,
    build_cefpubfile_argv,
    build_cefputfile_argv,
    build_cefsubfile_argv,
)


def _assert_no_shell_artifacts(argv):
    assert isinstance(argv, list)
    for el in argv:
        assert isinstance(el, str)
        assert ">" not in el
        assert "2>&1" not in el
        # shlex.quote would wrap shell-special values in single quotes.
        assert not (el.startswith("'") and el.endswith("'") and len(el) > 1)


# ---------------------------------------------------------------------------
# cefputfile
# ---------------------------------------------------------------------------


class TestPutfileArgv:
    def test_minimal(self):
        argv = build_cefputfile_argv("ccnx:/x", node_name="h2")
        assert argv == [
            "cefputfile", "ccnx:/x", "-f", "./sample-putfile", "-d", "./h2"
        ]

    def test_all_flags(self):
        argv = build_cefputfile_argv(
            "ccnx:/x",
            "/data/in.bin",
            node_name="h2",
            rate=10,
            block_size=1024,
            expiry=5000,
            cache_time=3000,
            valid_algo="crc32c",
            port_num=9999,
        )
        assert argv[:4] == ["cefputfile", "ccnx:/x", "-f", "/data/in.bin"]
        assert "-r" in argv and argv[argv.index("-r") + 1] == "10"
        assert argv[argv.index("-b") + 1] == "1024"
        assert argv[argv.index("-e") + 1] == "5000"
        assert argv[argv.index("-t") + 1] == "3000"
        assert argv[argv.index("-v") + 1] == "crc32c"
        assert argv[argv.index("-p") + 1] == "9999"
        assert argv[-2:] == ["-d", "./h2"]
        _assert_no_shell_artifacts(argv)

    def test_omitted_flags_absent(self):
        argv = build_cefputfile_argv("ccnx:/x", node_name="h0")
        for flag in ("-r", "-b", "-e", "-t", "-v", "-p"):
            assert flag not in argv

    def test_zero_value_is_emitted_not_dropped(self):
        # 0 is a real value (None means "omit"); the shared helper must keep it.
        argv = build_cefputfile_argv("ccnx:/x", node_name="h0", rate=0)
        assert argv[argv.index("-r") + 1] == "0"

    def test_special_chars_not_quoted(self):
        # A value with a space must remain a single raw argv element.
        argv = build_cefputfile_argv("ccnx:/a b;c", node_name="h0")
        assert "ccnx:/a b;c" in argv
        _assert_no_shell_artifacts(argv)


# ---------------------------------------------------------------------------
# cefgetfile
# ---------------------------------------------------------------------------


class TestGetfileArgv:
    def test_minimal(self):
        argv = build_cefgetfile_argv("ccnx:/x", "/recv/out", node_name="h0")
        assert argv == ["cefgetfile", "ccnx:/x", "-f", "/recv/out", "-d", "./h0"]

    def test_owner_only_is_bare_flag(self):
        argv = build_cefgetfile_argv(
            "ccnx:/x", "/recv/out", node_name="h0", owner_only=True
        )
        assert "-o" in argv
        # -o must not be followed by a value
        assert argv[argv.index("-o") + 1] == "-d"

    def test_sg_emits_literal_sg_keyword(self):
        argv = build_cefgetfile_argv("ccnx:/x", "/out", node_name="h0", sg=True)
        idx = argv.index("-z")
        assert argv[idx + 1] == "sg"

    def test_all_flags(self):
        argv = build_cefgetfile_argv(
            "ccnx:/x",
            "/recv/out",
            node_name="h0",
            chunk=50,
            pipeline=8,
            valid_algo="rsa-sha256",
            port_num=9695,
            sg=True,
        )
        assert argv[argv.index("-m") + 1] == "50"
        assert argv[argv.index("-s") + 1] == "8"
        assert argv[argv.index("-v") + 1] == "rsa-sha256"
        assert argv[argv.index("-p") + 1] == "9695"
        assert argv[argv.index("-z") + 1] == "sg"
        assert argv[-2:] == ["-d", "./h0"]
        _assert_no_shell_artifacts(argv)


# ---------------------------------------------------------------------------
# cefsubfile
# ---------------------------------------------------------------------------


class TestSubfileArgv:
    def test_minimal(self):
        argv = build_cefsubfile_argv("ccnx:/s", node_name="h0")
        assert argv == ["cefsubfile", "ccnx:/s", "-d", "./h0"]

    def test_output_dir_with_f_flag(self):
        argv = build_cefsubfile_argv(
            "ccnx:/s", node_name="h0", output_path="/recvdir"
        )
        assert argv[argv.index("-f") + 1] == "/recvdir"

    def test_ri_td_valid_algo_flags(self):
        argv = build_cefsubfile_argv(
            "ccnx:/s",
            node_name="h0",
            pipeline=4,
            ri_valid_algo="crc32c",
            td_valid_algo="rsa-sha256",
            port_num=9695,
        )
        assert argv[argv.index("-s") + 1] == "4"
        assert argv[argv.index("-v_RI") + 1] == "crc32c"
        assert argv[argv.index("-v_TD") + 1] == "rsa-sha256"
        assert argv[argv.index("-p") + 1] == "9695"
        _assert_no_shell_artifacts(argv)


# ---------------------------------------------------------------------------
# cefpubfile
# ---------------------------------------------------------------------------


class TestPubfileArgv:
    def test_minimal(self):
        argv = build_cefpubfile_argv("ccnx:/p", "/data/in.bin", node_name="h2")
        assert argv == [
            "cefpubfile", "ccnx:/p", "-f", "/data/in.bin", "-d", "./h2"
        ]

    def test_all_flags(self):
        argv = build_cefpubfile_argv(
            "ccnx:/p",
            "/data/in.bin",
            node_name="h2",
            rate=5,
            block_size=512,
            expiry=4000,
            cache_time=2000,
            lifetime=3,
            retry_limit=2,
            target="both",
            ti_valid_algo="crc32c",
            rd_valid_algo="rsa-sha256",
            port_num=9695,
        )
        assert argv[argv.index("-r") + 1] == "5"
        assert argv[argv.index("-b") + 1] == "512"
        assert argv[argv.index("-e") + 1] == "4000"
        assert argv[argv.index("-t") + 1] == "2000"
        assert argv[argv.index("-l") + 1] == "3"
        assert argv[argv.index("-m") + 1] == "2"
        assert argv[argv.index("-z") + 1] == "both"
        assert argv[argv.index("-v_TI") + 1] == "crc32c"
        assert argv[argv.index("-v_RD") + 1] == "rsa-sha256"
        assert argv[argv.index("-p") + 1] == "9695"
        assert argv[-2:] == ["-d", "./h2"]
        _assert_no_shell_artifacts(argv)


# ---------------------------------------------------------------------------
# ccninfo
# ---------------------------------------------------------------------------


class TestCcninfoArgv:
    def test_minimal(self):
        argv = build_ccninfo_argv("ccnx:/x", node_name="h0")
        assert argv == ["ccninfo", "ccnx:/x", "-d", "./h0"]

    def test_all_flags(self):
        argv = build_ccninfo_argv(
            "ccnx:/x",
            node_name="h0",
            cache_info=True,
            owner_only=True,
            hop_count=8,
            skip_hop=2,
            valid_algo="crc32c",
            port_num=9695,
        )
        # Byte-exact: pins head order (-c before -o), opt order (-r,-s,-v,-p),
        # and the trailing -d in one assertion so a reorder anywhere fails.
        assert argv == [
            "ccninfo", "ccnx:/x", "-c", "-o",
            "-r", "8", "-s", "2", "-v", "crc32c", "-p", "9695",
            "-d", "./h0",
        ]
        _assert_no_shell_artifacts(argv)

    def test_omitted_flags_absent(self):
        argv = build_ccninfo_argv("ccnx:/x", node_name="h0")
        for flag in ("-c", "-o", "-r", "-s", "-v", "-p"):
            assert flag not in argv

    def test_cache_info_bare_flag_alone(self):
        argv = build_ccninfo_argv("ccnx:/x", node_name="h0", cache_info=True)
        assert argv == ["ccninfo", "ccnx:/x", "-c", "-d", "./h0"]

    def test_owner_only_bare_flag_alone(self):
        argv = build_ccninfo_argv("ccnx:/x", node_name="h0", owner_only=True)
        assert argv == ["ccninfo", "ccnx:/x", "-o", "-d", "./h0"]

    def test_zero_value_passthrough_for_hop_count_and_skip_hop(self):
        # 0 is a real value the real binary treats distinctly from "omitted"
        # (an explicit -s rejects 0 upstream); the builder must not conflate
        # "0" with "None" and silently drop the flag.
        argv = build_ccninfo_argv(
            "ccnx:/x", node_name="h0", hop_count=0, skip_hop=0
        )
        assert argv[argv.index("-r") + 1] == "0"
        assert argv[argv.index("-s") + 1] == "0"

    def test_d_node_dir_always_last_two_elements(self):
        # Regardless of which options are set, "-d ./<node_name>" must be the
        # final two argv elements (matches the four existing builders).
        argv = build_ccninfo_argv(
            "ccnx:/x",
            node_name="h3",
            cache_info=True,
            owner_only=True,
            hop_count=5,
            skip_hop=1,
            valid_algo="rsa-sha256",
            port_num=1234,
        )
        assert argv[-2:] == ["-d", "./h3"]
