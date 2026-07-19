# Watcher requester user id 临时映射设计笔记

日期：2026-06-23

## 目标

live watcher 采集来源证据时，尽量记录播放观察发生时能够直接关联到的 VRChat `user_id`，但不把它做成永久身份追踪系统，也不在 watcher 内把这些证据解释成 canonical Requester Identity 或 Request Source Type。

## Watcher 职责边界

watcher 是来源证据采集器，只负责读取新增日志、解析来源 payload、做确定性的字段整理，以及在同一 watcher/房间上下文内进行可追溯的有限身份补全。整理后的观察写入证据表，并保留原始值、source file、line range、parser name 和参与补全的身份日志 provenance。

watcher 不负责：

- 汇总或维护 durable `events` 表、canonical playback event 或 playback occurrence。
- 把多条观察合并为产品层事件真相。
- 推断 `request_type`，包括 `random`、`self`、`other` 或 `unknown`。
- 决定 accepted、excluded、needs-attention 等接受或复核投影。
- 执行历史数据 repair/rebuild、跨来源去重或 reconciliation。

同一 session 内的 display-name → user-id 补全仍属于证据整理，因为输入和关联过程都可以保留并审计；它不能因此升级为类型推断。当前实现若仍经过 folded event、legacy live table 或直接写入带投影字段的 `playback_records`，只视为兼容/过渡路径，不扩大 watcher 的长期职责。正式边界见 ADR 0013。

## 已确认语义

- source evidence 中的 requester/source display name 表示来源日志在观察发生时写出的显示名；下游可以把它投影到 `playback_records.requester_display_name`。
- source evidence 中的 `requester_user_id` 表示 watcher 在同一 VRChat 房间、当前 watcher/replay 会话、或启动时预读到的当前日志上下文中能确认的 `usr_...`；是否投影到产品记录由下游负责。
- 对 WannaDance，source display name 只取世界 payload 的 `playerName`。USharpVideo `Started video load ... requested by <name>` 表示技术性 video owner / executor，必须作为独立 origin/provenance 保存，不能在 `playerName` 为空时回退填充 source display name 或 canonical requester。
- 不因为用户后续改名而改写旧播放记录。
- 不用跨会话、跨房间、全局缓存或 VRCX 历史去补 watcher 记录的 requester user id。
- 如果来源播放观察先出现、身份行后出现，允许在同一房间内延迟回填同一条 source evidence observation。
- 映射生命周期按当前 VRChat 房间，而不是整个 watcher 进程。
- 切换房间、重新进入房间、应用退出等房间边界会让旧映射失效。

## 房间状态

实现应该把房间状态视为：

1. `active`：正常房间内。`OnPlayerJoined` / `User Authenticated` 可以建立当前可用映射；播放事件可以用当前唯一映射补 `requester_user_id`。
2. `closing`：看到 `OnLeftRoom` 后，到下一次 `Entering Room` 前。此阶段不再给新的播放事件使用旧映射，但仍接受紧随其后的 `OnPlayerLeft <display_name> (<usr_id>)` 来回填此前同房间 pending 的播放事件。
3. `cleared`：下一次 `Entering Room`、应用退出、或兜底超时/异常边界触发后。旧房间映射和旧 pending 回填任务都丢弃。

## 映射分层

一场 watcher session 内维护两层映射，方向只做 `display_name -> user_id`：

1. 当前有效映射：当前房间、当前仍认为在线/可用的 `display_name -> user_id`。
2. 过期映射：本 watcher session 内见过、但已经因为 `OnPlayerLeft`、房间 closing、房间切换等原因从当前有效映射移除的 `display_name -> user_id`。

过期映射可以跨房间，但只限当前 watcher session 及启动预读得到的当前日志上下文；不从持久身份表加载，不写入持久 identity 表。

播放事件补 `requester_user_id` 时：

- 优先查当前有效映射。
- 当前有效映射没有时，可以查本 watcher session 的过期映射。
- `cleared` 状态不使用过期映射补新的播放事件；无房间上下文下的孤立 `OnPlayerLeft` 只能计数/warning，不能写入过期映射。
- 刚进入新房间后，不立即使用跨房间带来的过期映射。先给当前房间的 `OnPlayerJoined` / `User Authenticated` 留出一小段宽限窗口；宽限期内的播放事件登记为同房间 pending，若后续当前房间身份行出现则用当前有效映射回填。
- 宽限窗口过后仍没有当前房间身份行时，可以对仍未补全的同房间 pending 事件使用过期映射回填，并记录 warning；宽限期后新出现的播放事件也可以使用过期映射补 id，并记录 warning。
- watcher session 正常结束时，可以对仍未补全且已经捕获过期映射候选的 pending 事件做一次最终回填，并记录 warning。
- 同一个 `display_name` 在当前有效映射和过期映射之间也应当只有一个可查结果；如果 `display_name` 重新进入当前有效映射，应从过期映射移除。
- 使用过期映射补 id 时必须记录 warning，但不能阻塞 watcher。
- 如果同一 display name 在 session-local cache 中被观察到新的 user id，更新该 display name 的当前可查 user id，并记录 warning。
- 不维护 `user_id -> display_name` 作为查询路径或永久身份真相。
- 同一 `user_id` 在同一 watcher session 中出现多个 display name 不影响补 id 逻辑；播放记录保留事件发生时已经写入的 display name，不因为后续改名回改。
- 如果同一 display name 后续对应了新的 user id，按 session-local enrichment cache 更新该 display name 的当前可查 user id，并记录 warning；已经写入的旧记录不因此回改 display name。

