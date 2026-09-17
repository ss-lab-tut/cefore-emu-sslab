---
status: closed
type: task
claimed-by:
blocked-by: []
---
## Task

**候補6 — `runtime/result_detect.py` を Verdict に吸収**:
74 LOC の薄い adapter。`detect_*` 5 関数は `from_runtime_*` Verdict factory の evidence-unpacking wrapper で、CONTEXT.md の Verdict `_Avoid_` リスト ("detect result") に名前が抵触。5 関数を `src/core/verdict.py` の runtime-adapter section に移管 + `timestamp_utc` は `src/core/paths.py` 等に分離 → `result_detect.py` 削除。Worth exploring。
_Avoid_: 名前を `result_detect` のまま残すこと、Verdict factory と別モジュールに散らすこと

## Resolution (2026-09-02) — 撤回

- 95f175a で撤回。`src/core/verdict.py` の module docstring が「This module is pure (no Mininet, no file IO) so the runtime adapter (src/runtime/result_detect) ... can all depend on it」と契約を明記しており、log/artifact/file IO/CommandResult/ccninfo を unpack する adapter を core へ入れるのはこの契約に反する。
- `src/runtime/result_detect.py` (現 125 LOC。Task 本文の 74 LOC は旧値) は runtime adapter として維持。[07 W2](07-w2-sub-artifact-glob.md) の glob 整理は runtime 内で行う。
- 名前が気になる場合に許容されるのは `verdict_adapter` への rename + compat shim まで。
- _Avoid_: core/verdict.py に Path/glob/file IO を持ち込むこと (Task 本文の _Avoid_ は撤回前の原案のもの)
- frontmatter は tracker 語彙 (open/claimed/closed) に withdrawn が無いため `status: closed` とし、撤回はこの節で示す。

## Status (2026-08-23, 撤回前の記録)

- 未着手。`src/runtime/result_detect.py` は現存。importer: `content_ops.py:24` (`from .result_detect import (...)`)、`results_sink.py:13` (`timestamp_utc`)。
- `src/core/verdict.py` に `detect_*` は無い (grep 0 hits)。
- [07 W2](07-w2-sub-artifact-glob.md) (同 glob の解消) と同時に行う (blocked-by)。→ 撤回により blocked-by は解除。
