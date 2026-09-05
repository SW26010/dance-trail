# VRCX 证据归并审阅与复核

> 隐私说明：玩家名、日志文件名及事件时间已匿名化；示例路径需替换为本地实际路径。聚合统计与技术结论保留。

日期：2026-09-05。被审阅代码提交：`efc0d84ce39eec454b2487aa55d4878b8396ef59`。

审阅对象为工作区的 `playback_data_model_redesign.zh-CN.md` 改动及
`vrcx_playback_data_facts.zh-CN.md`。本文保留归并实验和审阅事实，生产 watcher 未修改。
当前正式 VRCX 数据库规则以 `vrcx_database_evidence_contract.zh-CN.md` 的 A1–A6 为准；
下文的跨来源增强方案作为后续研究，不构成当前自动归并合同。

结论：保留不可变来源证据、以共同原始输入确定来源关系、禁止仅凭时间窗自动归并的方向成立。
现有统计大部分可复现，但还不能据此认为严格归并合同已经得到充分验证。需要修正完整输入
归属的验证方法，并把 VRCX 实际支持的其他日志输入纳入实验。

后续已补充 `vrcx_database_evidence_contract.zh-CN.md`：追踪固定版本 VRCX 的完整写库
链路，执行 20 项实际源码/SQL 行为探针，再按仅依赖数据库的要求收敛分级合同。
正式方案采用 URL 白名单、有效来源时间、逐行证据和重复摄入去重；其他推断暂缓。
本报告的 watcher 边界问题保留为研究反例，不作为 VRCX adapter 发布来源证据的依赖。

## 验证方法和边界

使用用户指定的 VRCX 数据库及 v0.7、v0.8 两个 `source-vrc-logs` 目录。
`scripts/audit_vrcx_merge.py` 通过 SQLite `mode=ro`、`query_only=ON` 连接外部数据库，
使用 backup API 在仓库 `analysis/vrcx-merge-review-20260905/` 下生成一致性快照。
日志只以读取方式打开；113 个原文件的前后大小、修改时间及 SHA-256 全部一致。
外部数据库在整个实验期间的文件 hash 有变化，不能宣称该运行中的文件全程静止；本脚本
没有向外部数据库发出写入语句，全部 SQL 分析使用本地一致性快照，其 `integrity_check=ok`。

watcher 使用现有 `scripts/replay_vrc_logs.py` 的同一 `_run_replay` 入口、相同参数及真实
持久化路径。审计包装 `PlaybackEventBuilder.observe`，记录输入位置和其实际返回的
`event_key`，不更改输入、返回值或折叠算法。所有 132,319 条解析事件都有消费轨迹。
这与仅用最终 `request_at/first_seen_at` 倒查标记是两种不同的验证。

原始日志的时区明确按 UTC+08:00 处理。本样本所有 VideoPlay 标记均为秒级时间。
快照、完整行、原始 CSV payload、解析事件、逐输入消费关系、汇总事件及持久记录都保存在
被 `.gitignore` 排除的 `analysis/` 中；没有把原始用户名称、实例地址或完整数据库提交为 fixture。

## 需要修正的审阅发现

### P1：两个汇总时间不能证明一个 watcher occurrence 的完整锚点集合

原事实文档 143–155 行的 3,132 次时间倒查和两个“0”可以按其方法复现，且这些被找到的
标记确实被对应 watcher 消费。但完整消费轨迹分别在两批日志中发现一个 watcher 汇总
吸收了两个不同 VRCX 行；不能据倒查结果推断不存在多锚点。

| 数据集 | watcher event_key | VRCX 行 | 两条标记的本地时间 | 原文件与行号 |
| --- | --- | --- | --- | --- |
| v0.7 | `sample-event-a` | 两个不同来源行 | 同一会话中的两次标记（时间已省略） | `output_log_sample_05.txt`（行号省略） |
| v0.8 | `sample-event-b` | 两个不同来源行 | 同一会话中的两次标记（时间已省略） | `output_log_sample_06.txt`（行号省略） |

第一例中第一次加载报错，随后多首其他舞蹈出现明确 `OnVideoStart`，之后才再次
请求原舞蹈。第二例中间也有多首其他舞蹈明确开始播放。二者都不能解释成
一个连续播放过程。最终汇总把第一次请求时间与第二次实际开始拼在一起，产生 682 秒和
878 秒的延迟；已经结算的持久记录又保留了第一次的状态。

