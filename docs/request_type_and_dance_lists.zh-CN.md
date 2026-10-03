# request_type 与舞蹈计划讨论

日期：2026-06-26

状态：v2 Request Source Type Inference 与 Dance Plan 领域语义设计。Playback Handle、Source
Evidence Event 和 v2 切换边界以 `playback_data_model_redesign.zh-CN.md` 及相关 ADR 为准；
本文不定义物理 projection/cache schema，也不构成 v1→v2 迁移计划。除明确讨论 legacy
实现处外，本文的 playback record 在 v2 中应理解为 Handle-addressed Playback Occurrence。

## 已记录的判断

- 用户面对的 canonical term 使用“舞蹈计划”。“待跳清单”、“待跳舞清单”、“预排清单”只作为讨论词或说明词，不作为正式产品名。
- `queued_self` 这个名字不适合作为用户面对的舞蹈计划概念。
- 长期 `request_type` canonical value 使用 `planned`，表示这条已播放记录被识别为来自预先安排的舞蹈计划。`queued_self` 只作为 legacy input alias 或旧数据解释词，不进入新的正式产品表或 canonical `request_type` 投影。
- Request Source Type Inference 的分层是 `planned > recommend > self/other/random > unknown > NULL`。`self`、`other`、`random` 是互斥同级分类，没有彼此之间的优先级；`NULL` 不是 canonical value，只表示尚未推断或不适用推断。
- 真实 VRC output log 与 watcher evidence 范围内的显式 random 证据已经确认：WannaDance `isRandom=true`、PyPyDance 专属 `Random` marker、DUDU `shuffle=true` 可以由下游 Request Source Type Inference 投影为 canonical `random`；没有显式证据且无法建立可信 requester 时为 `unknown`。VRCX 历史数据库缺失 marker 的记录不能靠 blank requester 猜 random。
- `playback_records.request_type` 为空是预期内状态，因为它是推断输出，不是推断输入；现有 `request_type` 值不应影响新的全局 rebuild。
- watcher 只负责把真实日志中的直接观察做确定性整理并忠实写入证据表；它不负责汇总 durable `events` 表、生成 canonical playback event、推断 `request_type`、决定接受状态或执行 repair/rebuild。当前 watcher-side `player` / `random` / `unknown` 只属于待移除的 legacy projection，不是新证据 contract。
- Catalog 页面里的歌曲旁边应该有一个加号，用来把该舞蹈条目加入舞蹈计划。
- 舞蹈计划不应该继续用 txt/Markdown 文件作为长期存储，而应该规范化存到 SQLite 数据库内。
- Plan item 应该和实际跳过的 accepted 播放内容对应；如果当前跳舞日没有对应上，item 可以继续保留到后续跳舞日。
- `dance_plan` 本身不绑定日期。顺延意味着同一个未完成 item 继续留在 active plan 中，而不是每天创建一个新的 plan。
- 第一版默认就有一份舞蹈计划，不需要用户再次创建。第一版不强调计划名，但 schema 需要给未来多张命名舞蹈计划留兼容性。
- 第一版 Catalog 加号不弹目标选择框，默认加入当前 active/current `dance_plan`。
- 用户可以移除还没有匹配到 accepted playback 的 `dance_plan_item`。已经匹配到 accepted playback 的 item 不应直接删除，因为它已经成为计划与实际播放之间的对账痕迹。
- `dance_plan_item` 匹配到 accepted playback 后，可以直接把对应 playback record 的 `request_type` 提升为 `planned`。即使实际 requester 是别人，也可以视为 planned，因为 Request Source Type 的优先级用于保留更强的计划意图，requester identity 仍由 `requester_display_name` / `requester_user_id` 单独表达。
- 自然顺延不需要每天复制 item，但 UI 应让用户看出哪些 item 是当前跳舞日新增的，哪些是以前遗留下来继续顺延的。
- 用户可以添加当前时间之前的历史 plan item，用来补录或修正已经发生过的计划。
- 用户可以强行删除已匹配到 accepted playback 的 plan item，但系统必须警告：删除后 fulfillment 关系解除，playback record 的 `request_type` 会恢复为未匹配 plan 时的默认 request type，例如 `self`、`recommend`、`other`、`random` 或 `unknown`。
- 如果用户把已 fulfill 的 playback record 变为 excluded，系统应自动解除 fulfillment 关系，并移除 plan 对这条 record 的 `planned` 覆盖；该路径不需要删除警告。系统随后询问原 plan item 是继续顺延，还是直接移除。
- 旧 `data/queued_self/` manifest 不迁移、不保留长期兼容导入。用户如需恢复旧计划语义，应通过手动添加历史 plan item 的方式补回。
- Plan item 必须区分“添加日期”和“计划执行日期”。建议字段名使用 `intended_local_date`，表示用户希望这条 item 在哪个本地日期执行；`added_at` 只表示它何时被加入计划。
- 同一个 intended local date 内，同一首目标 dance track 不应重复出现。如果顺延 item 和当前跳舞日计划 item 重复，当前跳舞日显式计划 item 胜出，旧顺延 item 标记为 `superseded`，并记录取代它的新 item。
- 如果一个已 fulfilled 的 superseding item 被用户强行删除，旧 `superseded` item 不应自动改成 `fulfilled`，也不应接管同一条 playback。删除这条 fulfilled item 的产品语义是解除这次计划匹配；旧 item 应随这次删除一起从 active/superseded 链中移除或墓碑化，避免 UI 看起来像用户刚删除的匹配又回来了。
- 第一版 plan item 删除/移除使用 `removed` / tombstone 语义，而不是物理删除行。Removed item 默认不在 UI 的 active plan 中展示，也不参与顺延、supersede 恢复或 fulfillment 匹配。删除后可以提供短暂 undo；长期恢复入口以后再做。
- 第一版 `dance_plan_items` schema 草案包含 `superseded_by_plan_item_id` 和 `removed_at`，分别支撑 superseded 恢复链和 removed tombstone。
- 用户应能手动设置本地跳舞日的分界线。默认分界线是本地 24:00/00:00，也可以改为次日 01:00、03:00 等，用来让深夜播放归入前一个跳舞日。
- Local Dance Day Boundary 存在本地配置中，plan/item 不保存自己的 boundary snapshot。用户第一次操作 plan 相关功能时，系统必须显式提醒并引导去 Settings 设置；不要在计划界面内做完整设置表单。提醒中可以提供一次性确认当前设置的操作。
- 跳舞日分界线提醒必须显示当前设置值，并提供“使用当前设置”操作。用户确认的是当前 `dance_day_boundary_time` 设置，不是当前系统时间。
- 配置字段名使用 `dance_day_boundary_time`，值为 `HH:MM` 本地时分字符串；第一版允许范围为 `00:00` 到 `06:00`，默认建议值为 `00:00`。

