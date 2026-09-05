# VRCX 播放数据实测事实

> 隐私说明：玩家名、日志文件名及事件时间已匿名化；示例路径需替换为本地实际路径。聚合统计与技术结论保留。

日期：2026-09-05

状态：v2 合同设计的事实输入

## 记录边界

本文记录一次真实 VRCX 数据库快照、两批 VRChat output log 与当前仓库最新 watcher
重放结果之间可复核的结构、计数和对应关系。本文不据此规定 v2 的来源优先级、
默认接受规则、自动合并条件、时间窗口、最终表名或字段名。

本次只读检查使用：

- VRCX 数据库：`path/to/vrcx-snapshot/VRCX.sqlite3`；
- v0.7 原始日志：
  `path/to/portable-snapshot/logs/source-vrc-logs`；
- v0.8 原始日志：
  `path/to/portable-snapshot/logs/source-vrc-logs`；
- watcher：当前仓库提交 `efc0d84ce39eec454b2487aa55d4878b8396ef59` 的
  `scripts/replay_vrc_logs.py baseline` 与当前解析、折叠、持久化代码。

两份 portable 包自带的 watcher 程序和 watcher 数据库均未用作本轮 watcher 结论。
VRCX 数据库和两批原始日志全程只读；重放结果写入工作区或系统临时目录。
所有计数均属于上述文件在检查时的快照。

## VRCX 数据库与表结构

数据库中的 `configs` 表记录：

- `config:vrcx_databaseversion = 16`；
- `config:vrcx_lastvrcxversion = VRCX 2026.07.18`。

数据库的 `PRAGMA user_version` 和 `PRAGMA application_id` 均为 `0`。

`gamelog_video_play` 的建表 SQL 为：

```sql
CREATE TABLE "gamelog_video_play" (
  id INTEGER PRIMARY KEY,
  created_at TEXT,
  video_url TEXT,
  video_name TEXT,
  video_id TEXT,
  location TEXT,
  display_name TEXT,
  user_id TEXT,
  UNIQUE(created_at, video_url)
)
```

检查时共有 14,784 行：

- `id` 从 `1` 到 `14784`；
- 14,784 行的 `id` 均等于同一行的 SQLite `rowid`；
- `created_at` 覆盖一段跨月历史；具体起止时间不公开；
- 所有 `created_at` 都以 `.000Z` 结尾；
- 没有重复的 `(created_at, video_url)`；
- 21 组记录具有相同 `created_at`，这些组比“一时间一行”多出 31 行。

## 字段存在情况

空字符串和 `NULL` 在本节统一计为缺失。

| 字段 | 缺失行数 | 有值行数 |
| --- | ---: | ---: |
| `created_at` | 0 | 14,784 |
| `video_url` | 0 | 14,784 |
| `video_name` | 1,281 | 13,503 |
| `video_id` | 14,425 | 359 |
| `location` | 0 | 14,784 |
| `display_name` | 2,543 | 12,241 |
| `user_id` | 3,319 | 11,465 |

按 `video_url` host 计数最多的来源为：

| host | 行数 |
| --- | ---: |
| `api.udon.dance` | 13,014 |
| `api.wannadance.online` | 988 |
| `api.dudufit.dance` | 272 |
| `www.youtube.com` | 122 |
| `api.pypy.dance` | 109 |
| `jd.pypy.moe` | 92 |
| 其他 host 合计 | 187 |

按当前仓库的 `parse_dance_url` 解析，14,483 行能得到规范化舞蹈键，其中
`wannadance` 14,010 行、`dudu` 272 行、`pypydance` 201 行；另有 301 行不能得到
规范化舞蹈键。

对同一“规范化舞蹈键 + 完整 location”的相邻 VRCX 行统计，最短间隔为 5 秒；
不超过 5、10、20、30、60、90 秒的相邻对分别有 6、24、51、77、106、127 对。

## 原始日志中的 VRCX 标记

`[VRCX] VideoPlay(...)` 行的日志本地时间按 UTC+08:00 转为 UTC。随后使用
`(UTC 秒级时间, 完整原始 video_url)` 与 `gamelog_video_play` 比较。

