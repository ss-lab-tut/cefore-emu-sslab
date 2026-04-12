#!/usr/bin/env python3
"""Run mesh disaster autotests repeatedly and summarize results."""

import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config.loader import load_config  # noqa: E402


def _resolve_seed(base_config: dict, seed_base: int | None, index: int) -> int:
    if seed_base is not None:
        return seed_base + index
    base_seed = base_config.get("seed", 42)
    if not isinstance(base_seed, int):
        base_seed = 42
    return base_seed + index


def _ensure_autotest_safe(base_config: dict) -> None:
    if base_config.get("bridge") or base_config.get("bridges"):
        raise SystemExit("base-config must not include bridge/bridges for autotest")
    if base_config.get("ext"):
        raise SystemExit("base-config must not include ext for autotest")


def _run_one(
    run_idx: int,
    args,
    base_config: dict,
    run_root: Path,
    num: int,
    seed: int,
) -> Path:
    run_root.mkdir(parents=True, exist_ok=True)
    logs_root = run_root / "logs"
    logs_root.mkdir(parents=True, exist_ok=True)

    cfg = copy.deepcopy(base_config)
    cfg["num"] = num
    cfg["seed"] = seed
    cfg["no_cli"] = True
    cfg["duration"] = args.duration
    cfg["results_json"] = "results.json"
    cfg["output_dir"] = str(logs_root)
    cfg["timestamp"] = False

    config_path = run_root / "config.used.json"
    config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    run_log_path = run_root / "run.log"
    py = sys.executable
    cmd = [
        py,
        "-m",
        "src",
        "disaster",
        "--config",
        str(config_path),
        "--no-cli",
        "--duration",
        str(args.duration),
        "--results-json",
        "results.json",
    ]

    with open(run_log_path, "w", encoding="utf-8") as log_fp:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            stdout=log_fp,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )

    if proc.returncode != 0:
        raise SystemExit(f"run {run_idx} failed. see {run_log_path}")

    exp_dir = logs_root / f"ex{num}_seed{seed}"
    if not exp_dir.exists():
        candidates = sorted(logs_root.glob(f"ex{num}_seed{seed}*"))
        if not candidates:
            raise SystemExit(f"run {run_idx}: experiment directory not found under {logs_root}")
        exp_dir = candidates[0]

    result_path = exp_dir / "results.json"
    if not result_path.exists():
        raise SystemExit(f"run {run_idx}: results.json not found: {result_path}")

    index_path = run_root / "experiment_dir.txt"
    index_path.write_text(str(exp_dir) + "\n", encoding="utf-8")
    return result_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run cefore autotests repeatedly.")
    parser.add_argument("--base-config", required=True, help="base config (yaml/json)")
    parser.add_argument("--runs", type=int, required=True, help="number of runs")
    parser.add_argument("--out", required=True, help="output directory root")
    parser.add_argument("--duration", type=int, required=True, help="duration per run (sec)")
    parser.add_argument("--start-num", type=int, default=1, help="start experiment number")
    parser.add_argument("--seed-base", type=int, default=None, help="seed base (optional)")
    args = parser.parse_args()

    if args.runs < 1:
        raise SystemExit("--runs must be >= 1")
    if args.duration < 0:
        raise SystemExit("--duration must be >= 0")
    if os.geteuid() != 0:
        raise SystemExit("run.py must be executed with sudo/root")

    base_config = load_config(args.base_config)
    _ensure_autotest_safe(base_config)

    out_root = Path(args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    result_paths: list[Path] = []
    for i in range(args.runs):
        run_id = i + 1
        run_root = out_root / f"run_{run_id:04d}"
        num = args.start_num + i
        seed = _resolve_seed(base_config, args.seed_base, i)
        result_path = _run_one(run_id, args, base_config, run_root, num, seed)
        result_paths.append(result_path)

    analyze_cmd = [
        sys.executable,
        str(ROOT / "tools" / "autotest" / "analyze.py"),
        "--inputs",
        *[str(p) for p in result_paths],
        "--out-dir",
        str(out_root),
    ]
    proc = subprocess.run(
        analyze_cmd,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    summary_log = out_root / "analyze.log"
    summary_log.write_text(proc.stdout, encoding="utf-8")
    if proc.returncode != 0:
        raise SystemExit(f"analyze failed. see {summary_log}")


if __name__ == "__main__":
    main()
