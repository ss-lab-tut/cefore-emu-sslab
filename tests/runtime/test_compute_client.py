"""compute_client seam tests.

The seam under test is ``compute_call(runner, host_idx, endpoint, ...)``:
a pure client over the CommandRunner seam that reports a typed
``ComputeResult``. Success semantics: curl exit 0 AND HTTP 2xx AND, when a
publish is requested, cefputfile exit 0. Environment failures (DNS/connect/
timeout curl exits) are classified separately so the scheduler can record
them as skipped rather than failed.
"""

from pathlib import Path
from unittest.mock import patch

from src.runtime.command_runner import FakeCommandRunner
from src.runtime.compute_client import compute_call


def _call(fake, **kwargs):
    defaults = dict(
        host_idx=3,
        endpoint="http://10.0.0.100:8080/api/process",
    )
    defaults.update(kwargs)
    return compute_call(fake, **defaults)


def test_get_2xx_is_success_and_parses_status_from_trailing_line():
    fake = FakeCommandRunner()
    fake.script_run(returncode=0, stdout='{"ok": true}\n200')

    result = _call(fake, timeout=12)

    assert result.ok is True
    assert result.http_status == 200
    assert result.curl_exit == 0
    assert result.publish_ok is None
    assert result.stdout == '{"ok": true}'
    run = fake.runs[0]
    assert run["node"] == "h3"
    assert run["argv"] == [
        "curl", "-s", "-S", "--max-time", "12",
        "-w", "\n%{http_code}",
        "http://10.0.0.100:8080/api/process",
    ]
    # curl --max-time alone cannot bound a hung netns exec; the CommandRunner
    # deadline must also be armed (with margin so curl's own timeout wins).
    assert run["timeout"] == 12 + 5


def test_http_500_is_failure_not_environment():
    fake = FakeCommandRunner()
    fake.script_run(returncode=0, stdout="oops\n500")

    result = _call(fake)

    assert result.ok is False
    assert result.http_status == 500
    assert result.env_failure is False


def test_connect_refused_is_environment_failure():
    fake = FakeCommandRunner()
    fake.script_run(returncode=7, stdout="")

    result = _call(fake)

    assert result.ok is False
    assert result.curl_exit == 7
    assert result.http_status is None
    assert result.env_failure is True


def test_timeout_and_dns_exits_are_environment_failures():
    for exit_code in (6, 28):
        fake = FakeCommandRunner()
        fake.script_run(returncode=exit_code, stdout="")
        assert _call(fake).env_failure is True


def test_post_payload_and_headers_map_to_curl_argv():
    fake = FakeCommandRunner()
    fake.script_run(returncode=0, stdout="\n201")

    result = _call(
        fake,
        method="POST",
        payload='{"query": "analyze"}',
        headers={"Content-Type": "application/json"},
    )

    assert result.ok is True
    assert result.http_status == 201
    argv = fake.runs[0]["argv"]
    assert argv[argv.index("-X") + 1] == "POST"
    assert argv[argv.index("-d") + 1] == '{"query": "analyze"}'
    assert argv[argv.index("-H") + 1] == "Content-Type: application/json"


def test_output_file_resolved_under_run_dir():
    fake = FakeCommandRunner()
    fake.script_run(returncode=0, stdout="\n200")

    with patch(
        "src.runtime.compute_client.resolve_run_path",
        return_value=Path("logs/run-1/compute_result.json"),
    ):
        result = _call(fake, output_file="compute_result.json", run_dir="logs/run-1")

    argv = fake.runs[0]["argv"]
    assert argv[argv.index("-o") + 1] == "logs/run-1/compute_result.json"
    assert result.output_file == "logs/run-1/compute_result.json"


def test_publish_uses_cefputfile_builder_with_pub_opts(monkeypatch):
    out_file = "logs/run-2/compute_result.json"
    fake = FakeCommandRunner()
    fake.script_run(returncode=0, stdout="\n200")
    fake.script_run(returncode=0)

    monkeypatch.setattr("src.runtime.compute_client.Path.exists", lambda self: True)

    with patch(
        "src.runtime.compute_client.resolve_run_path",
        return_value=Path(out_file),
    ):
        result = _call(
            fake,
            host_idx=4,
            output_file="compute_result.json",
            publish_uri="ccnx:/compute/result1",
            pub_opts={"expiry": 5000, "cache_time": 2500},
            run_dir="logs/run-2",
        )

    assert result.ok is True
    assert result.publish_ok is True
    assert fake.runs[1]["node"] == "h4"
    assert fake.runs[1]["argv"] == [
        "cefputfile", "ccnx:/compute/result1", "-f", out_file,
        "-e", "5000", "-t", "2500", "-d", "./h4",
    ]


def test_publish_defaults_keep_legacy_expiry_and_cache_time(monkeypatch):
    fake = FakeCommandRunner()
    fake.script_run(returncode=0, stdout="\n200")
    fake.script_run(returncode=0)

    monkeypatch.setattr("src.runtime.compute_client.Path.exists", lambda self: True)

    with patch(
        "src.runtime.compute_client.resolve_run_path",
        return_value=Path("logs/run-2/out.json"),
    ):
        _call(
            fake,
            host_idx=4,
            output_file="out.json",
            publish_uri="ccnx:/compute/result1",
            run_dir="logs/run-2",
        )

    argv = fake.runs[1]["argv"]
    assert argv[argv.index("-e") + 1] == "3000"
    assert argv[argv.index("-t") + 1] == "3000"


