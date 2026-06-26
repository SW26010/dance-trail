# request_type 与舞蹈计划讨论

日期：2026-06-26

状态：讨论草案。本文记录 `request_type`、旧 `queued_self` 词系，以及未来舞蹈计划的产品和数据模型方向。它不是已批准的迁移计划，也不是当前 SQLite schema contract。

## 已记录的判断

- 用户面对的 canonical term 使用“舞蹈计划”。“待跳清单”、“待跳舞清单”、“预排清单”只作为讨论词或说明词，不作为正式产品名。
- `queued_self` 这个名字不适合作为用户面对的舞蹈计划概念。
- 长期 `request_type` canonical value 使用 `planned`，表示这条已播放记录被识别为来自预先安排的舞蹈计划。`queued_self` 只作为 legacy alias 或旧数据兼容值。
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

Accepted Playback Record 是实际发生或被导入、观察、结算后的播放证据。是否进入历史和 Insights 仍由 effective accepted projection 决定，不能因为某首歌在舞蹈计划里就直接算作 accepted。

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
  fulfilled_by_playback_record_id,
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

Local Dance Day Boundary 是本地配置项，不是 `dance_plans` 或 `dance_plan_items` 的字段。配置字段名使用 `dance_day_boundary_time`，值为 `HH:MM` 本地时分字符串；第一版允许范围为 `00:00` 到 `06:00`，默认建议值为 `00:00`。系统每次计算跳舞日归属时读取当前配置；如果用户修改 boundary，相关历史分组和 plan 匹配视图会随之改变。为了避免用户无意中改变行为，第一次使用 plan 相关功能时必须显式提醒并引导用户去 Settings 设置；计划界面本身不承载完整设置表单。提醒必须显示当前 `dance_day_boundary_time` 值，并提供“使用当前设置”操作，让用户一次性确认当前 boundary 设置。

建议规则：

- 只用 effective accepted playback records 来 fulfill plan item。
- 第一版不允许同一份舞蹈计划、同一个 intended local date 内重复计划同一支 dance track。未来如果允许重复计划同一支舞，再按计划顺序和播放时间顺序配对，避免一个 playback record fulfill 多个 item。
- item fulfill 后，对应 playback record 的 `request_type` 应提升为 `planned`。这表示“这次播放完成了预先计划”，不要求 requester 必须是 self。
- 未匹配的 item 不代表失败，也不应该制造 needs-attention playback record。
- 未匹配 item 可以继续保留为 planned，这就是顺延；不需要每天复制成一条新 item。
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

如果用户先把 fulfilled playback record 变为 excluded，则系统应自动解除 fulfillment，并移除 plan 对该 record 的 `planned` 覆盖，`request_type` 变为空。这个路径不需要强删警告，因为用户的主要动作是把 playback record 排除出 accepted history。解除后系统需要询问原 plan item：

- 继续留在 active plan 中自然顺延。
- 从 plan 中移除。

## 待讨论问题

### 1. `planned` 与旧 `queued_self` 的过渡策略

未确定：实现上什么时候把 `queued_self` 从运行时 Request Source Type precedence 中替换为 `planned`，以及旧数据、旧测试、Web UI label 是否需要继续显示 `queued_self`。

建议答案：长期只把 `planned` 作为 canonical Request Source Type；`queued_self` 只在旧 manifest 读取、旧 origin/provenance、旧数据解释和兼容 UI label 中出现。实现切换时，`REQUEST_TYPE_PRECEDENCE` 应加入 `planned` 作为最高值，并把 `queued_self` 保留为 legacy alias，而不是让两者成为并列产品值。

还没算定的原因：当前代码和测试仍以 `queued_self` 为最高 precedence，`promote_request_type()` 又是 no-op；这属于过渡实现，没有决定具体切换时机。

### 2. Request Source Type 推断策略的归属和输入

未确定：解除 fulfillment、VRCX reimport、watcher 新证据、手动修正之后，谁负责重新推断 `request_type`，以及推断时允许读取哪些输入。

