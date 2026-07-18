# dancing-log

> 隐私说明：玩家名、日志文件名及事件时间已匿名化；示例路径需替换为本地实际路径。聚合统计与技术结论保留。

`dancing-log` 是一个本地 VRChat 跳舞播放时间线工具。它记录：

- 播放了什么舞蹈曲目
- 什么时候播放
- 来源是什么，比如自己点歌、别人点歌、随机、推荐、预排清单
- 播放事件如何映射回舞蹈系统目录、真实音乐曲目和未来的录屏

当前实现使用 SQLite 作为运行时状态。CSV/JSON 只作为临时导入、导出和检查产物。

英文版入口见 `README.md`。

## 当前数据模型

数据库把四个概念拆开：

- `dance_systems`：舞蹈系统，比如 `wannadance`。
- `dance_tracks`：某个舞蹈系统里的一个可播放舞蹈条目。
- `music_tracks`：真实音乐曲目，可以被多个舞蹈版本共用。
- `playback_records`：Timeline、复查和 Insights 使用的 Local Playback Evidence。

WannaDance 专有缓存字段放在 `wannadance_songs`，不放在
播放历史行里。一次播放记录指向 `playback_records.dance_track_id`，再指向
`dance_tracks.id`。

核心表：

- `dance_systems`
- `dance_tracks`
- `wannadance_songs`
- `music_tracks`
- `dance_track_music_links`
- `playback_records`

过渡和取证表：

- `dance_events`
- `vrcx_import_events`
- `live_playback_events`

`dance_events`、`vrcx_import_events` 和 `live_playback_events` 在过渡期是
Legacy Playback Root、staging 溯源或运行时观察表。它们可以继续用于兼容、迁移和
排查，但普通 Timeline 读取基于 `playback_records` 的 effective playback projection，
Insights、daily report 和 recommendations 读取 effective accepted projection。
手动 log、VRCX import、queued-self sync 和 watcher-derived live evidence 现在都会把
Local Playback Evidence 写入 `playback_records`。

暂缓设计的表：

- 音乐平台匹配，比如 NetEase、Kugou、Last.fm、Spotify 的 id
- 热度、评论数、播放量等随时间变化的快照

更多设计原因见 `docs/dance_data_model.zh-CN.md`。

## 快速开始

查看命令入口：

```bash
uv run python main.py
```

如果当前 shell 没有 `uv`，也可以用已经安装依赖的 Python 环境：

```bash
python main.py
```

在 Codex 沙箱中，`uv` 可能需要提权执行，因为 runner 进程可能被沙箱权限拦住。

同步 WannaDance 本地目录：

```bash
uv run python main.py sync-wanna
uv run python main.py sync-wanna --offline
```

归档旧生成数据，并根据本地配置重建干净数据库：

```bash
uv run python main.py rebuild-data --archive-existing
```

重建流程会保留：

- `config/dancing-log.local.json`
- `data/queued_self/`

会归档这些生成文件：

- `data/dancing_log.sqlite3`
- `data/songs.csv`
- `data/wanna_songs.csv`
- `data/wanna_songs.json`

## 日常命令

手动记录一次跳舞，需要明确舞蹈系统：

```bash
uv run python main.py log --system wannadance 5038
uv run python main.py log --system wannadance 5038 --other
uv run python main.py log --system wannadance 5038 --source random
uv run python main.py log --system wannadance 5038 --note "nice run"
uv run python main.py log --system wannadance 5038 --time "2000-01-01T12:00:00+08:00"
```

这里的 `5038` 是所选系统内的外部 id，不是 `dance_tracks.id`。

生成推荐：

```bash
uv run python main.py recommend
uv run python main.py recommend -n 10
```

打印某个本地日期的舞蹈记录，每行一条：

```bash
uv run python main.py day 2026-06-07
uv run python main.py day 2026-06-07 --live
```

每行格式是 `HH:MM:SS song-id. song name`，例如：

```text
12:00:00 8378. Party In The U.S.A. - Miley Cyrus | Just Dance 2025
```

普通每日历史读取 accepted `playback_records`。不带 `--live` 时读取所有 accepted
历史；`--live` 会过滤到来源为 `live_watcher` 的 accepted 记录。实时 watcher
证据会统一进入 `playback_records`；`live_playback_events` 只保留为 deprecated
实验/取证路径。

当前推荐分数使用：

- 收藏标记
- 想学标记
- 已跳次数
- 距离上次跳舞的天数

