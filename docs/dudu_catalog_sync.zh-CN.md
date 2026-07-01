# DuDu FitDance 目录记录

> 隐私说明：玩家名、日志文件名及事件时间已匿名化；示例路径需替换为本地实际路径。聚合统计与技术结论保留。

日期：2026-07-01

英文对应文档：暂无

## 目的

本文记录 DuDu FitDance 官网曲库、公开 API 和 VRChat 日志里已经观察到的数据形状。
它目前是解析和未来目录同步的依据，不表示已经有完整的 `sync-dudu` 命令。

当前状态应描述为“实验性支持”：实现已经能把样本中观察到的 Dudu 播放证据识别为
`dudu` 系统，并把 live watcher/VRCX 里能确定的播放写入 `playback_records`。
它还不能宣称完整支持 DuDu FitDance；目录批量同步、更多场景和更多日志样本仍待验证。

## 官网来源

### 曲库页面

页面：

```text
https://www.dudufit.dance/zh/videos/
```

页面是官方中文曲库入口，提供按歌名、歌手、舞者或 ID 搜索的前端视图。页面本身
通过前端组件加载曲库数据；HTML 里还能看到 VRChat 群组链接：

```text
https://vrc.group/DUDU.1300
```

### 公开 API

当前可读接口：

```text
https://api.dudufit.dance/api/v1/videos?cdn=sha
```

2026-06-30 检查到：

- `timestamp`: `1782753707`
- `videos`: 2249 条
- `groups`: 11 组

顶层字段：

- `timestamp`
- `videos`
- `groups`

`videos` 条目字段：

- `id`
- `name`
- `artist`
- `dancer`
- `volume`
- `hflip`
- `start`
- `end`
- `original_published_at`

`groups` 条目字段：

- `name`
- `videos`

已观察到的分组包括：

- `Golfy Dance Fitness`
- `Fitness Marshall`
- `TML Crew`
- `DuDu FitDance`
- `Just Dance Series`
- `Southvibes`
- `FitDance`
- `Mylee Dance`
- `Michael Jackson: The Experience`
- `ACG Dance`
- `Other FitDance`

API 里包含 id `0` 的 Dudu 自身条目，说明 `0` 不能当作空值处理。

## 播放 URL

日志和 VRCX 里观察到三类当前可解析 URL。

Dudu API 视频 URL：

```text
https://api.dudufit.dance/api/v1/videos/<id>
https://api.dudufit.dance/api/v1/videos/<id>?cdn=sha
```

解析后的视频 CDN URL：

```text
https://api-ddfd.imkiva.com/videos/<id>-<hash>.mp4?...
https://global-cdn.dudufit.dance/videos/<id>-<hash>.mp4?...
```

官网曲库 URL：

```text
https://www.dudufit.dance/zh/videos/<id>
```

缩略图 URL 在日志里也能看到，但当前不作为播放身份：

```text
https://api.dudufit.dance/thumbnails/<id>.jpg
```

另外，2026-07-01 的本地观察里还看到过以下边界：

- `backup-cdn.dudufit.dance`：由 `cdn=backup` 重定向得到，需补样本后再决定是否作为
  可解析 CDN host。
- `api-hkg.dudufit.dance`：VRCX 里有 1 条较早的 legacy API 记录，当前
  importer 尚未解析，需确认是否是 Dudu 官方历史节点。

## 日志形状

Dudu 在 VRChat 日志里的核心来源是 `VideoQueueHandler`。

队列同步行：

```text
[VideoQueueHandler.OnDeserialization] Queue data = [...]
```

队列 JSON 条目中已观察到：

- `title`
- `playerName`
- `group`
- `groupName`
- `duration`
- `songVolume`
- `songId`

当前播放元数据行：

```text
[VideoQueueHandler.DeserializeVideoSongData] deserialize video data: {...}
```

当前播放 JSON 中已观察到：

- `ver`
- `id`
- `shuffle`
- `info`
- `user`
- `url`
- `flip`
- `volume`
- `group`
- `starttime`
- `dancer`
- `artist`
- `title`

真实开始播放信号：

```text
[VideoQueueHandler.OnVideoPlay] VizVid callback: video playback started
```

live watcher 采用保守的实验性折叠：先记录队列/当前播放元数据，看到
`OnVideoPlay` 后才把最近的 Dudu 元数据作为 actual play。

## 常见 requester display

样本里 `playerName`/`user` 经常是：

```text
ExamplePlayerA
```

