---
status: open
type: task
claimed-by:
blocked-by: [07]
---
## Task

**候補6 — `runtime/result_detect.py` を Verdict に吸収**:
74 LOC の薄い adapter。`detect_*` 5 関数は `from_runtime_*` Verdict factory の evidence-unpacking wrapper で、CONTEXT.md の Verdict `_Avoid_` リスト ("detect result") に名前が抵触。5 関数を `src/core/verdict.py` の runtime-adapter section に移管 + `timestamp_utc` は `src/core/paths.py` 等に分離 → `result_detect.py` 削除。Worth exploring。
_Avoid_: 名前を `result_detect` のまま残すこと、Verdict factory と別モジュールに散らすこと

## Status (2026-08-23)

- 未着手。`src/runtime/result_detect.py` は現存。importer: `content_ops.py:24` (`from .result_detect import (...)`)、`results_sink.py:13` (`timestamp_utc`)。
- `src/core/verdict.py` に `detect_*` は無い (grep 0 hits)。
- [07 W2](07-w2-sub-artifact-glob.md) (同 glob の解消) と同時に行う (blocked-by)。
