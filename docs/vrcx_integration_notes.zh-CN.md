# VRCX 集成笔记

> 隐私说明：玩家名、日志文件名及事件时间已匿名化；示例路径需替换为本地实际路径。聚合统计与技术结论保留。

日期：2026-05-17

英文对应文档：`docs/vrcx_integration_notes.md`

## 目标

评估本地 VRCX 数据能否作为可靠的跳舞播放历史来源，并记录这对
`dancing-log` 的开源边界和数据模型意味着什么。

## 开源边界

代码和个人数据必须分开。

推荐布局：

- `dancing_log/`：只放源码
- `docs/`：设计笔记和公开文档
- `data/`：本地派生数据，git 忽略
- `analysis/`：本地临时分析文件，git 忽略
- `.env` 或未来配置文件：本地路径和用户配置，git 忽略

仓库不应该包含：

- 原始 VRCX 数据库副本
- 个人 VRChat 标识
- 本地日志
- 生成的跳舞历史快照

## 推荐的点歌来源模型

当前使用的来源枚举：

- `queued_self`：自己提前排进清单，比临时自点更强的意图
- `self`：自己现场点歌
- `recommend`：来自本工具的每日推荐
- `other`：别人点歌
- `random`：世界或系统随机
- `unknown`：无法可靠判断

注意：

- `queued_self` 和 `self` 应该在分析里分开。
- `recommend` 不等同于 `self`，即使最后是用户确认跳的。
- `random` 是一类真实来源，不应该合并进 `unknown` 或 `other`。

这些值描述的是 Request Source Type，当前存储在 `playback_records.source_type`。
它们和 Evidence Source Priority 分开，后者当前存储在
`playback_records.source_priority`，表示多条 playback record 重叠或冲突时的证据强度。
重复导入可以刷新 VRCX staging 溯源，但不应该把 accepted row 上更强的 Request Source
Type，例如 `queued_self`，降级回 VRCX 推断出的 `random`。Request Source Type 不决定
effective playback acceptance；accepted、excluded、needs-attention 投影属于 playback
evidence、Evidence Source Priority 冲突规则和当前有效的 manual playback decision。

## 存储方向

SQLite 是当前主存储，CSV 只作为导出格式。

SQLite 更合适的原因：

- 项目已经需要读另一个 SQLite 来源，也就是 `VRCX.sqlite3`
- 播放历史是事件流，不只是简单表格
- 来源推断需要 join、过滤、去重和回填
- 未来分析用 SQL 会比手写 CSV 变换更稳
- 仍然可以导出目录或历史快照供检查

当前方向：

- 主数据库：`data/dancing_log.sqlite3`
- 可选导出：
  - WannaDance 目录通过 `sync-wanna --write-files` 导出 CSV/JSON
  - 跳舞历史未来可加 CSV 导出
  - 推荐快照未来可加 CSV 导出

## 本地 VRCX 发现

从本地 `path/to/vrcx-snapshot` 副本里确认过这些重要文件：

- `VRCX.sqlite3`
- `VRCX-WorldData.db`

`VRCX.sqlite3` 里的关键表：

- `gamelog_video_play`

字段：

- `created_at`
- `video_url`
- `video_name`
- `video_id`
- `location`
- `display_name`
- `user_id`

其他相关表：

- `gamelog_location`
- `gamelog_join_leave`
- `gamelog_event`
- `gamelog_resource_load`

这说明 VRCX 已经保存了一份可用的本地播放历史。

2026-06-21 追加检查了本地身份相关线索；检查范围只包括 schema、配置 key 名和聚合
计数，不读取配置值、cookie 或完整 `VRCX.json`：

- VRCX 会创建形如 `usr<32 hex>_...` 的本地账号作用域表。单一账号前缀可以转换回
  标准 VRChat `usr_00000000-0000-0000-0000-000000000000` 形状。
- `configs` 表是 key/value 结构，但身份候选检测只需要看 key 名，不需要读取 value。
- `gamelog_video_play`、`gamelog_join_leave` 和账号作用域 friend log 表都能提供
  `display_name` + `user_id` 映射。
- 实测样本中，`gamelog_video_play` 有 387 个 distinct `display_name` / `user_id`
  pair，`display_name` 对多个 `user_id` 的情况为 0，`user_id` 对多个 display name
  的情况为 14。这更像是改名历史，而不是显示名歧义。

## VRCX 源码确认的信息

已检查仓库：

- `vrcx-team/VRCX`

相关文件：

- `src/services/database/gameLog.js`
- `src/coordinators/gameLogCoordinator.js`
- `src/stores/gameLog/mediaParsers.js`
- `src/services/gameLog.js`
- `Dotnet/LogWatcher.cs`
- `Dotnet/AppApi/Cef/Folders.cs`

