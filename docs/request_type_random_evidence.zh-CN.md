# random 来源证据现状与更新计划

> 隐私说明：玩家名、日志文件名及事件时间已匿名化；示例路径需替换为本地实际路径。聚合统计与技术结论保留。

日期：2026-06-26

更新：2026-07-19

状态：真实 VRC output log 与 watcher 采集范围内的证据边界已经确认。watcher 只保存直接证据；下游 Request Source Type Inference 可以在存在本文定义的显式 random 证据时投影 `random`，没有显式证据时保持 `unknown`。VRCX 历史数据库不在这个已确认范围内。

## 背景

`random` 是真实的 Request Source Type 候选，但它不是 Requester Identity，也不是 requester 字段的空值状态。不能通过把 `requester_display_name` / `requester_user_id` 写成空、`NULL` 或 `"random"` 来表达随机来源。

当前暴露出的最严重问题是：watcher / playback-record origin 没有认真保留 VRC log 中可解析到的明确 random 证据。`playback_records.request_type` 为空本身不是问题；v2 `request_type` 是由已经纳入核心范围的 Request Source Type Inference 产出的可重建投影。

## 当前调查结论

VRC log 中存在可稳定识别的 random 直接证据：

- WannaDance `userData` 里有 `isRandom=true`，同时当前样本的 `playerName` 为空；`PlayRandomVideo` 是同一随机执行链的旁证。
- PyPyDance `[PyPyDanceQueue]` payload 使用 `playerName="Random"`；真实 PyPyDance URL 对应的 VRCX 标题尾部会派生出 `(Random)` marker。
- DUDU `DeserializeVideoSongData` payload 使用 `shuffle=true`，并输出相邻的 `is random = True` 文本。

这些线索应该作为 playback/source evidence 或 origin/provenance 的一部分保留，而不是被折叠成 requester 字段。

### 真实日志与 watcher 可使用的直接证据

本节只讨论真实 VRC output log 与 watcher 采集范围。`playerName` / `user` 是世界协议中的原始来源字段；canonical requester identity 是后续根据可信来源证据归一化出的概念。USharpVideo 的技术性 video owner / executor 证据只能保存在 origin/provenance 中，不能回退填充 requester。

watcher 只负责把这些观察做确定性整理并忠实写入证据表，同时保存原始 marker 和 provenance。它不负责汇总 durable `events` 表，不把多条观察解释成 canonical playback event，也不写出 `request_type`。下表描述的是 watcher 应保存的直接证据，不是 watcher 内部的类型推断规则。正式职责边界见 ADR 0013。

| 系统 | 判断 random 的原始直接证据 | 判断 requester 的原始直接证据 | 不能用于推断的字段 |
|---|---|---|---|
| WannaDance | `SerializeVideoUserData` / `DeserializeVideoUserData` JSON 中的 `isRandom=true`；`PlayRandomVideo` 只能作为旁证 | 同一 JSON 中非空的 `playerName` | USharpVideo 的 `requested by` 不是可靠 requester；blank requester 也不证明 random |
| PyPyDance | `[PyPyDanceQueue]` JSON 中的 `playerName="Random"`；真实 PyPy URL 对应的 VRCX 标题后缀 `(Random)` 可作为同一协议 marker 的派生旁证 | `[PyPyDanceQueue]` JSON 中非 `Random` 的 `playerName`；`[PyPyDance] <name> added song to queue` 可作为更直接的动作旁证 | blank requester 不证明 random；`VideoPlay(PyPyDance)` 标签不能代替 URL-derived system identity |
| DUDU | `DeserializeVideoSongData` JSON 中的 `shuffle=true`；相邻的 `is random = True` 文本可作为旁证 | 同一 JSON 中非空的 `user` | `user=""` 不证明 random |

