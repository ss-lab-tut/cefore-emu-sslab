---
status: open
type: prototype
claimed-by:
blocked-by: [09]
---
## Question

（post-v1）GitHub-hosted runner 上で Cefore 0.12.0 をソースビルド（キャッシュ
付き）+ apt mininet + `min_putget.yaml` 1 本の smoke が成立するかを、捨て可能な
workflow_dispatch ブランチで実証する。成立したら non-required job としての追加を
新たな decision ticket に切る。不成立なら「smoke はローカル恒久」を ADR-0004 に
追記して close。

判断材料: ビルド時間 / キャッシュヒット率 / Mininet が runner のカーネル
機能（netns, OVS）で安定動作するか / flakiness。