建议答案：把策略集中在 `playback_request_type.py` 附近，而不是分散到 writer、watcher、VRCX importer 或 plan UI。输入应是当前 Local Playback Evidence、origins/provenance、Self User Identity、Requester Identity、Dance Plan Fulfillment 和明确的 manual overlay；不要重新引入旧 `confidence` 或 `source_priority` 数字作为策略事实。

还没算定的原因：现有迁移文档已经说旧 `source_type` 不直接迁移到新 `request_type`，但还没有定义迁移后 rebuild/repair 的具体策略、运行入口和幂等边界。

### 3. `planned` 覆盖是否属于 evidence 字段还是用户/计划 overlay

未确定：`planned` 是直接写入 `playback_records.request_type` 的当前投影，还是应该由 fulfillment 表/overlay 推导出来，再投影到读模型。

建议答案：长期可以把 `request_type` 保留为当前投影字段，但 `planned` 的解释来源必须是 Dance Plan Fulfillment，而不是 playback evidence 本身。也就是说，写入 `planned` 时要保留可解释的 fulfillment 关系；解除 fulfillment 时重新推断默认 Request Source Type。

还没算定的原因：当前草案已经说 fulfilled item 会提升 playback record 的 `request_type`，但还没有决定是否需要额外记录“这个 request_type 是由 plan fulfillment 产生的”以支持审计、undo 和冲突解释。

### 4. 手动编辑 Request Source Type 与 plan fulfillment 的优先级

未确定：用户在 Timeline 手动把一条 fulfilled playback record 的 Request Source Type 改成 `self`、`other` 或 `recommend` 时，是否应解除 fulfillment，还是只创建一个更强的 manual overlay。

建议答案：手动编辑应先被建模为 Manual Record Update overlay，强于自动推断，但不必自动删除 fulfillment。UI 需要明确提示：这会让显示的 Request Source Type 不再来自计划；如果用户要取消计划对账，应执行“解除 fulfillment / 从计划中移除”的显式动作。

还没算定的原因：现有文档覆盖了 plan item 删除和 playback exclusion，但没有覆盖“保留 accepted + fulfillment，同时手动改 source type”的场景。

### 5. Accepted playback 与 plan item 的自动匹配规则

未确定：一个本地跳舞日内多个 accepted playback 和多个 plan item 匹配时，第一版是否只按 `dance_track_id` 匹配，还是还要考虑时间顺序、plan_order、requester、系统来源或手动确认。

建议答案：第一版在“同一 plan、同一 intended local date、同一 dance_track 只能有一个 active planned item”的约束下，可以按 `dance_track_id + Local Dance Day` 自动匹配；如果未来允许重复计划同一支舞，再引入 `plan_order + played_at` 的顺序配对规则。

还没算定的原因：草案已经排除了第一版重复 planned item，但没有明确当播放记录重复、导入来源重叠或同一舞一天多次实际播放时的精确 tie-breaker。

### 6. 旧 `data/queued_self/` manifest 的产品入口何时移除

未确定：第一版数据库 Dance Plan 上线后，现有 Lists 页面和 `sync_queued_self_manifests` 是立即隐藏/废弃，还是保留一个只读诊断或一次性参考入口。

建议答案：不要做长期导入或自动迁移；如果要保留，最多作为只读 legacy preview，提醒用户手动补录为历史 plan item。正常产品导航应转向数据库里的 Dance Plan，而不是继续强化 manifest 编辑流。

还没算定的原因：文档已经决定旧 manifest 不迁移、不长期兼容导入，但现有 Web UI 仍有 Lists manifest 预览，尚未决定切换时的 UI 处置。

### 7. `request_type = unknown`、`NULL` 和空值的语义

未确定：长期 schema 中未能推断的 Request Source Type 应写成 `unknown`，还是保留 `NULL`；两者在 UI、Insights 和 rebuild 中是否有不同意义。

建议答案：区分两者：`NULL` 表示尚未运行或不适用 Request Source Type 推断，`unknown` 表示策略已运行但只能判断为未知来源。Insights 可以把两者合并展示为 unknown，但数据修复和迁移验证应保留差异。

还没算定的原因：现有文档同时提到恢复为 `unknown` 或空值，迁移计划又要求新 `request_type` 默认 `NULL`，需要统一长期语义。
