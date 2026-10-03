# 播放数据结构新定义

日期：2026-07-19

状态：方向性定义，后续继续讨论

数据模型定义版本：v2（当前目标）

## 目的与范围

本文定义下一代播放数据结构的大方向：不同种类的数据分别代表什么、由谁产生、
能否修改以及能否重建。

这是一个全新目标模型。设计时优先追求概念清晰、来源可信、可解释、可恢复和长期
可维护，不为现有数据库结构、历史字段或迁移成本让步。本文不提前固定表名、字段、
索引和实现方式。

旧的字段级方案保留在 `docs/playback_records_schema_redesign.zh-CN.md`，仅作为命名、
字段语义和历史讨论参考；它不再定义目标结构。

当前 v2 的来源证据实施范围只包括 watcher 捕获的 VRChat 日志证据和 VRCX 数据库证据。
人工补录以及其他未来来源在模型中保留明确扩展位置，但本阶段不实现对应的表、API、
界面或写入路径。v2 完成切换前，现有 v1 入口可以继续服务当前应用；切换后不保留这些
入口作为 v2 兼容读写路径。

把另一个 DanceTrail app root 或 v2 数据库中的证据、Handle 关系和用户状态语义合入
当前数据库，只保留为未来可能的扩展方向，不是 v2 完成条件，也不保证以后一定实现。
当前模型不得为了这项极少使用的可能性预建 Merge Plan、跨库冲突流程或全局 Handle 身份，
也不得让它决定本地主键长度；若未来正式立项，应以新的 ADR 重新定义范围和语义。
Playback Handle ID 只保证在所属数据库内部稳定，不保证跨数据库唯一、保持同值或可直接
比较。未来若实现跨库导入，应优先采用保守策略：在目标数据库重新分配本地 Handle ID，
并重映射其 membership、redirect、operation 和用户状态引用；只有未来导入协议另行证明
保留原 ID 安全时才可以例外。

舞蹈计划不属于来源证据，而是 v2 明确需要实现的持久用户意图。v2 将实现数据库中的
Dance Plan、计划条目和 Dance Plan Fulfillment，并让完成关系引用可跨投影重建解析的
稳定播放句柄；来源证据范围的限制不缩减这一实现范围。

## 版本关系

这些版本号表示播放数据模型定义的代际，不是应用发布版本：

- pre-v0：以 `dance_events` 为中心的早期事件模型；
- v0：首次以统一 `playback_records` 表示本地播放记录的模型；
- v1：继续围绕 `playback_records` 细化字段、来源和人工叠加层的模型，由 ADR 0003 记录其
  实现读取根，现已弃用；
- v2：本文定义的证据、稳定播放身份、用户判断和当前解释相分离的新方向。

同一代模型内的措辞澄清和非原则性补充不升级版本。只有数据所有权、可修改性、稳定
身份或可重建界线发生方向性变化时，才进入下一代版本。数据库结构迁移和应用发布使用
各自的版本体系，不与这里的模型定义版本混用。

## v2 模型边界与切换

本文所说的 v2 是播放数据库结构、表间关系及直接依赖它们的领域逻辑一代，不是整个
应用的功能代际。“v2 完成”不表示“完整复刻 v1 的所有功能”，也不要求在本文中
决定 Home、OBS Overlay、Insights、CLI 报告或其他上层界面的发布优先级。

v2 模型范围包括：

- watcher 和 VRCX adapter 将已整理的不可变来源证据写入公共证据表与来源细则表；
- 来源位置与内容指纹、Playback Evidence Deduplication、证据 membership 关闭及其人工裁决履历；
- Playback Handle、Playback Evidence Membership、Playback Handle Redirect 及其有效期和操作审计；
- Playback Reconciliation、Handle 归并、重定向解析和可重建 Playback Occurrence 当前投影；
- 统一的 Handle-based Playback Read Boundary；
- Handle 上可逆的人工 `accepted` / `excluded` 判断覆盖层与恢复默认解释；
- Dance Plan、计划条目及引用 Playback Handle 的 Fulfillment 关系；
- Handle-based Request Source Type Inference，以及可重建的 canonical `planned`、`recommend`、
  `self`、`other`、`random`、`unknown` 当前分类。

上层业务可以作为上述合同的消费者和验收用例，但不因此成为 v2 数据模型本身。例如，
Timeline 按舞蹈日读取和提交 `accepted` / `excluded` 用于验证读取边界与用户判断逻辑；
Insights 是另一个派生消费者。它们的产品发布时序由应用切换计划另行决定。

v2 模型与上述直接领域逻辑实现后采用一次干净数据权威切换，不设计 v1→v2 数据迁移、
双写、混合读取或兼容回退。切换前当前应用仍由 v1 `playback_records` 模型负责；切换后
v2 Handle 模型成为唯一产品权威，v1 数据不再参与当前业务决定。

v2 不转换 `playback_records`、旧人工状态或旧投影来延续历史。仍然可获得的 VRCX 数据库
内容和 VRChat 日志可以通过 v2 正常 importer 或 replay 重新摄入，形成新的 v2 Source
Evidence Events；这属于从受支持来源重新建立数据，不是旧模型迁移。无法从当前支持来源
重新获得的 v1 状态允许在切换时丢失。旧数据库可以作为人工备份保留，但不是 v2 运行时
输入或兼容读取根。

### v2 schema 演进

无 v1→v2 数据迁移只约束代际切换，不意味着投入使用后的 v2 数据库可以在结构变化时
反复重建。v2 会保存无法从 watcher 或 VRCX 重新产生的持久状态，包括用户的
accepted/excluded 决策、Dance Plan、Handle 关系及其审计履历。因此，从 v2 第一版开始，
数据库必须具有明确的 schema version，并通过有顺序、可校验、事务化的 schema migration
升级同一代 v2 数据库。应用不得仅凭 `CREATE TABLE IF NOT EXISTS` 猜测数据库结构；遇到
高于自身支持范围或无法完成升级的版本时，应停止写入并明确报错，而不是部分打开。

schema version 应随数据库自身保存，使数据库文件可自描述。v2 使用专用 migration history
表作为 schema 版本与已应用迁移的唯一权威，不与领域 Operation 混用，也不再并行维护
`PRAGMA user_version` 作为第二份真相。具体表名、字段、版本编号形式和迁移框架留待实现
设计。这套 v2 内部升级机制不得被解释为恢复 v1→v2 迁移、双写或旧模型兼容。

