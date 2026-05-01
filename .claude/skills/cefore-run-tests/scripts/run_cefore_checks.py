#!/usr/bin/env python3
"""Run targeted pytest coverage and minimal disaster smoke checks."""

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

PYTEST_TARGETS = (
    "tests/runtime/test_cefore.py",
    "tests/scenarios/test_disaster_pubsub.py",
)
SMOKE_CONFIGS = ("min_putget", "min_pubsub", "min_pubsub_verify", "min_empty", "min_mixed")


@dataclass(frozen=True)
class SmokeCase:
    """Single smoke test configuration."""

    name: str
    config_relpath: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run targeted pytest checks and minimal disaster smoke configs."
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
    """Create a timestamped output base under /tmp."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return Path("/tmp/cefore-run-tests") / stamp


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
    """Run the targeted pytest files."""
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


def build_smoke_cases() -> list[SmokeCase]:
    """Return the known smoke configs."""
    return [
        SmokeCase("min_putget", "config/examples/min_putget.yaml"),
        SmokeCase("min_pubsub", "config/examples/min_pubsub.yaml"),
        SmokeCase("min_pubsub_verify", "config/examples/min_pubsub_verify.yaml"),
        SmokeCase("min_empty", "config/examples/min_empty.yaml"),
        SmokeCase("min_mixed", "config/examples/min_mixed.yaml"),
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


def validate_min_putget(data: list[dict]) -> None:
    """Validate the normal put/get smoke output."""
    if not data:
        raise RuntimeError("min_putget expected at least 1 result")
    for row in data:
        if not row.get("success"):
            raise RuntimeError("min_putget contains an unsuccessful result")
        if not row.get("has_completed_log"):
            raise RuntimeError("min_putget contains a row without completed-log marker")
        if not row.get("has_output_file"):
            raise RuntimeError("min_putget contains a row without output artifact")


def validate_min_pubsub(data: list[dict]) -> None:
    """Validate the pub/sub smoke output."""
    if not data:
        raise RuntimeError("min_pubsub expected at least 1 result")
    for row in data:
        if not row.get("success"):
            raise RuntimeError("min_pubsub contains an unsuccessful result")
        if not row.get("has_output_file"):
            raise RuntimeError("min_pubsub contains a row without output artifact")
        if row.get("has_completed_log"):
            raise RuntimeError("min_pubsub should not rely on completed-log detection")
        if "RNP0x" not in str(row.get("out_file", "")):
            raise RuntimeError("min_pubsub out_file does not point to an RNP0x*.out artifact")


def validate_min_empty(data: list[dict]) -> None:
    """Validate the empty-op smoke output."""
    if data != []:
        raise RuntimeError(f"min_empty expected [], got {data!r}")


def validate_min_mixed(data: list[dict]) -> None:
    """Validate the mixed normal/pubsub smoke output."""
    if not data:
        raise RuntimeError("min_mixed expected at least 1 result")
    if not all(row.get("success") for row in data):
        raise RuntimeError("min_mixed contains unsuccessful results")

    file_rows = [row for row in data if row.get("uri") == "ccnx:/test/file"]
    stream_rows = [row for row in data if row.get("uri") == "ccnx:/test/stream"]
    if not file_rows or not stream_rows:
        raise RuntimeError("min_mixed missing one or more expected URIs")
    if not all(row.get("has_completed_log") for row in file_rows):
        raise RuntimeError("min_mixed file URI is missing completed-log markers")
    if not all(row.get("has_output_file") for row in stream_rows):
        raise RuntimeError("min_mixed stream URI is missing output artifacts")
    if any(row.get("has_completed_log") for row in stream_rows):
        raise RuntimeError("min_mixed stream URI should keep has_completed_log == false")


def validate_results(case_name: str, data: list[dict]) -> None:
    """Dispatch per-config result validation."""
    validators = {
        "min_putget": validate_min_putget,
        "min_pubsub": validate_min_pubsub,
        "min_pubsub_verify": validate_min_pubsub,
        "min_empty": validate_min_empty,
        "min_mixed": validate_min_mixed,
    }
    validators[case_name](data)


def run_single_smoke(
    repo_root: Path,
    python_bin: Path,
    case: SmokeCase,
    base_output_dir: Path,
    timeout_seconds: int,
    tmp_dir: Path,
) -> Path:
    """Run one config-driven disaster smoke test and validate its results."""
    config_path = repo_root / case.config_relpath
    ensure_exists(config_path, f"smoke config {case.name}")

    case_output_dir = base_output_dir / case.name
    case_output_dir.mkdir(parents=True, exist_ok=True)

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
    validate_results(case.name, data)
    print(f"[OK] {case.name}: {results_path}")
    return case_output_dir


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
