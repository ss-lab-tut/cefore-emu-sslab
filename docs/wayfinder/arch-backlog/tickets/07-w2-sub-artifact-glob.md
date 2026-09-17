---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**W2 — sub-artifact double-glob 解消**: `content_ops.py:417` (log 用) と `result_detect.py:69` (detect_sub_success) が同一 `RNP0x*.out` glob + non-empty filter。clear_sub_output_artifacts (:52) も同 glob の 3 つ目。候補6 (result_detect → Verdict 吸収) と同時に行うのが合理的。

## Status (2026-08-23)

- 未着手。`RNP0x*.out` glob 3 箇所が現存: `content_ops.py:417`、`result_detect.py:52` (`clear_sub_output_artifacts`)、`result_detect.py:69` (`detect_sub_success`)。元記述 :409-414 / :66-67 / :49 から更新。
- (2026-09-17 訂正) 候補6 ([16](16-kouho6-result-detect-into-verdict.md)) は 95f175a (2026-09-02) で撤回済みのため、Task 末尾の「候補6 と同時に行う」ペアリングと「16 がこの ticket に blocked」は失効。glob 整理は runtime 内 (result_detect.py を runtime adapter として維持したまま) で行う。