下游 Request Source Type Inference 的最小规则是：显式 random 证据为真时可投影为 `request_type=random`，canonical requester 留空，但原始姓名和技术 owner 证据仍保存在 provenance 中；没有显式 random 证据且没有可信 requester 时投影为 `request_type=unknown`。任何系统都不能仅凭 requester 为空推断 random。以上 `request_type` 结论均不得由 watcher 写回证据表。

### WannaDance 真实事件链验证

当前69份 source log 中共找到2366行 `isRandom=true` payload；这些 payload 的 `playerName` 均为空。另有156次 random load 在相邻事件链中出现独立的 USharpVideo `Started video load ... requested by <name>`：

- 60次前面出现 `PlayVideo Button Clicked`，属于玩家手动触发上下文。
- 80次前面出现视频结束事件，属于自动续播上下文。
- 16次在可用局部窗口中无法确定触发上下文。

手动样本 `output_log_sample_04.txt` 的顺序是 `PlayVideo Button Clicked` → `RandomOnEnd` → `PlayRandomVideo()` → `isRandom=true, playerName=""` → USharpVideo `requested by 示例玩家乙`。自动样本 `output_log_sample_05.txt` 的顺序是 `OnVideoEnd` → `RandomOnEnd` → USharpVideo `requested by ExamplePlayerC` → `isRandom=true, playerName=""`。

这两类事件链证明：

- USharpVideo `requested by` 可以在手动随机和自动随机中同时出现，表达 video owner / executor，不能证明谁选择了歌曲，也不能证明手动触发。
- WannaDance 的 source display name 只能忠实取自世界 payload 的 `playerName`；技术性 `requested by` 只能保存到 origin/provenance，不能作为缺失 `source_display_name` 或 requester 的回退。
- `PlayVideo Button Clicked`、`OnVideoEnd`、`RandomOnEnd` 和 `PlayRandomVideo()` 都是原始日志事实；`manual` / `automatic` / `unknown` 是根据事件邻接关系作出的分析分类。当前产品不需要保存 canonical trigger type。

当前 `watcher_playback_materializer.py` 仍使用 `source_display_name or display_name`，可能把 USharpVideo 技术 owner 提升成 requester。这是已确认的 legacy 实现偏差，不是新 evidence contract；后续实现应移除该回退。即使 explicit random 时 canonical requester 留空，原始 `playerName` 和技术 owner 仍应分别保存在 provenance 中。

### PyPyDance `Random` 哨兵的经验边界

当前69份 source log 中找到23行 `[PyPyDanceQueue]` `playerName="Random"`，以及26行真实 PyPyDance URL 对应的 VRCX `(Random)`；VRCX 行包含同一次播放的起始/进度重复，因此两个计数不代表独立播放次数。同一批日志中没有发现名为 `Random` 的玩家加入、离开、认证或添加歌曲。

因此，当前 watcher contract 可以在 PyPyDance 专属 payload 中把精确的 `playerName="Random"` 保存为显式 random marker；VRCX `(Random)` 是同一字段的派生旁证，不是独立证明。这个规则是当前真实日志支持的协议惯例，不是 PyPyDance 提供的正式布尔字段。解析必须同时受 URL-derived `dance_system_key=pypydance` 和 PyPyDance payload 结构约束，并保留原始字符串，不能把其他上下文中的显示名 `Random` 泛化为随机。

当前正式数据库里的状态不一致：

- `vrc_log_replay` 的许多历史播放记录 `request_type` 是 `NULL`，这是预期内的，因为它们等待未来统一推断。
- 部分 replay origin 只保留了 source file、line range 和 parser names，没有保留 `source_hint`、`source_type`、`requester_marker` 或 `isRandom` 这样的 random 证据摘要；这会导致只读数据库时无法直接解释 random，必须回源日志重算。
- 新 live watcher 路径里已经出现过 `request_type=random` 的记录，但这不应成为新推断模块的输入或约束。

当前 portable database 快照中，`dance_system_key=pypydance AND request_type IS NULL` 共87条，其中65条来自 `vrc_log_replay`，22条来自 `vrc_log_live`。这87条不是全部随机；`NULL` 只表示尚未投影 Request Source Type。

