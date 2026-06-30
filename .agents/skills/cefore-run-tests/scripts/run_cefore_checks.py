#!/usr/bin/env python3
"""Run the full unit pytest suite and minimal disaster smoke checks."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PYTEST_TARGETS = ("tests",)
SMOKE_CONFIGS = (
    "min_putget", "min_putget_class_a", "min_pubsub", "min_pubsub_verify",
    "min_empty", "min_mixed", "min_event_putget", "min_event_pubsub",
    "min_failure", "min_event_link", "min_monitoring", "connect",
)


@dataclass(frozen=True)
class SmokeCase:
    """Single smoke test configuration.

    ``kind`` selects how the case is run and validated:
    - ``"disaster"``: ``python -m src disaster --config <config_relpath> --no-cli``
      writing a ``results.json`` that is then validated against the
      declarative ``expect`` spec (see ``validate_results``).
    - ``"connect"``: the ConnectScenario path (ceforeemu-connect), which has no
      ``--results-json`` and produces no results.json; validated by exit 0 plus
      the topology PNG that proves the configure stage completed.
    """

    name: str
    kind: str = "disaster"
    config_relpath: str | None = None
    expect: dict | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the full unit pytest suite and minimal disaster smoke configs."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="repository root (default: current directory)",
    )
    parser.add_argument(
        "--configs",
        nargs="+",
        choices=SMOKE_CONFIGS,
        default=list(SMOKE_CONFIGS),
        help="smoke configs to execute",
    )
    parser.add_argument(
        "--output-base",
        type=Path,
        default=None,
        help="base directory for smoke artifacts (default: /tmp/cefore-run-tests/<timestamp>)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=180,
        help="per-config timeout for disaster smoke runs",
    )
    parser.add_argument(
        "--skip-pytest",
        action="store_true",
        help="skip pytest phase",
    )
    parser.add_argument(
        "--skip-smoke",
        action="store_true",
        help="skip config-driven smoke phase",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="remove smoke artifact directories after a fully successful run",
    )
    parser.add_argument(
        "--tmpdir",
        type=Path,
        default=None,
        help="temporary directory for subprocesses (default: <output-base>/_tmp)",
    )
    return parser.parse_args()


def find_repo_root(start: Path) -> Path:
    """Find the repository root by walking upward."""
    for candidate in (start.resolve(), *start.resolve().parents):
        if (
            (candidate / "pyproject.toml").is_file()
            and (candidate / "src").is_dir()
            and (candidate / "config" / "examples" / "min_putget.yaml").is_file()
        ):
            return candidate
    raise FileNotFoundError(
        f"Could not locate repo root from {start}. Pass --repo-root explicitly."
    )


def ensure_exists(path: Path, label: str) -> None:
    """Require a file or directory to exist."""
    if not path.exists():
        raise FileNotFoundError(f"Missing {label}: {path}")


def venv_python(repo_root: Path) -> Path:
    """Return the repository venv interpreter."""
    interpreter = repo_root / ".venv" / "bin" / "python3"
    ensure_exists(interpreter, "repo venv interpreter")
    return interpreter


def default_output_base() -> Path:
    """Create a timestamped output base under $TMPDIR (fallback /tmp)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base_root = Path(os.environ.get("TMPDIR") or "/tmp")
    return base_root / "cefore-run-tests" / stamp


def command_env(tmp_dir: Path) -> dict[str, str]:
    """Build a subprocess environment with an explicit temp directory."""
    env = os.environ.copy()
    env["TMPDIR"] = str(tmp_dir)
    return env


def run_command(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    """Run a command and raise on failure."""
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, check=False, env=env)
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {result.returncode}: {' '.join(cmd)}"
        )


def run_pytest_phase(repo_root: Path, python_bin: Path, tmp_dir: Path) -> None:
    """Run the full unit suite (root/env-gated tests skip themselves)."""
    cmd = [
        str(python_bin),
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-ra",
        *PYTEST_TARGETS,
    ]
    run_command(cmd, repo_root, env=command_env(tmp_dir))


