# playback_records schema redesign

本文记录下一版 `playback_records` 及其相邻表的目标设计。它是进行中的设计文档，记录已经确认的决定；后续实现中发现的新问题应继续补充到本文。

## 设计原则

- `playback_records` 保持为长期稳定的产品表名；不把永久产品读路径迁移到 `playback_records_v2` / `playback_records_v3`。
- `playback_records` 是规范化的 Local Playback Evidence 根表。它不是 raw evidence 仓库，也不是单纯的外部来源 row copy。
- 主表只保留 Timeline、Insights、review、report 等产品读路径需要直接查询的规范化字段。
- 来源坐标、原始 payload、legacy source residue、debug/audit 细节放到相邻的 origin/provenance 表，不放进主表。
- 人工接受、排除、复查等用户判断继续作为 overlay 存储，不改写 evidence 行本身。
- 字段命名按概念分组，避免旧字段中 `source_*` 同时表达 evidence、request、origin、priority 的混用。

## 已确认决定

### 主表边界

`playback_records` 表示当前 app root 拥有的规范化 Local Playback Evidence。它可以包含 request、acceptance、observation 等规范化产品字段，但这些字段必须以清晰前缀表达概念边界。

不采用把 request、acceptance、observation 拆成多张产品主表的方案。这个拆法概念上更纯，但会显著增加 Timeline、Insights、report、writer 和 watcher settlement 的 join/迁移面。

### Request Source Type

Request Source Type 作为规范化产品字段保留在 `playback_records` 主表，长期字段名使用 `request_type`。

相关字段：

```sql
request_type TEXT,
requester_display_name TEXT,
requester_user_id TEXT
```

`source_type` 是当前 legacy 存储名，不作为长期字段名。`player` 这类旧 watcher 粗分类不是长期规范的 Request Source Type。

watcher requester identity enrichment 只负责尽量补全 `requester_display_name` / `requester_user_id`，不因为拿到 `requester_user_id` 就直接决定 `request_type = self` 或 `other`。

主表不保留 `request_confidence`。旧 `confidence` 是历史上把 source、request classification 和推断优先级混在一起产生的字段，不作为新模型的策略输入。正常产品逻辑应基于 `request_type`、Default Acceptance Result、manual overlay 和明确的 Request Source Type strategy 工作。

### Default Acceptance Result

旧的 `playback_status + counts_in_history + status_reason` 合并为一个默认接受结果概念。

长期字段名：

```sql
default_acceptance_status TEXT NOT NULL
```

`default_acceptance_status` 表达 evidence-derived 默认结果，枚举至少包括：

- `accepted`
- `pending`
- `excluded`
- `needs_attention`

`counts_in_history` 不作为长期字段保留。它和 `playback_status` 共同表达一个概念，容易出现不一致状态。是否计入普通历史和 Insights 应由 default result 加 manual overlay 后的 effective projection 决定。

主表不保留 `default_acceptance_reason`。默认接受结果的解释应由 `evidence_source`、`observation_status`、`observation_reason` 和明确的 acceptance strategy 推导。旧 `status_reason` 大多是这些字段的重复表达；把 reason 字符串存成主表事实会带来 drift 风险。

### Playback Observation

旧的 `completion_status + completion_reason` 改名为 observation 概念，并保留在主表。

长期字段名：

```sql
observation_status TEXT,
observation_reason TEXT,
observed_end_at TEXT
```

这些字段描述本地观察到的播放生命周期状态，例如 active observation、completed observation、interruption、watcher stop、video shutdown。它们可以影响 Default Acceptance Result，也可以帮助 Timeline 解释 pending 或 attention-needed 的原因，但它们不是 request source，也不是 acceptance 本身。

`observed_end_at` 表示本地观察到这次 playback observation 结束的时间边界，正常完成和意外打断都使用同一个字段；具体是 completed 还是 interrupted 由 `observation_status` / `observation_reason` 解释。pending 或没有本地结束观测的记录为 `NULL`。

不使用裸 `end_at`，因为它容易被误解成视频理论结束时间或只有正常完成才填。也不保留 `completed_at` / `interrupted_at` 两个主表字段；把结束时间拆成两个字段会让同一概念有多个空值组合。

原始 watcher lifecycle 细节、旧 payload、parser residue 放 origin/audit 细节，不作为主表规范字段扩张。

### Original Playback Time

主表不保留 `original_played_at`。主表只保留规范化后的 `played_at`，作为 Timeline、Insights、report 使用的播放时间。

旧 `original_played_at` 这类来源输入的原始时间表达属于 origin/audit 细节。需要解释时间归一化时，使用 `origin_json.original_played_at`。

普通产品读路径不应同时面对两个播放时间字段。

### Ingest Time

主表不保留 `ingested_at`。

主表的 `created_at` / `updated_at` 表达当前 app root 中这条 Local Playback Evidence 的本地记录生命周期。具体哪次导入、迁移、replay 或 merge 产生了某个来源关系，属于 origin/audit 层，由 `playback_record_origins.ingest_run_id` 和 origin row 的 `created_at` 表达。

