# dancing-log

> Privacy note: Personal paths and activity examples are anonymized. Replace example paths with your own; sample timestamps are illustrative. Aggregate results and technical conclusions are retained.

舞蹈歌曲记录与数据分析工具，用于管理 [Wanna Dance](https://wanna.kiva.moe/) 歌曲数据库并获取歌曲热度信息。

## 功能规划

- [x] 爬取 Wanna Dance 歌曲数据库
- [x] 查询网易云音乐歌曲热度 (popularity, 评论数)
- [x] 歌曲主数据初始化 (songs.csv)
- [x] 舞蹈记录 (dance_log.csv)
- [x] 根据频次和喜爱程度自动生成推荐歌单
- [ ] 歌曲"喜欢"、"待练"标记管理
- [ ] 在线更新歌曲热度信息
- [ ] 数据分析可视化

## 项目结构

```
dancing-log/
├── dancing_log/                # 核心库
│   ├── __init__.py
│   └── models.py               # 数据模型、推荐权重计算
├── scripts/                    # 数据采集脚本
│   ├── scrape_wanna.py         # 爬取 Wanna Dance 全部歌曲
│   ├── match_netease.py        # 批量查询网易云音乐热度
│   ├── init_songs.py           # 初始化歌曲主数据 (songs.csv)
│   └── test_music_apis.py      # 音乐热度 API 测试工具
├── data/                       # 数据文件 (git ignored, 由脚本生成)
│   ├── songs.csv               # 歌曲主数据 (主键: id)
│   ├── dance_log.csv           # 舞蹈记录
│   ├── wanna_songs.json        # Wanna Dance 原始数据
│   └── wanna_netease_matched.json  # 网易云匹配结果
├── docs/                       # 文档
│   └── music_api_research.md   # 音乐 API 调研报告
├── main.py                     # CLI 入口
├── pyproject.toml
└── README.md
```

## 快速开始

### 环境要求

- Python >= 3.14
- [uv](https://docs.astral.sh/uv/) 包管理器

### 爬取 Wanna Dance 歌曲

```bash
uv run python main.py scrape
```

从 [wanna.kiva.moe](https://wanna.kiva.moe/) API 获取全部歌曲信息，输出到 `data/` 目录。

### 查询网易云音乐热度

```bash
uv run python main.py match --limit 100   # 测试前 100 首
uv run python main.py match               # 全量查询 (约 2-3 小时)
uv run python main.py match --resume      # 断点续查
```

### 初始化歌曲主数据

```bash
uv run python main.py init
```

合并 wanna 歌曲数据和网易云热度数据，生成 `data/songs.csv`。

### 记录舞蹈

```bash
uv run python main.py log 5038              # 自动判断（在今日推荐中→系统推荐，否则→主动点）
uv run python main.py log 5038 --other       # 别人点的
uv run python main.py log 5038 --source self # 强制指定来源
uv run python main.py log 5038 --note "很好玩"
uv run python main.py log 5038 --time "2000-01-01T12:00:00+08:00"
```

记录保存在 `data/dance_log.csv`。点歌来源自动判断：若歌曲在当日推荐歌单中，自动标记为 `recommend`。

### 生成推荐歌单

```bash
uv run python main.py recommend           # 默认推荐 20 首
uv run python main.py recommend -n 10     # 推荐 10 首
```

### 测试各音乐平台 API

```bash
uv run python main.py test-apis
```

## 数据格式

### songs.csv (歌曲主数据)

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | 主键，Wanna Dance ID |
| `name` | str | 歌名 |
| `artist` | str | 歌手 |
| `dancer` | str | 舞者/系列名 |
| `player_count` | int | 舞蹈人数 |
| `group` | str | 子分组 |
| `major` | str | 大类 |
| `favorite` | 0/1 | 是否喜欢 |
| `want_to_learn` | 0/1 | 是否待练 |
| `netease_id` | int | 网易云音乐 ID |
| `popularity` | float | 网易云热度 (0-100) |
| `comment_count` | int | 网易云评论数 |

### dance_log.csv (舞蹈记录)

| 字段 | 类型 | 说明 |
|---|---|---|
| `timestamp` | str | ISO 8601 时间 |
| `song_id` | int | 歌曲 ID (对应 songs.csv) |
| `source` | str | 点歌来源: `self`=主动点, `recommend`=系统推荐, `other`=别人点 |
| `note` | str | 备注 |

## 推荐算法

根据多维度加权计算推荐分数：

$$W = 2.0 \times \text{favorite} + 1.0 \times \frac{\text{popularity}}{100} + 3.0 \times \frac{1}{1+\text{dance\_count}} + 2.5 \times \text{recency\_decay} + 2.5 \times \text{want\_to\_learn}$$

| 因子 | 权重 | 说明 |
|---|---|---|
| favorite | 2.0 | 标记喜欢的歌 +1.0 |
| popularity | 1.0 | 网易云热度归一化 (0-1) |
| frequency_decay | 3.0 | 跳得越少分越高: $\frac{1}{1+n}$ |
| recency_decay | 2.5 | 越久没跳分越高: sigmoid(7天半衰期) |
| want_to_learn | 2.5 | 标记待练的 +1.0 |

### 确定性歌单种子

每日推荐歌单使用 `SHA-256("dancing-log-{YYYY-MM-DD}:{song_id}")` 作为同权重歌曲的确定性排序依据。同一天多次运行 `recommend` 得到相同结果，从而支持自动判断“系统推荐”来源。

## 数据来源

| 来源 | 用途 | 认证 |
|---|---|---|
| [Wanna Dance API](https://x.kiva.moe/api/v2/wanna/songs) | 歌曲数据库 | 无需 |
| [网易云音乐](https://music.163.com) | 歌曲热度 (popularity 0-100, 评论数) | 无需 |
| [Last.fm](https://www.last.fm/api) | 播放次数, 听众数 | API Key (免费) |
| [Spotify](https://developer.spotify.com) | 热度 (0-100) | OAuth |

详见 [docs/music_api_research.md](docs/music_api_research.md)