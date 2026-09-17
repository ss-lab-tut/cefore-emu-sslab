---
status: closed
type: grilling
claimed-by: claude-code
blocked-by: []
---
## Question

coverage を gate にするか、床値をいくつにするか、artifact をどう残すか。

## Resolution (2026-08-01)

**fail_under=85 + artifact 常時 upload**。実測 89.93% に対し 4.9pt バッファの
保守的な床 — 「大規模なテスト削除だけを止め、日常の増減では鳴らない」regression
検知。fail_under は pyproject `[tool.coverage.report]` に置き、ローカルと CI で
同一判定。`--cov-context=test` で回して `.coverage`/`cov.json` を毎回 artifact
保存（2026-09-17 訂正: 実装では `.coverage` のみ upload。cov.json は下記 Status 参照） — issue 16 の「covering set は陳腐化する」警告への回答で、mutation round 2
の covering-set 再導出材料になる。ratchet（毎回床上げ）は mypy baseline と同種の
脆さのため不採用。

## Status (2026-09-17)

- done: `fail_under = 85`（pyproject `[tool.coverage.report]`）と `.coverage` artifact upload（832ffe3、PR #19 merge 8c346c5）。
- 訂正: artifact は `.coverage`（SQLite、contexts を含む）**のみ**。`show_contexts` の cov.json は同データで 142 MB あり生成しない（ci.yml の upload-artifact 直前コメントと [ADR-0004](../../../adr/0004-ci-guards-unit-surface-only.md) coverage 節）。