一条 Local Playback Evidence 可能有多个 origin，也可能被重复导入或 replay。把 `ingested_at` 放在主表会制造歧义：它既不像 `played_at` 那样是播放发生时间，也不像 `created_at` 那样是本地记录创建时间。

### Catalog Match Fields

主表不保留旧的 `catalog_status` / `catalog_attention`，也不在当前设计中新增 `dance_match_status` / `dance_match_reason`。

主表已有：

```sql
dance_track_id INTEGER,
dance_system_key TEXT NOT NULL,
dance_external_id TEXT NOT NULL
```

这些字段足够表达当前产品需要的 catalog 绑定状态：`dance_track_id IS NULL` 表示尚未绑定到本地 catalog track；非空表示已经绑定。`dance_system_key` / `dance_external_id` 保留证据中的舞蹈系统身份，使未绑定记录仍可展示、复查和后续修复。

如果未来出现明确的 UI/report 读路径，需要解释“为什么没有匹配”或“匹配需要人工处理”，再引入专门的 repair/report 输出或清晰命名字段。当前不要提前存 `*_status` / `*_attention` 缓存字段，避免和 catalog repair 逻辑 drift。

### VRCX Location

主表不保留旧 `location` 字段。

当前真实数据中，`location` 几乎全部来自 VRCX history，表达的是 VRCX 记录里的 VRChat world/instance 字符串，例如 `wrld_...:76264~region(jp)`；也存在少量非 location 状态值，例如 `traveling`。`location` 这个字段名过泛，容易被理解成任意地点、显示地点或产品级位置。

这类 source-side 细节属于 `origin_json.vrcx_location`。未来如果出现明确产品需求，再新增更精确的规范化字段，例如 `vrchat_world_id`、`vrchat_instance_id`、`vrchat_region`。

### Identity and provenance

采用三层身份：

| 字段 | 所属表 | 含义 | 主要用途 |
| --- | --- | --- | --- |
| `id` | `playback_records` | 当前 SQLite 数据库里的行身份 | 外键、manual overlay、UI action、API route |
| `evidence_key` | `playback_records` | 当前 app root 拥有的 Local Playback Evidence 稳定身份 | writer/import/replay/merge upsert 和 dedupe |
| `origin_key` | `playback_record_origins` | 来源侧事件、坐标或 payload 的稳定身份 | provenance、audit、debug、迁移解释 |

`id` 保留为 `INTEGER PRIMARY KEY AUTOINCREMENT`。它是最适合 SQLite 外键和 UI 操作的本地 surrogate key，但它只能在插入后获得，不能解决“这次导入/重放是不是同一条 evidence”的问题。

`evidence_key` 是主表的业务去重 key，长期替代旧 `source_fingerprint`。它表达的是本地规范化证据身份，不表达来源表、来源 row id、来源文件路径或 raw payload。正常 writer、importer、replay、merge 应该围绕 `evidence_key` upsert。

`origin_key` 放在 origin 表。来源侧 table、row id、event key、source path、raw JSON 等只用于解释这条 evidence 从哪里来，不参与主表身份命名。

推荐约束：

```sql
playback_records.evidence_key TEXT NOT NULL UNIQUE
playback_record_origins.origin_key TEXT NOT NULL UNIQUE
```

如果一个 raw source event 未来合法拆出多条 playback evidence，adapter 应生成多个不同的 `origin_key`，而不是让一个 `origin_key` 绑定多个主表记录。

### Evidence Source

主表保留 `evidence_source TEXT NOT NULL`。它是小而稳定的 evidence adapter enum，回答“这条 Local Playback Evidence 由哪类证据 adapter 产出”。

初始枚举：

- `vrcx_history`
- `vrc_log_replay`
- `vrc_log_live`
- `manual_log`

`evidence_source` 不包含 source table、source row、source path、旧 root 名、操作名或脚本版本。以下值不应作为长期 `evidence_source`：

- `import`
- `dance_events`
- `live_playback_events`
- `watcher_playback_events`
- 带日期或版本号的脚本名

操作脚本日期、迁移版本、adapter 版本和批次信息属于 ingest/origin audit 元数据。确实需要保留时，放在 origin 表字段或 `origin_json` 中，例如：

```sql
ingest_run_id TEXT,
origin_json.adapter_version,
origin_json.migration_name
```

主表已有 `created_at` / `updated_at` 表达本地记录生命周期。不要为了记录脚本运行日期新增 `evidence_source` 变体，也不要把每次 migration 的日期编码进主表字段值。

### Evidence Source Priority

长期主表不保留 `evidence_priority` / `source_priority` 字段。

Evidence Source Priority 是策略计算结果，不是来源事实。它应由 evidence source、default acceptance、active manual decision，以及未来明确的冲突处理规则共同推导。把 priority 数字存进主表会带来 drift 风险：策略变了，旧行里的数字就可能过期。