Request Source Type Inference 是 v2 核心的独立、可重建领域模块。它消费 Handle 解析后的
当前 Playback Evidence、Requester Identity、Self User Identity、Dance Plan Fulfillment
以及存在时的 Recommendation List Snapshot；watcher、VRCX importer、普通 writer 和读路径
都不直接决定 canonical `request_type`。真实 VRC output log 中已经确认的显式 random marker
由 watcher 保存为证据，再由该模块投影为 `random`。

推荐机制整体暂缓，不属于 v2 完成条件，包括推荐算法、推荐 UI、清单生成和 Recommendation
List Snapshot 的生产流程。Request Source Type Inference 必须在数据库不存在任何 snapshot
时完整运行，继续产生 `planned`、`self`、`other`、`random` 或 `unknown`；只有存在未来正式
冻结的 snapshot 时才允许产生新的 `recommend`。暂缓推荐机制不删除 `recommend` 这个
canonical value 或已经确定的未来证据语义。

## 核心认识

现有模型容易把几件不同的事混成一条“跳舞事件”：来源记录了什么、哪些证据当前共同支持
一个 Playback Occurrence、系统现在如何解释、用户后来怎样修正。

新模型首先承认：

- 一条来源记录不等于一个 Playback Occurrence；
- 一个 Playback Occurrence 可以由多个来源证据支持，也可以由同一来源的多条证据支持；
- 来源证据、用户判断和系统当前解释有不同的所有者和生命周期；
- 可以重算的结果不能成为不可替代的历史依据。

## 四类核心职责

### 一、来源证据

来源证据只回答：“这个来源当时记录到了什么？”

这里的证据单元是来源 adapter 在创建时已经确定性整理好的 Playback Evidence，不是未经
整理的 VRChat 原始日志行或 VRCX 原始数据库 row。watcher 把同一来源内能够确定归属的日志
信号整理成不可修改的来源事件；VRCX importer 把数据库内容转换成同样不可修改、保留来源
坐标的事件证据。原始行、payload 和整理依据作为 provenance 保留，但不直接作为跨来源
合并算法的工作单位。

每个 Evidence Source adapter 都应在来源能力允许的范围内，先把预计共同支持一个 Playback
Occurrence 的有界原始观察整理为一条自足的 Playback Evidence，使该来源通常只需这一条
证据就能完整表达自己的主张。这个原则不构成“每来源每 occurrence 只能有一条”的数据库
唯一约束；证据替换、来源异常和未来来源仍可能留下多条证据。但实现不得主动把一次来源
观察拆成零碎 Playback Evidence，再要求 reconciliation 或读取层拼装后才能理解其基本含义。

所有 Playback Evidence 统一写入一个公共证据表。公共表拥有证据的本地主键和来源间
真正共用的字段，使 watcher、VRCX 和未来来源共享同一个稳定且全局唯一的本地身份命名
空间，不依赖多个独立来源表之间难以声明和引用的“跨表唯一”。

每种来源使用自己的证据细则表保存专有字段。细则表与公共证据表是一对一关系，其
`evidence_id` 同时作为本表主键和指向公共证据表的外键，不再建立独立的细则身份。来源
数据库行号、日志文件坐标和外部主键只属于 provenance，不能充当公共证据身份。

VRCX 导入、实时日志观察、离线日志重放和未来的用户手动补录都可以提供证据。手动补录
是用户提供的一条来源主张，不是人工修正覆盖层，也不是对其他来源证据的改写。未来启用
后，它可以独立支持一次播放默认计入历史，但不能覆盖与之冲突的 watcher、VRCX 或其他
来源事实；当前阶段只保留这一语义边界，不实现手动补录路径。

已经保存的证据不能被用户、推断规则或后续整理覆盖或删除。来源同一位置的内容后来发生
变化时，应先保留待裁决输入；裁决需要收入时创建另一条不可变证据，并用可审计关系
表达旧证据是否失效，而不是在原行上更新版本。实时观察与离线重放如果来自同一种日志，
具有相同的证据语义，不应因为运行方式不同而变成两种事实。

watcher 应先在正式证据层之外完成同一来源事件的有界折叠、生命周期整理和 requester
identity enrichment，再发布一条单独即可描述清楚该来源观察的 Playback Evidence。
尚未完成的 capture candidate 可以在 watcher 内存或专用 staging 中变化，也可以供 Live
Status / OBS Overlay 使用，但它不是 Playback Evidence 或 Playback Occurrence。整理完成
或达到明确的有界等待条件后，即使部分可选信息仍未知，也应一次性写入当时完整可得的证据；
正式写入后不得再回填、upsert 或覆盖字段。不能把一次 watcher 播放拆成多条零散持久证据，
再要求下游重新拼装成一条来源事件。

Playback Evidence 一旦完整、不可变地持久化，就算该来源证据发布成功；发布不以已经建立
Handle 或 membership 为前提。每次发布新证据后，写入流程都必须及时、明确地触发 Playback
Reconciliation，而不能等待普通读取顺带补建身份。Playback Evidence Deduplication 仍应在
创建新证据前完成，避免重复输入进入 Playback Reconciliation。前者只判断同一 Evidence
Source 的输入是否已经产生相同证据；后者判断不同 Evidence Sources 的 Playback Evidence
是否共同支持一个 Playback Occurrence，两者不得合并为同一个“去重”或“合并”步骤。

新证据开始 reconciliation 时尚无 Handle。若它严格匹配一个既有 Playback Occurrence，直接
把 membership 建立到解析后的 Canonical Handle；若没有严格匹配，则新建薄 Handle 和
membership，使它作为独立播放被上层发现。不得为了过渡期先创建临时 Handle、随后仅因匹配
成功再重定向它。当前 watcher 与 VRCX 两种来源、同来源位置去重并在每次摄入后及时
reconciliation 的正常路径，不应由一条新证据促使两个既有 Handles 合并。

