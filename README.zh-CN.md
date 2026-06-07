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

数据库把三个概念拆开：

- `dance_systems`：舞蹈系统，比如 `wannadance`。
- `dance_tracks`：某个舞蹈系统里的一个可播放舞蹈条目。
- `music_tracks`：真实音乐曲目，可以被多个舞蹈版本共用。

WannaDance 专有缓存字段放在 `wannadance_songs`，不放在
`dance_events`。一次播放事件指向 `dance_events.dance_track_id`，再指向
`dance_tracks.id`。

核心表：

- `dance_systems`
- `dance_tracks`
- `wannadance_songs`
- `music_tracks`
- `dance_track_music_links`
- `dance_events`
- `vrcx_import_events`

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

不带 `--live` 时，命令使用更严格的正式历史口径，只读取 `dance_events`。
`--live` 会读取实时表 `live_playback_events`，适合检查
`watch-vrc-log --live-db` 当时观察到了什么；但它可能包含没有提升到正式历史的
live row，包括 `interrupted` 或 `pending` 记录。

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

如果 `config/dancing-log.local.json` 里配置了 `vrcx_db_path`，路径可以省略：

```bash
uv run python main.py import-vrcx
```

当前 importer 支持 WannaDance URL。PyPyDance、Dudu 和其他系统会被统计为
unsupported，不会误判成 WannaDance。

## 实时 VRChat 日志和 OBS Overlay

捕获 VRChat Unity 输出日志：

```bash
uv run python main.py watch-vrc-log
```

启用实时 SQLite 状态和本地 OBS overlay：

```bash
uv run python main.py watch-vrc-log --live-db --overlay-port 8765
```

overlay 地址是 `http://127.0.0.1:8765/overlay`。它只绑定本机，通过
server-sent events 更新，不依赖外部字体、图片、CDN 或网络请求。

`live_playback_events` 会随着日志信号即时更新；`dance_events` 只有在显式传入
`--promote-live` 且 live row 严格完整播放已知 `duration_seconds` 后才会写入。
半路进房、带正 progress offset、未播完离开、未播完切歌、两次播放间隔小于曲目时长的记录
都不会进入正式历史。

watcher 会识别离开房间和 VRChat 退出/视频系统关闭日志，用它们清空 overlay 当前播放，
并把尚未完成的 live row 标记为 `interrupted`。进入房间状态只会显示到更新的播放事件
到来为止，避免没有当前曲目时残留旧的“Entering Room/进入房间”状态。

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
进入正式历史。

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

## 本地配置

本机路径放在 `config/dancing-log.local.json`，该文件会被 git 忽略。

支持字段：

```json
{
  "self_user_id": null,
  "vrcx_db_path": null,
  "vrc_log_dir": null,
  "wanna_cache_dir": null,
  "recordings_dir": null
}
```

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
- `docs/vrcx_integration_notes.zh-CN.md`
- `docs/music_api_research.zh-CN.md`

## 研究脚本

`scripts/match_netease.py` 和 `scripts/test_music_apis.py` 仍然是研究工具，
不是当前运行时数据模型的一部分。

`scripts/init_songs.py` 已废弃，因为运行时数据库不再有 `songs` 表。
