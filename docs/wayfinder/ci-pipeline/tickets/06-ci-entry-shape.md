---
status: closed
type: grilling
claimed-by: claude-code
blocked-by: []
---
## Question

CI は各ツールを直接叩くか、run_cefore_checks.py --skip-smoke を単一エントリに
するか。config examples 検証の置き場所はどこか。

## Resolution (2026-08-01)

**直接叩く + examples 検証は pytest テスト化**。run_cefore_checks.py は smoke
込みのローカル総合判定器で、CI 用に coverage/lint を組み込むと責務が肥大化する。
CI の各 step は素の 1 コマンドで、YAML を読めば gate が一目で分かる形に。
examples 検証を pytest テスト（tests/core/config/test_example_configs.py）に
すると、cefore-run-tests の pytest phase は `pytest tests` を丸ごと回すため
**runner にも CI にも自動で乗る**（専用 phase 案は CI から見えなくなるため不採用。
ユーザーの「cefore-run-tests に追加」意向はこの包含関係の提示後に本案で確定）。

## Status (2026-09-17)

- done: ci.yml の各 step は素の 1 コマンド（832ffe3）、examples 検証は `tests/core/config/test_example_configs.py`（a940011）。[ADR-0004](../../../adr/0004-ci-guards-unit-surface-only.md) Consequences に記録。