同一算法版本的一次 reconciliation 必须对完整的有界候选组产生自洽的等价分组，不能仅按
证据对独立决策，也不能把 `A–C` 与 `B–C` 两条匹配机械地做传递闭包，借 `C` 合并原本无法
确认的 `A–B`。自动合并整个组之前，算法必须直接证明该组作为整体是同一次播放；否则保持
既有分离。对已经声明支持的输入，算法必须总能形成完整、自洽的保守分组；无法证明属于
同一次播放就输出保持分离，不能把算法覆盖缺口发布成运行时结果，也不得发布部分
membership 或 redirect。
并发摄入也不得绕过这一边界：证据可以先分别发布，但必须经过协调后的 reconciliation 才能
建立 Handle membership，不能各自抢先创建 Handle。只有用户显式使用不同算法或版本重新
处理已经具有稳定 Handles 的旧数据时，才可能产生既有 Handles 的新合并；它不是新增证据
摄入的常规效果。redirect 只作用于已经发布的稳定 Handles，不作用于证据身份。

证据发布与 identity reconciliation 是两个有先后关系的生命周期阶段；是否由同一进程、
相邻事务或可恢复作业完成属于实现期细节。正常路径应及时结束无归属窗口；执行中断、异常
或延迟必须留下可检测、可恢复、可诊断的未完成工作，并在恢复后继续处理，不能成为终态
reconciliation 结果，也不能让无归属证据永久不被上层发现。

来源证据的原始值可以不一致，也可以信息不足。系统应在后续处理中确定性解析这些输入，
不能回头修改证据来制造一致，也不能把内部不一致直接暴露成产品状态。

一个 Playback Occurrence 可以关联两个、三个或更多来源证据，模型和规则不能假设最多只有
两个来源。
来源数量本身不是投票权：同一原始来源经实时捕获、离线重放、转存或重复导入形成的记录
可能具有共同血缘，不能冒充多份独立证据。原始值不一致时，应按“播放是否发生、时间、
舞蹈身份、请求者、观察过程”等具体事实，结合来源能力、直接程度、血缘和用户判断分别
解析，不能交给一条全局来源排序或外部 conflict 状态。

因此不定义一条适用于所有事实的全局来源排序。对重叠的普通观察事实，watcher 可以比
VRCX 更直接，但这不使 watcher 对所有字段拥有绝对权威，也不决定合并时保留哪个稳定
播放身份。未来增加来源时，应声明它能直接观察哪些事实以及与既有来源是否独立，而不是
插入一条不断增长的总优先级列表。

### 二、Playback Occurrence 与稳定身份

Playback Occurrence 是 v2 面向普通上层业务的一次播放单位。它不等同于任意来源的一行记录，
也不要求存在一张持久保存全部当前字段的 occurrence 表。系统持久保存不可变证据、独立的
最小播放句柄、证据归属关系和最小合并关系，并据此构建当前 Playback Occurrence；其具体
呈现可以是按需投影、视图或可重建缓存。

持久层为 Playback Handle 保留独立的薄身份表。该表只提供句柄主键，不复制播放事实、
当前解释或投影字段。证据通过独立的 handle—evidence 关系表连接到句柄；句柄之间已经确认
的合并与重定向通过另一张独立关系表保存。两张关系表的职责分离、时间段语义和共同
Operation 审计根已经确定；最终表名、非语义性辅助字段、索引和具体约束实现后续再定。

Handle 以自身创建事务的提交作为身份发布边界，但 Playback Evidence 可以先于 Handle
发布。reconciliation 若严格确认新证据属于现有 Handle，可以直接建立证据归属而不创建
新 Handle；没有严格匹配时才创建新的薄 Handle 和证据归属。新建 Handle 一旦提交，就是
永久稳定的身份；不得因为当前查不到业务引用而回收、复用或改挂其证据，后续合并只能通过
Handle 重定向表达。

Handle 表不保存 `is_used`、`published` 或其他可从提交事实和业务引用推导的使用状态。
判断“当前没有引用”不能作为改写稳定身份的依据。证据发布后、identity reconciliation
完成前的短暂无 Handle 状态属于证据摄入作业的可观察生命周期，不属于 Playback Handle，
也不需要在 Handle 上保存 `is_used` 或 `published` 标记。

不同来源或同一来源的多条证据可以共同支持一次播放。Playback Occurrence 投影可以整体
删除并重建，因此它的物理行键不能成为其他领域数据唯一依赖的历史依据。用户修改、舞蹈
计划完成关系和后续引用应指向可跨重建解析的稳定播放句柄。播放句柄采用独立于
Playback Evidence 身份的最小身份锚点；句柄自身只提供稳定身份，不复制播放事实、
当前解释或当前重定向状态。

证据通过持久的证据归属关系直接支持播放句柄；多条证据可以直接归属于同一个句柄。
证据归属与句柄重定向是两种不同关系：前者说明证据直接支持哪个播放身份，后者说明两个
已经存在的稳定播放身份后来被确认属于同一次播放。两种关系都必须保留可审计的建立、
撤销和修复履历。每条关系都必须能够说明何时建立、当前是否有效、由什么来源或决定建立，
以及何时、为何、由谁或什么操作使其失效或被取代；撤销不能通过物理删除关系完成。其最终
表名、辅助字段和具体操作命名后续再定；当前有效关系已经由下述开放时间段及其
Operation 引用确定，不再另设一套状态表达。

两类关系的每个版本仍以半开有效时间段 `[effective_from, effective_to)` 表达效力，但时间
只保存在其引用的 Playback Identity Operations 中，不在关系行重复存储。关系行保存必需的
`established_by_operation_id`，以及可空的 `closed_by_operation_id`；`effective_from` 由建立
Operation 的时间得到，`effective_to` 由关闭 Operation 的时间得到。关闭 Operation 为空表示
该关系当前有效，因此也不另存 `is_active` 布尔字段。

Playback Identity Operation 是瞬时操作，只保存一个操作发生时间，不区分
`established_time` 与 `closed_time`。同一个 Operation 被某条关系的
`established_by_operation_id` 引用时，它的发生时间是该关系的有效起点；被
`closed_by_operation_id` 引用时，则是该关系的有效终点。

Operation 不允许回溯生效，也不支持预约未来生效；它的生效时间取创建该 Operation 事务的
提交时间。因此关系只能从开放时间段关闭一次，关闭后不得重新打开；恢复或重新建立相同
关系必须创建新版本，并引用新的建立 Operation。该模型不重复保存关系级 `created_at`、
`recorded_at`、`effective_from` 或 `effective_to`，也不引入双时态时间线。