| 数据集 | 文件数 | bytes | 含标记文件数 | 标记数 | 精确对应 VRCX 行 | 仅日志侧 | 标记时间范围内 VRCX 行 | 仅 VRCX 侧 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| v0.7 | 72 | 129,991,053 | 64 | 2,022 | 1,808 | 214 | 2,317 | 509 |
| v0.8 | 41 | 98,149,684 | 40 | 1,364 | 1,346 | 18 | 1,522 | 176 |
| 合计 | 113 | 228,140,737 | 104 | 3,386 | 3,154 | 232 | 3,839 | 685 |

两批日志各自都不存在重复的 `(UTC 秒级时间, 完整原始 video_url)`。VRCX 表对该二元组
也有数据库唯一约束。3,154 个精确对应中，VRCX `location` 与同一日志文件此前最近一次
`[Behaviour] Joining ...` 的完整 world instance 全部一致。

在 3,154 个精确对应中，日志标记解析出的请求者显示名与 VRCX `display_name` 的比较为：

- 2,953 对两侧都有值且完全相同；
- 200 对都为空，对应日志中的 `Random`；
- 1 对仅一侧有值；
- 0 对两侧都有值但不同。

日志标记解析出的标题与 VRCX `video_name` 只有 84 对完全相同，3,064 对不同，6 对仅一侧
有值。解析出的 `video_id` 只有 84 对完全相同，30 对不同，3,039 对仅一侧有值，1 对都为空。
这里的标题比较使用当前 watcher 解析后的标题，而不是原始 payload 字符串。

v0.7 精确对应中的 `[VRCX] VideoPlay` position 有 1,791 条为零、17 条为正；v0.8
分别为 1,345 条和 1 条。正 position 标记可出现在已经播放一段时间后。

v0.8 的 18 个仅日志侧标记中有 17 个集中在
`output_log_sample_07.txt`。该文件存在同一 URL 数秒后再次输出标记、但 VRCX
只保存其中一行的实例。

VRCX 表也存在不同 URL 共享同一秒 `created_at` 的实例。例如 两个不同记录具有相同的秒级时间，URL 指向不同舞蹈（具体记录编号、时间及舞蹈编号省略）。在完整 VRCX 表中，“规范化舞蹈键 + `created_at`”以及再加上
`location` 的组合均没有碰撞。

## 最新 watcher 重放结果

使用相同最新 watcher 分别重放两批日志：

| 数据集 | 原始行 | 解析事件 | 汇总 playback events | 持久 `playback_records` | accepted/completed | needs_attention/interrupted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| v0.7 | 751,523 | 74,098 | 2,043 | 2,032 | 1,660 | 372 |
| v0.8 | 575,344 | 58,221 | 1,489 | 1,467 | 1,303 | 164 |
| 合计 | 1,326,867 | 132,319 | 3,532 | 3,499 | 2,963 | 536 |

用 watcher 汇总事件的 `request_at` 或 `first_seen_at` 与全部原始日志中的同一规范化舞蹈键
定位 `[VRCX] VideoPlay` 标记，再用标记的精确 `(UTC 时间, 原始 URL)` 定位 VRCX 行，结果为：

| 数据集 | 汇总时间代理找到的唯一 watcher—VRCX 锚点 | 代理找到多个锚点的 watcher | 精确日志/VRCX 重合中的覆盖率 |
| --- | ---: | ---: | ---: |
| v0.7 | 1,796 | 0 | 1,796 / 1,808（99.34%） |
| v0.8 | 1,336 | 0 | 1,336 / 1,346（99.26%） |
| 合计 | 3,132 | 0 | 3,132 / 3,154（99.30%） |

这张表只使用两个汇总时间，不代表 watcher 实际消费的完整输入集合。完整消费轨迹发现：

| 数据集 | 只有一条支持舞蹈锚点的 watcher | 有多条支持舞蹈锚点的 watcher | 覆盖的支持舞蹈 VRCX 行 |
| --- | ---: | ---: | ---: |
| v0.7 | 1,806 | 1 | 1,808 |
| v0.8 | 1,336 | 1 | 1,338 |
| 合计 | 3,142 | 2 | 3,146 |