## 现有上下文

`CONTEXT.md` 已经把 Dance Plan 定义为播放前的计划集合，和 Catalog、Timeline、历史播放分开。中文产品名使用“舞蹈计划”。

`CONTEXT.md` 和现有数据模型文档也把 Request Source Type 定义为播放记录上的 request/playback-source 分类。当前运行时字段仍叫 `source_type`，长期字段名计划使用 `request_type`。

当前代码里的 `queued_self_importer.py` 仍读取 `queued_self_dir` 下的 Markdown manifest，并按本地日期、舞蹈系统和 external id 去匹配已有 accepted `playback_records`。真正修改 `request_type` 的 hook 目前是暂停状态，`promote_request_type()` 不会写入数据。

当前 Web UI 的 Catalog 主要是搜索和查看舞蹈条目；Lists 页面展示的是 queued-self manifest 文件预览，而不是数据库里的规范化舞蹈计划。

## 建议边界

舞蹈计划是计划意图，不是播放证据。Plan item 可以指向一个 `dance_track`，表示“我想把这首放进某个舞蹈计划里”，但它本身不应该创建 playback record。

舞蹈计划允许混合不同舞蹈系统的 dance track。`dance_plan_items` 存规范化后的 `dance_track_id`；系统名不是 plan item 的独立字段，而是由 `dance_track_id` 关联到 `dance_tracks` / `dance_systems` 得出。任何使用系统内编号的输入或导入路径都必须同时提供舞蹈系统 key，避免裸 external id 歧义。

这个设计依赖一个前提：`dance_track_id` 必须是同一个本地数据库内部的稳定引用。Catalog 同步和导入可以更新 dance track 的标题、舞者、人数等 metadata，但不应因为 metadata 变化而删除并重建 dance track row。一个 dance track 的长期自然身份由舞蹈系统和系统内 external id 决定；如果未来确实需要合并、拆分或重建 dance track，必须显式迁移所有引用它的 plan item，而不是让计划静默断链。