def test_publish_timed_out_or_cancelled_vetoes_publish_ok(monkeypatch):
    """cefputfile's CommandResult flags are as authoritative as curl's:
    a timed-out/cancelled publish must not count as published, and the
    publish run must carry a deadline so a hung cefputfile cannot stall
    the scheduler thread."""
    for flag in ("timed_out", "cancelled"):
        fake = FakeCommandRunner()
        fake.script_run(returncode=0, stdout="\n200")
        fake.script_run(returncode=0, **{flag: True})

        monkeypatch.setattr(
            "src.runtime.compute_client.Path.exists", lambda self: True
        )
        with patch(
            "src.runtime.compute_client.resolve_run_path",
            return_value=Path("logs/run-6/out.json"),
        ):
            result = _call(
                fake,
                host_idx=4,
                output_file="out.json",
                publish_uri="ccnx:/compute/result1",
                run_dir="logs/run-6",
                timeout=10,
            )

        assert result.publish_ok is False, flag
        assert result.ok is False, flag
        # 2026-07-16 audit fix: the publish deadline is independent of the
        # HTTP timeout — at cefputfile's minimum rate (0.001 Mbps) even a
        # small result outlives timeout+margin, so reusing it would kill
        # valid slow publications.
        assert fake.runs[1]["timeout"] == 120


def test_publish_timeout_field_overrides_default_deadline(monkeypatch):
    """publish_timeout bounds only the cefputfile run; the HTTP run keeps
    its own timeout-derived deadline."""
    fake = FakeCommandRunner()
    fake.script_run(returncode=0, stdout="\n200")
    fake.script_run(returncode=0)

    monkeypatch.setattr("src.runtime.compute_client.Path.exists", lambda self: True)
    with patch(
        "src.runtime.compute_client.resolve_run_path",
        return_value=Path("logs/run-7/out.json"),
    ):
        _call(
            fake,
            host_idx=4,
            output_file="out.json",
            publish_uri="ccnx:/compute/result1",
            run_dir="logs/run-7",
            timeout=10,
            publish_timeout=600,
        )

    assert fake.runs[0]["timeout"] == 10 + 5
    assert fake.runs[1]["timeout"] == 600


def test_publish_failure_fails_the_call(monkeypatch):
    fake = FakeCommandRunner()
    fake.script_run(returncode=0, stdout="\n200")
    fake.script_run(returncode=1)

    monkeypatch.setattr("src.runtime.compute_client.Path.exists", lambda self: True)

    with patch(
        "src.runtime.compute_client.resolve_run_path",
        return_value=Path("logs/run-3/out.json"),
    ):
        result = _call(
            fake,
            host_idx=4,
            output_file="out.json",
            publish_uri="ccnx:/compute/result1",
            run_dir="logs/run-3",
        )

    assert result.publish_ok is False
    assert result.ok is False


def test_publish_requested_but_output_missing_fails_without_running_cefputfile(
    monkeypatch,
):
    fake = FakeCommandRunner()
    fake.script_run(returncode=0, stdout="\n200")

    monkeypatch.setattr("src.runtime.compute_client.Path.exists", lambda self: False)

    with patch(
        "src.runtime.compute_client.resolve_run_path",
        return_value=Path("logs/run-4/out.json"),
    ):
        result = _call(
            fake,
            host_idx=4,
            output_file="out.json",
            publish_uri="ccnx:/compute/result1",
            run_dir="logs/run-4",
        )

    assert result.publish_ok is False
    assert result.ok is False
    assert len(fake.runs) == 1


def test_no_publish_on_http_failure(monkeypatch):
    fake = FakeCommandRunner()
    fake.script_run(returncode=0, stdout="\n503")

    monkeypatch.setattr("src.runtime.compute_client.Path.exists", lambda self: True)

    with patch(
        "src.runtime.compute_client.resolve_run_path",
        return_value=Path("logs/run-5/out.json"),
    ):
        result = _call(
            fake,
            host_idx=4,
            output_file="out.json",
            publish_uri="ccnx:/compute/result1",
            run_dir="logs/run-5",
        )

    assert result.ok is False
    assert result.publish_ok is None
    assert len(fake.runs) == 1


def test_runner_timeout_rejects_success_even_with_status_line():
    # A timed-out CommandResult can still carry returncode 0 and a body from
    # the injected runner; the timeout flag must veto success and classify
    # the call as an environment failure.
    fake = FakeCommandRunner()
    fake.script_run(returncode=0, stdout="\n200", timed_out=True)

    result = _call(fake)

    assert result.ok is False
    assert result.env_failure is True


def test_cancelled_run_rejects_success_and_is_environment():
    fake = FakeCommandRunner()
    fake.script_run(returncode=0, stdout="\n200", cancelled=True)

    result = _call(fake)

    assert result.ok is False
    assert result.env_failure is True


def test_unparseable_status_line_yields_none_status_and_failure():
    fake = FakeCommandRunner()
    fake.script_run(returncode=0, stdout="body without status")

    result = _call(fake)

    assert result.http_status is None
    assert result.ok is False
