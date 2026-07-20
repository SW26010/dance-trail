# playback_records v0 → v1 migration plan（历史）

本文记录从 `playback_records` v0 运行时结构迁移到数据模型定义 v1 所对应结构的一次性
历史迁移规则。

本文是旧 `playback_records` 方案下的历史迁移设计，不是下一代数据结构的约束。
新的方向性定义见 `docs/playback_data_model_redesign.zh-CN.md`；新结构优先最大化长期模型优势，
明确不以本文件中的迁移成本、字段映射或兼容要求作为设计输入。
v2 已明确采用无数据迁移、无双写、无兼容读取的干净切换；本文只记录历史上的 v0→v1
方案，不能作为 v1→v2 实施计划。
旧方案当时采用的字段级目标仍保留在 `docs/playback_records_schema_redesign.zh-CN.md`，
仅用于理解本文的历史上下文。

## 迁移原则

- 严格失败，不静默猜测。
- 映射必要字段，丢弃混乱残留，不做垃圾搬家。
- 一条旧 `playback_records` 对应一条新 `playback_records`。
- 保留当前 app root 中已有 `playback_records.id`，保护 manual overlay、Web UI action 和 legacy live promotion 兼容引用。
- 不在 schema migration 中重建 Request Source Type。queued-self、recommend、self/other 等分类由后续独立、可重复的 rebuild/repair 流程处理。

## 迁移前校验

迁移前必须验证：

- `PRAGMA quick_check` 返回 `ok`。
- 旧 `playback_records.source_fingerprint` 无重复。
- 旧 `playback_records.imported_at` 全部非空且可规范化。
- 旧 `playback_status` / `counts_in_history` 组合全部在本文映射表内。
- 已有 `manual_playback_decisions.playback_record_id` 均能引用到旧 `playback_records.id`。
- 若保留 legacy `live_playback_events`，其 `promoted_playback_record_id` 均能引用到旧 `playback_records.id`。

任一校验失败，中止迁移并报告具体旧 `id` 与原因。

## 主表迁移

迁移保持旧 `playback_records.id` 原样写入新表。迁移完成后必须校准 AUTOINCREMENT 序列。

字段映射：

| 旧字段 | 新位置 | 规则 |
| --- | --- | --- |
| `id` | `playback_records.id` | 原样保留 |
| `source_fingerprint` | `playback_records.evidence_key` | 作为初始迁移兼容值 |
| `source_kind` / `event_source` | `playback_records.evidence_source` | 通过 adapter-specific mapping 转换，不做字符串直搬 |
| `played_at` | `playback_records.played_at` | 规范化后迁移 |
| `dance_track_id` | `playback_records.dance_track_id` | 原样迁移 |
| `dance_system_key` | `playback_records.dance_system_key` | 原样迁移 |
| `dance_external_id` | `playback_records.dance_external_id` | 原样迁移 |
| `requester_display_name` | `playback_records.requester_display_name` | 空字符串规范化为 `NULL` |
| `requester_user_id` | `playback_records.requester_user_id` | 空字符串规范化为 `NULL` |
| `playback_status` / `counts_in_history` | `playback_records.default_acceptance_status` | 按下方状态映射 |
| `completion_status` | `playback_records.observation_status` | 空字符串规范化为 `NULL` |
| `completion_reason` | `playback_records.observation_reason` | 空字符串规范化为 `NULL` |
| legacy live `completed_at` / `interrupted_at` | `playback_records.observed_end_at` | 见 observation 规则 |
| `video_url` | `playback_records.video_url` | 空字符串规范化为 `NULL` |
| `video_name` | `playback_records.video_name` | 空字符串规范化为 `NULL` |
| `imported_at` | `playback_records.created_at`, `playback_records.updated_at` | 规范化后同时写入 |

迁移后的 `request_type` 默认保持 `NULL`，不从旧 `source_type` 重建。

## Acceptance 映射

`default_acceptance_status` 映射：

| 旧 `playback_status` | 旧 `counts_in_history` | 新 `default_acceptance_status` |
| --- | ---: | --- |
| `accepted` | `1` | `accepted` |
| `pending` | `0` | `pending` |
| `needs_attention` | `0` | `needs_attention` |
| `excluded` | `0` | `excluded` |

任何其他组合都严格失败。旧 `status_reason` 不参与目标字段生成，只能作为迁移校验的诊断上下文，然后丢弃。

## Observation 映射

`observation_status` 值域：

