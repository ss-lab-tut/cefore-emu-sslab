import subprocess
import sys
from pathlib import Path

from src.runtime.daemon_logs import (
    HostLogScope,
    cleanup_stale_cefnetd_log,
    cleanup_stale_csmgrd_log,
    cleanup_stale_daemon_logs,
    collect_daemon_logs,
    read_csmgr_port_num,
    read_local_sock_id,
    tmp_daemon_log_paths,
)


def test_read_local_sock_id_uses_daemon_conf_value(tmp_path: Path) -> None:
    node_dir = tmp_path / "h3"
    node_dir.mkdir()
    (node_dir / "cefnetd.conf").write_text("LOCAL_SOCK_ID=3\n", encoding="utf-8")

    assert read_local_sock_id(node_dir, "cefnetd.conf") == "3"


def test_read_local_sock_id_defaults_to_zero_when_conf_is_missing(
    tmp_path: Path,
) -> None:
    assert read_local_sock_id(tmp_path / "h0", "cefnetd.conf") == "0"


def test_read_local_sock_id_reads_the_requested_daemon_conf(tmp_path: Path) -> None:
    node_dir = tmp_path / "h4"
    node_dir.mkdir()
    (node_dir / "cefnetd.conf").write_text("LOCAL_SOCK_ID=4\n", encoding="utf-8")
    (node_dir / "csmgrd.conf").write_text("LOCAL_SOCK_ID=cache4\n", encoding="utf-8")

    assert read_local_sock_id(node_dir, "cefnetd.conf") == "4"
    assert read_local_sock_id(node_dir, "csmgrd.conf") == "cache4"


def test_read_csmgr_port_num_uses_csmgrd_conf_value(tmp_path: Path) -> None:
    node_dir = tmp_path / "h0"
    node_dir.mkdir()
    (node_dir / "csmgrd.conf").write_text("PORT_NUM=8000\n", encoding="utf-8")

    assert read_csmgr_port_num(node_dir) == 8000


def test_read_csmgr_port_num_defaults_when_unset(tmp_path: Path) -> None:
    node_dir = tmp_path / "h0"
    node_dir.mkdir()
    (node_dir / "csmgrd.conf").write_text("#PORT_NUM=8000\n", encoding="utf-8")

    assert read_csmgr_port_num(node_dir) == 9799


def test_tmp_daemon_log_paths_without_csmgrd_uses_cefnetd_conf(
    tmp_path: Path, monkeypatch
) -> None:
    tmp_dir = tmp_path / "tmp"
    node_dir = tmp_path / "h7"
    node_dir.mkdir()
    (node_dir / "cefnetd.conf").write_text(
        "PORT_NUM=6000\nLOCAL_SOCK_ID=7\n", encoding="utf-8"
    )
    monkeypatch.setattr("src.runtime.daemon_logs._TMP_DIR", tmp_dir)

    assert tmp_daemon_log_paths(HostLogScope(7, node_dir, False)) == [
        tmp_dir / "cefnetd_6000_7.log"
    ]


def test_tmp_daemon_log_paths_with_csmgrd_uses_independent_csmgrd_conf(
    tmp_path: Path, monkeypatch
) -> None:
    tmp_dir = tmp_path / "tmp"
    node_dir = tmp_path / "h2"
    node_dir.mkdir()
    (node_dir / "cefnetd.conf").write_text(
        "PORT_NUM=9696\nLOCAL_SOCK_ID=net2\n", encoding="utf-8"
    )
    (node_dir / "csmgrd.conf").write_text(
        "PORT_NUM=9798\nLOCAL_SOCK_ID=cache2\n", encoding="utf-8"
    )
    monkeypatch.setattr("src.runtime.daemon_logs._TMP_DIR", tmp_dir)

    assert tmp_daemon_log_paths(HostLogScope(2, node_dir, True)) == [
        tmp_dir / "cefnetd_9696_net2.log",
        tmp_dir / "csmgrd_9798_cache2.log",
    ]