Playback Evidence Membership 与 Handle 重定向共用一个 Playback Identity Operation 审计
根。Operation 的边界是一次原子的播放身份变更动作，不是某一种关系表；同一个 Operation
可以建立或关闭两类关系中的多行。两张关系表分别引用建立自身的 Operation 和关闭自身的
Operation；彼此无关的身份变更不得仅因发生在同一批处理或同一张表中而共用一个 Operation。

当前产品范围只建立 membership 和 Handle 重定向，不提供关闭关系、拆分 Handle、解除或
改挂证据归属的普通流程。唯一已承认的例外方向是“同来源位置内容变化”经人工
判定为原事件证据更新时，可审计地关闭旧证据 membership 并建立新证据 membership；
该完整工作流尚未设计。`closed_by_operation_id` 和关系失效时间保留了未来进行可审计
修复的表达能力，但不代表当前已经定义或授权这些危险操作。只有排除、舞蹈计划完成
关系和其他全部上层引用都具备明确的迁移、归属和验证规则后，才能另行设计并开放修复流程。

两个 Playback Handles 合并时，已有的证据归属关系保持原目标不变，不把被重定向句柄下的
证据批量迁移到 Canonical Handle。系统只增加相应的 Playback Handle Redirect；当前 Playback
Occurrence 通过有效证据归属和有效重定向闭包构建。当前模型不定义撤销该重定向后如何
处理原句柄、直接证据成员和全部上层引用。

同一 Playback Evidence 在任一时刻最多只能有一条有效的 Playback Evidence Membership，
禁止它同时直接归属于两个 Playback Handles；历史 membership 可以有多条，但有效时间段
不得重叠。零条有效 membership 在数据结构上是合法的，也是证据发布后等待 identity
reconciliation 的正常短暂状态；它不能成为稳定业务结果。摄入和修复流程应尽快为这类证据
建立归属，系统必须能够发现、报告并重试超过正常处理窗口的无归属证据，避免一个可能的
Playback Occurrence 永久不被上层发现。

系统只有在依据足够明确时才能自动认定多条记录属于同一次播放。时间接近、舞蹈相同
或某个来源更可信，只能产生“可能重复”的线索，不能单独成为自动合并依据。无法确定时
宁可暂时分开并等待复查，也不能悄悄合并或删除证据。

### 三、用户判断

用户修改表达的是用户对一次播放的判断，不是对来源历史的重写。当前 v2 在本层只定义：

- 是否以 `accepted` 或 `excluded` 计入历史；
- 是否撤销人工判断并恢复默认解释。

用户判断应保留履历。新判断可以取代旧判断的当前效力，但旧判断仍然存在，以便解释、
撤销和恢复。

是否计入历史的人工判断是 Playback Handle 上的可逆覆盖层。`accepted` 表示用户
明确要求当前 Playback Occurrence 纳入普通历史和统计，`excluded` 表示明确要求不纳入；
两者都不改写 Playback Evidence 或归并关系。恢复默认解释表示关闭当前人工
判断的效力，再由证据和系统规则给出当前结果；它不是第三种持久纳入状态。

v2 直接沿用当前 Timeline 已实现的用户行为：一个身份同时最多一条
有效人工判断；新的 `accepted` 或 `excluded` 判断取代旧判断的当前效力但保留旧行；
恢复默认只关闭当前人工判断；当前解释优先使用有效人工判断，没有时使用默认结果。
这是业务行为参考，不是照搬 v1 物理 schema：v2 引用 Playback Handle 而非 `playback_record_id`，
人工判断值只有 `accepted` 和 `excluded`。当前 v1 底层 schema 和 HTTP 接口虽也容许人工
`needs_attention`，但 Timeline 没有该操作入口；这是未对用户暴露的 legacy 实现容许值，
不是 v2 要沿用的用户行为。

没有人工覆盖时，系统使用已发布证据和规则产生的默认结果。v2 默认结果可以是
`accepted` 或不计入历史的 `needs_attention`。尚在观察的 watcher capture 可以在正式证据
层之外暂时为 `pending`，但它不进入 Playback Occurrence，也不是 Default Acceptance Result。
`needs_attention` 在这里是系统推导的非计入结果，不是人工判断，也不表示正常使用必须等待
用户处理。`excluded` 只来自用户覆盖，不是默认推导结果。

当一个 Playback Occurrence 当前仅由 VRCX Playback Evidence 支持、且没有有效人工覆盖时，
Default Acceptance Result 为 `accepted`。这是明确接受 VRCX 记录可能带来假阳性的产品取舍；
它只决定该 VRCX-only Occurrence 是否计入历史，不把 VRCX 证据解释成 watcher 已观察到完整
播放过程。以后若同一 Occurrence 合入 watcher 证据，观察过程和默认接受结果仍由对应的
字段 resolver 根据全部有效证据重新计算。

对已有播放的舞蹈条目映射、请求者身份或备注进行人工修正，属于独立的 Manual Record
Update 覆盖层。该能力整体暂缓，不属于当前 v2 schema、解析输入、API 或合并行为；以后如
确有产品需要，应在不改写 Playback Evidence 的前提下重新设计。它也不得与未来的
人工补录来源记录混为一谈。

“手动补录一次播放”和“修改已有播放”必须保持区别：前者增加来源证据，后者增加用户
判断。播放业务不另外定义“删除”或“隐藏”意图；`excluded` 是唯一的播放移除判断，
用于表达不参与普通历史和统计。界面可以默认过滤 excluded，也可以在复查视图中展示，
但这只是读取方式，不形成新的业务状态。恢复默认会撤销当前排除；排除不删除证据、稳定
Playback Handle、身份关系或用户判断履历。

### 四、当前解释

时间线、分析、日报和推荐统计需要的是：“根据当前所有输入，系统现在应该如何理解
这次播放？”

当前解释综合来源证据、Playback Evidence Membership、Handle redirect、用户判断、请求者
推断、舞蹈计划、
推荐结果等稳定输入。它是系统结论，不是不可改变的历史事实，因此必须能够整体删除
并重新生成。规则变化时应重算结论，不能修改原始证据。

