---
status: open
type: task
claimed-by:
blocked-by: []
---
## Task

**R8候補 — legacy 障害サイクル (down_\*) + legacy キャッシュ設定 (cache_count) の廃止**:
2026-07-02 の R7-1 grilling で user が廃止意向を表明、behavior-preserving な OptionSpec 統合と混ぜると differential gate が無意味になるため分離した。2026-07-07 の即時fixで `down_interval`/`down_duration` の省略 default は 0/0 になり、no-failure config は暗黙 flap を起動しなくなった。残るR8決定は [ADR-0002](../../../adr/0002-failure-config-resolves-to-explicit-policy.md): bootstrap 時に `FailurePolicy` へ一度だけ解決し、legacy `down_*` OptionSpec 5つ (down_stagger 含む、2026-09-02 訂正)・`periodic_host_flap`・summarizer legacy metadata・`min_failure.yaml` smoke 証拠・`cache_count`/`down_count+1` fallback を同時に整理する。追記 (2026-07-09, B1 fix 時に発見): `failure_scenarios: "none"` (文字列リテラル) は ADR-0002 が「省略と等価で許可」と定めるのに、現状 `_validate_failure_scenarios` が `'must be a dict'` で reject する — ADR 未実装ギャップ。"none" 許可は FailurePolicy 解決 (mode=none) の一部として R8 で実装すること。`down_count=5` は cache fallback の二役が残るため即時fixでは維持した。
_Avoid_: `down_count` default だけを単独で 0 化すること、legacy down_\* 廃止を cache fallback 再設計なしで進めること、min_failure の gate 証拠を代替なしで消すこと

## Status (2026-08-23)

- 未着手。`FailurePolicy` は src/tools/tests で 0 hits。
- legacy `down_*` OptionSpec は 4 つではなく **5 つ** 現存 (2026-09-17 訂正、95f175a / a455bc7): `validator.py:343` `down_interval` / :353 `down_duration` / :363 `down_exclude` / :372 `down_count` / :382 `down_stagger`。これとは別に legacy cache 設定 `cache_count` が :392。
- `periodic_host_flap`: `failure_manager.py:19` (def)、`runtime/__init__.py:50` / :128 (lazy export)、`disaster.py:259` (呼び出し)。
- cache fallback `self._down_count + 1` は `cache_manager.py:220`。
- `failure_scenarios: "none"` は依然 `validator.py:798-802` で `'must be a dict'` reject (ADR-0002 未実装ギャップ、上記追記のとおり R8 の mode=none として実装)。旧記述 :747-751 は 7a545f8 以前の行。
- (2026-09-17 訂正) S5 同梱の判断は不要になった: S5 ([02](02-s5-validate-flap-descriptor.md)) は 7a545f8 (2026-08-25) で単独解消済み。duration/interval >= 1 への tightening は引き続き R8 の scope。
- ADR-0002 の `## Status note (2026-09-02)` が記すコードとの乖離 2 点を着手時に決着させること: (1) legacy `down_*` OptionSpec は 5 つ (上記)、(2) validator の `failure_scenarios.strategy` 集合は `simple / cyclic / random / manual` (`validator.py:805`) だが ADR は cycle mode を `cycles` と呼び `random`/`manual` に触れていない — `FailurePolicy` の mode にするか別 policy にするか、綴りの統一を含めて判断する。