其中至少15条可以由原始证据确认是随机：

- 13条 replay record 的 origin 保存了 source file 与 line range，回到对应原始日志后可看到 `playerName="Random"` / `(Random)`。
- 2条 live record 的 origin 可以关联到仍保存 `source_hint=random`、`source_type=random` 和 `requester_marker=Random` 的 legacy `live_playback_events` row。

这些 playback record 的 origin 标明 `adapter_version=oneoff-2026-06-25`、`migration_name=playback_records_v0_to_v1`。该一次性迁移没有把 legacy/source random 结论投影到 `playback_records.request_type`；部分 replay origin 又只保留了文件、行范围和 parser names。这解释了为什么记录仍是 `NULL`，以及为什么必须由 repair/rebuild 回源证据，而不能根据 `NULL` 本身猜 random。

VRCX 历史不能稳定证明 random：

- VRCX `gamelog_video_play` 没有可靠保存 `(Random)` 或 `isRandom` 语义。
- blank requester 不等于 random；不知道就是不知道。
- 现有 importer 曾经把 blank requester 解释成 random，这是 legacy 兼容或旧推断，不应作为新 canonical inference 的事实。

## 已决定边界

真实 VRC output log 与 watcher evidence 范围内的 provisional 暂缓结论已经结束：WannaDance `isRandom=true`、PyPyDance 专属 `Random` marker 和 DUDU `shuffle=true` 都是下游可以消费的显式 random 证据。存在这些证据时可投影 canonical `random`；没有显式 random 证据且无法建立可信 requester 时投影 `unknown`。VRCX 历史数据库中缺失 marker 的记录继续保持 `unknown`。

Request Source Type Inference 不追溯、审判或纠正来源可靠性。它不应该为了证明某条历史记录是不是 random 而重新打开 VRC log、比较 provenance 可信度，或修复旧 watcher / importer 的语义。需要修复时，应由 watcher 证据记录升级、重导入、数据修复或专门的 random evidence rebuild 处理。

现有 `playback_records.request_type` 不能影响新推断。我们是来推断它的，不是被旧投影、旧 precedence 或旧 `playback_request_type.py` 影响。

UI 可以提供明确的用户展示偏好，例如把未知来源降级显示为 random，但这只能是 UI 层展示或用户判断，不能写回 raw evidence，不能擅自修改 imported evidence，也不能让 `unknown` 与 `random` 在数据层混淆。

## 后续计划

当前真实日志样本中可直接使用的稳定信号已整理在上表。后续若世界协议变化、出现与当前规则冲突的新样本，或需要扩展到 VRCX 历史数据库等范围，应继续复核并更新证据边界。

watcher 升级时应保留明确的 random evidence 摘要，例如：

- source hint / source marker。
- 产生 random 结论的原始 marker，如 `PlayRandomVideo`、`isRandom=true`、`title_marker_random`；通过现有 parser/origin provenance 保留，不新增 canonical manual/automatic trigger type。
- 相关 source file 与 line range。
- 原始 event payload 或精简后的 origin JSON 字段。

实现或更新 Request Source Type Inference 的 canonical `random` 投影时，应有测试覆盖：

- WannaDance `isRandom=true`，并确认 USharpVideo `requested by` 不进入 requester。
- WannaDance `PlayRandomVideo` marker 被保存，但不被误写成 manual/automatic trigger type。
- PyPyDance queue `playerName="Random"` 和真实 PyPyDance URL 对应的 VRCX `(Random)` marker。
- DUDU `shuffle=true`。
- blank requester 但无 random evidence 的 VRCX 历史行必须保持 `unknown`。
- 有 requester display name 但缺 requester user id 的记录必须保持 `unknown`，不能退成 `random`。

random 投影仍属于独立 Request Source Type Inference，不属于 watcher、parser、evidence writer 或 ordinary read path。