def test_tmp_daemon_log_paths_reflects_custom_daemon_ports(
    tmp_path: Path, monkeypatch
) -> None:
    tmp_dir = tmp_path / "tmp"
    node_dir = tmp_path / "h5"
    node_dir.mkdir()
    (node_dir / "cefnetd.conf").write_text(
        "PORT_NUM=6000\nLOCAL_SOCK_ID=5\n", encoding="utf-8"
    )
    (node_dir / "csmgrd.conf").write_text(
        "PORT_NUM=8000\nLOCAL_SOCK_ID=5\n", encoding="utf-8"
    )
    monkeypatch.setattr("src.runtime.daemon_logs._TMP_DIR", tmp_dir)

    assert tmp_daemon_log_paths(HostLogScope(5, node_dir, True)) == [
        tmp_dir / "cefnetd_6000_5.log",
        tmp_dir / "csmgrd_8000_5.log",
    ]


def test_collect_daemon_logs_copies_existing_tmp_logs(
    tmp_path: Path, monkeypatch
) -> None:
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    node_dir = tmp_path / "h0"
    node_dir.mkdir()
    (node_dir / "cefnetd.conf").write_text("LOCAL_SOCK_ID=0\n", encoding="utf-8")
    source = tmp_dir / "cefnetd_9695_0.log"
    source.write_text("cefnetd log\n", encoding="utf-8")
    monkeypatch.setattr("src.runtime.daemon_logs._TMP_DIR", tmp_dir)

    warnings = collect_daemon_logs(run_dir, [HostLogScope(0, node_dir, False)])

    assert warnings == []
    assert (run_dir / source.name).read_text(encoding="utf-8") == "cefnetd log\n"


def test_collect_daemon_logs_skips_missing_sources_and_copies_existing(
    tmp_path: Path, monkeypatch
) -> None:
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    node_dir = tmp_path / "h1"
    node_dir.mkdir()
    (node_dir / "cefnetd.conf").write_text("LOCAL_SOCK_ID=1\n", encoding="utf-8")
    (node_dir / "csmgrd.conf").write_text("LOCAL_SOCK_ID=1\n", encoding="utf-8")
    csmgr_log = tmp_dir / "csmgrd_9799_1.log"
    csmgr_log.write_text("csmgrd log\n", encoding="utf-8")
    monkeypatch.setattr("src.runtime.daemon_logs._TMP_DIR", tmp_dir)

    warnings = collect_daemon_logs(run_dir, [HostLogScope(1, node_dir, True)])

    assert warnings == []
    assert not (run_dir / "cefnetd_9695_1.log").exists()
    assert (run_dir / csmgr_log.name).read_text(encoding="utf-8") == "csmgrd log\n"


def test_collect_daemon_logs_returns_warning_when_copy_fails(
    tmp_path: Path, monkeypatch
) -> None:
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    node_dir = tmp_path / "h0"
    node_dir.mkdir()
    (node_dir / "cefnetd.conf").write_text("LOCAL_SOCK_ID=0\n", encoding="utf-8")
    source = tmp_dir / "cefnetd_9695_0.log"
    source.write_text("cefnetd log\n", encoding="utf-8")
    monkeypatch.setattr("src.runtime.daemon_logs._TMP_DIR", tmp_dir)

    def fail_copy(src: Path, dst: Path) -> None:
        raise OSError(f"cannot copy {src} to {dst}")

    monkeypatch.setattr("src.runtime.daemon_logs.shutil.copy2", fail_copy)

    warnings = collect_daemon_logs(run_dir, [HostLogScope(0, node_dir, False)])

    assert len(warnings) == 1
    assert "failed to collect daemon log" in warnings[0]
    assert "cefnetd_9695_0.log" in warnings[0]