NetEase/Kugou 等平台热度目前没有进入运行时推荐分数。

## VRCX 导入

从 VRCX 导入历史播放记录：

```bash
uv run python main.py import-vrcx "path/to/vrcx-snapshot/VRCX.sqlite3"
uv run python main.py import-vrcx --dry-run
```

如果 `config/dancing-log.local.json` 里配置了 `vrcx_db_path`，路径可以省略。该字段为空时，importer 也会在本次运行中尝试标准 VRCX 数据库 `%APPDATA%/VRCX/VRCX.sqlite3`，但不会把自动检测结果写入配置：

```bash
uv run python main.py import-vrcx
```

当前 importer 支持 WannaDance URL 和实测 PyPyDance URL；对实测 DuDu FitDance
API/CDN/官网 URL 是实验性识别。其他系统会被统计为 unsupported，不会误判成
WannaDance。

## 实时 VRChat 日志和 OBS Overlay

监听 VRChat Unity 输出日志、写入 capture artifacts，并把有稳定舞蹈身份的 watcher
观察写成 watcher-derived Local Playback Evidence：

```bash
uv run python main.py watch-vrc-log
```

不启动 Web UI、只运行 watcher 时，可以启动独立的本地 OBS overlay：

```bash
uv run python main.py watch-vrc-log --overlay-port 8765
```

此独立 CLI 模式的 overlay 地址是 `http://127.0.0.1:8765/overlay`。它只绑定本机，通过
server-sent events 更新，不依赖外部字体、图片、CDN 或网络请求。停止 standalone overlay
服务时，会同时关闭已接收的普通 HTTP 连接和 SSE 流，并在对应 handler 全部退出后才返回。

watcher 会在启动维护前为应用根目录和实际 SQLite 数据库取得操作系统级排他锁，并持续持有
到 settlement、数据库提交、capture artifact 清理和 finalizer 全部结束。因此 CLI、Web UI
和托盘工作流不能在相同应用或数据库范围内并行启动冲突 watcher。

普通 watcher 路径会在 folded event 有稳定 dance identity 后直接写入
`playback_records`。新记录先是 `pending + counts_in_history=0`，后续 watcher
settlement 再把它更新成 accepted 或 needs-attention。`live_playback_events`
在正式场景下 deprecated；如需额外保留 legacy forensic table，可使用实验参数：

```bash
uv run python main.py watch-vrc-log --live-db
```
半路进房、带正 progress offset、未播完离开、未播完切歌、两次播放间隔小于曲目时长的记录
会进入 Timeline 复查，但在结算前或未被接受前不会进入 accepted history。

watcher 会识别离开房间和 VRChat 退出/视频系统关闭日志，用它们清空 overlay 当前播放，
并结算尚未完成的 watcher-derived playback record。graceful stop 也会先判断是否
满足自动接受条件；否则写成不计入历史的 needs-attention 记录。进入房间状态只会显示
到更新的播放事件到来为止，避免没有当前曲目时残留旧的“Entering Room/进入房间”状态。

WannaDance 的 `PreviewVideo` 会抑制预览播放器带来的 load/resolve/start 噪声；如果之后
出现真正的 VRCX `VideoPlay`，同一首歌仍会被接受为真实播放。同一首歌的 retry/resolve
信号会合并回当前 playback event，所以 overlay 会保留 VRCX 曲名，不会退回显示原始 URL。

WannaDance 的 `PlayQueueVideo` / `PlayRandomVideo ... videoDuration` 和
`VideoQueueManager` queue JSON 只会作为运行时 metadata 解析。它们可以给真实 playback
event 补 `songId`、曲名、点歌人、duration 和 `duration_source`，但不会单独创建播放事件，
也不依赖 catalog DB。

WannaDance/PyPyDance 的 `Playing synced` 行现在只记录为 `synced_play_at`，不会单独
清空 overlay，也不会直接把 live row 判定为半路播放。半路播放以 VRCX 的正 progress
offset 等明确偏移信号为准；这类 row 会作为 pending current 显示在 overlay 上，但不会
在 watcher settlement 前自动进入 accepted history。

## Queued-Self 清单

queued-self 清单可以直接写外部 id。同步时通过命令行指定默认舞蹈系统：

```text
# 2026-04-17
5038 Good Time
```

如果一份清单需要混合多个系统，仍然可以写系统前缀：

```text
# 2026-04-17
wannadance:5038 Good Time
```

同步 queued-self 清单：