v2 面向上层业务的统一身份边界是 Playback Handle。Timeline、Insights、日报和推荐处理
播放时只能使用输入 Handle 或解析其重定向后的 Canonical Handle；排除、舞蹈计划
完成关系和其他用户操作也引用稳定 Handle。除明确以证据审计、诊断或来源详情为职责的
业务外，上层合同不得暴露或接收 `evidence_id`。

Playback Occurrence 是围绕 Handle 构建的可重建当前呈现，不预先规定物理形态。实现可以
按需计算、使用数据库视图或保存可删除缓存；如果直接读取证据表效率更高，也可以在内部
这样实现，但必须同时解析有效 membership、Handle 重定向和当前解释规则，最终仍向上层
提供以 Handle 为身份的结果。直接读取证据不等于允许把证据行当成产品播放身份。

上述约束由统一的 Handle-based Playback Read Boundary 执行。Timeline、Insights、日报、
推荐和其他普通上层业务只能通过这一领域边界读取播放；边界统一负责输入 Handle 的重定向
解析、当前解释规则和 evidence id 隔离。边界可以按用例采用不同的内部查询计划，不要求
所有业务读取同一张物理投影表，但不得让各上层模块分别重写 Handle 解析和解释语义。

ADR 0003 中以 `playback_records` 作为 Timeline 和 Insights 直接读取根的决定只描述已弃用的
v1 实现，不定义 v2。v2 不读取 `playback_records` 作为迁移或兼容输入；内部为效率直接读取
证据时，读取的是 v2 Playback Evidence。新上层业务不得把任意证据行当作一次播放的
产品身份或对外标识。

当前解释不应再压缩成一个含义过多的总状态。至少应分别表达：观察到怎样的播放过程、
是否计入历史、是否需要关注，以及当前如何解释其计划、推荐、自己、他人、随机或未知
来源。

实时播放中的临时状态可以留在内存中。只有确实需要长期查询，或者能够从证据稳定重建
的内容，才进入持久化的当前解释。

## 四类职责不等于四张表

这四类是概念、所有权和生命周期规则，不是物理建表数量规定。

目前已经确定的持久结构边界包括：公共证据表及其共享主键的来源细则表；只提供主键的
薄 Playback Handle 表；handle—evidence 关系表；保存句柄合并与重定向的关系表；以及两类
关系共用的 Playback Identity Operation 审计根。这些边界不预先决定最终表名和字段。当前
解释可以实时计算，也可以为了查询效率保存成可重建结果；其他结构仍可按数据形状、约束
和性能选择合并或拆分。

但不能跨越以下原则：

- 不可修改的证据不能与可重算状态混在同一条可更新记录中；
- 用户判断不能被当成系统推断，也不能在重建时丢失；
- 稳定的播放身份不能依附于随时可以删除的结果；
- 普通读取不能顺便修改证据或隐式修复数据库。

此前提到的“第五层”是面向产品的只读查询入口。它只是“当前解释”的交付方式，没有
独立的事实来源和生命周期，所以在方向性模型中归入第四类。

## 历史导入与重复处理

历史导入不能简单地把来源中的每一条记录都当成一次播放。

v2 必须实现两个来源位置识别不变量：

- 重复导入 VRCX 时，同一来源记录位置必须能跨导入运行被识别；
- 同一 VRChat 原始日志事件必须在 watcher live 和 watcher replay 之间解析为同一
  来源位置，不能因为 live/replay 模式、运行 session 或导入作业不同而变化。

在这两个不变量之上，再用内容指纹区分完全相同的重复摄入和同位置内容变化。
来源位置的最终编码字段及指纹算法属于后续建表和 adapter 实现细节。
其他长期规则包括：

- 重复导入同一 VRCX 数据或重复 replay 同一 VRChat 日志时，已知的相同来源位置与
  内容指纹永远复用原 Playback Evidence identity，不再发布第二份证据；
- “当前有效证据”指仍具有当前有效 Playback Evidence Membership、正在为 Handle 提供支持的
  Playback Evidence；证据行自身不另存 `active` 或独立生命周期状态；
- 来源摄入幂等性不受 membership 状态影响；重复摄入不会自动恢复已关闭的 membership，
  恢复只能通过明确的身份操作完成；
- 产品级去重只在当前有效的 Playback Evidence 中比较不同来源位置；已失效的历史证据
  不得阻止另一个真实来源位置以后以相同内容成为有效证据；
- 来源位置身份与证据内容指纹必须分开：前者用于发现“同一位置内容变了”，
  后者用于判定是否为内容完全相同的重复摄入；
- 同一来源位置出现不同内容时，不覆盖旧证据，也不自动断定它是原事件的证据更新
  还是一次全新播放；这是与 Handle 拆分同级的危险裁决；
- 同一来源的不同记录也可能属于同一次播放；
- 导入记录必须与本机已有证据一起判断重复，不能只在本批次内部去重；
- 更可信或更完整的证据可以影响当前解释，但不能消灭其他证据；
- 仅靠时间窗口、舞蹈编号或模糊相似度不能自动合并；
- 只对进入候选集的关系判断是否合并；没有形成候选关系的播放天然独立，不打负向标记；
- 候选关系证据不足时可以保留 `possible_match`，但播放继续独立且不要求用户处理；
- 用户确认的“同一次”或“不合并”是持久判断，重新导入和重建必须尊重。

### VRCX 数据库证据的最小正式合同

当前采用 `docs/vrcx_database_evidence_contract.zh-CN.md` 的
`vrcx-db-conservative-v1` A1–A6。其准入和来源去重仅依赖 VRCX 数据库，watcher 只作
研究参照。正式范围是：全量只读保留原行；通过明确 URL 白名单与唯一正整数 id 确定
舞蹈键；验证带明确时区的来源时间；一行发布一份自足来源证据；按稳定来源位置和完整
原值指纹消除重复摄入。同位置内容变化保留待裁决输入，不补写或静默替换正式证据。

标题、请求者、video_id、location 和 catalog 完整度不是额外准入条件。来源时间只表示
日志记录时间，请求者按源行成组保留；缺失值不靠其他行或表回填，不据此推断随机、
实际开始、结束、时长或完成。已发布的 VRCX-only occurrence 继续适用前述默认 accepted
规则；未支持输入与来源冲突不以新 occurrence 计入。