def require_smoke_prereqs(repo_root: Path) -> None:
    """Check prerequisites for the smoke phase."""
    ensure_exists(repo_root / "sample-putfile", "sample put file")

    sudo_check = subprocess.run(
        ["sudo", "-n", "true"],
        cwd=repo_root,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if sudo_check.returncode != 0:
        raise RuntimeError("Smoke phase requires passwordless sudo (`sudo -n`).")


def mn_cleanup(repo_root: Path) -> None:
    """Best-effort Mininet cleanup via `sudo -n mn -c`."""
    print("$ sudo -n mn -c")
    result = subprocess.run(
        ["sudo", "-n", "mn", "-c"],
        cwd=repo_root,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        print(f"[WARN] best-effort Mininet cleanup failed with exit code {result.returncode}")


# Verdict Factor expectations shared by several configs. Values: True means
# the Factor must be truthy on every row of that op_type; "falsy" means it
# must stay false/null; "out_file_contains" substring-matches the artifact.
GET_FACTORS = {"has_completed_log": True, "has_output_file": True}
SUB_FACTORS = {
    "has_output_file": True,
    "has_completed_log": "falsy",
    "out_file_contains": "RNP0x",
}

PUTGET_EXPECT = {
    "min_rows": 1,
    "all_success": True,
    "require_op_types": ("get",),
    "op_factors": {"get": GET_FACTORS},
}
PUBSUB_EXPECT = {
    "min_rows": 1,
    "all_success": True,
    "require_op_types": ("sub",),
    "op_factors": {"sub": SUB_FACTORS},
}


def build_smoke_cases() -> list[SmokeCase]:
    """Return the known smoke configs with their expected-outcome specs."""
    return [
        SmokeCase(
            "min_putget",
            config_relpath="config/examples/min_putget.yaml",
            expect=PUTGET_EXPECT,
        ),
        SmokeCase(
            # Same as min_putget but on a Class A (10.0.0.0/16) network, where
            # get must actually receive content end-to-end. Functional
            # regression guard for the ifconfig classful-default-netmask bug
            # (bare 10.x → /8) that broke get; success here means the kernel
            # got a working per-link netmask, not asserted directly.
            "min_putget_class_a",
            config_relpath="config/examples/min_putget_class_a.yaml",
            expect=PUTGET_EXPECT,
        ),
        SmokeCase(
            "min_pubsub",
            config_relpath="config/examples/min_pubsub.yaml",
            expect=PUBSUB_EXPECT,
        ),
        SmokeCase(
            "min_pubsub_verify",
            config_relpath="config/examples/min_pubsub_verify.yaml",
            expect=PUBSUB_EXPECT,
        ),
        SmokeCase(
            "min_empty",
            config_relpath="config/examples/min_empty.yaml",
            expect={"empty": True},
        ),
        SmokeCase(
            "min_mixed",
            config_relpath="config/examples/min_mixed.yaml",
            expect={
                "min_rows": 1,
                "all_success": True,
                "require_op_types": ("get", "sub"),
                "op_factors": {
                    "get": {"has_completed_log": True},
                    "sub": {"has_output_file": True, "has_completed_log": "falsy"},
                },
            },
        ),
        SmokeCase(
            "min_event_putget",
            config_relpath="config/examples/min_event_putget.yaml",
            expect=PUTGET_EXPECT,
        ),
        SmokeCase(
            "min_event_pubsub",
            config_relpath="config/examples/min_event_pubsub.yaml",
            expect=PUBSUB_EXPECT,
        ),
        SmokeCase(
            "min_failure",
            config_relpath="config/examples/min_failure.yaml",
            expect={
                # Cycle evidence only: gets during a failure window may
                # legitimately fail, so content rows are not gated here.
                "min_rows": 1,
                "require_event_types": ("host_down", "host_up"),
                "all_events_success": True,
            },
        ),
        SmokeCase(
            "min_event_link",
            config_relpath="config/examples/min_event_link.yaml",
            expect={
                "min_rows": 1,
                "all_success": True,
                "require_op_types": ("get",),
                "require_event_types": ("link_down", "link_up"),
                "op_factors": {"get": GET_FACTORS},
            },
        ),
        SmokeCase(
            "min_monitoring",
            config_relpath="config/examples/min_monitoring.yaml",
            expect={
                "min_rows": 1,
                "all_success": True,
                "require_op_types": ("get",),
                "monitor_json": {"min_entries": 1},
            },
        ),
        SmokeCase("connect", kind="connect"),
    ]


def find_results_json(output_dir: Path) -> Path:
    """Locate the single results.json file produced by a smoke run."""
    matches = sorted(output_dir.rglob("results.json"))
    if not matches:
        raise FileNotFoundError(f"No results.json found under {output_dir}")
    if len(matches) > 1:
        raise RuntimeError(f"Expected one results.json under {output_dir}, found {len(matches)}")
    return matches[0]


def load_results(results_path: Path) -> list[dict]:
    """Load the scenario results JSON."""
    return json.loads(results_path.read_text(encoding="utf-8"))


def validate_results(
    case_name: str, data: list[dict], expect: dict, case_output_dir: Path
) -> None:
    """Validate results.json against a declarative expectation spec.

    Spec keys:
    - ``empty``: results must be exactly ``[]``.
    - ``min_rows``: minimum number of result rows.
    - ``all_success``: every row must have a truthy ``success``.
    - ``require_op_types``: at least one row per listed op_type.
    - ``op_factors``: per-op_type Verdict Factor requirements; ``True`` =
      truthy, ``"falsy"`` = must stay false/null, ``out_file_contains`` =
      substring of ``out_file``.
    - ``require_event_types``: at least one ``op_type == "event"`` record per
      listed event_type (scheduler / failure-cycle outcome records).
    - ``all_events_success``: every event record must have truthy ``success``.
    - ``monitor_json``: a monitor.json with at least ``min_entries`` entries
      must exist under the case output directory.
    """

    def fail(msg: str) -> None:
        raise RuntimeError(f"{case_name}: {msg}")

    if expect.get("empty"):
        if data != []:
            fail(f"expected [], got {data!r}")
        return
    if len(data) < expect.get("min_rows", 0):
        fail(f"expected at least {expect['min_rows']} result rows, got {len(data)}")
    if expect.get("all_success") and not all(row.get("success") for row in data):
        fail("contains an unsuccessful result row")
    for op_type in expect.get("require_op_types", ()):
        if not any(row.get("op_type") == op_type for row in data):
            fail(f"expected at least 1 {op_type} result")
    for op_type, factors in expect.get("op_factors", {}).items():
        for row in (r for r in data if r.get("op_type") == op_type):
            for key, want in factors.items():
                if key == "out_file_contains":
                    if want not in str(row.get("out_file", "")):
                        fail(f"{op_type} row out_file does not contain {want!r}")
                elif want == "falsy":
                    if row.get(key):
                        fail(f"{op_type} row should keep {key} falsy")
                elif not row.get(key):
                    fail(f"{op_type} row missing {key}")
    event_rows = [r for r in data if r.get("op_type") == "event"]
    for event_type in expect.get("require_event_types", ()):
        if not any(r.get("event_type") == event_type for r in event_rows):
            fail(f"expected at least 1 {event_type} event record")
    if expect.get("all_events_success") and not all(
        r.get("success") for r in event_rows
    ):
        fail("contains a failed event record")
    monitor_spec = expect.get("monitor_json")
    if monitor_spec:
        matches = sorted(case_output_dir.rglob("monitor.json"))
        if not matches:
            fail("no monitor.json produced")
        entries = json.loads(matches[0].read_text(encoding="utf-8"))
        min_entries = monitor_spec.get("min_entries", 1)
        if len(entries) < min_entries:
            fail(f"monitor.json has {len(entries)} entries, expected >= {min_entries}")


def validate_connect(case_output_dir: Path) -> None:
    """Validate a ConnectScenario smoke run.

    Connect has no --results-json, so success is exit 0 (enforced by the caller)
    plus the topology PNG, which only exists if the configure stage ran to the
    visualization step (mesh built, daemons started, FIB applied). Also assert
    no results.json so a future regression that wires connect into autotest
    output is noticed here.
    """
    pngs = list(case_output_dir.rglob("*.png"))
    if not pngs:
        raise RuntimeError(
            "connect produced no topology PNG; configure stage did not complete"
        )
    if list(case_output_dir.rglob("results.json")):
        raise RuntimeError("connect unexpectedly produced results.json")


def run_single_smoke(
    repo_root: Path,
    python_bin: Path,
    case: SmokeCase,
    base_output_dir: Path,
    timeout_seconds: int,
    tmp_dir: Path,
) -> Path:
    """Run one smoke case (disaster or connect) and validate its output."""
    case_output_dir = base_output_dir / case.name
    case_output_dir.mkdir(parents=True, exist_ok=True)

    try:
        if case.kind == "connect":
            cmd = [
                "timeout",
                f"{timeout_seconds}s",
                "sudo",
                "-n",
                "env",
                f"TMPDIR={tmp_dir}",
                str(python_bin),
                "-c",
                "from src.runtime.external_net import main; main()",
                "--hosts",
                "3",
                "--switches",
                "2",
                "--seed",
                "42",
                "--no-cli",
                "--no-script-log",
                "--output-dir",
                str(case_output_dir),
            ]
            run_command(cmd, repo_root)
            validate_connect(case_output_dir)
            print(f"[OK] {case.name}: ConnectScenario lifecycle exit 0 + topology PNG")
            return case_output_dir

        config_path = repo_root / case.config_relpath
        ensure_exists(config_path, f"smoke config {case.name}")
        cmd = [
            "timeout",
            f"{timeout_seconds}s",
            "sudo",
            "-n",
            "env",
            f"TMPDIR={tmp_dir}",
            str(python_bin),
            "-m",
            "src",
            "disaster",
            "--config",
            str(config_path),
            "--output-dir",
            str(case_output_dir),
            "--results-json",
            "results.json",
            "--no-cli",
        ]
        run_command(cmd, repo_root)

        results_path = find_results_json(case_output_dir)
        data = load_results(results_path)
        validate_results(case.name, data, case.expect or {}, case_output_dir)
        print(f"[OK] {case.name}: {results_path}")
        return case_output_dir
    finally:
        mn_cleanup(repo_root)


def run_smoke_phase(
    repo_root: Path,
    python_bin: Path,
    selected_configs: list[str],
    output_base: Path,
    timeout_seconds: int,
    tmp_dir: Path,
) -> list[Path]:
    """Run all selected smoke configs."""
    require_smoke_prereqs(repo_root)
    mn_cleanup(repo_root)
    case_map = {case.name: case for case in build_smoke_cases()}

    outputs = []
    for name in selected_configs:
        outputs.append(
            run_single_smoke(
                repo_root=repo_root,
                python_bin=python_bin,
                case=case_map[name],
                base_output_dir=output_base,
                timeout_seconds=timeout_seconds,
                tmp_dir=tmp_dir,
            )
        )
    return outputs


def cleanup_outputs(output_base: Path) -> None:
    """Delete output directories after a successful run."""
    if output_base.exists():
        shutil.rmtree(output_base)


def main() -> int:
    args = parse_args()
    repo_root = find_repo_root(args.repo_root)
    python_bin = venv_python(repo_root)

    smoke_outputs: list[Path] = []
    output_base = args.output_base.resolve() if args.output_base else default_output_base()
    output_base.mkdir(parents=True, exist_ok=True)
    tmp_dir = args.tmpdir.resolve() if args.tmpdir else output_base / "_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    print(f"repo_root={repo_root}")
    print(f"python_bin={python_bin}")
    print(f"output_base={output_base}")
    print(f"tmp_dir={tmp_dir}")

    if not args.skip_pytest:
        run_pytest_phase(repo_root, python_bin, tmp_dir)
        print("[OK] pytest phase passed")

    if not args.skip_smoke:
        smoke_outputs = run_smoke_phase(
            repo_root=repo_root,
            python_bin=python_bin,
            selected_configs=args.configs,
            output_base=output_base,
            timeout_seconds=args.timeout_seconds,
            tmp_dir=tmp_dir,
        )
        print("[OK] smoke phase passed")

    if args.cleanup and smoke_outputs:
        cleanup_outputs(output_base)
        print("[OK] removed smoke artifacts")

    print("[OK] all requested checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI helper
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1)
