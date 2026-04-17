# dancing-log

舞蹈歌曲记录与数据分析工具，用于管理 [Wanna Dance](https://wanna.kiva.moe/) 歌曲数据库并获取歌曲热度信息。

## 功能规划

- [x] 爬取 Wanna Dance 歌曲数据库
- [x] 查询网易云音乐歌曲热度 (popularity, 评论数)
- [ ] 在线更新歌曲热度信息
- [ ] 歌曲"喜欢"、"待练"标记
- [ ] 舞蹈记录导入（哪天几点跳了什么歌，主动点/别人点）
- [ ] 根据频次和喜爱程度自动生成每日歌单
- [ ] 数据分析可视化

## 项目结构

```
dancing-log/
├── scripts/                    # 数据采集脚本
│   ├── scrape_wanna.py         # 爬取 Wanna Dance 全部歌曲
│   ├── match_netease.py        # 批量查询网易云音乐热度
│   └── test_music_apis.py      # 音乐热度 API 测试工具
├── data/                       # 数据文件 (git ignored)
│   ├── wanna_songs.json        # Wanna Dance 歌曲列表
│   ├── wanna_songs.csv         # CSV 格式
│   ├── wanna_netease_matched.json  # 网易云匹配结果
│   └── wanna_netease_matched.csv
├── docs/                       # 文档
│   └── music_api_research.md   # 音乐 API 调研报告
├── main.py                     # 主程序入口
├── pyproject.toml
└── README.md
```

## 快速开始

### 环境要求

- Python >= 3.14
- [uv](https://docs.astral.sh/uv/) 包管理器

### 爬取 Wanna Dance 歌曲

```bash
uv run python scripts/scrape_wanna.py
```

从 [wanna.kiva.moe](https://wanna.kiva.moe/) API 获取全部歌曲信息，输出到 `data/` 目录。

### 查询网易云音乐热度

```bash
# 测试前 100 首
uv run python scripts/match_netease.py --limit 100

# 全量查询 (约 2-3 小时)
uv run python scripts/match_netease.py

# 断点续查
uv run python scripts/match_netease.py --resume
```

### 测试各音乐平台 API

```bash
# 需要先配置环境变量 (可选)
# LASTFM_API_KEY / SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET / YOUTUBE_API_KEY
uv run python scripts/test_music_apis.py
```

## 数据来源

| 来源 | 用途 | 认证 |
|---|---|---|
| [Wanna Dance API](https://x.kiva.moe/api/v2/wanna/songs) | 歌曲数据库 | 无需 |
| [网易云音乐](https://music.163.com) | 歌曲热度 (popularity 0-100, 评论数) | 无需 |
| [Last.fm](https://www.last.fm/api) | 播放次数, 听众数 | API Key (免费) |
| [Spotify](https://developer.spotify.com) | 热度 (0-100) | OAuth |

详见 [docs/music_api_research.md](docs/music_api_research.md)