本版本不自动合并不同来源位置的 VRCX 行，也不以顺序、时间窗、同歌同实例或相邻错误
抑制计数。新证据仍及时进入 reconciliation 并取得合法 Handle/membership，公共流程
继续尊重既有有效关系及用户判断。B 级只保留来源信息，C 级推断与优化只作研究，均不
隐式改变发布、身份或默认计入结果。

### VRCX—watcher 共同来源规则（研究候选，暂未纳入正式合同）

日志中的原始 `[VRCX] VideoPlay(...)` 及 VRCX 实际支持的其他媒体输入，可能提供跨来源
对应。未来验证应保留实际消费的完整输入集合，包括标记时间、完整原始 URL、当时的
完整实例和稳定日志位置，另保留 position、duration、world parser 与 payload。
这些细节属于一条自足 watcher evidence，不能要求上层拼装零碎证据。

数据库时间、URL、location 的精确对应支持共同输入研究，但尚不能替代一次播放过程的
边界证明。实测已发现当前 watcher 将两个不同播放过程折叠到同一事件；因此不能把
“唯一标记匹配”直接升格为当前自动 merged 合同，也不通过打分或时间窗口修补它。
多行是否共同支持一次播放、输入集合双向唯一性、重试和重播边界须在未来单独验证。

VRCX 数据库行与其原始日志具有共同血缘，不作为独立投票。相关样本与反例保留在
`docs/vrcx_playback_data_facts.zh-CN.md` 和 `docs/vrcx_merge_review.zh-CN.md`；这些 watcher
统计不作为本版 VRCX 数据库准入规则的精准率或召回率。研究规则只有明确升级后才参与
正式 reconciliation，当前不生成此类自动关系。

来源位置相同但内容指纹变化是预期极少发生的危险事件。系统不得在普通导入路径中
静默覆盖或发布新的当前证据；它应保留足够的新输入和导入坐标，交由人工区分：

- 原来的同一来源事件更新了证据内容；
- 该来源位置现在表示一次全新的播放事件。

若已有时间、舞蹈条目和其他事实相符的 watcher 证据，可以在不发布任何关系的预览模式中重用
Playback Reconciliation 的同一套严格匹配规则，并把结果作为强力意见提供给人工。该结果
是裁决依据，不会越过这个危险边界自动替换已有有效证据。

若人工判定为原事件的证据更新，系统创建一条全新、不可变的 Playback Evidence，
将它归属到旧证据当前解析到的 Playback Handle，并以同一次可审计操作关闭旧证据
的当前 membership、建立新证据的 membership。旧证据行和历史 membership 都不物理删除或改写。

若人工判定为全新事件，系统同样创建新的不可变证据，但为它建立独立 Handle 和
membership；旧证据继续有效。这个人工判断必须持久化，使后续重新导入和
reconciliation 不会把两者重新当成未裁决的内容变化或静默合并。

除上述安全边界和裁决结果的方向外，本阶段不再为该极少事件设计完整审核流程、
候选生命周期、交互界面或更多自动化。它们不是当前 v2 主要工作。

导入的目标不是尽可能减少记录数量，而是在不损坏证据的前提下，尽可能准确地产生证据所
支持的 Playback Occurrence 分组和当前解释。

Playback Reconciliation 直接读取一个或多个来源的 Playback Evidence、持久证据归属
关系，以及已有的稳定播放句柄、锁定合并、redirect、`do_not_merge` 和相关用户状态。它不
在证据与 Playback Handle / Playback Occurrence 之间再创建“来源播放候选”表或概念层。
调用方一次性向它交付明确的一批
新证据；reconciliation 自己负责读取所需的既有持久状态，并为整批输入产生完整结果。
是否生成候选、如何检索和比较、是否构图或分组，以及是否采用全量或增量优化，都是算法
内部实现，不能由调用方预先划分所谓独立单元，也不能改变可观察结果。算法可以报告：

- `merged`：严格规则确认候选属于同一次播放并完成合并；
- `possible_match`：候选具有相关性但不满足严格合并规则，保留关系线索但继续独立消费；
- 无候选关系：播放天然独立，不保存 `confirmed_separate` 或其他负向标记。

只有 `merged` 会改变稳定播放之间的身份关系。`possible_match` 和无候选关系都不合并，上层
把相关 Playback Occurrences 作为彼此独立的播放消费；不额外设置“身份分离但统计暗中只算
一次”的隐藏关系。`possible_match` 可以被动保存或展示，但不产生 review 任务，也不能让
正常运行依赖用户有时间确认。

Playback Reconciliation 不允许存在终态 `failed`。它对负责的一批证据必须提交完整、原子且
自洽的身份结果：能严格证明的合并，不能证明的保持分离，并为每条新证据建立且只建立一条
有效 membership。算法、字段 resolver 和不变量校验必须对全部已声明支持的输入组合全定义；
达不到这一要求的模块不能视为实现完成。

一次调用所接收的整批新证据就是对外的原子 reconciliation 边界。内部可以使用任意等价的
优化，但不能把子集结果提前发布，也不能要求调用方根据候选关系拆批。对于相同的持久输入、
同一批新证据和同一算法版本，重复执行必须产生相同的语义分组；摄入批次的技术组织不得成为
判断两条证据是否属于同一次播放的事实依据。

进程崩溃、数据库忙、I/O 异常或其他执行问题只会中断一次 attempt，不是 reconciliation
结果。该批证据保持持久的未完成状态，本轮任何 identity 关系变更都不生效；系统保存 attempt
次数、最后错误、规则版本和涉及的证据坐标用于诊断，并在启动恢复或后台恢复中继续执行，
直到完整结果成功提交。普通读取不得顺便执行 reconciliation，也不得把未完成批次伪装成
独立 Playback Occurrences。来源证据的安全提交不因一次执行中断而回滚。

`user_decision_required` 是显式合并或历史修复流程中的暂停态。只有当身份证据支持合并、
但两侧当前实际支持的用户状态无法无损共存时才进入该状态。用户可以完成 `merged`，也可以
创建一条持久的 `do_not_merge` 判断；用户暂不处理时，两边继续分离，原身份、证据和用户
状态全部保持不变，上层仍按独立播放消费。它不进入日常 review 队列。

重复处理优先通过实验寻找可靠的候选生成和严格合并规则。无法满足严格规则的候选保持
`possible_match` 并继续独立消费；不采用来源抑制、暗中只算一次或等待用户确认等中间
策略。