```bash
uv run python main.py sync-queued-self --system wannadance
```

## 本地 Web UI

启动主本地 Web UI：

```bash
uv run python main.py webui
uv run python main.py webui --port 8787 --no-open
```

Web UI 只绑定到 `127.0.0.1`，默认打开 `http://127.0.0.1:8787/home`。Home、Timeline、Catalog、Lists、Insights、Data Operations、Settings 分别使用 `/home`、`/timeline`、`/catalog`、`/lists`、`/insights`、`/data-operations`、`/settings`，刷新和浏览器前进后退都会保留当前页面。Timeline 的日期和倒序选择会写入查询参数。

桌面/Web UI 模式的 OBS overlay 共用同一个 HTTP 服务，地址为 `http://127.0.0.1:8787/overlay`；状态和 SSE 接口位于 `/api/overlay/state` 和 `/api/overlay/events`。此模式不会再为 overlay 占用第二个端口。停止实时 overlay 发布后，该页面会明确显示 `Overlay inactive`；只有 overlay 已启用、watcher 尚未捕获当前播放时才显示 `Waiting for playback`。即使 overlay 发布已禁用，Home 仍从独立的内存 Live Status 状态显示 watcher 当前播放；开关只控制面向 OBS 的投影。Settings 保存支持字段时，会把不认识的本地配置键作为只读值保留。UI 支持英语和中文，可在浏览器本地切换语言。

桌面应用退出时会先停止 Web UI 接收新请求并等待普通 HTTP handler 完成，再把实时会话不可逆地转入关闭状态。请求头和正文受单调时钟绝对期限约束；退出还会主动关闭尚未进入业务操作的连接。只有已收到并解析完整请求的 handler 才参与无界的可靠排空。这样可以等待同步 CLI watcher、后台 watcher 完成数据库提交、结算和 artifact 清理，而不会让慢速或半包请求永久卡住退出。SSE 连接使用独立的主动关闭和有界 drain；如果已受理的业务操作或 finalizer 永久卡住，进程会保留以便诊断，而不是冒险截断 SQLite 提交或留下不完整的 capture artifact。

## 应用目录与本地配置

本机路径放在 `config/dancing-log.local.json`，该文件会被 git 忽略。完整目录约定见 `docs/app_directories.zh-CN.md`。

支持字段：

```json
{
  "config_version": 1,
  "app_db": "data/dancing_log.sqlite3",
  "queued_self_dir": "data/queued_self",
  "capture_dir": "logs/captures",
  "run_log_dir": "logs/runs",
  "source_vrc_log_dir": "logs/source-vrc-logs",
  "recording_frames_dir": "analysis/recording_frames",
  "self_user_id": null,
  "vrcx_db_path": null,
  "vrc_log_dir": null,
  "wanna_cache_dir": null,
  "recordings_dir": null,
  "dance_day_boundary_time": "00:00",
  "auto_start_watcher": false,
  "auto_start_overlay": false,
  "overlay_port": 8765
}
```

`dance_day_boundary_time` 是一个跳舞日开始的本地墙钟时刻，使用操作系统的真实本地时区，可设置为 `00:00` 至 `06:00`。Timeline、day report、queued-self 匹配和每日推荐种子共同使用这一分界。

`overlay_port` 是不启动 Web UI 时供独立 watcher overlay 使用的高级兼容配置；桌面/Web UI 模式使用 Web UI 端口。

## 文档索引

英文文档：

- `docs/dance_data_model.md`
- `docs/app_directories.md`
- `docs/portable_release.md`
- `docs/wanna_catalog_sync.md`
- `docs/vrcx_integration_notes.md`
- `docs/music_api_research.md`

中文文档：

- `docs/dance_data_model.zh-CN.md`
- `docs/app_directories.zh-CN.md`
- `docs/portable_release.zh-CN.md`
- `docs/wanna_catalog_sync.zh-CN.md`
- `docs/dudu_catalog_sync.zh-CN.md`
- `docs/vrcx_integration_notes.zh-CN.md`
- `docs/music_api_research.zh-CN.md`

## 研究脚本

`scripts/match_netease.py`、`scripts/test_music_apis.py` 和 `sample-frames`
仍然是研究工具，不是当前运行时数据模型或 portable release 的一部分。

`sample-frames` 需要可选的录屏工具依赖：

```bash
uv sync --extra recording-tools
```

`scripts/init_songs.py` 已废弃，因为运行时数据库不再有 `songs` 表。