源码确认：

- VRCX 会把视频播放事件写进 `gamelog_video_play`
- VRCX 自己的 game log 和 session 视图也会使用这些事件
- VRCX 有一些舞蹈或媒体世界的特殊 parser，比如 PyPyDance、VRDancing、ZuwaZuwaDance、LSMedia、PopcornPalace
- parser 会把事件规整成类似 `VideoPlay` 的形状，包括时间、URL、展示名、推断 user id 和位置

## 真实播放事件来源

真正上游不是 `VRCX.sqlite3`，而是 VRChat 的 Unity output logs。

Windows 路径：

```text
%LOCALAPPDATA%Low\VRChat\VRChat
```

文件模式：

```text
output_log_*.txt
```

VRCX 的 `LogWatcher` 会扫描这些日志，识别视频播放事件，再由 JS 侧解析和写入
`gamelog_video_play`。

数据层级可以理解为：

1. VRChat `output_log_*.txt` 是真实事件来源。
2. VRCX `LogWatcher` 是 parser/tailer。
3. VRCX `gamelog_video_play` 是持久化缓存。
4. `dancing-log` 优先从 VRCX SQLite 导入历史，未来再考虑直接解析 VRChat 日志做实时捕获。

## 当前实现状态

VRCX importer 已实现于 `dancing_log/vrcx_importer.py`，入口命令：

```bash
uv run python main.py import-vrcx
uv run python main.py import-vrcx "path/to/vrcx-snapshot/VRCX.sqlite3"
uv run python main.py import-vrcx --dry-run
```

VRCX 数据库路径也可以配置在 `config/dancing-log.local.json` 的 `vrcx_db_path`。

当前 importer 会：

- 读取 `gamelog_video_play`
- 解析支持的 WannaDance 和实测 PyPyDance 播放 URL
- 写入 staging 溯源表 `vrcx_import_events`
- 写入 accepted Local Playback Evidence row 到 `playback_records`
- 如果解析到的 id 不在目录里，就创建 placeholder `dance_tracks`
- 根据 requester 字段推断 `self`、`other`、`random` 或 `unknown`
- 跳过不支持的舞蹈系统，避免误判成 WannaDance
- 重复导入时保留更强的来源推断

ADR 0003 和 ADR 0004 之后，`dance_events` 是用于兼容、迁移和排查的 Legacy
Playback Root，`vrcx_import_events` 是导入 staging 溯源。普通 Timeline 和 Insights
读取 accepted `playback_records`，当前 importer 会直接创建这些记录。

当前支持的 WannaDance URL 包括公开 API host、实测 API-compatible host、Kiva
上游 host，以及支持的 CDN 文件 URL 模式。实测 PyPyDance API URL 也会解析为
`pypydance:<id>`。

Dudu、VRDancing 和其他系统目前只识别为 unsupported 或 unknown，等看到真实
元数据形状后再扩展。

实时原始日志捕获单独实现在 `dancing_log/vrc_log_watcher.py`，入口命令：

```bash
uv run python main.py watch-vrc-log
```

基础命令是默认 live watcher workflow。它会 tail VRChat `output_log_*.txt`，把 session
存到 `logs/captures/`，并在 folded observation 有稳定舞蹈身份后写入 watcher-derived
`playback_records`。如需额外把 folded state 镜像到 deprecated 的
`live_playback_events` 取证表，运行 `watch-vrc-log --live-db`。

watcher 默认读取 `config/dancing-log.local.json` 的 `vrc_log_dir`，否则回退到 Windows
LocalLow 下的 VRChat 标准日志目录。默认从当前日志文件末尾开始，避免游玩时重扫旧
日志；新建日志文件会从头读取，避免漏掉启动阶段信号。

折叠后的 playback 行保留 `first_seen_at`、`resolved_at`、`video_loaded_at`、
`actual_play_at`、`delay_to_actual_seconds`、`load_to_actual_seconds` 等延迟字段，
也保留 `source_type`、`source_display_name` 等来源字段。

实测捕获里有两类可用 actual-play 路径：

- WannaDance/USharpVideo 会暴露 `DelayedVideoReady` 和 `OnVideoStart`；正常开播时
  request-to-play 延迟稳定在约 10 秒。
- PyPyDance 会出现第二条带正数播放 offset 的 VRCX `VideoPlay` 信号；watcher 用
  `timestamp - offset` 作为近似 `actual_play_at`，并标记
  `actual_play_method = vrcx_progress_offset`。

半路观察会排除在 delay metrics 外。PyPyDance 大 offset 会标记
`observed_mid_play` 和 `elapsed_at_first_seen_seconds`；WannaDance 的
`Playing synced` 会写入 `synced_play_at`。

## 实时 watcher 性能和方向

