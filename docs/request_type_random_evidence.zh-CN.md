# random 来源证据现状与更新计划

日期：2026-06-26

状态：调查记录与后续计划。本文不定义第一版 Request Source Type Inference 的阻塞需求；在各来源对 random 的定义和证据记录方式清晰前，canonical `request_type` 推断可以先不产出 `random`，统一降级为 `unknown`。

## 背景

`random` 是真实的 Request Source Type 候选，但它不是 Requester Identity，也不是 requester 字段的空值状态。不能通过把 `requester_display_name` / `requester_user_id` 写成空、`NULL` 或 `"random"` 来表达随机来源。

当前暴露出的最严重问题是：watcher / playback-record origin 没有认真保留 VRC log 中可解析到的明确 random 证据。`playback_records.request_type` 为空本身不是问题；`request_type` 本来就是未来由 Request Source Type Inference 产出的投影。

## 当前调查结论

VRC log 中存在可稳定识别的 random 线索：

- WannaDance 日志里有 `PlayRandomVideo`。
- WannaDance `userData` 里有 `isRandom=true`，同时 `playerName` 为空。
- PyPy / VRCX `VideoPlay(PyPyDance)` 标题尾部可能带 `(Random)` marker。

这些线索应该作为 playback/source evidence 或 origin/provenance 的一部分保留，而不是被折叠成 requester 字段。

当前正式数据库里的状态不一致：

- `vrc_log_replay` 的许多历史播放记录 `request_type` 是 `NULL`，这是预期内的，因为它们等待未来统一推断。
- 部分 replay origin 只保留了 source file、line range 和 parser names，没有保留 `source_hint`、`source_type`、`requester_marker` 或 `isRandom` 这样的 random 证据摘要；这会导致只读数据库时无法直接解释 random，必须回源日志重算。
- 新 live watcher 路径里已经出现过 `request_type=random` 的记录，但这不应成为新推断模块的输入或约束。

VRCX 历史不能稳定证明 random：

- VRCX `gamelog_video_play` 没有可靠保存 `(Random)` 或 `isRandom` 语义。
- blank requester 不等于 random；不知道就是不知道。
- 现有 importer 曾经把 blank requester 解释成 random，这是 legacy 兼容或旧推断，不应作为新 canonical inference 的事实。

## 已决定边界

第一版 Request Source Type Inference 不需要实现 `random` 推断。它可以保留读取 random evidence / candidate 的能力，但 canonical 输出可以先降级为 `unknown`，直到各来源的 random 定义和证据记录方式清晰。

Request Source Type Inference 不追溯、审判或纠正来源可靠性。它不应该为了证明某条历史记录是不是 random 而重新打开 VRC log、比较 provenance 可信度，或修复旧 watcher / importer 的语义。需要修复时，应由 watcher 证据记录升级、重导入、数据修复或专门的 random evidence rebuild 处理。

现有 `playback_records.request_type` 不能影响新推断。我们是来推断它的，不是被旧投影、旧 precedence 或旧 `playback_request_type.py` 影响。

UI 可以提供明确的用户展示偏好，例如把未知来源降级显示为 random，但这只能是 UI 层展示或用户判断，不能写回 raw evidence，不能擅自修改 imported evidence，也不能让 `unknown` 与 `random` 在数据层混淆。

## 后续计划

需要进一步分析或收集日志，确认玩家在房间里点击 `next song (random)` 时，各系统分别留下什么稳定信号。

watcher 升级时应保留明确的 random evidence 摘要，例如：

- source hint / source marker。
- random trigger 类型，如 `PlayRandomVideo`、`isRandom=true`、`title_marker_random`。
- 相关 source file 与 line range。
- 原始 event payload 或精简后的 origin JSON 字段。

未来如果要让 Request Source Type Inference 产出 canonical `random`，应先有测试覆盖：

- WannaDance `PlayRandomVideo`。
- WannaDance `isRandom=true`。
- PyPy / VRCX `(Random)` marker。
- blank requester 但无 random evidence 的 VRCX 历史行必须保持 `unknown`。
- 有 requester display name 但缺 requester user id 的记录必须保持 `unknown`，不能退成 `random`。

这些工作不阻塞 Dance Plan、`planned`、`recommend`、`self`、`other` 和 `unknown` 的第一版推断实现。