证据可以通过持久归属关系直接支持一个播放句柄。不同的稳定播放句柄最初保持独立；严格
规则确认后的 Playback Occurrence Merge 通过最小、持久且可审计的 Playback Handle Redirect
表达。当前 Playback Occurrence 是不可变证据、有效 Playback Evidence Membership 和有效
Playback Handle Redirect 闭包的可重建投影，而不是
另一份重复保存的完整事实。普通重建只能重放有效关系，后续算法不能静默拆分。若发现错误
归属或错误合并，当前阶段只记录并暴露诊断，不在上层引用尚未具备安全处理能力时执行关系
关闭、Handle 拆分或证据改挂。自动建立的关系必须记录判断依据、算法和版本，以便解释、
验证和复现当时为何建立这条关系。

合并多个稳定 Playback Handles 时，必须指定其中一个现有 Handle 继续作为 Canonical Handle，
其他句柄可追溯地 redirect 到它；后续构建根据有效关系的闭包产生当前 Playback Occurrence。
不能丢失原句柄和合并履历，也不为合并结果新建第三个播放身份或永久“同次播放组”层。
合并不得改写已有 Playback Evidence Membership；关系失效或修复也不得通过物理删除历史
membership 或 redirect 完成。

有效 Playback Handle Redirect 形成有向森林，而不是全部扁平指向当前 Canonical Handle。每个被重定向
句柄同时最多有一个有效的直接父 Handle，父 Handle 可以继续重定向；系统禁止环，并沿直接
父关系的闭包解析当前 Canonical Handle。直接父关系保留自然的合并顺序和局部分组，为未来
可能的安全修复保留必要结构，但本文不定义拆分结果。读取所需的扁平 canonical 映射只能
作为可删除、可重建的缓存保存。

为减少读取时解析 membership 和重定向链的成本，可以保存扁平的
`evidence → current Canonical Handle` 查询投影。该投影不是新的证据归属，不得回写或取代
权威 Playback Evidence Membership；缓存缺失或失效时必须能从有效 membership 与 Handle
重定向森林完整重建。
舞蹈计划完成关系、排除和其他当前领域引用必须通过稳定句柄和 redirect 解析，而不引用
可重建投影的物理行身份。句柄本身不保存权威的当前重定向指针；有效重定向来自可审计的
Playback Handle Redirects，若以后为读取性能保存当前指针或闭包，它只能是可重建缓存。

watcher live、watcher replay、VRCX 导入以及未来任何受支持来源在写入新证据后，都必须自动
触发 Playback Reconciliation。它比较本次新增证据与本机已有全部相关证据和稳定播放，不是
只在当前批次内部去重；它是证据摄入后的明确阶段，不能由普通读取暗中触发。VRCX adapter
在这个过程中只增加 VRCX 来源证据，不创建或导入人工判断、舞蹈计划完成关系或当前解释。

通常先完成来源证据归并，再在稳定播放上叠加用户状态。若稳定播放已经带有人工判断或
舞蹈计划完成关系，后来导入的无状态来源证据仍可自动合入，并保留原 canonical
identity 和全部用户状态。用户状态本身不阻止自动合并；两侧状态完全兼容时仍可自动
合并。若身份证据支持合并，但两侧当前实际支持的用户状态无法无损共存，则自动流程暂停并
请求一次 Merge Decision，由用户决定是否合并以及保留或组合哪些状态；系统不得用来源
优先级替用户裁决。用户决定前不得创建 redirect 或发布部分合并结果。

这种 Merge Decision 不应出现在正常的即时 ingestion 路径：新来源证据写入后立即执行
reconciliation，因此通常至少一侧尚未叠加用户状态。它主要可能出现在以下例外：

- 过去保留为 `possible_match` 的两次播放都已被用户修改，后来新增证据
  或改进规则才确认它们属于同一次；
- 两个曾独立使用的 app root、备份分支或数据库各自积累了用户状态，之后进行跨库合并；
- 用户主动用新规则重新处理旧数据，发现过去分别维护的播放实际应当合并；
- reconciliation 执行曾被中断，而产品错误地允许用户在未完成归并的中间状态上继续编辑；
  最后一种是实现缺陷，应由 Handle-based read boundary 阻止。

来源证据字段的原始值不一致不进入 Merge Decision。只要严格规则已经确认是同一次播放，
证据仍然合并保存；字段级 resolver 必须按已定义规则，为每个对外字段产生唯一、有效且
确定性的合并结果。产品只消费这个结果，不对外暴露 field conflict 或 ambiguous 状态。
所有原始值、来源关系、解析依据和规则版本仍保留在内部，以支持解释和重建。

严格合并规则只有在字段 resolver 能为合并后的所有对外字段产生满足不变量的完整结果时才算
成立。某个输入组合缺少对应解析规则时，候选必须保持分离并记录开发诊断，不能发布部分
合并结果，也不能临时把选择责任转交给界面或用户；对已声明支持的输入组合，测试必须证明
不存在这类覆盖缺口。只有所有来源都没有提供某字段时，合并结果才可以按该字段自身语义
为空；“为空”不能作为隐藏原始值不一致的兜底。

## 与其他业务的关系

v2 中，所有舞蹈系统的条目统一写入公共舞蹈表。公共表拥有舞蹈条目的主键并保存系统间
真正共用的字段；需要专有字段的舞蹈系统使用自己的舞蹈细则表。细则表与公共舞蹈表是
一对一关系，其 `dance_track_id` 同时作为本表主键和指向公共舞蹈表的外键，不再建立独立
的细则身份。

公共舞蹈表采用整数主键，并由稳定的舞蹈系统标识与系统内部 id 通过约定的位分配规则
确定性生成。相同输入在不同数据库环境中必须得到相同主键，不依赖插入顺序或本地自增
状态。