代码原因可定位至 `dancing_log/live_playback_folding.py` 的 `_event_key_for_record`：一个
尚无 `actual_play_at` 的同舞蹈 open event 会继续吸收后续 request/load-start；
`live_playback_runtime.py` 的结算并不总是关闭 builder 中相应的 open event。
这属于当前实现的行为，不能把它直接提升为 v2 的 occurrence 证明。

建议修改设计文档 433–439 行：把“以后发现多个共同标记”改为已存在的验收输入。必须先
确定当前播放过程的边界，再认可其完整锚点集合；对这种互相矛盾的集合保持分离并记录诊断。
不能从两个锚点中挑选一个，也不能仅因 builder 返回相同 event_key 就把两个 VRCX Handle 合并。

### P2：时间窗表遗漏了“唯一候选但原标记不在窗口”的情况

原事实文档 187 行的 v0.7 / 10 秒窗口，“唯一候选”实为“原标记对应行也在窗口时的
唯一候选”。使用持久 `playback_records.played_at`，全部 1,796 个样本中实际有 1,622 个
唯一候选，而非 1,620；另两例选择的是 两个相邻的其他来源行（具体行编号省略）。
20/30/90 秒窗口的原数值可以复现。

这也不能直接当作“两次真实播放被错合”的真值：第一组相邻行 的上下文是同一加载失败后
切换 `node=cf` 再解析 URL；第二组相邻行 涉及延迟加载、预览及重试。它们说明最近行可能
偏离初始标记，以及一个播放过程可能对应多条 VRCX 行；仅凭最初选中的数据库行还不足以
定义完整 occurrence 的 ground truth。

建议表格分别报告全部唯一候选、原锚点在窗口内的唯一候选、偏离原锚点的候选，并将
“原始来源行一致性”与“播放过程归属正确性”分开验收。明确 `played_at` 来自持久记录；
最终 `playback_events.jsonl` 的 `actual_play_at` 会受前述两个异常影响，不能混用。

## 已复现的结果与新增覆盖

14,784 条 VRCX 播放、字段缺失数、host 分布、舞蹈键解析数、时间重复数和相邻播放间隔
统计均与原事实文档一致。两批原始日志没有跨数据集重复的 `(UTC 时间, 原始 URL)`。

| 指标 | v0.7 | v0.8 | 合计 |
| --- | ---: | ---: | ---: |
| 日志文件 | 72 | 41 | 113 |
| 原始字节 | 129,991,053 | 98,149,684 | 228,140,737 |
| VideoPlay 标记 | 2,022 | 1,364 | 3,386 |
| 标记与 VRCX 行精确对应，完整 instance 一致 | 1,808 | 1,346 | 3,154 |
| watcher 汇总 / 持久记录 | 2,043 / 2,032 | 1,489 / 1,467 | 3,532 / 3,499 |
| accepted / needs_attention | 1,660 / 372 | 1,303 / 164 | 2,963 / 536 |
| 两个汇总时间倒查出的唯一锚点 | 1,796 | 1,336 | 3,132 |
| 完整消费轨迹：支持舞蹈的单 VRCX 锚点 watcher | 1,806 | 1,336 | 3,142 |
| 完整消费轨迹：支持舞蹈的多 VRCX 锚点 watcher | 1 | 1 | 2 |
| 完整消费轨迹覆盖的支持舞蹈 VRCX 行 | 1,808 | 1,338 | 3,146 |

最后 8 条对应的是当前不支持的外部 URL。原来没有被两个汇总时间找到的 22 行中，12 行
能从实际消费轨迹补回为单锚点，2 行属于上述两个有问题的多锚点集合，8 行没有支持的舞蹈身份。
补回这 12 行不需要把精确时间放宽为 ±1 秒。

3,132 / 3,154 = 99.30% 是“已经在日志找到 VideoPlay 标记的 VRCX 行”这一条件下的
倒查覆盖率，不是全部历史的召回率、自动合并准确率或 watcher 已实现 v2 合同的证明。

### 其他共同输入有实际收益

