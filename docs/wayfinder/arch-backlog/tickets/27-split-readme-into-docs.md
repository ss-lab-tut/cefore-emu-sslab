---
status: open
type: task
claimed-by:
blocked-by: []
category: enhancement
---
## Task

**2026-11-02 利用者提案: README の説明を docs/ へ分割**:
README.md と README_ja.md はそれぞれ約 700 行あり、説明が肥大化している。概要、依存、Quick Start など
最初に見えるべきものだけを README に残し、それ以外は docs/ の複数のファイルに分けて置く。
PR #42 は同じ README を整理しているが、構成の変更は README の中に閉じており、この分割は意図的に含めていない。

## Status (2026-11-02)

- 未着手。PR #42 のマージ後に始める（節の構成が PR #42 で変わるため）。
- 移す候補の規模（PR #42 時点の README.md の行数）: Configuration Files 228、Architecture 80、Topology Types 59、Log Summarization 55。

## 着手時に決めること

- README に残す範囲: 概要、依存、Quick Start の他に何を残すか。
- 分け方: docs/ の下のファイルの単位と名前。既存の `docs/adr/`、`docs/runbooks/`、`docs/known-cefore-behaviors.md` との役割分担も含む。
- 日本語版: 分割先のファイルも英日の両方を持つか。

## 着手時に確認すること

移動すると古くなる参照:

- `CLAUDE.md` の冒頭: architecture、project structure、command usage、configuration reference の参照先を README.md と案内している。
- `src/runtime/scheduler.py` のコメント: single-threaded `EventScheduler` の説明を README に求めている。
- `tests/core/config/test_example_configs.py` の docstring: README が example を参照している前提で書かれている。
- `pyproject.toml` の `readme`: README.md がパッケージの説明になる。分割後の README 内の相対リンクがパッケージの配布先で切れないか確かめる。