当 watcher 或 VRCX Playback Evidence 已经提供稳定的 `dance_system_key +
dance_external_id`，但本地 Catalog 尚无完整条目时，这对稳定键已经足以确定 Dance Track
身份；缺少 Catalog 行不是身份未决。证据写入不必为了该身份立即物化公共舞蹈表条目，
也不得因此阻塞或丢弃不可再生的播放证据。系统可以在首次确实需要解析或展示该 Dance
Track、且 Catalog 中仍无对应条目时，按稳定键懒创建最小条目。标题、舞者、人数和其他
可选 metadata 可以为空，以后由 Catalog 同步补全同一条目；缺少 metadata 不得被解释成
该 metadata 已经验证。该惰性物化不构成业务上的 unresolved binding，也不需要额外的
unresolved-binding 生命周期；证据具体保存稳定键还是确定性主键留待表结构设计时决定。

舞蹈计划表示播放前的用户意图，不是播放证据，也不创造 Playback Occurrence。计划完成关系
应连接计划条目与稳定 Playback Handle；只有存在这一关系时，系统才能把相应 Playback
Occurrence 解释为计划内。计划状态本身可以修改，因为它属于用户意图。

来源观察到的名称、用户身份、随机标记或自动播放信号应先作为证据保存。请求者身份和
计划、推荐、自己、他人、随机、未知等解释由统一规则产生。请求者为空不能自动证明是
随机，存在请求者也不能自动证明是手动点播；不知道时应保留未知。

## 可重建的界线

必须长期保存的内容包括：不可变来源证据、证据 membership 的建立与关闭履历及其人工裁决、
独立的稳定播放句柄、有效证据归属及其修复
履历、有效 Playback Handle Redirects 及其算法版本和修复履历、用户判断履历（包括明确
的 `do_not_merge` 判断），以及舞蹈计划等用户意图。不长期保存一份重复的完整 Playback
Occurrence 当前事实表。

可以删除并重新生成的内容包括：Playback Occurrence 当前投影、证据经句柄重定向解析到
当前 occurrence 的成员闭包、`possible_match` 候选关系、当前接受或排除结果、复查提示、
请求来源解释、面向时间线和分析的汇总，以及只为查询性能存在的缓存结果。这里可重建的
成员闭包不等于必须长期保存的证据归属关系。

重建必须只依赖长期保存的输入，并满足相同输入和相同规则得到相同结果。重建和修复应
是明确、可观察、可验证的操作，而不是普通读取的副作用。

## 剩余工作的决策层级

### 方向决定已收敛

Self User Identity 是一组经用户确认属于本人的稳定 VRChat user ids，不是一个会覆盖旧值的
单一当前 id，也不使用有效时间段。Request Source Type Inference 在全部保留历史上把
requester user id 命中该集合的 Playback Occurrence 解释为 `self`；删除误录成员后，全量
rebuild 应按修正后的集合重新产生 `self` / `other`。VRCX identity detection 只提出候选，
用户确认一个候选时将它加入集合，不隐式替换已经确认的其他成员。具体持久化结构和设置
界面仍属于实现设计。

至此，当前没有发现仍需通过产品方向选择才能继续的 v2 核心分岔。

### 实现前必须形成可测试合同

以下事项不是新的产品方向，但在开始相应模块实现前必须从既有原则推导成明确合同：

- watcher 与 VRCX 的公共证据字段、来源细则、provenance 最小集合，以及稳定 Source
  Evidence Location、内容指纹和来源血缘规则；
- 同来源位置内容变化时的最小安全落盘与诊断合同；完整人工审核 UI 仍可暂缓；
- Playback Handle、membership、redirect、Playback Identity Operation、Manual Playback
  Decision 和 migration history 的物理 schema、约束与事务边界；
- 初始 Handle 建立、无归属证据检测、并发摄入、reconciliation 原子提交和未完成作业恢复规则；
- reconciliation 批次输入与完整输出、严格自动合并、Canonical Handle 选择、三方及更多来源、`do_not_merge`
  闭包约束、算法版本与执行诊断的完整 Playback Reconciliation 合同；
- played time、dance identity、requester、location 和 observation 等字段的确定性 resolver，
  包括所有受支持输入组合的唯一结果和算法覆盖缺口行为；
- Default Acceptance Result 的规则表，明确哪些已发布证据得到 `accepted`，哪些得到非计入的
  `needs_attention`，并消除 ADR 0002 中只适用于 v1 的全局来源排序与 routine review 语义；
- Handle-based Playback Read Boundary 的 API、重定向解析、投影重建和缓存一致性合同；
- Dance Plan、Handle-based Fulfillment、Request Source Type Inference、全量 reconciliation /
  rebuild 触发条件，以及它们与 accepted/excluded/restore-default 的事务协作；
- v2 schema migration runner、未知版本拒绝、失败回滚、切换备份，以及现有 `rebuild-data`
  不得销毁 v2 持久用户状态的替代行为；
- 单元测试、真实 VRC log replay、重复 VRCX import、live/replay 同源去重、三来源合并、
  reconciliation 中断恢复、投影全量重建和干净切换的验收门槛。

这些合同多数应由代码、真实数据实验和测试收敛；只有实验暴露出两个具有不同产品后果的
合理方向时，才需要再次请求用户决定。

跨来源时间合同的真实数据输入已记录在
`docs/vrcx_playback_data_facts.zh-CN.md`。该记录包括 VRCX 表结构与字段存在情况、
两批共 228 MB VRChat 日志与 `gamelog_video_play` 的直接对应、当前最新 watcher 的重放结果、
共同原始标记覆盖率、字段一致性和 `played_at` 时间窗反例；事实记录本身不规定公共证据根的
时间表示、basis、来源优先级、接受规则或 reconciliation 条件。

### 可在实现期选择的细节

最终表名、列名、Handle 主键类型、整数位分配、索引、JSON 与结构化列的取舍、attempt 重试
间隔与退避、候选窗口参数、事务内辅助字段、投影采用按需查询/视图/缓存、全量重建的批量
大小、局部重建优化、诊断页面布局和 UI 文案都属于实现细节。它们仍需实现和验证，但不应
提前升级为领域规则；实现可以选择最简洁可靠的方案，只要不违反本文的不变量。

### 已明确暂缓或排除

Manual Log Entry、Manual Record Update、单次播放评分、推荐算法与 Recommendation List
Snapshot 生产、跨 DanceTrail 数据库语义导入、Handle 拆分、Handle redirect 关闭、任意
membership 解除或改挂，以及完整的同位置内容变化审核产品流程均不属于当前 v2 完成条件。
v1→v2 数据迁移、双写、混合读取和兼容回退已经明确不实施，也不是待决项。