`dance_track_id` 不是跨数据库、跨重建或导出文件里的公开身份。舞蹈计划在本地表里可以引用 `dance_track_id`，但任何导入、导出、重建、修复或跨库迁移路径都必须能回到 `dance_system_key + dance_external_id` 这个自然身份。

用户可以补录历史 plan item。历史 plan item 仍是计划意图的修正，不是播放证据；它只有匹配到 accepted playback 后才形成 fulfillment。

Accepted Playback Occurrence 是当前被纳入普通历史和 Insights 的 Handle-addressed 播放解释。它必须由已发布证据支持，不能因为某首歌在舞蹈计划里就直接算作 accepted。

`request_type = planned` 只描述某条已播放记录“被识别为来自预先安排的舞蹈计划”。它不应该作为计划表、计划页面或用户操作的主名称。旧 `queued_self` 如果继续被读取，只应该作为兼容旧数据的 alias。

`planned` 继承旧 `queued_self` 在 Request Source Type 优先级里的最高语义。计划匹配可以覆盖 `recommend`、`self`、`other`、`random` 或 `unknown`，后续 VRCX 导入、watcher 解析或手动来源推断不应该把它降级。这个覆盖只改变 request/source 分类，不删除或改写 requester identity。

`planned` 覆盖需要可撤销，但不需要保存覆盖前的 request type。每种 Request Source Type 都应该能由自己的证据和策略解释；解除 fulfillment 时，系统重新运行 Request Source Type 推断，恢复为未匹配 plan 时的 `self`、`recommend`、`other`、`random`、`unknown` 或空值。

舞蹈计划规范化后，文件 manifest 不再作为导入来源、迁移输入或长期编辑面。旧 `data/queued_self/` 内容可以丢弃；需要保留的计划语义由用户手动补录为历史 plan item。

## 初步数据模型方向

这只是讨论草案，不是最终 schema。

已确认采用两层表：

- `dance_plans`：一份舞蹈计划。
- `dance_plan_items`：舞蹈计划中的具体舞蹈条目。

使用复数表名是为了和现有 schema 里的 `dance_systems`、`dance_tracks`、`music_tracks`、`playback_records` 保持一致。领域概念和代码类型可以用单数 `Dance Plan` / `DancePlan`。

当前 `dance_plans` schema 草案：

```sql
dance_plans(
  id,
  plan_name,
  status,       -- active / archived
  sort_order,
  created_at,
  updated_at
)
```

`dance_plans` 不应该要求 `target_local_date`。计划日期属于 `dance_plan_items.intended_local_date` 或实际 accepted playback 的日视图查询上下文，不属于 plan 的主身份。所有本地日期都应按用户配置的 Local Dance Day Boundary 计算，而不是直接使用自然日 00:00。

不建议在 `dance_plans` 上放 `is_default`。第一版默认就有一份舞蹈计划，用户不需要创建，也不需要关注计划名；当前目标计划可以直接由“唯一 active plan”推导。未来实现多计划时再持久化当前目标，优先考虑放在应用状态或配置中，例如 `current_dance_plan_id`，而不是让多行 plan 通过布尔值竞争默认身份。

当前 `dance_plan_items` schema 草案：

```sql
dance_plan_items(
  id,
  dance_plan_id,
  dance_track_id,
  plan_order,
  status,
  fulfilled_by_playback_handle_id,
  superseded_by_plan_item_id,
  intended_local_date,
  added_at,
  removed_at,
  updated_at
)
```

这版草案覆盖了所属舞蹈计划、目标舞蹈条目、计划顺序、状态、fulfillment、superseded 恢复链、计划执行日期、加入时间、移除时间和更新时间。`superseded_by_plan_item_id` 在旧 item 被后续同目标 item 取代时指向取代它的新 item。`removed_at` 在 item 进入 `removed` tombstone 状态时记录移除时间；`updated_at` 仍表示最后修改时间，不兼任移除时间。未匹配 item 可以被用户移除或标记 skipped。已匹配 item 默认不直接删除；如果用户强行删除，必须先警告并解除 fulfillment，同时让 playback record 重新推断未匹配 plan 时的 request type。

第一版最小数据规则用自然语言表达即可，数据库约束以后从这些规则推导：

