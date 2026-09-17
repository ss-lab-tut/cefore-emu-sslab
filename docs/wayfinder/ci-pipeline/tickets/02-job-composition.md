---
status: closed
type: grilling
claimed-by: claude-code
blocked-by: []
---
## Question

pytest 以外に CI へ何を載せるか（ruff check / mypy / coverage / format gate /
その他の追加候補）。

## Resolution (2026-08-01)

採用: **ruff check + mypy + coverage + uv lock --check + entry-points 検査**。
- uv lock --check: lock/pyproject drift 検知（実測で pytest>=8.0 宣言 vs lock 9.0.2 の類のズレあり）
- entry-points 検査: `uv sync` はプロジェクト本体を入れないため `[project.scripts]`
  破損は現状どのテストも検出不能 → `uv pip install -e .` + `--help`×3 で塞ぐ
- config examples 検証: pytest テストとして追加（ticket 06 で置き場所確定）

不採用: **ruff format gate**（54 files 大整形 + blame 汚れの引き換えを却下、再訪可）、
**mutation workflow_dispatch ジョブ**（v1 外、round 2 の別 effort へ）。

## Status (2026-09-17)

- done: ci.yml の 4 jobs（test: pytest+coverage / lint: ruff check / typecheck: mypy / packaging: editable install + `--help`×3）と全 job の `uv lock --check` で実装（832ffe3、PR #19 merge 8c346c5）。examples 検証は a940011（PR A merge 63608b7）。却下案は [ADR-0004](../../../adr/0004-ci-guards-unit-surface-only.md) Consequences。
