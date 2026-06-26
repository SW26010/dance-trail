# request_type 推断中的推荐清单证据

日期：2026-06-26

状态：第一版实现约束。本文只记录为了先实现 Dance Plan 和 Request Source Type Inference 所必须确定的推荐相关事项；推荐算法、推荐 UI、清单长度、重生成规则、排序细则和最终推荐表 schema 暂缓。

## 目标

`request_type = recommend` 必须来自一个可解释、可重复读取的推荐清单证据，而不是来自当前推荐算法的即时结果。

第一版要先保证：

- Dance Plan 能把已 fulfill 的 Accepted Playback Record 推断为 `planned`。
- Request Source Type Inference 能作为独立模块先实现。
- 推荐清单能在用户显式启用或接受后，作为 `recommend` 推断材料；没有推荐清单存储时，Request Source Type Inference 仍然必须能运行，只是不能产生新的 `recommend` 推断。
- 推荐算法以后可以替换，不影响已经冻结的推荐清单证据。

## 已决定的边界

Request Source Type Inference 必须是独立模块。它可以放在 `playback_request_type.py` 或相邻模块中，但不应混入 watcher、VRCX importer、writer、推荐算法或普通读路径。它不要求实时运行；可以由 rebuild、repair、plan fulfillment 变更、推荐清单变更或显式维护命令触发。

推荐算法不固定。算法可以改权重、改排序、改候选来源、改随机 tie-breaker，也可以以后替换成别的策略。算法输出在用户显式启用或接受之前只是 preview/candidate，不是历史证据，也不能参与 `request_type` 推断。

推荐清单必须固定。用户显式启用或接受推荐功能时，系统要冻结当时的清单内容，形成 Recommendation List Snapshot。之后算法变化、catalog metadata 更新或用户重新生成推荐，都不能改写旧 snapshot 的内容。未来也可以把“信息已经传达给用户或被系统代为使用”的动作视为冻结动作，例如用户复制推荐清单，或未来自动点歌系统使用了推荐清单内容。

推荐清单是 `request_type` 推断材料。推断模块可以用 frozen snapshot 判断某条 Accepted Playback Record 是否来自本工具推荐，并把默认 Request Source Type 推断为 `recommend`。这不创建 playback record，不决定 accepted/excluded，也不覆盖 requester identity。

推荐清单只向后生效。snapshot 只能作用于同一个 Local Dance Day 内、snapshot 内容已经冻结之后发生的 playback。不能在舞蹈后补建或补接受推荐清单，再把已经发生的 playback 改成 `recommend`。

Dance Plan 比推荐清单更强。如果同一条 Accepted Playback Record 同时满足 Dance Plan Fulfillment 和 Recommendation List Snapshot，`planned` 胜出，`recommend` 只作为次级可解释材料保留。

## Recommendation List Snapshot 的最小语义

最终 schema 待定。第一版如果实现推荐 snapshot 存储，至少必须能保存这些语义：

- snapshot 的本地跳舞日，按 Local Dance Day Boundary 计算。
- 用户显式启用或接受推荐清单的时间。
- snapshot 冻结时间；通常可等于启用或接受时间。
- 冻结后的 item 清单，至少能稳定指向 dance track。
- 可选的算法版本、参数或生成原因，只用于解释，不参与 `request_type` 事实判断。

snapshot item 应保存足够稳定的舞蹈身份。数据库内可以引用 `dance_track_id`；任何导出、重建、修复或跨库迁移路径都应能回到 `dance_system_key + dance_external_id`，避免本地 surrogate id 失效后无法解释旧推荐证据。

多次确认推荐清单的策略待定。当前可以只保留用户最后一次确认的清单；这会让 Request Source Type Inference 只使用这份最后确认清单作为推荐证据。未来如果需要解释同一天多次确认过的推荐清单，再引入多 snapshot 历史。

## 推断规则

当一条 playback record 是 effective accepted，并且它的 `dance_track_id` 能匹配同一 Local Dance Day 的 Recommendation List Snapshot item，且 `played_at` 晚于或等于 snapshot 的冻结时间时，Request Source Type Inference 可以把它推断为 `recommend`。

如果当前数据库还没有推荐 snapshot 表，或表存在但当天没有 frozen snapshot，Request Source Type Inference 应继续运行，并把推荐证据视为空输入。此时它可以继续根据 Dance Plan Fulfillment、Requester Identity、Self User Identity、legacy/source evidence 和 Manual Record Updates 推断 `planned`、`self`、`other`、`random` 或 `unknown`，但不能凭当前算法即时结果推断 `recommend`。

以下情况不能推断为 `recommend`：

- 用户只看到了推荐 preview，但没有显式启用或接受。
- snapshot 是 playback 发生后才创建、接受或冻结的。
- snapshot 属于另一个 Local Dance Day。
- snapshot 内容没有保存，当前只能重新运行推荐算法得到相似结果。
- 更强的来源已经适用，例如 Dance Plan Fulfillment 推断出的 `planned`，或 active Manual Record Update。

重新运行推断时，必须读取 frozen snapshot，而不是重新计算当天推荐。这样 rebuild/repair 才是幂等的，算法更新也不会改写过去的 Request Source Type。

第一版 snapshot 不做物理删除和事后编辑。关闭推荐功能只影响未来推荐，不改写旧 snapshot，也不触发旧 playback 的 `request_type` 重写。推荐误判应通过 Manual Record Update 覆盖，或由后续显式 repair/rebuild 重新投影。

## 与其他模块的关系

watcher 只负责观察和保存 playback evidence，可保留 raw/coarse source label，但不负责把最终 `request_type` 判成 `recommend`。

VRCX importer 只负责导入历史 evidence 和 requester identity。它不应因为当前算法推荐了某首歌，就在导入时直接写 `recommend`。

writer 只负责写 Local Playback Evidence 和 origins。它不应内嵌推荐清单匹配规则。

推荐算法只负责生成候选和排序。它可以产生 snapshot 的内容，但 snapshot 冻结后就是推断证据，不能再由算法实时解释。

Dance Plan Fulfillment 是 `planned` 的证据来源。Recommendation List Snapshot 是 `recommend` 的证据来源。两者都是 Request Source Type Inference 的输入，但不是同一个模型。

## 暂缓事项

以下细节不阻塞第一版 Dance Plan 和 Request Source Type Inference：

- 推荐算法权重和排序公式。
- 推荐清单长度、分组和 UI 呈现。
- 用户接受推荐时的具体按钮文案。
- 同一天多次启用或接受推荐时的 UI 合并体验。
- 推荐 snapshot 的最终表名和完整 schema。
- 未来是否把推荐清单导出为 CSV 或用于分析报表。

这些事项可以后续设计，但不能改变本文的核心约束：`recommend` 必须来自用户显式启用或接受后冻结的同日推荐清单，不能由事后补推荐或当前算法即时结果倒推。
