# dancing-log

> Privacy note: Personal paths and activity examples are anonymized. Replace example paths with your own; sample timestamps are illustrative. Aggregate results and technical conclusions are retained.

`dancing-log` 是一个面向 VRChat 舞蹈场景的本地记录与管理工具。它的核心目标不是单纯记一张歌单，而是维护一条可回看、可分析、可关联录像的舞蹈时间线。

项目目前围绕 [Wanna Dance](https://wanna.kiva.moe/) 歌曲库工作，已经包含歌曲数据抓取、歌曲热度补充、手动舞蹈记录和每日推荐。后续会扩展为实时记录 VRChat 播放事件、OBS overlay、录像文件索引和本地视频管理。

## 项目名

暂时建议继续使用 `dancing-log`。

这个名字的优点是边界足够清楚：它描述的是“舞蹈记录与时间线”，而不是 CDN、OBS 或某个具体世界。后续即使加入实时采集、录像索引和 overlay，它们仍然都服务于同一个核心对象：舞蹈记录。

不建议把本项目改名成包含 `cdn`、`obs` 或 `vrc` 的名字，因为这些都是数据来源或输出方式，不是核心领域。如果未来产品形态明显扩大，可以再考虑一个更上层的套件名，但当前仓库名保留 `dancing-log` 更稳。

## 总体设计

长期上只保留两个主要项目：

- `dancing-log`：舞蹈日志、歌曲库、事件采集、录像索引、overlay、推荐与分析。
- `local-cdn`：本地视频缓存/CDN 重构项目，只负责视频代理、缓存、文件规范和自己的运行日志。

两者相关，但职责不同。`local-cdn` 看到的是资源请求，适合记录缓存命中、下载、URL 到本地文件的映射；`dancing-log` 关心的是舞蹈事实，应该负责判断某首歌是否真的播放、何时播放、对应哪段录像。

### dancing-log 的职责

`dancing-log` 管理的是舞蹈时间线。时间线中的核心信息包括：

- 歌曲什么时候播放。
- 播放事件来自哪里，以及可信度如何。
- 对应哪个 Wanna Dance song id、原始视频 URL 和本地视频文件。
- 当时是否正在录屏。
- 对应哪个 OBS 录像文件、录像内偏移时间是多少。
- 实时 overlay 向 OBS 展示了什么。
- 后续如何统计、推荐、筛选、回看和导出。

因此，`dancing-log` 内部可以包含多个模块，但它们都围绕同一个数据库工作：

- 歌曲库管理。
- 舞蹈事件采集。
- VRChat 日志监听。
- VRCX 数据库导入。
- CDN 日志导入。
- OBS overlay 本地服务。
- 录像文件扫描与索引。
- 推荐与分析。

### local-cdn 的职责

`local-cdn` 应保持纯粹，只做 CDN 相关事情：

- 替代现有黑盒本地 CDN。
- 管理视频缓存。
- 规定本地视频文件放置位置和命名格式。
- 记录自己的运行日志。
- 暴露可供 `dancing-log` 读取的缓存、解析和文件映射信息。

`local-cdn` 不负责判断“这首歌是否真的被跳了”。原因是 CDN 请求可能来自世界预缓存、视频预览、失败重试或提前加载。它的日志可以作为辅助证据，但不应作为最高可信的舞蹈事件来源。

## 记录来源优先级

理想的数据来源是 VRChat 本身产生的播放事件。后备来源按可信度递减：

1. VRChat 日志或事件源：最接近真实播放事件，优先实现。
2. VRCX 数据库：适合补历史、补漏和交叉校验，但需要确认运行中是否有锁、延迟或格式变化。
3. `local-cdn` 日志：适合辅助确认 URL、缓存和本地文件映射，但可能受预缓存影响。
4. 录像 OCR 或听歌识别：作为最恶劣情况下的恢复方案，最后考虑。

记录程序应尽量轻量，因为它会和 VRChat 同时运行。理想形态是一个持续运行的小服务：

```text
VRChat log watcher
+ event normalizer
+ database writer
+ OBS overlay server
+ health/status page
```

它应边实时写入日志，边为 OBS 提供当前歌曲、时间和状态展示。性能上应避免频繁扫描大目录和高频全库查询。

## Overlay 与录像

OBS overlay 不再作为独立项目，而是 `dancing-log` 的实时展示模块。

overlay 的目标是在录屏时尽可能把需要的信息一次性录进去，例如当前歌曲、状态和时间。但历史事实仍应以数据库为准，overlay 只是当时画面上的投影。

现有的 ISO 8601 时间 overlay 建议保留。它是视频画面中的人工校准锚点，即使数据库、文件时间或章节信息之后出现偏差，仍然可以帮助重新对齐。

歌曲信息 overlay 可以保留为实时体验的一部分，但长期还应支持把歌曲时间线写入视频章节或旁路元数据。这样即使画面不显示歌名，仍可以在后期快速定位某天某首舞。

## 录像管理

`dancing-log` 后续应管理 OBS 录屏目录，例如：

```text
path/to/recordings
```

录像文件应被视为一等数据对象，而不是备注。推荐的数据关系是：

```text
recordings
- file_path
- started_at
- ended_at
- duration
- indexed_at

dance_events
- played_at
- song_id
- source
- confidence
- recording_id
- recording_offset_seconds
```

这样未来可以从一条舞蹈记录直接定位到某个录像文件的某个时间点，也可以为视频自动生成章节轨道。

## 当前功能

- [x] 抓取 Wanna Dance 歌曲数据库。
- [x] 查询网易云音乐歌曲热度和评论数。
- [x] 初始化歌曲主数据 `songs.csv`。
- [x] 手动记录舞蹈历史 `dance_log.csv`。
- [x] 根据频次、喜好和最近跳舞时间生成每日推荐歌单。
- [ ] 从 VRChat 日志实时采集播放事件。
- [ ] 从 VRCX 数据库导入历史播放事件。
- [ ] 从 CDN 日志导入辅助信息。
- [ ] 迁移到 SQLite 作为主存储，CSV 作为导出格式。
- [ ] 管理 OBS 录像文件并关联舞蹈事件。
- [ ] 提供 OBS overlay 本地服务。
- [ ] 支持视频章节或元数据导出。

## 当前项目结构

```text
dancing-log/
|-- dancing_log/                # 核心库
|   |-- __init__.py
|   `-- models.py               # 当前 CSV 数据模型和推荐权重计算
|-- scripts/                    # 数据采集脚本
|   |-- scrape_wanna.py         # 抓取 Wanna Dance 全部歌曲
|   |-- match_netease.py        # 批量查询网易云音乐热度
|   |-- init_songs.py           # 初始化歌曲主数据
|   `-- test_music_apis.py      # 音乐 API 测试工具
|-- docs/                       # 设计和调研文档
|   |-- music_api_research.md
|   `-- vrcx_integration_notes.md
|-- data/                       # 本地数据，git ignored
|-- analysis/                   # 本地分析草稿，git ignored
|-- main.py                     # 当前 CLI 入口
|-- pyproject.toml
`-- README.md
```

## 快速开始

### 环境要求

- Python >= 3.14
- [uv](https://docs.astral.sh/uv/) 包管理器

### 抓取 Wanna Dance 歌曲

```bash
uv run python main.py scrape
```

从 Wanna Dance API 获取全部公开歌曲信息，输出到 `data/` 目录。

### 查询网易云音乐热度

```bash
uv run python main.py match --limit 100
uv run python main.py match
uv run python main.py match --resume
```

### 初始化歌曲主数据

```bash
uv run python main.py init
```

合并 Wanna Dance 歌曲数据和网易云热度数据，生成 `data/songs.csv`。

### 记录舞蹈

```bash
uv run python main.py log 5038
uv run python main.py log 5038 --other
uv run python main.py log 5038 --source self
uv run python main.py log 5038 --note "很好玩"
uv run python main.py log 5038 --time "2000-01-01T12:00:00+08:00"
```

记录保存到 `data/dance_log.csv`。当前版本会在手动记录时检查歌曲是否在当日推荐歌单中，如果在，则自动标记为 `recommend`。

### 生成推荐歌单

```bash
uv run python main.py recommend
uv run python main.py recommend -n 10
```

## 当前数据格式

当前版本仍使用 CSV。后续计划迁移到 SQLite，CSV 保留为导入导出格式。

### songs.csv

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | Wanna Dance song id |
| `name` | str | 歌名 |
| `artist` | str | 歌手 |
| `dancer` | str | 舞者或系列名 |
| `player_count` | int | 舞蹈人数 |
| `group` | str | 子分组 |
| `major` | str | 大类 |
| `favorite` | 0/1 | 是否喜欢 |
| `want_to_learn` | 0/1 | 是否待练 |
| `netease_id` | int | 网易云音乐 id |
| `popularity` | float | 网易云热度 |
| `comment_count` | int | 网易云评论数 |

### dance_log.csv

| 字段 | 类型 | 说明 |
|---|---|---|
| `timestamp` | str | ISO 8601 时间 |
| `song_id` | int | 对应 `songs.csv` 的歌曲 id |
| `source` | str | 当前支持 `self`、`recommend`、`other` |
| `note` | str | 备注 |

后续 source 会扩展为更细的枚举，例如：

- `queued_self`：自己提前排队点歌。
- `self`：自己现场点歌。
- `recommend`：来自本工具推荐。
- `other`：别人点歌。
- `random`：世界或系统随机播放。
- `unknown`：无法可靠判断来源。

## 推荐算法

当前推荐权重由喜好、热度、跳舞频次、距离上次跳舞时间和待练标记共同决定：

```text
weight =
  2.0 * favorite
+ 1.0 * popularity / 100
+ 3.0 * 1 / (1 + dance_count)
+ 2.5 * recency_decay
+ 2.5 * want_to_learn
```

每日推荐歌单使用 `SHA-256("dancing-log-{YYYY-MM-DD}:{song_id}")` 作为同权重歌曲的确定性排序依据。同一天多次运行 `recommend` 会得到相同结果，便于判断一条记录是否来自当日推荐。

## 数据边界

本项目应保持代码和个人数据分离。仓库不应提交：

- 原始 VRCX 数据库。
- VRChat 个人标识。
- 本地运行日志。
- OBS 原始录像。
- 从本机生成的历史快照。

本地路径、用户 id、录像目录、VRCX 路径和 CDN 路径应放在 `.env` 或未来的本地配置文件中，并保持 git ignored。

