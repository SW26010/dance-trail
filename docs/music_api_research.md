想要获取歌曲的“热度”、“播放量”和“收藏数”，主要可以通过**官方开放平台 API** 或 **社区开源接口**来实现。

由于版权和数据隐私保护，国内各大平台（网易云、QQ音乐）的官方 API 对“播放次数”这类敏感数据通常是不公开的（仅对合作伙伴开放），但会提供“热度指数”或“评论数”。

以下是几种主流的实现方案：

---

### 1. 网易云音乐 (Netease Cloud Music)
**官方 API：** 针对普通开发者基本只提供基础检索。
**开源推荐：** [Binaryify/NeteaseCloudMusicApi](https://github.com/Binaryify/NeteaseCloudMusicApi)
这是目前最流行的 NodeJS 开源接口，通过模拟客户端请求实现。
* **热度数据：** 可以通过歌曲详情接口获取 `pop` (Popularity) 值，代表歌曲热度。
* **收藏/喜欢：** 虽然无法直接看到全网总收藏数，但可以通过查看**包含该歌曲的歌单数量**或**歌曲评论数**来侧面反映。
* **播放量：** 官方不对外显示精确播放次数，通常只能看到“最近听过”或排行榜的相对热度。

### 2. QQ 音乐 (Tencent Music)
**官方 API：** [QQ音乐开发者平台](https://developer.y.qq.com/)
* **特点：** 需要企业资质申请，主要面向硬件厂商或 APP 接入。
* **开源推荐：** [jsososo/QQMusicApi](https://github.com/jsososo/QQMusicApi)
* **数据：** 能获取到歌曲的 `index`（热度指数）、评论数，以及歌曲在各类榜单（热歌榜、流行指数榜）中的排名。

### 3. Spotify (全球数据最全)
**官方 API：** [Spotify Web API](https://developer.spotify.com/documentation/web-api/)
如果你需要的是国际歌曲的数据，Spotify 是最透明的：
* **Popularity（热度）：** 提供 0-100 的数值，基于近期播放量计算。
* **Play Count（播放量）：** 官方 Web API **不直接提供**精确播放总数（该数据通常只在客户端显示），但可以通过一些第三方数据采集器（如 [Apify Spotify Scraper](https://apify.com/beatanalytics/spotify-play-count-scraper)）获取。

### 4. Last.fm (统计数据专家)
**官方 API：** [Last.fm API](https://www.last.fm/api)
这是获取歌曲“播放次数”和“听众数”最方便的合法渠道：
* **接口：** `track.getInfo`
* **返回数据：**
    * `playcount`: 全球总播放次数。
    * `listeners`: 听过这首歌的总人数。
* **优点：** 免费、无需模拟登录、数据公开透明。

---

### 方案对比表

| 平台 | 获取热度 (Score) | 播放次数 (Play Count) | 收藏/喜欢 (Likes) | 推荐工具 |
| :--- | :--- | :--- | :--- | :--- |
| **网易云** | 支持 (`pop` 值) | 不支持 | 侧面参考评论数 | NeteaseCloudMusicApi |
| **QQ 音乐** | 支持 (指数) | 不支持 | 侧面参考评论数 | QQMusicApi |
| **Spotify** | 支持 (0-100) | 需第三方爬虫 | 需用户授权 | Spotify Web API |
| **Last.fm** | 支持 | **支持 (精确数字)** | 支持 (Listeners) | Last.fm API |

### 建议
1.  **如果你做国内歌曲分析：** 建议使用网易云开源接口，抓取 **评论数** 和 **pop热度值**。评论数是目前国内衡量歌曲火爆程度最公认的指标。
2.  **如果你需要精确播放量：** 建议接入 **Last.fm API**，它的 `playcount` 字段是目前唯一能直接拿到的公开统计数据。

---

## 实测验证 (2026-04-17)

> 测试环境: Windows, 中国大陆 IP, Python 3.14  
> 测试曲目: Ed Sheeran - Shape of You / 周杰伦 - 晴天  
> 测试脚本: `scripts/test_music_apis.py`

### 各 API 实测可用性

| API | 认证要求 | 实测结果 |
|---|---|---|
| Deezer | 无需 | ❌ 地区限制 (返回 total>0 但 data 为空) |
| Last.fm | API Key (免费) | ⏭️ 未配置 Key, 待测 |
| Spotify | OAuth (Client ID/Secret) | ⏭️ 未配置凭证, 待测 |
| YouTube Data v3 | API Key (免费配额) | ⏭️ 未配置 Key, 待测 |
| **网易云音乐** | **无需** | **✅ 直接可用** |

### 网易云音乐实测数据

**接口地址：**
- 搜索: `https://music.163.com/api/search/get?s={query}&type=1&limit=3`
- 详情: `https://music.163.com/api/song/detail?ids=[{id}]`
- 评论: `https://music.163.com/api/v1/resource/comments/R_SO_4_{id}?limit=1`
- 需设置请求头: `Referer: https://music.163.com/` + `User-Agent`

#### 周杰伦 - 晴天
| 版本 | id | popularity | score | 评论数 |
|---|---|---|---|---|
| 周杰伦-, A-LNK - 晴天 | 3339230677 | 95.0 | 95 | 110 |
| 周杰伦-, Asasblue - 晴天 | 3334653818 | 100.0 | 100 | 104 |

#### Ed Sheeran - Shape of You
| 版本 | id | popularity | score | 评论数 |
|---|---|---|---|---|
| 原版 | 451703096 | 100.0 | 100 | 152,140 |
| Tour Collection Live | 2659782246 | 10.0 | 10 | 4 |
| Live | 2659779522 | 20.0 | 20 | 15 |

### 实测结论

1. **在中国大陆环境下，网易云音乐 API 是唯一零配置直接可用的方案**
2. `popularity` (0-100) 可直接用于歌曲热度量化对比
3. 评论数可作为辅助热度指标，尤其适合中文歌曲
4. Deezer 因地区限制不可用；其余 API 需申请 Key 后才能测试
5. 注意：网易云为非官方接口，搜索结果中会混入翻唱/remix 版本，需要根据歌手名过滤

### 环境变量配置（如需测试其他 API）

```
LASTFM_API_KEY=xxx          # https://www.last.fm/api/account/create
SPOTIFY_CLIENT_ID=xxx       # https://developer.spotify.com/dashboard
SPOTIFY_CLIENT_SECRET=xxx
YOUTUBE_API_KEY=xxx         # Google Cloud Console
```

---

## Wanna Dance 歌曲数据爬取

> 数据来源: [wanna.kiva.moe](https://wanna.kiva.moe/)（VRChat 舞蹈地图 WannaDance 的 Web 前端）  
> 爬取脚本: `scripts/scrape_wanna.py`  
> GitHub: [ClownpieceStripedAbyss/aya-dance-web](https://github.com/ClownpieceStripedAbyss/aya-dance-web)

### API 端点

```
GET https://x.kiva.moe/api/v2/wanna/songs
```

无需认证，返回 JSON 格式：

```json
{
  "code": 0,
  "data": {
    "time": "2026-04-17T...",
    "groups": [
      {
        "title": "Just Dance Solo",
        "major": "Just Dance Series",
        "entries": [
          {
            "id": 5038,
            "name": "Good Time",
            "artist": "Owl City & Carly Rae Jepsen",
            "dancer": "JAMAA",
            "playerCount": 1,
            "group": "Just Dance Solo",
            "genre": "",
            ...
          }
        ]
      }
    ]
  }
}
```

### 关键字段

| 字段 | 说明 |
|---|---|
| `id` | 歌曲唯一 ID |
| `name` | 歌名 |
| `artist` | 歌手 |
| `dancer` | 舞者/系列名 |
| `playerCount` | 舞蹈人数 (1=Solo, 2=Duet, 3=Trio, 4+=Crew) |
| `group` | 子分组 (如 Just Dance Solo, FitDance) |
| `genre` / `major` | 大类 (Just Dance Series, Major in Fitness Dance 等) |
| `composedTitle` | 组合标题: "歌名 - 歌手 \| 舞者" |
| `originalUrl` | 原始视频 URL (通常是 Bilibili/YouTube) |
| `disablePublic` | 是否隐藏 |

### 爬取结果 (2026-04-17)

共 **9,745 首** 公开歌曲，按大类分布：

| 大类 | 歌曲数 |
|---|---|
| Major in Fitness Dance | 4,075 |
| Major in ACGN Dance | 2,270 |
| Just Dance Series | 2,134 |
| Major in K-POP | 1,042 |
| else | 223 |

### 使用方法

```bash
uv run python scripts/scrape_wanna.py
```

输出文件：
- `wanna_songs.json` — JSON 格式
- `wanna_songs.csv` — CSV 格式 (UTF-8 BOM, Excel 可直接打开)

### 注意事项

- API 直连 `x.kiva.moe` 在 Python 3.14 中存在 SSL 兼容性问题，脚本通过 `curl` 子进程解决
- `disablePublic=true` 的条目已被过滤
- 同一首歌可能出现在多个 group 中，脚本按 `id` 去重