def test_collect_daemon_logs_continues_same_scope_after_one_source_copy_fails(
    tmp_path: Path, monkeypatch
) -> None:
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    node_dir = tmp_path / "h0"
    node_dir.mkdir()
    (node_dir / "cefnetd.conf").write_text("LOCAL_SOCK_ID=0\n", encoding="utf-8")
    (node_dir / "csmgrd.conf").write_text("LOCAL_SOCK_ID=0\n", encoding="utf-8")
    cefnetd_log = tmp_dir / "cefnetd_9695_0.log"
    csmgrd_log = tmp_dir / "csmgrd_9799_0.log"
    cefnetd_log.write_text("cefnetd log\n", encoding="utf-8")
    csmgrd_log.write_text("csmgrd log\n", encoding="utf-8")
    monkeypatch.setattr("src.runtime.daemon_logs._TMP_DIR", tmp_dir)
    original_copy2 = __import__("shutil").copy2

    def copy2(src: Path, dst: Path) -> None:
        if src.name.startswith("cefnetd_"):
            raise OSError(f"cannot copy {src}")
        original_copy2(src, dst)

    monkeypatch.setattr("src.runtime.daemon_logs.shutil.copy2", copy2)

    warnings = collect_daemon_logs(run_dir, [HostLogScope(0, node_dir, True)])

    assert len(warnings) == 1
    assert "failed to collect daemon log" in warnings[0]
    assert "cefnetd_9695_0.log" in warnings[0]
    assert (run_dir / csmgrd_log.name).read_text(encoding="utf-8") == "csmgrd log\n"