另有 8 条精确对应行的 URL 不被当前舞蹈 parser 支持。两个多锚点 watcher 各消费两条
VRCX 行；后续上下文证明它们跨越不同播放过程，不能据此合并。3,132 个汇总时间代理锚点
指向 3,132 个不同 VRCX 行，没有两个 watcher 汇总事件争用同一 VRCX 行。
在这些已确认锚点中，watcher 的 `request_at` 或 `first_seen_at` 至少一个与 VRCX
`created_at` 精确相同；按“精确时间 + 规范化舞蹈键”查询完整 VRCX 表时，每一条都只得到
对应的唯一 VRCX 行。

当前 watcher 的其他汇总字段与这 3,132 个锚点的比较为：

- `routed_url` 与 VRCX 原始 `video_url` 完全相同 3,050 次；
- watcher `video_url` 与 VRCX 原始 `video_url` 完全相同 225 次；
- watcher 请求者显示名与 VRCX `display_name`：两侧有值且相同 2,175 次，两侧有值但不同
  758 次，仅一侧有值 187 次，两侧都为空 12 次；
- watcher 请求者 user id 与 VRCX `user_id`：两侧有值且相同 2,091 次，两侧有值但不同
  583 次，仅一侧有值 446 次，两侧都为空 12 次；
- watcher 汇总的 `source_file` 与实际承载共同标记的日志文件不同 1,602 次，其中 v0.7
  997 次、v0.8 605 次。

最后一项发生在相同舞蹈键跨文件再次出现时：汇总事件的时间和其他内容属于新 occurrence，
但 `source_file` 仍可能保留此前 occurrence 的文件名。

汇总时间代理遗漏的 22 条包括：12 条实际已被 watcher 消费、2 条是上述多锚点集合中的
第二行、8 条 URL 不被当前舞蹈 parser 支持。它们说明代理时间不能重建完整输入血缘；
不应通过 ±1 秒或最近候选补造归属。

## `played_at` 时间窗实验

对已经由共同原始标记确认的 watcher—VRCX 锚点，使用
“同规范化舞蹈键 + 同完整 location + `0 <= watcher.played_at - VRCX.created_at <= 窗口`”
重新寻找候选。下表中的“最近正确”表示在候选中选择距 `played_at` 最近者时仍选中共同标记
确认的 VRCX 行。

| 数据集 | 窗口 | 真值数 | 真值进入窗口 | 唯一候选 | 多候选 | 最近正确 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| v0.7 | 10 秒 | 1,796 | 1,620 | 1,622 | 0 | 1,620 |
| v0.7 | 20 秒 | 1,796 | 1,745 | 1,742 | 3 | 1,743 |
| v0.7 | 30 秒 | 1,796 | 1,781 | 1,775 | 6 | 1,779 |
| v0.7 | 90 秒 | 1,796 | 1,785 | 1,776 | 9 | 1,783 |
| v0.8 | 10 秒 | 1,336 | 1,222 | 1,222 | 0 | 1,222 |
| v0.8 | 20 秒 | 1,336 | 1,316 | 1,316 | 0 | 1,316 |
| v0.8 | 30 秒 | 1,336 | 1,332 | 1,332 | 0 | 1,332 |
| v0.8 | 90 秒 | 1,336 | 1,336 | 1,335 | 1 | 1,336 |

v0.7 中有 11 条 `observed_mid_play` 的 watcher `played_at` 早于 VRCX `created_at`，最早
相差 181.5036 秒；它们不进入上述任何单向正窗口。其余 v0.7 锚点的中位差为 10 秒、
P95 为 14 秒、最大正差为 39 秒。v0.8 的最小差为 0 秒、中位数 10 秒、P95 13 秒、
最大值 65 秒。

v0.7 的 10 秒窗口另有 2 个唯一候选并非共同标记确认的原行，因此“唯一候选”高于
“真值进入窗口”；这两条不能计入最近正确。

样本中存在同一舞蹈、同一完整 location 在很短时间内再次出现的情况。v0.7 的 20 秒及更宽
窗口已经出现“最近 VRCX 行不是共同标记所确认行”的实例。
