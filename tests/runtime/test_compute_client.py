from pathlib import Path
from unittest.mock import patch

from src.runtime.command_runner import FakeCommandRunner
from src.runtime.compute_client import check_external_connectivity, compute_call


def test_compute_call_runs_curl_with_timeout_and_output_file():
    fake = FakeCommandRunner()
    fake.script_run(returncode=0, stdout='{"ok": true}')

    run_dir = "logs/run-1"
    with patch("src.runtime.compute_client.MininetCommandRunner", return_value=fake), \
            patch(
                "src.runtime.compute_client.resolve_run_path",
                return_value=Path("logs/run-1/compute_result.json"),
            ):
        exit_code, stdout = compute_call(
            net=object(),
            host_idx=3,
            endpoint="http://10.0.0.100:8080/api/process",
            method="POST",
            payload='{"query": "analyze"}',
            output_file="compute_result.json",
            run_dir=run_dir,
            timeout=12,
        )

    assert exit_code == 0
    assert stdout == '{"ok": true}'
    assert fake.runs == [
        {
            "node": "h3",
            "argv": [
                "curl",
                "-s",
                "-S",
                "--max-time",
                "12",
                "-X",
                "POST",
                "-d",
                '{"query": "analyze"}',
                "-o",
                "logs/run-1/compute_result.json",
                "http://10.0.0.100:8080/api/process",
            ],
            "log_path": None,
            "cwd": None,
            "timeout": None,
            "cancel_event": None,
            "capture": True,
            "capture_stderr": False,
        }
    ]


def test_compute_call_publishes_existing_output_file_on_success(monkeypatch):
    out_file = "logs/run-2/compute_result.json"
    fake = FakeCommandRunner()
    fake.script_run(returncode=0, stdout="published source")
    fake.script_run(returncode=0)

    monkeypatch.setattr("src.runtime.compute_client.Path.exists", lambda self: True)

    with patch("src.runtime.compute_client.MininetCommandRunner", return_value=fake), \
            patch(
                "src.runtime.compute_client.resolve_run_path",
                return_value=Path(out_file),
            ):
        exit_code, stdout = compute_call(
            net=object(),
            host_idx=4,
            endpoint="http://edge.local/process",
            output_file="compute_result.json",
            publish_uri="ccnx:/compute/result1",
            run_dir="logs/run-2",
        )

    assert exit_code == 0
    assert stdout == "published source"
    assert fake.runs[1]["node"] == "h4"
    assert fake.runs[1]["argv"] == [
        "cefputfile",
        "ccnx:/compute/result1",
        "-f",
        out_file,
        "-t",
        "3000",
        "-e",
        "3000",
        "-d",
        "./h4",
    ]


def test_compute_call_does_not_publish_on_curl_failure(monkeypatch):
    fake = FakeCommandRunner()
    fake.script_run(returncode=7, stdout="connection refused")

    monkeypatch.setattr("src.runtime.compute_client.Path.exists", lambda self: True)

    with patch("src.runtime.compute_client.MininetCommandRunner", return_value=fake), \
            patch(
                "src.runtime.compute_client.resolve_run_path",
                return_value=Path("logs/run-3/compute_result.json"),
            ):
        exit_code, stdout = compute_call(
            net=object(),
            host_idx=4,
            endpoint="http://edge.local/process",
            output_file="compute_result.json",
            publish_uri="ccnx:/compute/result1",
            run_dir="logs/run-3",
        )

    assert exit_code == 7
    assert stdout == "connection refused"
    assert len(fake.runs) == 1


def test_check_external_connectivity_accepts_2xx_and_3xx():
    for status in ("200", "302"):
        fake = FakeCommandRunner()
        fake.script_run(stdout=status)
        with patch("src.runtime.compute_client.MininetCommandRunner", return_value=fake):
            assert check_external_connectivity(object(), 2, "http://edge.local")
        assert fake.runs[0]["argv"] == [
            "curl",
            "-s",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--max-time",
            "5",
            "http://edge.local",
        ]


def test_check_external_connectivity_rejects_other_statuses():
    fake = FakeCommandRunner()
    fake.script_run(stdout="500")
    with patch("src.runtime.compute_client.MininetCommandRunner", return_value=fake):
        assert not check_external_connectivity(object(), 2, "http://edge.local")
