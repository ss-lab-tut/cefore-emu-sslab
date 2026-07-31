"""config/examples/ の全設定ファイルが schema 検証を通ることを固定するテスト。

CI (ADR-0004) とローカルの cefore-run-tests pytest phase の両方で走る、
example の schema-drift 防止線。validator を deepening し続けるこのリポで、
「README や smoke が参照する example が静かに invalid 化する」事故を検出する。

保証範囲は raw parse (load_config) + schema 受理 (validate_config) まで。
CLI merge / validate_merged_args / 実行可能性は保証しない — min_*.yaml の
root smoke (cefore-run-tests) の代替ではない。
"""

from pathlib import Path

import pytest

from src.core.config.loader import load_config, validate_config

EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "config" / "examples"

# .yaml だけでなく .yml/.json も対象にする。example.json は YAML glob から
# 漏れて消失しても green のままだった前歴があるため、拡張子を列挙して拾う。
_PATTERNS = ("*.yaml", "*.yml", "*.json")

EXAMPLE_FILES = sorted(
    path for pattern in _PATTERNS for path in EXAMPLES_DIR.glob(pattern)
)

# glob が静かに空振りすると個別テストが 0 件収集で green になってしまうので、
# discovery 自体を検証対象にする。smoke が使う min_*.yaml 13 本は、消えたら
# cefore-run-tests の証拠構成が壊れるため存在を明示的に固定する。
_SMOKE_EXAMPLES = frozenset(
    {
        "min_ccninfo.yaml",
        "min_compute.yaml",
        "min_empty.yaml",
        "min_event_link.yaml",
        "min_event_pubsub.yaml",
        "min_event_putget.yaml",
        "min_failure.yaml",
        "min_mixed.yaml",
        "min_monitoring.yaml",
        "min_pubsub.yaml",
        "min_pubsub_verify.yaml",
        "min_putget.yaml",
        "min_putget_class_a.yaml",
    }
)


def test_example_discovery_is_complete():
    """glob の空振り・smoke 用 example の消失を検出する。"""
    names = {path.name for path in EXAMPLE_FILES}
    assert names, f"no example configs found under {EXAMPLES_DIR}"
    missing_smoke = _SMOKE_EXAMPLES - names
    assert not missing_smoke, (
        f"smoke examples missing from config/examples/: {sorted(missing_smoke)}"
    )


@pytest.mark.parametrize(
    "example_path", EXAMPLE_FILES, ids=lambda p: p.name
)
def test_example_config_validates_clean(example_path: Path):
    """全 example が load_config + validate_config を errors なしで通る。"""
    config = load_config(example_path)
    errors = validate_config(config)
    assert errors == [], (
        f"{example_path.name} failed schema validation: {errors}"
    )