旧 `source_priority` 没有目标模型语义。正常产品逻辑不应读取旧 priority 数字来决定当前行为。

### Playback Record Origins

相邻表命名为 `playback_record_origins`。它存来源坐标、raw payload、legacy residue 和 audit/debug 细节，不参与普通 Timeline/Insights/report 主查询。

选择 `origins` 而不是 `provenance`：这里的主要职责是记录“这条 Local Playback Evidence 来自哪个来源事件或来源坐标”。`provenance` 容易扩张成泛化审计杂物箱，边界不如 `origin` 干净。

字段：

```sql
CREATE TABLE playback_record_origins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playback_record_id INTEGER NOT NULL,
    origin_key TEXT NOT NULL UNIQUE,
    origin_source TEXT NOT NULL,
    origin_root_key TEXT,
    origin_root_path TEXT,
    origin_table TEXT,
    origin_row_id INTEGER,
    origin_event_key TEXT,
    ingest_run_id TEXT,
    origin_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,

    FOREIGN KEY(playback_record_id) REFERENCES playback_records(id) ON DELETE CASCADE
);
```

字段含义：

- `origin_key`: 来源侧事件、坐标或 payload 的稳定身份；用于 origin 去重。
- `origin_source`: 来源坐标命名空间，例如 VRCX 数据库、VRChat log、legacy dancing-log root、manual entry。它不是 `evidence_source` 的替代品。
- `origin_root_key` / `origin_root_path`: 来源 app root、数据库、日志目录或文件集合的定位信息。
- `origin_table` / `origin_row_id` / `origin_event_key`: 来源侧表、行或事件 key；没有对应概念时为空。
- `ingest_run_id`: 一次导入、迁移、replay 或 merge 的运行身份；脚本日期或版本不要编码进 `evidence_source`。
- `origin_json`: 低频 audit/debug 细节，例如 raw payload、adapter version、migration name、parser diagnostics。

不为 `playback_record_origins` 建显式查询索引。origin 是低频 audit/debug 路径，先依赖 `origin_key UNIQUE` 的隐式唯一索引。等以后出现按 source root 批量查询 origin 的 Data Operations 功能或明确性能问题，再补充 origin 查询索引。

不额外保留 `UNIQUE(playback_record_id, origin_key)`。在 `origin_key` 已全局唯一时，该约束没有额外表达力。未来如果真的出现一个 raw source event 需要拆成多条 evidence 的情况，adapter 应生成不同的 `origin_key`。

### Migration Plan

从当前 v0 runtime schema 迁移到本文目标 schema 的一次性迁移规则记录在 `docs/playback_records_migration_plan.zh-CN.md`。本文只定义长期目标模型；旧字段映射、保留旧 `id`、严格失败策略和迁移验证项不属于长期 schema contract。

### Indexes

显式索引只保留当前产品读路径需要的最小集合：

```sql
CREATE INDEX idx_playback_records_played_at
    ON playback_records(played_at);

CREATE INDEX idx_playback_records_identity
    ON playback_records(dance_system_key, dance_external_id);

CREATE INDEX idx_playback_records_acceptance
    ON playback_records(default_acceptance_status);
```

暂不为 `dance_track_id`、`evidence_source`、`request_type`、`requester_user_id`、`observed_end_at` 或 origin 查询字段建立显式索引。等出现明确产品查询路径、性能问题或稳定 join 需求时再补。

`UNIQUE(evidence_key)` 和 `UNIQUE(origin_key)` 会由 SQLite 隐式维护唯一索引；它们是身份约束，不属于额外查询索引。

## 当前目标 schema 草案

以下草案反映当前已经确认的字段结构。

```sql
CREATE TABLE playback_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_key TEXT NOT NULL UNIQUE,
    evidence_source TEXT NOT NULL,

    played_at TEXT NOT NULL,
    dance_track_id INTEGER,
    dance_system_key TEXT NOT NULL,
    dance_external_id TEXT NOT NULL,

    request_type TEXT,
    requester_display_name TEXT,
    requester_user_id TEXT,

    default_acceptance_status TEXT NOT NULL,

    observation_status TEXT,
    observation_reason TEXT,
    observed_end_at TEXT,

    video_url TEXT,
    video_name TEXT,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY(dance_track_id) REFERENCES dance_tracks(id)
);

CREATE TABLE playback_record_origins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playback_record_id INTEGER NOT NULL,
    origin_key TEXT NOT NULL UNIQUE,
    origin_source TEXT NOT NULL,
    origin_root_key TEXT,
    origin_root_path TEXT,
    origin_table TEXT,
    origin_row_id INTEGER,
    origin_event_key TEXT,
    ingest_run_id TEXT,
    origin_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,

    FOREIGN KEY(playback_record_id) REFERENCES playback_records(id) ON DELETE CASCADE
);
```

## 待决问题

当前没有未决的 schema 命名项。后续实现中如果发现目标模型无法表达新的产品需求，应回到本文补充新的决策。