- `completed`
- `interrupted`
- `pending`
- `NULL`

旧 `completion_status` 为 `NULL` 或空字符串时，`observation_status` / `observation_reason` / `observed_end_at` 均为 `NULL`。

旧 watcher reason 原词保留到 `observation_reason`，例如：

- `observed_completion_threshold`
- `room_left`
- `application_quit`
- `video_shutdown`
- `watcher_stopped`
- `superseded_before_completion`
- `unknown_duration_before_superseded`
- `observed_mid_play`
- `watcher_interrupted_unexpectedly`

`observed_end_at` 优先从 legacy live origin 的 `completed_at` 或 `interrupted_at` 迁移；旧 `playback_records` 本身没有结束时间时为 `NULL`。如果两个结束时间同时存在或与 `completion_status` 矛盾，严格失败。

## Origin 迁移

每条新 `playback_records` 至少创建一条 `playback_record_origins`。

`origin_key` 从来源坐标确定性生成，但必须使用不同于 `evidence_key` 的命名空间。推荐格式：

```text
origin:v1:<sha256(source_root_key, source_table, source_row_id, source_event_key)>
```

不允许 `origin_key` 和 `evidence_key` 直接同值。即使两者由同一批旧字段派生，也必须通过不同 namespace 表达不同身份层级。

字段映射：

| 旧字段 | 新位置 |
| --- | --- |
| `source_root_key` | `playback_record_origins.origin_root_key` |
| `source_root_path` | `playback_record_origins.origin_root_path` |
| `source_table` | `playback_record_origins.origin_table` |
| `source_row_id` | `playback_record_origins.origin_row_id` |
| `source_event_key` | `playback_record_origins.origin_event_key` |
| `cleanup_batch_id` 或迁移运行标识 | `playback_record_origins.ingest_run_id` |

`origin_source` 使用来源坐标命名空间，不等同于 `evidence_source`。它可以来自 legacy root、VRCX database、VRChat log replay source 或 manual source 的稳定命名。

`playback_record_origins.created_at` 使用迁移运行时间，表示这条 origin 关系是在本次迁移中写入的。主表 `created_at` / `updated_at` 仍使用旧 `imported_at`。

## origin_json 白名单

只允许必要的 raw/origin/debug 信息进入 `origin_json`：

- `original_played_at`：仅当它和规范化 `played_at` 不同或有审计价值。
- `vrcx_location`：旧 `location` 非空时写入。
- 必要 raw payload：仅当它能解释来源事件或后续诊断需要。
- `adapter_version`、`migration_name`、parser diagnostics。
- observation 时间冲突诊断：仅在严格失败前输出或在可判定的非致命诊断中记录。

不整包搬迁旧 `provenance_json`。迁移脚本只提取白名单信息。

## 丢弃字段

以下字段直接丢弃，不进入主表，也不进入 `origin_json`：

- `source_type`
- `confidence`
- `source_priority`
- `source_display_name`
- `status_reason`
- `catalog_status`
- `catalog_attention`

这些字段要么来自旧 `source` 词系混用，要么是可由新字段/策略推导的缓存状态。`source_type` 整列丢弃，不按值白名单迁移到 `request_type`。

## FK 行为

`playback_record_origins.playback_record_id` 使用：

```sql
FOREIGN KEY(playback_record_id) REFERENCES playback_records(id) ON DELETE CASCADE
```

虽然正常产品流程不鼓励删除 playback evidence，但 origin 是 evidence 的附属行；如果显式删除 evidence，不应留下 origin 孤儿行。

## 迁移后验证

迁移后必须验证：

- 新旧 `playback_records` 总行数相同。
- 旧 `id` 集合和新 `id` 集合相同。
- `evidence_key` 唯一且非空。
- `origin_key` 唯一且非空。
- 每条 `playback_records` 至少有一条 `playback_record_origins`。
- `manual_playback_decisions` 无孤儿引用。
- 若保留 legacy `live_playback_events`，`promoted_playback_record_id` 无孤儿引用。
- accepted / pending / needs_attention / excluded 计数与映射结果一致。
- `requester_user_id` 非空值数量不下降。
- VRCX history、log replay、live watcher 的来源覆盖数符合预期。

## 文档同步

`docs/dance_data_model.md` 和 `docs/dance_data_model.zh-CN.md` 描述当前/v0 runtime model，不是下一版 schema contract。迁移实现完成后，应更新这两份文档，使它们描述新的 runtime model，或继续明确标注 legacy/v0 语义。