- `dance_plans.status` 只允许 active 或 archived。
- `dance_plan_items.status` 只允许 planned、fulfilled、skipped、superseded、removed。
- 每个 plan item 必须属于一份舞蹈计划，并指向一个 dance track。
- fulfilled item 必须指向一条 fulfilled 它的 playback record；非 fulfilled item 不应该保留 fulfillment 关系。
- superseded item 必须指向 superseding item；非 superseded / removed item 不应该保留 superseded chain。
- removed item 必须有 removed time；非 removed item 不应该有 removed time。
- removed、skipped、superseded item 都不参与 active plan 展示、自然顺延、重复目标检查或 fulfillment 匹配。
- 同一份舞蹈计划、同一个 intended local date 内，同一支 dance track 第一版只能有一个 active planned item。

同一 `dance_plan` 内，不允许同一个 `intended_local_date` 下重复添加同一个 `dance_track_id` 作为 active planned item。顺延 item 与当前跳舞日新计划 item 撞车时，当前跳舞日显式计划 item 胜出，旧顺延 item 标记为 `superseded`，并保存 `superseded_by_plan_item_id` 指向新 item。这样旧 item 不会继续顺延，也不会被错误标成 `skipped` 或 `fulfilled`。

## Catalog 加号行为

Catalog 里的加号应该表示“把这个舞蹈条目加入当前目标舞蹈计划”，不是“记录一次播放”。

需要避免两个误解：

- 加号不直接写 playback record。
- 加号不直接把未来的播放结果标记为 accepted。

加号点击后，第一版默认加入那份已经存在的 active/current `dance_plan`。若该 `dance_track` 已经在当前 plan 的同一个 intended local date 中，按钮应显示已加入或执行 no-op，避免重复添加。

未来支持多张命名 plan 时，可以在加号旁边增加下拉菜单或二级选择；这不改变第一版默认加号语义。

## 与 accepted 播放记录的对应关系

舞蹈计划和实际 accepted 播放可以在某个本地日期的视图里按 `dance_track_id` 和顺序做对应。日期是匹配窗口，不是 plan 的身份。

本地日期不是简单的自然日。所有 daily history、plan view、`intended_local_date` 和 fulfillment 匹配都应该使用 Local Dance Day Boundary。默认边界是 00:00；如果用户设为 03:00，则本地 2026-06-27 02:00 的播放仍属于 2026-06-26 这个跳舞日。

Local Dance Day 使用操作系统的真实本地时区规则，不假设固定 UTC offset。若春季 DST 跳变使配置的墙钟分界不存在，使用不早于该配置值的第一个有效墙钟时刻；若秋季 DST 使分界重复，第一次到达（`fold=0`）即进入新跳舞日。归属按解析后的 UTC 瞬间比较，回拨后不会退回前一个跳舞日。

Local Dance Day Boundary 是本地配置项，不是 `dance_plans` 或 `dance_plan_items` 的字段。配置字段名使用 `dance_day_boundary_time`，值为 `HH:MM` 本地时分字符串；第一版允许范围为 `00:00` 到 `06:00`，默认建议值为 `00:00`。系统每次计算跳舞日归属时读取当前配置；如果用户修改 boundary，相关历史分组和 plan 匹配视图会随之改变。为了避免用户无意中改变行为，第一次使用 plan 相关功能时必须显式提醒并引导用户去 Settings 设置；计划界面本身不承载完整设置表单。提醒必须显示当前 `dance_day_boundary_time` 值，并提供“使用当前设置”操作，让用户一次性确认当前 boundary 设置。

建议规则：

- 只用 effective accepted playback records 来 fulfill plan item。
- 第一版不允许同一份舞蹈计划、同一个 intended local date 内重复计划同一支 dance track。未来如果允许重复计划同一支舞，再按计划顺序和播放时间顺序配对，避免一个 playback record fulfill 多个 item。
- item fulfill 后，对应 playback record 的 `request_type` 应提升为 `planned`。这表示“这次播放完成了预先计划”，不要求 requester 必须是 self。
- 未匹配的 item 不代表失败，也不应该制造 needs-attention playback record。
- 未匹配 item 可以继续保留为 planned，这就是顺延；不需要每天复制成一条新 item。
- 用户补录历史 plan item 时，系统推荐或帮助匹配 existing accepted playback records 的范围必须有界。第一版只在 item 的 `intended_local_date` 和用户明确指定的有限未来天数内寻找有效 records，不能让很早以前未 fulfilled 的历史 item 自动顺延并匹配到大量后续历史。
- UI 应区分“当前日期预定”的 item 和“从以前顺延下来”的 item。这个区分应优先由 `intended_local_date` 与当前查看日期比较得出；`added_at` 只用于解释何时加入。
- 未匹配 item 可以由用户从 plan 中移除；已匹配到 accepted playback 的 item 只能在警告后强行删除。
- 如果未来确实需要复制式顺延，应保留来源关系，避免以后无法解释这个 item 是哪次加入计划的。