当前 `watch-vrc-log` 已经足够轻，可以作为实时层继续演进。它每 0.25 秒轮询一次，
用 `readline()` 读新增日志行，先用低成本 token 过滤大部分行，只有视频相关候选行才
进入较重的 parser。

第五轮真实捕获 `analysis/vrc_log_capture/2026-05-17_171055` 约 7.6 分钟：

- raw 日志 5546 行，约 12 行/秒
- candidate 165 行
- parsed signal 57 个
- 折叠后 playback event 9 首
- VRCX 同时间窗：VRCX 9 行，watcher 9 行，0 漏捕，0 多捕
- candidate 读取延迟：min 0.125s，avg 0.571s，max 1.23s，p95 约 1.026s

和 VRCX 相比，思路相似但目标更窄。VRCX 的 C# `LogWatcher.cs` 也没有依赖
`FileSystemWatcher`，而是在后台线程轮询 VRChat 日志目录，记录文件 offset，用
`FileShare.ReadWrite` 打开日志，再把规整后的 raw events 交给前端。前端再通过
`gameLogCoordinator.js`、各世界的 media parser，以及 `gamelog_video_play` 等
SQLite 写入完成持久化。

`watch-vrc-log` 的优势不是历史覆盖；历史导入仍应优先使用 VRCX SQLite。它的优势是
我们可以掌握一个低延迟实时层，并保存 VRCX video table 没有的字段：
`actual_play_at`、`actual_play_method`、`observed_mid_play`、
`elapsed_at_first_seen_seconds`、来源字段、resolve/load 时序和 raw line 溯源。

## 实时数据库和 OBS 叠加层

实时更新管线保留 JSONL 取证输出，同时增加可选运行时状态：

- `PlaybackEventBuilder` 会在折叠后的 playback event 每次变化时触发 update callback。
- `live_playback_events` 会在 request、resolve、load、progress、sync、actual-play
  信号到来时持续 upsert。
- `playback_events.jsonl` 仍然作为 session artifact，适合调试，也适合把真实 capture
  回放成测试 fixture。
- 本地 overlay server 可以这样启动：

```bash
uv run python main.py watch-vrc-log --overlay-port 8765
```

服务只绑定 `127.0.0.1`，提供给 OBS Browser Source 的页面：

```text
http://127.0.0.1:8765/overlay
```

overlay 页面通过 server-sent events 读取同一份 live state。它显示：

- 当前时钟时间
- 当前曲目标题
- 舞蹈系统和 external id
- requester/source，包括 `random` 和玩家名
- 已播放 / 总时长，若 duration 已知
- 进度条
- 可选小号 debug 行，显示 delay method、sync/mid-play、source file 等

页面应完全本地自包含：不依赖外部字体、图片、CDN 或网络请求。OBS 应能在整场录制中
保持打开，不受联网状态影响。

### WannaDance 运行时 duration 来源

实时 watcher 和 overlay 里的 WannaDance duration 必须来自 VRChat 日志中的运行时信号。
overlay 不应依靠主数据库的信息补运行时字段：不要从 `dance_tracks`、`wannadance_songs`、
目录同步结果、收藏数据或已落库的 catalog metadata 反查 duration。主数据库可以作为
watcher-derived `playback_records` 和可选 deprecated `live_playback_events` 取证 row
的写入目标，但不能作为 overlay 当前状态的事实来源。

历史日志里有两个可用的日志侧 duration 来源：

1. `PlayQueueVideo` / `PlayRandomVideo` 日志行里的 `videoDuration = N`。
2. `VideoQueueManager` queue metadata，包括 `queue info serialized` 和
   `syncedQueuedInfoJson` JSON 里的 `duration`。

对 `analysis/vrc_logs` 的历史日志统计：

- queue JSON 读到 452 条 duration，覆盖 75 个唯一 song id。
- `PlayQueueVideo` / `PlayRandomVideo ... videoDuration` 读到 78 条 duration，覆盖 74 个唯一 song id。
- 折叠后的 127 次 WannaDance 播放里，两个来源都有 24 次，只有 queue JSON 39 次，只有
  `videoDuration` 54 次，两个都没有 10 次。

对当前 VRChat 日志目录 `%USERPROFILE%\AppData\LocalLow\VRChat\VRChat` 的统计：

- queue JSON 读到 68 条 duration，覆盖 29 个唯一 song id。
- `PlayQueueVideo` / `PlayRandomVideo ... videoDuration` 读到 65 条 duration，覆盖 61 个唯一 song id。
- 折叠后的 85 次 WannaDance 播放里，两个来源都有 20 次，只有 queue JSON 12 次，只有
  `videoDuration` 45 次，两个都没有 8 次。

