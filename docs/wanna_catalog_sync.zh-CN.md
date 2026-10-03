# WannaDance 目录同步

日期：2026-05-17

英文对应文档：`docs/wanna_catalog_sync.md`

## 目的

`dance-trail` 会把 WannaDance 目录元数据保存到本地 SQLite 数据库中，让播放事件
可以指向稳定的舞蹈条目，同时还能展示歌名、歌手、舞者、分组、人数和本地缓存路径。

目录同步使用两个来源：

- WannaDance 公共 API：权威的公开目录元数据。
- 本地 `wanna_cache_dir`：`config/dance-trail.local.json` 中配置的本地下载缓存。

即使 API 不可用，本地缓存仍然有价值，因为每个缓存歌曲目录里可能有
`metadata.json`、`download.txt` 和 `video.mp4`。

## 命令

在线同步：

```powershell
uv run python main.py sync-wanna
```

离线或只用本地缓存：

```powershell
uv run python main.py sync-wanna --offline
```

导出 CSV/JSON 供检查：

```powershell
uv run python main.py sync-wanna --write-files
```

指定缓存目录：

```powershell
uv run python main.py sync-wanna --cache-dir "D:\path\to\wannadance-song"
```

如果当前 shell 没有 `uv`，也可以用已经安装依赖的 Python 环境：

```powershell
python main.py sync-wanna
```

在 Codex 沙箱中，`uv` 可能需要提权执行，因为 runner 进程可能被沙箱权限拦住。

## 数据来源

### 公共 API

接口：

```text
https://x.kiva.moe/api/v2/wanna/songs
```

使用字段：

- `id`
- `name`
- `artist`
- `dancer`
- `playerCount`
- group `title`
- group `major`

`disablePublic=true` 的行会被跳过，重复 song id 会去重。

### 本地缓存

配置方式：

```json
{
  "wanna_cache_dir": "D:\\path\\to\\wannadance-song"
}
```

期望结构：

```text
wannadance-song/
|-- 1/
|   |-- metadata.json
|   |-- download.txt
|   `-- video.mp4
`-- 10000/
    |-- metadata.json
    |-- download.txt
    `-- video.mp4
```

有用的缓存字段：

- `id`
- `category`
- `title`
- `titleSpell`
- `playerIndex`
- `volume`
- `start`
- `end`
- `flip`
- `skipRandom`
- `checksum`
- `url`
- `urlForQuest`

同步时会记录本地 `metadata.json`、`download.txt` 和 `video.mp4` 的路径。

## SQLite 存储

当前运行时数据库不再有 `songs` 表。

WannaDance 同步会把通用条目字段写入 `dance_tracks`：

- `system_id`
- `external_id`
- `title`
- `artist`
- `dancer`
- `player_count`
- `group_name`
- `major`

WannaDance 专有字段写入 `wannadance_songs`：

- `wanna_id`
- `cache_category`
- `cache_title`
- `cache_title_spell`
- `cache_player_index`
- `cache_volume`
- `cache_start_seconds`
- `cache_end_seconds`
- `cache_flip`
- `cache_skip_random`
- `cache_checksum`
- `cache_url`
- `cache_url_for_quest`
- `local_video_path`
- `local_metadata_path`
- `local_download_path`
- `cache_updated_at`

当标题和歌手都存在时，同步还会创建：

- 一个基于归一化标题/歌手的 `music_tracks` 行
- 一个 `dance_track_music_links` 行，`match_method = 'title_artist_auto'`

`favorite` 和 `want_to_learn` 这类本地标记保存在 `dance_tracks`，目录 upsert
时会保留。

NetEase/Kugou 等平台 id 和热度字段不属于当前运行时 schema。

## 合并规则

1. 先加载本地缓存元数据。
2. 使用缓存 `title` 作为标题 fallback。
3. 如果 API 可用，用 API 元数据覆盖，因为它有更完整的歌手、舞者、人数、分组和大分类。
4. 按 `(system_id, external_id)` upsert 通用字段到 `dance_tracks`。
5. 按 `dance_track_id` upsert WannaDance 专有字段到 `wannadance_songs`。
6. 标题和歌手存在时，upsert 音乐曲目和舞蹈到音乐的映射。

同步不会删除最新 API 或本地缓存里缺失的目录行。已有播放历史可能仍然引用它们。

## 当前本地快照

2026-05-17 检查到的本地数据库快照：

- `dance_tracks`: 10,204
- `wannadance_songs`: 10,204
- `music_tracks`: 7,378
- `dance_track_music_links`: 9,782

这些数字是本地派生数据，不是仓库源码的一部分。

## 生成文件

默认只更新 SQLite：

- `data/dance_trail.sqlite3`

传入 `--write-files` 时，会额外导出检查用 CSV/JSON：

- `data/wanna_songs.csv`
- `data/wanna_songs.json`

旧的 `data/songs.csv` 不再是运行时来源。

这些文件会被 git 忽略，属于本地派生数据。

## 实现文件

- `dance_trail/wanna_catalog.py`：目录加载、合并、导出和 SQLite upsert。
- `dance_trail/storage.py`：SQLite schema 和共享 upsert helper。
- `scripts/sync_wanna_songs.py`：命令行包装。
- `main.py`：暴露 `sync-wanna` 命令。