`superseded` 是系统自动状态，不是用户跳过。它表示旧 item 的计划意图已经被后续同目标 item 接管。只有 `planned` item 会继续自然顺延；`superseded` item 不再顺延。

如果 superseding item 后来被用户删除且尚未 fulfilled，系统应恢复被它取代的旧 item：清空旧 item 的 `superseded_by_plan_item_id`，把状态从 `superseded` 改回 `planned`，让它重新进入 active 顺延链。

如果 superseding item 已经 fulfilled 后又被用户强行删除，旧 item 不应改为 `fulfilled`，也不应恢复为 `planned` 并立刻重新匹配同一条 playback。用户删除已 fulfilled item 的含义是解除这次 plan fulfillment，并让 playback record 重新推断未匹配 plan 时的 Request Source Type；如果旧 item 自动接管 fulfillment，UI 会表现得像删除没有生效。因此旧 `superseded` item 应随这次删除一起从 active/superseded 链中移除，第一版用 `removed` / tombstone 语义保留痕迹，但不能把它标成 `fulfilled`。

Removed item 默认从 active plan UI 中隐藏，不参与自然顺延、supersede 恢复、重复目标检查或 fulfillment 匹配。它保留在数据里是为了审计、解释“为什么旧 superseded item 没有恢复”，以及支持删除后的短暂 undo；长期恢复入口以后再做。从表中移除所有 Removed item 应当对正常业务行为没有任何影响。

## 移除、排除与恢复

移除未 matched 的 plan item 是普通计划编辑，不影响 playback records。

强行删除已 fulfill 的 plan item 是破坏对账关系的操作，必须给出警告。确认后：

- 删除或解除该 plan item 的 fulfillment。
- 重新运行 Request Source Type 推断，将 playback record 的 `request_type` 从 `planned` 恢复为未匹配 plan 时的默认分类。
- 保留 playback record 本身和 requester identity。
- 如果该 fulfilled item 曾经 supersede 旧 item，旧 item 不能接管这条 playback；它应随这次强删一起标记为 `removed`，而不是变成 `fulfilled`。

如果用户先把 fulfilled playback record 变为 excluded，则系统应自动解除 fulfillment，并移除 plan 对该 record 的 `planned` 覆盖，`request_type` 变为空。这个路径不需要强删警告，因为用户的主要动作是把 playback record 排除出 accepted history。解除 fulfillment 后，原 plan item 的处置必须和这次 exclude 在同一个操作里完成，不能留下一个需要之后再处理的 pending plan action。UI / API 提交时应同时包含 `manual_decision = excluded` 和 `plan_item_action = carry_forward | remove`，后端在同一个 transaction 中应用 manual exclusion、解除 fulfillment、处理 plan item，并触发全局重算。

- 继续留在 active plan 中自然顺延。
- 从 plan 中移除。

用户可以选择“默认顺延，以后不再反复询问”。启用该偏好后，后续 fulfilled planned record 被 excluded 时，系统默认使用 `carry_forward` 处置原 plan item；用户仍应能在需要时修改这个偏好或在明确操作中选择移除。

如果用户随后把该 playback record 恢复默认，系统不恢复旧 fulfillment，而是按当前 Dance Plan 状态和 effective accepted records 重新全局对账。若原 plan item 仍 active 且匹配规则成立，它可以重新 fulfill；若原 plan item 已移除、已被其他 item supersede，或已匹配到别的 accepted record，则不会因为恢复默认而复活旧 fulfillment。

## 已收敛与暂缓事项

### 1. `planned` 与旧 `queued_self` 的过渡策略