## 延迟回填范围

- 允许回填同一 watcher session 内同一 source evidence observation 的 `requester_user_id`；下游记录当前处于何种投影状态不属于 watcher 的判断条件。
- 回填只填 `requester_user_id` 为空的证据；已有 `requester_user_id` 不覆盖。
- 证据 upsert 时必须保留已有的非空 `requester_user_id`；自动 watcher 写入不能用空值或另一个新非空值覆盖它。
- 保留已有 `requester_user_id` 时，origin/provenance 中的 `requester_user_id` 和 `requester_user_id_source` 也必须同步保留，避免规范字段和证据 JSON 表达不同身份。
- 回填只能按 watcher/source observation 的稳定身份更新同一条证据，不能只凭 display name 去扫描旧历史。
- 如果回填使用的信息来自过期映射，应继续记录 warning。
- Requester Identity 是用户可纠正的播放字段；watcher 身份补全属于来源证据补全。未来如果存在 active Manual Record Update/overlay，自动补全不得覆盖用户手动纠正的 requester 身份。
- 不倒改已经写出的 `parsed_events.jsonl`。`parsed_events.jsonl` 表示按日志时间线 append-only 记录的单行解析结果；延迟回填写入同一 source evidence observation 及其 provenance。当前 folded playback event、live DB 或 `playback_records` 若镜像该结果，只属于兼容路径，不能成为唯一来源。

## 临时快照（暂缓该方案，但保留这个备选设计，不删除）

- watcher 应把当前 session-local enrichment cache 保存到临时运行状态文件，用于异常退出后给下一次 watcher session 作为初始过期映射加载。
- 快照包含当前有效映射和过期映射，但下一次 session 加载时全部视为过期映射；不能把旧 session 的 active 直接恢复成新 session 的 active。
- 快照不是永久身份真相，不写 SQLite，不参与历史重算。
- 保存可以懒惰、节流，不能影响 watcher 性能；正常退出时应再保存一次。
- 快照需要有增长控制，避免过期映射无限传递（如数量上限）。

## 启动预读

- watcher 启动时向前读取一定量当前 VRChat log 内容，重建初始 `display_name -> user_id` enrichment cache。
- 预读范围优先从当天当前日志里最近一次 `Entering Room` 开始，到 watcher 开始读取的位置为止。
- 如果预读判断当前仍在房间内，预读得到的 mapping 初始化为当前有效映射。
- 如果可靠信息表明当天最后一个 `Entering Room` 后已经 `OnLeftRoom`、app quit、或其他可判断的离房/离线状态，严格语义下可以不使用这些信息；当前实现可以宽松地把这些 mapping 初始化为过期映射。
- 如果预读内容来自此前房间或无法确认当前仍在房间内，预读得到的 mapping 初始化为过期映射。
- 如果因为任何原因没有读到可用内容，例如进游戏前先启动 watcher、文件太短、找不到当天 `Entering Room`，则用空 mapping 启动，不阻塞 watcher。
- 当天日志文件不存在是正常启动路径，不应记录 warning。
- 找不到可用房间段、读取超限、解析失败等预读异常可以记录 warning。
- 预读得到的过期映射只有在被实际用于填 `requester_user_id` 时才记录 warning；单纯加载不 warning。
- 启动预读必须有上限，不能无界扫描当天所有日志；如果达到上限仍找不到可用上下文，则用空 mapping 启动并记录 warning。
- 现有日志中 2-3 小时房间段有 22 个，行数约 7.5k-17k，字节数约 1.5-3.4MB。按当前样本，预读一个长房间段的性能压力较小，但仍保留 bounded 设计。
- 预读是从源 VRChat 日志重建当前上下文，不是永久身份缓存，不写 SQLite，不参与历史重算。

## 实现位置

