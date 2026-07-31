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

# .yaml だけでなく .yml/.json も対象にする。2026-08-01 レビュー実測: example.json
# は *.yaml glob から漏れ、消えても suite が green のままになる穴があった —
# 拡張子の列挙と下の期待 inventory の両方で塞ぐ。
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


# 期待 inventory は意図的に完全固定 (2026-08-01 review fix: 非空 + smoke 13 本
# だけの assert では example.json や非-smoke example の消失が素通りだった)。
# example の追加/削除は必ずこの manifest の更新を伴う = 意図的な変更であること
# を強制する。
_EXPECTED_EXAMPLES = _SMOKE_EXAMPLES | frozenset(
    {
        "autotest_hot.yaml",
        "autotest_minimal.yaml",
        "disaster_auto_min.yaml",
        "disaster_bandwidth.yaml",
        "example.json",
        "example.yaml",
        "flexible_cache.yaml",
    }
)


def test_example_discovery_is_complete():
    """glob の空振り・example inventory の増減を検出する。"""
    names = {path.name for path in EXAMPLE_FILES}
    assert names == _EXPECTED_EXAMPLES, (
        "config/examples inventory drifted: "
        f"missing={sorted(_EXPECTED_EXAMPLES - names)} "
        f"unexpected={sorted(names - _EXPECTED_EXAMPLES)}"
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