已决定：从数据库 Dance Plan 第一版实现开始，所有新的 canonical `request_type` 输出都只使用 `planned`，不再新写 `queued_self`。`queued_self` 不进入新的正式产品表，不作为 `request_type`、Dance Plan、Dance Plan Fulfillment 或推荐/推断表里的规范值。

`queued_self` 只允许作为 legacy input alias、旧 manifest 读取、旧数据解释、旧测试输入 normalization 和 raw/origin/provenance 审计材料出现。任何统一 inference / rebuild 输出都必须把旧 `queued_self` 语义规范化为 `planned`；Web UI 可以识别旧值用于兼容显示，但正式产品文案和新写入数据都应使用“舞蹈计划”/`planned`。

实现切换时，`REQUEST_TYPE_PRECEDENCE` 应加入 `planned` 作为最高值。`queued_self` 可以在输入 normalization 层被识别，但不能和 `planned` 成为并列产品值。

### 2. Request Source Type 推断策略的归属和输入

已决定：Request Source Type Inference 是 canonical `request_type` 的唯一决策点。watcher、VRCX importer、普通 writer、Dance Plan UI 和普通读路径都不直接决定最终 canonical `request_type`；它们只写入或维护稳定输入。v2 不迁移或继承 legacy `request_type`，当前 v1 importer 的兼容保护不是 v2 约束。

推断策略集中在 `playback_request_type.py` 或相邻模块中。输入应是 Handle 解析后的当前 Playback Evidence、origins/provenance、Self User Identity、Requester Identity、Dance Plan Fulfillment 和存在时的 Recommendation List Snapshots；不要重新引入旧 `confidence` 或 `source_priority` 数字作为策略事实。Manual Record Update 已整体暂缓，不是第一版推断输入。

已决定：Request Source Type Inference 的分层是 `planned > recommend > self/other/random > unknown > NULL`。`planned` 与 `recommend` 是更强的解释性证据；`self`、`other`、`random` 是互斥同级分类，不能用优先级互相覆盖；`unknown` 表示推断已经运行但证据不足；`NULL` 表示尚未推断或不适用推断，不是 canonical Request Source Type。

已决定：`self` / `other` / `random` 这一层由单一归一化判断产出，而不是三个规则按优先级抢结果。显式 watcher random evidence 为真时产出 `random`，不再读取 requester 来改变该分类；没有显式 random evidence 时，再根据 Requester Identity 与 Self User Identity 判定 `self` 或 `other`。两类证据都不足时产出 `unknown`。如果记录只有 `requester_display_name` 而缺少可信 `requester_user_id`，不应推断为 `random`；它应该落到 `unknown`，并作为 requester identity 补全或诊断需要关注的数据。

已决定：random 不是 requester identity。不能通过把 `requester_display_name` / `requester_user_id` 写成空值、`NULL` 或 `"random"` 来表达随机来源；random 必须作为独立的 playback/source evidence 被记录或解释。当前暴露出的主要问题不是 `playback_records.request_type` 为空，而是 watcher / playback-record origin 没有认真保留 VRC log 中可解析的 random 证据。

已决定：VRCX 历史里的随机不能靠 blank requester 猜出来；不知道就是不知道。用户未来可以在 UI 上选择把未知来源降级显示为 random，但这只能是明确的展示偏好或用户判断，不能糊进原始证据，也不能擅自修改 imported evidence。

random 证据现状与后续计划另见 `docs/request_type_random_evidence.zh-CN.md`。该文档记录 watcher / VRC log / VRCX 的证据问题，但不阻塞第一版 Request Source Type Inference。

已决定：watcher 是 source evidence adapter，而不是 event aggregator 或 inference engine。它可以解析 payload、规范化时间/URL/单位、在同一 session 内做有 provenance 的有限关联和身份补全，但输出止于证据表。canonical event/occurrence 汇总、Request Source Type Inference、Default Acceptance Result 和历史修复必须由可独立重跑的下游流程负责。正式职责边界见 ADR 0013。

已决定：Request Source Type Inference 消费当前模型化后的稳定输入，不负责追溯这些输入的来源可靠性。即使历史上某些 `requester_user_id` 可能来自 video owner、parser fallback 或旧 watcher 语义，推断模块也不重新打开原始日志、不比较 provenance 可信度、不纠正 Requester Identity；这些问题若需要修正，应由 requester identity enrichment、数据修复或重导入流程处理。