在这些样本中，两个来源同时存在时没有发现 duration 不一致。`DeserializeVideoUserData`
JSON 没有携带 duration；WannaDance 的 VRCX `VideoPlay` payload 里 duration 是
`114514` 哨兵值，不能当真实时长。

因此 runtime 取值优先级应是：

1. 优先使用当前播放附近的 `PlayQueueVideo` / `PlayRandomVideo ... videoDuration`。
2. 没有时，再使用 queue JSON，但必须先用 `songId` 匹配到当前播放。
3. 如果两个来源都存在且冲突，记录 anomaly，不能静默覆盖。
4. 如果没有任何运行时 duration，overlay 只显示 elapsed，不从 catalog 或主数据库回填。

Live watcher 工作流默认会在 folded observation 有稳定舞蹈身份后 materialize
watcher-derived `playback_records`。新记录先是 `pending`、`counts_in_history = 0`、
`status_reason = live_observation_pending`。watcher 观察到已知时长至少 80% 后会把记录
settle 为 accepted；下一首过早出现、离开房间、退出 VRChat、视频系统关闭或 graceful
watcher stop 出现在自动接受前，则 settle 为不计入历史的 `needs_attention` 证据。

`--live-db` 是 deprecated experimental 输出，只额外把 folded state 镜像到
`live_playback_events`。正常 watcher evidence 属于 `playback_records`；overlay/live
status 应使用运行时内存状态。

当前 watcher/overlay 行为基于 2026-05-17 和 2026-05-18 的真实 live capture 收口：

- 离开房间、退出应用、视频系统 shutdown 会清空 overlay 当前播放，并中断 pending live row。
  进入房间状态会在更新的播放事件到来后自动让位。
- WannaDance `PreviewVideo` 会开启预览抑制窗口，避免歌曲卡片预览被误认成当前播放。
  如果之后同一首歌出现真正的 VRCX `VideoPlay`，抑制会被解除。
- 同一首歌在开始播放后短时间内出现 retry/resolve，会合并回已有 playback event，保留
  VRCX 曲名和 requester 字段，不再生成一个只显示 URL 的 current row。
- `Playing synced` 只记录为 `synced_play_at`，不会清空 overlay，也不会让 row 变成
  `observed_mid_play`。
- 真正半路进房由明确的正 progress offset 判断。这类 row 可以保持为 overlay 的 pending
  current playback，但在 watcher settlement 前不会自动进入 accepted history。

## 还不能完全确定的事

这些来源区分仍然不能只靠 VRCX 保证：

- `queued_self` vs `self`
- requester 空白时的 `other` vs `random`

空白 requester 可能代表：

- 随机播放
- parser 限制
- 世界没有提供点歌人身份
- 从状态恢复的播放事件，不是一次显式点歌

所以剩下的难点不是“能不能拿到播放历史”，而是“能不能以足够置信度推断来源语义”。

## 从 VRCX 检测本机身份

从 VRCX 只读推断 `self_user_id` 候选是可行的。

推荐流程：

1. 从 VRCX 的账号作用域表名和安全的配置 key 名里提取候选 `usr_...`。
2. 如果只找到一个候选 id，再从 `gamelog_video_play` 和 `gamelog_join_leave` 查它
   最近或最常见的 `display_name`。
3. UI 用 display name 让用户确认，因为它比原始 `usr_...` 更直观。
4. 保存时仍保存稳定的 `self_user_id`，不要把 display name 当身份主键。

display name 只适合做确认标签。它可能改名，也理论上可能重复；真正用于 VRCX 导入和
后续回填判断 `self` / `other` 的，仍然应该是稳定的 `usr_...`。

如果 VRCX 里出现多个本地账号候选，或一个 display name 对应多个 `user_id`，辅助检测
应该让用户明确选择，或者保持手动填写；不要静默猜测。

## 推荐下一步

1. 继续收集真实 PyPyDance、Dudu、VRDancing 和其他舞蹈系统的 VRCX 行作为 fixture。
2. 为带正 playback offset 的真实 PyPyDance 半路进房行为增加 fixture。
3. 增加一个只读 VRCX 身份辅助检测，用 display name 给用户确认，背后写入
   `self_user_id`。
4. 看到输入形状后，再为每个新舞蹈系统设计自己的扩展表。
5. 增加一个修正或回填命令，用来处理现有 `unknown` 来源。身份辅助检测也可以用于
   回填：当附近播放或 player-history 风格记录里的 `display_name` 映射无歧义时，
   恢复稳定 VRChat `user_id`，再回填 `self` 或 `other`。

## 结论

VRCX 路线是可行且值得优先支持的。

它已经足够支持：

- 自动导入大量播放历史
- 对大部分记录区分 self 和 non-self
- 从 WannaDance URL 解析 song id

它还不足以无人工干预地保证所有来源分类，特别是 `queued_self` 和部分空白 requester
行。