- 身份补全应发生在 watcher drain loop 中，位于 parser 产出 capture record 之后、证据 writer 写入之前。
- 证据 row 与 origin/provenance 必须看到同一个 enrichment 结果；runtime-only folded event 可以读取它，但不能成为唯一持久来源。
- evidence materializer/storage 层只负责保存 capture record 中已经确定的 `requester_user_id`，不再自己查身份映射。
- `requester_user_id` 的补全来源写入证据及其 provenance；是否投影到产品记录由下游独立流程决定。
- 来源分类保持粗粒度：`active`、`expired`、或 `payload`。其中 `payload` 表示播放日志 payload 本身已经包含 user id，不是通过 display-name mapping 查出来。
- watcher 身份补全不负责推断任何 Request Source Type，也不因为拿到 `requester_user_id` 就写出 `random`、`self`、`other` 或 `unknown`。
- Request Source Type 推断应由后续独立流程负责；它可以使用 `requester_user_id`、`self_user_id` 和其他证据，而且不需要强调实时性。
- 现有 watcher 产出的 `player` / `random` / `unknown` 粗分类可以为了兼容暂时保留，但应显式视为待移除的 watcher-side legacy projection；它不是新证据 contract，也不能作为新推断的输入。

## OnPlayerLeft 处理

- `OnPlayerLeft <display_name> (<usr_id>)` 证明该用户刚刚离开前的身份。
- 它可以用于回填此前同房间、同 display name 的 pending source evidence observation。
- 它会把该 display name/user id 从当前有效映射移到过期映射。
- 后续播放事件如果当前有效映射没有匹配，可以从过期映射里找唯一匹配并补 `requester_user_id`，但要记录 warning。

## 现有日志验证

基于 `logs/source-vrc-logs` 的只读统计：

- source log 文件：46
- 房间段：173
- 有 `OnLeftRoom` 关闭的房间段：127
- 文件结束时仍打开的房间段：46
- `OnPlayerJoined`：1958
- `OnPlayerLeft`：1730
- 没有 active join 的 leave：0
- 同一 active 房间内同 display name 多 user id：0
- 关闭房间后未配对 active user：0
- `OnLeftRoom`：127
- `OnLeftRoom` 后出现下一次 `Entering Room`：127
- `OnLeftRoom` 和下一次 `Entering Room` 之间的身份行：775
- `OnLeftRoom` 和下一次 `Entering Room` 之间的视频相关行：1175
- 相邻 `Entering Room` 房间段整体行数：p50 696，p90 10112，p95 12676，max 17058。
- 2-3 小时房间段：22 个；行数 p50 12227、p90 14368、max 17058；字节数 p50 2.4MB、max 3.4MB；身份事件 p50 80、max 140。
- 2-3 小时房间段的身份事件通常贯穿整段：首个身份事件 p50 在第 248 行，22/22 个段在前 1000 行内有身份事件，21/22 个段在后 90% 区间也有身份事件。
- 当前样本中，完整读取并解析 46 个 source log（约 78.5MB）约 2.1-2.7 秒；最大单文件约 3.8MB，完整扫描约 0.10 秒；最大 2-3 小时段按整文件读取并扫描约 0.05 秒。

结论：样本支持房间内映射和 leave 回填，但实现不能假设 `OnLeftRoom` 后没有其他日志行。

## 验收要求

- 真实日志 replay 是实现验收的一部分，不是可选 smoke。
- 实现后必须用 `logs/source-vrc-logs` replay，统计 watcher source evidence 的 `requester_user_id` 覆盖率、active/expired/payload 来源数量、warning 数量，以及预读相关 warning。
- 单元测试需要覆盖核心状态机和回填规则，但不能替代真实日志 replay。

## 容错原则

- 可以按理想路径写核心逻辑，但 watcher 不能因为异常顺序阻塞或崩溃。
- 如果触发兜底路径，应记录 warning，继续运行。
- 当前仓库还没有系统性的程序日志实现；watcher 身份映射 warning 先写入本次 session 的 `summary.json`，不要混入 `errors`。
- warning 记录方式应保留未来升级空间：后续如果引入正式日志系统，可以把同一类诊断迁移为程序日志，同时继续按需在 summary 中保留汇总。
- warning 默认保留完整 display name 和 user id，方便本地用 VRCX 或源日志验证；脱敏可以作为后续可选能力，不作为当前默认。
- 兜底场景至少包括：
  - `OnLeftRoom` 后迟迟没有 `Entering Room`。
  - `OnPlayerLeft` 后又出现同 display name 的播放事件，并使用过期映射补 id。
  - 使用启动预读得到的过期映射补 id。
  - 同一 watcher session 内同一 display name 被观察到新的 user id，并替换 cache 中该 display name 的 user id。
  - 看到无法配对的 `OnPlayerLeft`。
  - watcher 从日志中段启动，缺少当前房间的初始 join burst。
  - 启动预读找不到可用房间段、读取超限、解析失败。