这只是实测样本中常见的 display name，不是仓库里的默认 identity。解析器不会主动
把空 requester 补成 `ExamplePlayerA`，也不会根据 display name 推断 VRChat user id。
VRCX 或日志里缺少 user id 时，`requester_user_id` 保持为空，以尊重真实来源数据。

## 当前本地观察（2026-07-01）

### 活动时间和样本范围

样本中观察到由玩家组织的 Dudu 活动；具体活动日程和组织者已匿名化。
活动安排不是解析 contract，解析器不应依赖星期或固定时间判断 Dudu 播放。

当前 `logs/source-vrc-logs` 中能解析出 Dudu 证据的文件：

- `output_log_sample_01.txt`
- `output_log_sample_02.txt`
- `output_log_sample_03.txt`

当前解析器从这些日志中看到的 Dudu 信号：

- `metadata`: 1160 条
- `actual-play`: 54 条
- `parser:dudu_queue_info`: 808 条
- `parser:dudu_song_data`: 352 条
- `parser:dudu_on_video_play`: 54 条
- 唯一 Dudu `external_id`: 43 个

### requester 身份边界

Dudu 自己的队列/当前播放 JSON 里目前只看到 display 字段：

- 队列条目：`playerName`
- 当前播放：`user`

当前样本中它们基本都是 `ExamplePlayerA`，但这些 JSON 没有携带 VRChat `usr_...`
身份。原始 VRC 日志的通用 VRChat 行里能看到 `ExamplePlayerA` 的 join/sticker
相关身份映射，watcher 运行时也有 session-local requester identity enrichment：

- 能看到同一场日志里的 VRChat display name 与 user id 映射；
- 不能在 Dudu 播放 payload 内直接看到 requester user id；
- watcher 可以用同房间 `OnPlayerJoined` / `User Authenticated` 建立的当前映射，
  或离房附近的 `OnPlayerLeft` 过期映射，自动补 `requester_user_id`；
- 补全来源会记录为 `active` / `expired` / `payload`，缺少可用映射时仍保持为空；
- 当前实现不把 `ExamplePlayerA` 或任何 user id 当默认 requester。

2026-07-01 用当前 watcher 对全量 `logs/source-vrc-logs` replay 验证：

- 共 replay 55 个源日志文件；
- Dudu watcher playback records 为 47 条，只出现在上面三份 Dudu 日志中；
- 45 条自动补上 `ExamplePlayerA` 的 VRChat user id，来源均为 `active` 映射；
- 2 条保持空 user id，因为折叠后的 Dudu playback 没有 requester display name；
- 临时 `playback_records` 结果与 `playback_events.jsonl` 一致：47 条 Dudu 中 45 条有
  `requester_user_id`。

### 预览文件和重加载

当前日志能看到大量缩略图/图片加载与视频加载信号，例如：

- `thumbnails/<id>.jpg`
- `FetchVideoImages`
- `ApplyVideoImage`
- `VideoImageHandler`
- `Attempting to resolve URL`
- `BeginLoad`
- `OnVideoPlay`

这些足够让解析器忽略缩略图，把 `OnVideoPlay` 作为实际播放信号；但还不足以可靠区分：

- 预览文件 vs 正式播放文件；
- 用户主动重加载 vs 播放器内部重试/恢复；
- 同一首歌的预加载、重解析、失败重试之间的语义差异。

目前只把 `OnVideoPlay` 之后最近的 Dudu 元数据折叠为 actual play，不宣称支持
预览/重加载分类。

### CDN 节点推测

房间里观察到的节点类型是：全球、亚太、大陆、备用。官网组件未直接暴露这些中文
节点名到 URL 参数的映射；当前只能结合日志、VRCX、API 重定向和 HEAD 探测推测。

已观察/测试到的 `cdn` 参数与目标主机：

| 节点显示 | 推测参数 | 观察/测试目标 | 可信度 |
| --- | --- | --- | --- |
| 全球 | 无参数或 `global` | `global-cdn.dudufit.dance` | 较高 |
| 亚太 | `jpn` | 当前探测仍重定向到 `global-cdn.dudufit.dance`；VRCX 大量使用 `cdn=jpn` | 中等 |
| 大陆 | `sha` | `api-ddfd.imkiva.com` | 较高 |
| 备用 | `backup` | `backup-cdn.dudufit.dance` | 较高 |