已决定：现有 `playback_records.request_type` 是推断输出或旧投影，不是 Request Source Type Inference 的输入。全局 rebuild / repair 不能因为已有 `request_type` 是 `random`、`player`、`queued_self`、`self` 或其他旧值就保留它；它必须只根据当前稳定输入重新推断。旧值只能用于兼容显示、迁移诊断或审计解释。

已决定：当前 `dance_trail/playback_request_type.py` 不是按本语义设计的长期模块，可以在正式实现 Request Source Type Inference 时整体替换；不需要保留旧 `REQUEST_TYPE_PRECEDENCE`、旧 `queued_self` promotion seam 或历史数字优先级作为实现约束。

已决定：Request Source Type Inference 第一版接受全局重算作为普通写操作后的稳定路径。Dance Plan Fulfillment、Recommendation List Snapshot、planned record exclusion 和恢复默认等强输入发生变化时，可以直接触发全局 Dance Plan Fulfillment reconciliation 和全局 `request_type` rebuild，以正确性和可验证性优先。VRCX importer、watcher 和 PlaybackRecord writer 不内嵌最终策略。另提供显式 repair/rebuild 命令，用于切换后、策略更新后或用户怀疑数据漂移时批量重投影。普通 Timeline / Insights 读路径不做隐式修复，避免读页面时改变数据库。

已决定：全局重算是 Dance Plan Fulfillment 和 Request Source Type Inference 的稳定正确性基准，而不仅是异常兜底。第一版需要记录全局重算的性能成本，包括触发入口、扫描范围、受影响记录数、运行耗时和数据规模；如果成本在真实数据库上可接受，就不急于引入局部优化。局部重算只能作为后续优化路径，不作为第一版正确性的唯一依据。实现顺序应先有可重复的全局 reconciliation / rebuild，再引入局部重算；局部重算必须通过测试证明与全局重算结果一致，并且在范围不明确、检测到冲突或验证失败时退回全局重算。

局部重算的候选范围可以从受影响的 `dance_plan_id`、`dance_track_id`、相关 plan item 的 `intended_local_date`、相关 playback record 的 Local Dance Day、superseded 链和 fulfillment 链扩张出来。但这个范围定义属于可验证优化，不是领域事实。测试需要覆盖跨多天顺延、superseded 恢复、fulfilled item 强删、planned record exclude、恢复默认、同一 dance track 多次播放和导入来源重叠等场景。

### 3. `planned` 覆盖是否属于 evidence 字段还是用户/计划 overlay

已决定：`playback_records.request_type = planned` 只是当前投影；它的正式解释来源必须是 Dance Plan Fulfillment。换句话说，不能只有一条 playback record 被写成 `planned`，却没有可追溯的 plan item fulfillment 关系解释它为什么是 planned。

第一版可以用 `dance_plan_items.fulfilled_by_playback_handle_id` 表达 fulfillment，不急着拆独立的 `dance_plan_fulfillments` 表；该引用必须经过 Handle redirect 解析，不能指向可重建 Occurrence 行或 evidence id。若未来需要一次 Playback Occurrence 同时 fulfill 多份 plan、fulfillment 自身需要审计字段、或需要保存更复杂的匹配解释，再考虑拆表。

写入 `planned` 时必须保留 fulfillment 关系；解除 fulfillment 时，系统重新运行 Request Source Type Inference，恢复为未匹配 plan 时的默认分类。

### 4. 手动编辑 Request Source Type 与 plan fulfillment 的优先级

已决定：第一版不提供用户直接编辑 Request Source Type 的入口。用户在 Timeline 里主要处理 accepted / excluded / restore default 这类 review 决策；Request Source Type 由统一 inference 模块根据稳定输入投影出来，而不是由用户手动把某条 record 改成 `self`、`other`、`recommend` 或 `planned`。

用户未来可以手动新增一条播放来源记录，用来补录确实发生过但 watcher、VRCX 或导入没有捕获到的播放，但这个能力当前暂缓实现。该未来记录应作为 `manual_log` Playback Evidence 写入，而不是作为对已有 Handle 的字段修正。手动新增记录可以包含 dance track、played time、可选 requester/note 等播放事实，但不能直接携带 canonical `request_type`；写入后由统一 Request Source Type Inference 和 Dance Plan Fulfillment reconciliation 决定它最终显示为 `planned`、`self`、`other`、`recommend`、`random` 或 `unknown`。

