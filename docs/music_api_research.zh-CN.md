# 音乐 API 研究

日期：2026-04-17

这是归档研究笔记，记录早期本地实验。外部 API 可能变化，本文不保证这些接口现在仍然可用。

英文对应文档：`docs/music_api_research.md`

音乐平台匹配和热度数据不属于当前运行时模型。当前 schema 有意暂缓这部分，
先稳定核心时间线。

## 目标

探索如何给 `music_tracks` 补充公开音乐平台元数据，例如：

- 平台 id
- 热度分数
- 听众数或播放数
- 评论数

建模上的重点是：这些数据属于真实音乐曲目，而不是某一个 WannaDance 条目。
同一首歌可以有多个舞蹈版本。

## 候选平台

### NetEase Cloud Music

早期本地测试发现，NetEase 一些接口不需要本地 API key，能返回：

- 搜索结果
- 歌曲详情字段，比如 `popularity`
- 评论数

测试过的接口：

```text
https://music.163.com/api/search/get?s={query}&type=1&limit=3
https://music.163.com/api/song/detail?ids=[{id}]
https://music.163.com/api/v1/resource/comments/R_SO_4_{id}?limit=1
```

请求使用了类似浏览器的 `User-Agent` 和 `Referer`。

风险：

- 非官方接口
- 匹配时容易混入翻唱、remix、live 版本和译名
- 可用性和返回结构可能变化

### Last.fm

Last.fm 有官方 API，可以提供全局统计，例如：

- play count
- listener count

风险：

- 需要 API key
- 匹配质量依赖标题/歌手归一化
- 中文歌曲、remix 和舞蹈版本覆盖可能不稳定

### Spotify

Spotify Web API 提供 0-100 的 popularity 分数。

风险：

- 需要 OAuth 凭据
- 公共 API 不提供精确总播放数
- 地区可用性和 canonical track 匹配可能麻烦

### YouTube Data API

YouTube 可以在已知具体视频时提供视频级统计。

风险：

- 需要 API key
- 一首歌可能对应很多视频，不一定有唯一 canonical song
- 有 quota 限制

### Deezer

早期本地测试受地区可用性限制。

## 现有研究脚本

- `scripts/test_music_apis.py`：临时 API 探测。
- `scripts/match_netease.py`：实验性的 NetEase 匹配和评论数查询。

这些脚本是研究工具，不是运行时命令。

## 建议的未来 schema

平台标识应该和核心时间线分开：

```text
music_tracks
  -> music_provider_matches
  -> music_popularity_snapshots
```

未来可能的表：

- `music_provider_matches`：把 `music_tracks.id` 映射到平台 id，带置信度和匹配方式。
- `music_popularity_snapshots`：存带时间戳的平台指标，比如热度、评论数、听众数或播放数。

这样变化频繁的平台数据就不会污染不可变的播放历史。

## 建议

暂时不要把平台热度加入推荐分数。

更有价值的下一步是做一个可人工审核的平台匹配流程：

1. 取一批 `music_tracks`。
2. 用归一化标题和歌手搜索平台候选。
3. 保存候选匹配、置信度和平台 payload。
4. 允许人工修正后，再用于分析或推荐。