def test_collect_daemon_logs_returns_warning_when_destination_escapes_run_dir(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    source.write_text("escape\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    escaped_source = source / ".."
    original_is_file = Path.is_file

    def is_file(path: Path) -> bool:
        if path == escaped_source:
            return True
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", is_file)
    monkeypatch.setattr(
        "src.runtime.daemon_logs.tmp_daemon_log_paths",
        lambda scope: [escaped_source],
    )

    warnings = collect_daemon_logs(run_dir, [HostLogScope(0, tmp_path / "h0", False)])

    assert len(warnings) == 1
    assert "failed to collect daemon log" in warnings[0]
    assert "escapes run directory" in warnings[0]


def test_collect_daemon_logs_warns_when_path_derivation_fails_and_continues(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    good_log = tmp_path / "cefnetd_9695_1.log"
    good_log.write_text("good\n", encoding="utf-8")
    calls = []

    def derive_paths(scope: HostLogScope) -> list[Path]:
        calls.append(scope.idx)
        if scope.idx == 0:
            raise RuntimeError("cannot derive")
        return [good_log]

    monkeypatch.setattr("src.runtime.daemon_logs.tmp_daemon_log_paths", derive_paths)

    warnings = collect_daemon_logs(
        run_dir,
        [
            HostLogScope(0, tmp_path / "h0", False),
            HostLogScope(1, tmp_path / "h1", False),
        ],
    )

    assert calls == [0, 1]
    assert len(warnings) == 1
    assert "failed to collect daemon log" in warnings[0]
    assert "cannot derive" in warnings[0]
    assert (run_dir / good_log.name).read_text(encoding="utf-8") == "good\n"


def test_collect_daemon_logs_warns_when_source_stat_fails_and_continues(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bad_log = tmp_path / "cefnetd_9695_0.log"
    good_log = tmp_path / "cefnetd_9695_1.log"
    good_log.write_text("good\n", encoding="utf-8")
    original_is_file = Path.is_file

    def is_file(path: Path) -> bool:
        if path == bad_log:
            raise OSError("cannot stat")
        return original_is_file(path)

    def derive_paths(scope: HostLogScope) -> list[Path]:
        if scope.idx == 0:
            return [bad_log]
        return [good_log]

    monkeypatch.setattr(Path, "is_file", is_file)
    monkeypatch.setattr("src.runtime.daemon_logs.tmp_daemon_log_paths", derive_paths)

    warnings = collect_daemon_logs(
        run_dir,
        [
            HostLogScope(0, tmp_path / "h0", False),
            HostLogScope(1, tmp_path / "h1", False),
        ],
    )

    assert len(warnings) == 1
    assert "failed to collect daemon log" in warnings[0]
    assert "cannot stat" in warnings[0]
    assert (run_dir / good_log.name).read_text(encoding="utf-8") == "good\n"


def test_daemon_logs_import_does_not_load_mininet_modules() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys;"
                "import src.runtime.daemon_logs;"
                "loaded=[name for name in sys.modules "
                "if name == 'mininet' or name.startswith('mininet.')];"
                "raise SystemExit(1 if loaded else 0)"
            ),
        ],
        check=False,
    )

    assert result.returncode == 0


def test_cleanup_stale_daemon_logs_unlinks_existing_logs_and_ignores_missing(
    tmp_path: Path, monkeypatch
) -> None:
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    node_dir = tmp_path / "h0"
    node_dir.mkdir()
    (node_dir / "cefnetd.conf").write_text("LOCAL_SOCK_ID=0\n", encoding="utf-8")
    cefnetd_log = tmp_dir / "cefnetd_9695_0.log"
    cefnetd_log.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr("src.runtime.daemon_logs._TMP_DIR", tmp_dir)

    cleanup_stale_daemon_logs(HostLogScope(0, node_dir, True))

    assert not cefnetd_log.exists()


def test_cleanup_stale_daemon_logs_removes_csmgrd_default_and_configured_ports(
    tmp_path: Path, monkeypatch
) -> None:
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    node_dir = tmp_path / "h1"
    node_dir.mkdir()
    (node_dir / "cefnetd.conf").write_text("LOCAL_SOCK_ID=1\n", encoding="utf-8")
    (node_dir / "csmgrd.conf").write_text(
        "PORT_NUM=8000\nLOCAL_SOCK_ID=cache1\n", encoding="utf-8"
    )
    default_log = tmp_dir / "csmgrd_9799_cache1.log"
    configured_log = tmp_dir / "csmgrd_8000_cache1.log"
    default_log.write_text("default\n", encoding="utf-8")
    configured_log.write_text("configured\n", encoding="utf-8")
    monkeypatch.setattr("src.runtime.daemon_logs._TMP_DIR", tmp_dir)

    cleanup_stale_daemon_logs(HostLogScope(1, node_dir, True))

    assert not default_log.exists()
    assert not configured_log.exists()


def test_cleanup_stale_daemon_logs_ignores_unlink_oserror(
    tmp_path: Path, monkeypatch
) -> None:
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    node_dir = tmp_path / "h0"
    node_dir.mkdir()
    (node_dir / "cefnetd.conf").write_text("LOCAL_SOCK_ID=0\n", encoding="utf-8")
    cefnetd_log = tmp_dir / "cefnetd_9695_0.log"
    cefnetd_log.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr("src.runtime.daemon_logs._TMP_DIR", tmp_dir)

    def fail_unlink(path: Path, missing_ok: bool = False) -> None:
        raise OSError(f"cannot unlink {path}")

    monkeypatch.setattr(Path, "unlink", fail_unlink)

    cleanup_stale_daemon_logs(HostLogScope(0, node_dir, False))


def test_stale_cleanup_helpers_target_each_daemon_independently(
    tmp_path: Path, monkeypatch
) -> None:
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    node_dir = tmp_path / "h0"
    node_dir.mkdir()
    (node_dir / "cefnetd.conf").write_text(
        "PORT_NUM=6000\nLOCAL_SOCK_ID=0\n", encoding="utf-8"
    )
    (node_dir / "csmgrd.conf").write_text(
        "PORT_NUM=8000\nLOCAL_SOCK_ID=cache0\n", encoding="utf-8"
    )
    cefnetd_log = tmp_dir / "cefnetd_6000_0.log"
    csmgrd_default_log = tmp_dir / "csmgrd_9799_cache0.log"
    csmgrd_configured_log = tmp_dir / "csmgrd_8000_cache0.log"
    for log in (cefnetd_log, csmgrd_default_log, csmgrd_configured_log):
        log.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr("src.runtime.daemon_logs._TMP_DIR", tmp_dir)

    cleanup_stale_cefnetd_log(node_dir, 0)

    assert not cefnetd_log.exists()
    assert csmgrd_default_log.exists()
    assert csmgrd_configured_log.exists()

    cefnetd_log.write_text("old\n", encoding="utf-8")
    cleanup_stale_csmgrd_log(node_dir, 0)

    assert cefnetd_log.exists()
    assert not csmgrd_default_log.exists()
    assert not csmgrd_configured_log.exists()