注意：`cdn=<任意值>` 看起来可能生成 `<值>-cdn.dudufit.dance` 形式的重定向，
因此“有 302”本身不能证明节点真实可用；应以日志中实际出现、HEAD/GET 能访问、
或官方前端明确使用为准。

当前已在真实日志/VRCX 中看到的 `cdn` 值：

- 无参数：VRCX 26 条
- `jpn`：VRCX 70 条
- `sha`：VRCX 50 条
- `backup`：VRCX 1 条

当前已在真实日志或探测中看到的 Dudu 视频主机：

- `api.dudufit.dance`
- `api-ddfd.imkiva.com`
- `global-cdn.dudufit.dance`
- `backup-cdn.dudufit.dance`

### VRCX 导入观察

只读检查 `path/to/vrcx-snapshot/VRCX.sqlite3` 后，VRCX 中 Dudu-like 记录为 147 条：

- `api.dudufit.dance`: 146 条
- `api-hkg.dudufit.dance`: 1 条 legacy 记录

`api.dudufit.dance` 的 146 条可以被当前 importer 识别并导入为 Dudu
`playback_records`。这些记录的 VRCX requester display/user id 都为空，因此
当前 VRCX importer 只按 `gamelog_video_play` 行内字段保留 requester，不能从这些
空行内直接补出 `ExamplePlayerA` 身份。如果未来从 VRCX 其他 player-history 风格记录做
只读身份增强，应作为独立流程实现，而不是让 Dudu importer 默认猜测。

唯一的 `api-hkg.dudufit.dance` legacy 记录来自较早的样本，
URL 是 `http://api-hkg.dudufit.dance/api/v1/videos/0`，VRCX 行里带有
`ExamplePlayerD` 的 display/user id。当前 importer 尚未把 `api-hkg.dudufit.dance`
列为 Dudu API host，因此这 1 条目前会被跳过。是否纳入要单独确认它是否是
Dudu 官方历史节点或只是一条迁移期旧记录。

## SQLite 映射

当前已实现的是实验性播放证据映射，不是完整目录同步。

通过实验性解析确认的播放证据会写入通用 `dance_tracks`：

- `system_id`
- `external_id`
- `title`
- `artist`
- `dancer`
- `group_name`

其中 `system_id` 指向 `dance_systems.key = 'dudu'`，`external_id` 是 Dudu 的
视频 id。`player_count` 和 `major` 目前没有可靠来源，保持为空。

如果未来实现目录同步，通用字段可以从 API 的 `videos` 和 `groups` 推导：

- `external_id` <- `videos[].id`
- `title` <- `videos[].name`
- `artist` <- `videos[].artist`
- `dancer` <- `videos[].dancer`
- `group_name` <- `groups[].name` 反查 `videos` 列表

Dudu 专有扩展字段暂未建表。候选字段包括：

- `dudu_id`
- `volume`
- `hflip`
- `start_seconds`
- `end_seconds`
- `original_published_at`
- `thumbnail_url`
- 分组成员关系

是否需要单独的 `dudufitdance_songs` 表，要等真正实现 `sync-dudu` 时再定。

## 当前实现文件

- `dancing_log/vrc_log_parser.py`：实验性解析 Dudu 队列、当前播放元数据和实际播放信号。
- `dancing_log/live_playback_folding.py`：把 Dudu 元数据和 `OnVideoPlay` 保守折叠成播放证据。
- `dancing_log/vrcx_importer.py`：实验性解析 Dudu API/CDN/官网 URL，保守保留 requester 字段，不推断 user id。
- `dancing_log/storage.py`：定义 `dudu` 系统名。

## 与 WannaDance 的差异

- Dudu 暂无本地缓存目录配置，当前只有官网/API/日志来源。
- API 暂未提供 WannaDance 的 `playerCount` 或 `major` 等字段。
- 分组是顶层 `groups[].videos` 的反向关系，不是每个视频条目内的字段。
- 日志里的当前播放 JSON 已包含 `title`、`artist`、`dancer`、`group`，因此即使没有
  目录同步，也能为实际播放生成较完整的 `dance_tracks` 行。

## 待确认

- `timestamp` 与日志里的 `ver` 看起来像同一类目录版本，但暂未把它作为 contract。
- `cdn=sha` 和其他 `cdn` 参数是否只影响视频解析 URL，还是也会影响目录返回内容。
- 同一个视频是否可能同时属于多个分组；如果会，`dance_tracks.group_name` 只能保存
  其中一个展示值，完整分组关系需要扩展表。
- 是否存在更适合目录同步的分页、增量或单条详情接口。