固定版本 VRCX 还读取 `[Video Playback] Attempting to resolve URL` / `Resolving URL`、
`User ... added URL` 及特定 USharpVideo 加载行。URL 解析行在本样本提供新增对应。
依据见 [VRCX LogWatcher.cs](https://github.com/vrcx-team/VRCX/blob/v2026.07.18/Dotnet/LogWatcher.cs#L737)。

| 原始解析行实验 | v0.7 | v0.8 | 合计 |
| --- | ---: | ---: | ---: |
| 没有 VideoPlay 标记对应的额外 VRCX 行 | 189 | 176 | 365 |
| 其中有支持的舞蹈身份 | 177 | 162 | 339 |
| 其中实际归入支持舞蹈 watcher | 70 | 117 | 187 |
| 其中支持舞蹈但未被 watcher 消费 | 107 | 45 | 152 |
| 将全部共同输入合看后新增的单锚点 watcher | 60 | 111 | 171 |
| 全部共同输入合看后的单锚点支持舞蹈 watcher | 1,864 | 1,447 | 3,311 |
| 全部共同输入合看后的多行支持舞蹈 watcher | 6 | 4 | 10 |

实验要求精确 UTC 时间、从原始语句抽取的完整 URL、当时完整 instance；记录消费关系，
并在所有此类输入上检查双向唯一性。本样本没有一条 VRCX 行被多个 watcher 争用。
这里的“单锚点”按不同 VRCX 行计数，同一行的多条同血缘日志不重复计票。

3,311 是按上述输入与一对一限制得到的候选规模，不是已经验证、上线的自动合并数。
相对仅 VideoPlay 的 3,142，净增加 169：171 个新增单锚点，同时完整输入又暴露两个
原先看似单锚点的多行集合。不能只加新增覆盖而忽略新发现的歧义。

152 条有舞蹈身份却没有被 builder 消费的解析行对应其 preview suppression 路径。
VRCX 有记录不等于 watcher 观察到完整舞蹈。其是否默认计入历史仍由产品接受规则决定，
不能以 reconciliation 暗中压掉这些记录。原设计的 VRCX-only 默认 accepted 是显式产品
取舍，不是这次实验能证明的完成事实。

## 精准率、召回率与候选覆盖率的区别

追加复核仍只读取冻结产物，结果见
`analysis/vrcx-merge-review-20260905/coverage_metrics.json`。
正例定义为“某条 VRCX evidence 与 watcher evidence 属于同一次播放”；精准率的分母是
实际放行的合并，召回率的分母是独立真值中所有应该合并的关系。
当前完整的过程边界验证尚未实现，也未独立标注全部播放关系，因此真实精准率和召回率
均不能给出可靠百分比。不能用本方案自己找到的共同输入直接构造真值再宣称精准率 100%。

以下是可以实测的候选覆盖，以同一批 3,499 个持久 watcher 记录为分母：

| 指标 | 数值 | 含义 |
| --- | ---: | --- |
| 仅 VideoPlay、完整消费轨迹的单锚点候选 | 3,142 / 3,499 = 89.80% | 相同限制下的比较基线 |
| 扩展共同输入后的单锚点候选 | 3,311 / 3,499 = 94.63% | 净增加 169 个、提高 4.83 个百分点；不是召回率 |
| 多锚点而暂缓归并 | 10 个 watcher，涉及 22 行 VRCX | 包含 2 个已确认串播反例，也包含需要确认的重试链 |
| 未找到精确共同输入 | 178 个 watcher | 其中 142 个消费过 VideoPlay，36 个没有消费过该标记 |

v0.7、v0.8 的扩展候选覆盖率分别为 91.73%、98.64%，不能把综合比例当作不同日志版本
或其他用户环境的保证。没有精确数据库对应行也可能是 VRCX 未运行、同 URL 去重，或
两侧来源覆盖不同；178 个未匹配不能直接全部计为假阴性。

归并假阳性是把不同播放合到一起。已知主要风险是 watcher 先串错播放过程；如果其中一条
VRCX 行缺失，串错的 watcher 还可能呈现单锚点，因此双向唯一不能替代过程边界验证。
其他潜在风险包括同秒同 URL 的不同播放、上下文缺失使 instance/session 误归属、过度 URL
归一化，以及缺乏明确请求身份时的异步回调交错。本样本未验证这些风险的发生率。

归并假阴性是同一次播放的两份证据仍然分开。可能来自共同原始输入缺失、时间或 URL
表示差异、暂未支持的来源解析路径、watcher 把同一过程拆成多个片段，以及一对一规则
保守拒绝本可由明确重试链证明的多行关系。某个 occurrence 只在一个来源存在时，不属于
“应该合并却没合并”的错误。

下一阶段应独立标注放行候选和拒绝集合中的播放过程，单独核对重试与重播，再计算
`precision = TP / (TP + FP)` 和 `recall = TP / (TP + FN)`。抽样评估还需报告样本覆盖
和置信区间。是否 accepted/完成是另一项评估：即使归并完全正确，预览或失败记录默认
计入历史仍可能产生计数上的假阳性。

## 哪些原始信息值得保留

| 信息 | 本次证据 / 用途 | 不能做的推断 |
| --- | --- | --- |
| VideoPlay 原始 UTC 时间、完整 URL、完整 instance、位置 | 3,154 条直接对应；作为共同来源锚点 | 不用实际播放开始时间替代标记时间 |
| URL 解析输入、路由边、明确 retry/error | 额外 365 行；可建立版本化的其他共同输入规则，证明明确的加载重试链 | 不能仅按舞蹈 id 把不同 URL 视作同一次 |
| 原始 CSV title、position、duration、world parser | 保留未清洗值，能重放来源解析；`114514` 在本样本需保留为原值，不能当真实时长 | position=0 不证明开始或完成，正 position 不一定是新请求 |
| 标记时的 requester、同房间身份映射及来源位置 | 标记层 user id 比对：2,632 对两侧有值且相同，0 对两侧有值却冲突，296 对单侧缺失，226 对均缺失 | 不把旧缓存的 user id 与当前名称拼成新的可信身份 |
| PlayQueueVideo / PlayRandomVideo、userData、isRandom | 分辨排队、预览、随机、当前加载状态，辅助字段 resolver | 队列中出现不等于已经播放 |
| userData.version | 每批分别有 52 / 50 个 version 跨多个 event 重复，最多覆盖 92 / 53 个 event | 不能当 occurrence id 或唯一队列请求 id |
| OnVideoStart、OnVideoError、明确切歌、OnLeftRoom、进程/日志边界 | 划定一次播放观察过程，防止异常挂起记录吸收后来的重播 | 无日志不证明没有发生；无完整上下文时保持未证明 |
| gamelog_location / gamelog_join_leave | 快照分别有 1,769 / 40,359 行，能辅助实例与请求者上下文 | VRCX 行的 id、world_id、全局显示名不等于播放身份 |
| gamelog_event / resource_load / external | 分别有 272 / 0 / 0 行；错误类上下文可诊断 | 本样本没有额外资源加载表信息可用来提高覆盖 |

### 字段差异需要先排除表示方法和缓存污染

原文的标题“仅 84 对相同”可复现，但比较的是 Dancing Log 去掉编号后的标题与 VRCX
自己的解析结果。复刻固定版本 VRCX 的 PyPyDance 解析后，3,153 个适用样本的标题全部
一致（含 5 对两侧为空）；`video_id` 同样一致或同时为空。剩余 1 个是 VRDancing。
因此这是可解释的表示差异，不能用来证明原始标题信息不可靠。
依据见 [VRCX mediaParsers.js](https://github.com/vrcx-team/VRCX/blob/v2026.07.18/src/stores/gameLog/mediaParsers.js#L101)。

原文的请求者 758 次冲突对应汇总的原始 `display_name`；当前持久化实际采用
`source_display_name or display_name`，在同一 3,132 对上只有 3 次两侧有值却不同，
2,930 次相同、187 次单侧缺失、12 次均缺失。应明确字段名，避免把旧 metadata 字段当作
最终 requester。聚合 user id 的 583 次冲突仍可复现，说明保留标记时的身份依据比仅保存
最终汇总更有价值；不能以“id 稳定”为由盲信已经串到旧 occurrence 的 id。

原文 URL 的 3,050 / 225 次相同对应持久 `origin_json.watcher_playback_event`。
若读取重放结束时的 `playback_events.jsonl`，则为 3,051 / 222。此差异也说明统计应注明
具体产物及字段，汇总与结算快照不能混用。`source_file` 的 1,602 次不一致已复现，不能
从这个字段配合 first/last line 重建原始来源位置。

VRCX 的 PyPyDance parser 对当前相同 URL 会更新 now-playing 而不新增历史；通用输入
还有 `decodeURI`、RPC-world gating 和 last URL 去重。实际保存 `created_at` 的时钟来自
原日志前 19 字符转 UTC，并非实际播放开始时间。实现时应固定并记录这些来源解析规则的
版本，保存原始时间及其 timezone/precision，不把本机现在的时区作为历史时间的隐含依据。
补充源码探针确认：`nowPlaying` 还可能因本地计时结束被清空，因此同 URL 去重范围并非
固定时间窗；晚处理历史输入与实时处理可能产生不同写库行为。计时状态及位置、时长没有
写入视频表，不能用数据库行恢复完成事实。
依据见 [时间转换](https://github.com/vrcx-team/VRCX/blob/v2026.07.18/Dotnet/LogWatcher.cs#L319)、
[通用视频输入处理](https://github.com/vrcx-team/VRCX/blob/v2026.07.18/src/coordinators/gameLogCoordinator.js#L306)、
[历史插入条件](https://github.com/vrcx-team/VRCX/blob/v2026.07.18/src/stores/gameLog/index.js#L256)。
固定版本的实现与样本相符，不意味着这些历史行都由同一版本 VRCX 生成。

## 建议采用的经验方案

1. **先修正并验证 watcher 的播放过程边界。** 预览、失败后被其他正式播放替代、离房和
   重新请求都必须有明确语义。每条最终证据保存该过程实际消费的完整来源位置集合；
   raw 行、byte offset、line number、日志血缘/稳定身份、内容指纹及解析版本随之保留。
   单个汇总 `source_file`、首尾时间或 line range 不够。文件完整 SHA-256 用于本次静态审计；
   追加中的 live 日志不能以不断变化的整文件 hash 直接充当永久来源身份。
2. **将“定位 VRCX 来源行”与“归入同一次播放”分别验证。** VideoPlay 首选精确标记
   UTC 秒、未归一化 URL、完整 instance。为通用解析输入增加独立的版本化规则，验证
   VRCX 的实际解析路径和 URL 转换；当前实验只覆盖 raw URL 本身精确一致的子集。
   这两种输入都需要 watcher 在正确播放过程中实际消费，不能靠全局时间检索来补造血缘。
3. **默认只接受完整集合中的双向唯一、自洽关系。** 同舞蹈、相同 title/requester、位置
   接近、时间接近、队列 version 或顺序只能检索候选。完整集合含不同过程、不同实例、
   身份矛盾或候选争用时，不生成自动 redirect；不能从集合中选一条恰好能匹配的边。
4. **多条 VRCX 行只在来源过程已有明确证明时合入同一 Handle。** 如失败后的明确
   路由重试链，可成为一条自足 watcher evidence 中的多个共同输入；需有过程内链路，
   不能用同 URL 或“只间隔几秒”代替。明确进入新播放过程、或无法解释的多个锚点继续
   保持独立，不把任意相似边做传递闭包。
5. **字段独立解析，保留成组的身份依据。** 时间同时保留 marker/request、actual-play
   及估计依据；requester 的名称和 id 绑定到同一时间、房间及来源证明；标题保留 raw 和
   源 parser 表示。来源字段有差异不否定已经证明的血缘，也不通过全局来源优先级掩盖
   已串到旧播放的字段。VRCX 与其原始日志是同血缘，不是两份独立投票。
6. **按现有 v2 Handle 合同提交。** 双向唯一性在整批与已有相关有效证据中检查；尊重
   `do_not_merge`、已有 membership、redirect 和用户状态；来源位置去重、自动关系依据与
   算法版本持久化。无严格证明的关系仍为 `possible_match`，继续独立消费，无隐形计数抑制。

这保留了当前设计的严格归并原则，也避免把 `[VRCX] VideoPlay` 永久写成唯一允许的共同
来源语句。它比放宽 `played_at` 时间窗有可解释的新增覆盖，但需先解决本报告的过程边界
反例才能实现。3,311 个一对一候选是当前样本的工程参考，不宣称全局最优或零误合率。

## 复现及实现验收

在仓库根目录执行，`--output` 必须是被 git 忽略的 `analysis/` 下的新目录：

```powershell
& .venv\Scripts\python.exe scripts/audit_vrcx_merge.py capture `
  --vrcx-db 'path/to/vrcx-snapshot/VRCX.sqlite3' `
  --log-dir 'v07=path/to/portable-snapshot/logs/source-vrc-logs' `
  --log-dir 'v08=path/to/portable-snapshot/logs/source-vrc-logs' `
  --output analysis/vrcx-merge-audit-new --utc-offset-hours 8
& .venv\Scripts\python.exe scripts/audit_vrcx_merge.py analyze `
  --output analysis/vrcx-merge-audit-new
```

`analyze` 只读取冻结产物，不重新访问外部来源。本轮在补充房间上下文时使用过
`refresh-context`；它在重新只读扫描前后检查原文件与 manifest 一致。新 capture 已直接
生成该上下文。主要产物为 `manifest.json`、`report.json`、各批次的 `diagnostics.json`、
`markers.jsonl`、`rooms.jsonl`、`consumption.jsonl` 及现有重放产物。

验证已运行：parser/folding/replay/importer/materializer 相关 14 项测试和 watcher 52 项
测试，全部通过；审计脚本通过 Ruff。既有测试通过未覆盖本次发现的两个真实边界反例。
未来实现至少需要以下验收：失败后隔多首歌重播不再串成一次；明确重试链可解释多行归属；
VideoPlay 与通用解析输入全量对照；相同输入 live/replay 幂等；跨文件及 timezone 不确定
时不伪造锚点；多输入/多批次排列、`do_not_merge` 和用户覆盖不会改变合法分组。