如果用户认为 `planned` 不对，应通过 plan 行为处理：exclude fulfilled playback record、解除 fulfillment、移除或顺延 plan item。若用户认为 `self` / `other` 不对，第一版优先通过修正 Self User Identity、Requester Identity 或相关 evidence 输入来影响推断，而不是直接覆盖 Request Source Type。

已决定：对已有 Handle 的舞蹈条目映射、Requester Identity 或备注进行 Manual Record Update 整体暂缓，不属于第一版 schema、API、推断输入或重算触发条件。未来若重新引入，也不能借此直接改 `request_type` 或自动破坏 Dance Plan Fulfillment。

### 5. Accepted playback 与 plan item 的自动匹配规则

已决定：第一版 plan item 与 accepted playback record 的自动 fulfillment 主匹配键是 `dance_track_id`，匹配窗口是同一个 Local Dance Day。Requester、请求来源、evidence source、系统来源和手动确认都不参与主匹配。

在“同一 plan、同一 intended local date、同一 dance_track 只能有一个 active planned item”的约束下，常规场景可以按 `dance_track_id + Local Dance Day` 自动匹配。未来如果允许重复计划同一支舞，再引入 `plan_order + played_at` 的顺序配对规则。

已决定：当同一 Local Dance Day 内同一个 `dance_track_id` 有多条 effective accepted playback records 时，Dance Plan fulfillment 只匹配当天最早的一条 eligible record。后续同 track 播放不会因为同一个 plan item 继续被标记为 `planned`。

已决定：导入来源重叠、重复 evidence、同一次实际播放对应多条 playback records 的识别和处理，不属于 Dance Plan Fulfillment reconciliation 或 Request Source Type Inference 的职责。它们只消费 effective accepted projection 给出的候选 records，然后按 `dance_track_id + Local Dance Day + earliest played_at` 匹配。overlap / merge / duplicate resolution 属于 Playback Evidence Merge、acceptance/effective projection 或专门的数据修复流程。

### 6. 旧 `data/queued_self/` manifest 的产品入口何时移除

已决定：数据库 Dance Plan 上线后，旧 `data/queued_self/` manifest 入口不保留。用户没有依赖这个旧入口，因此不需要长期导入、自动迁移、只读诊断页或 CLI 兼容命令。

现有 Lists 页面应转向数据库里的 Dance Plan，或在没有替代入口前移除旧 manifest 展示。`sync_queued_self_manifests` / `sync-queued-self` 可以随实现切换删除或隐藏，不再作为正式 workflow。需要保留的旧语义只存在于 legacy input normalization、旧数据解释和 raw/origin/provenance 审计材料中；正式 Dance Plan 表和 canonical `request_type` 不写 `queued_self`。

用户如需恢复某条旧计划语义，应手动添加历史 Dance Plan item，而不是从旧 manifest 自动迁移。

### 7. `request_type = unknown`、`NULL` 和空值的语义

已决定：`NULL` 和 `unknown` 必须区分。

- `NULL` 表示 Request Source Type Inference 尚未运行、记录不适用推断，或 v2 初始化后等待首次 rebuild。
- `unknown` 表示推断已经运行，但稳定输入不足以判定为 `planned`、`recommend`、`self`、`other` 或 `random`。

UI 可以把两者都显示成“未知”，但诊断、repair、测试和迁移校验必须保留差异。全局 rebuild 跑完后，对适用推断的 accepted records，不应继续留下 `NULL`；要么有具体 Request Source Type，要么是 `unknown`。

`unknown` 是 debug 和数据修复需要重点关注的对象。它表示系统已经尝试解释来源但证据仍不够清楚，不应被当成无害的空值或普通默认值忽略。

### 8. 手动新增 playback record

暂缓：用户未来可以凭空插入一条新的 Manual Log Entry / `manual_log` Playback Evidence，用来补录确实发生过但 watcher、VRCX 或导入没有捕获到的播放。但这个能力不进入当前 Dance Plan 和 Request Source Type Inference 第一版实现范围。

已决定的边界：未来手动新增 playback record 也不能直接携带 canonical `request_type`。它只写播放事实，之后由统一 Request Source Type Inference 和 Dance Plan Fulfillment reconciliation 决定最终分类。

未讨论：手动新增 playback record 的默认 acceptance、UI 入口、去重规则、与现有 evidence 的 merge/overlap 规则。
