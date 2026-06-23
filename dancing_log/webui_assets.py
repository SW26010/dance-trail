"""Static HTML/JS asset for the Local Web UI."""

from __future__ import annotations

CSRF_TOKEN_PLACEHOLDER = "__DANCING_LOG_CSRF_TOKEN__"
WEBUI_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>dancing-log</title>
<style>
:root {
  color-scheme: light;
  --bg: #f6f7f9;
  --panel: #ffffff;
  --panel-alt: #fbfbfc;
  --line: #d8dde5;
  --line-strong: #b8c0cc;
  --text: #18212f;
  --muted: #657083;
  --blue: #256fc4;
  --green: #187758;
  --orange: #a95716;
  --red: #b33131;
  --violet: #6c5a9a;
  --shadow: 0 10px 26px rgba(24, 33, 47, 0.08);
  --sidebar: #111820;
  --sidebar-text: #edf2f7;
  --sidebar-muted: #aeb8c6;
  --sidebar-hover: #182333;
  --sidebar-hover-line: #344154;
  --nav-active-bg: #eef4ff;
  --nav-active-text: #132033;
  --input-bg: #ffffff;
  --input-readonly: #eef1f5;
  --primary-text: #ffffff;
  --code-bg: #111820;
  --code-text: #e7edf6;
  --green-line: #98d6c1;
  --green-bg: #eef9f5;
  --orange-line: #e5bf96;
  --orange-bg: #fff7ed;
  --red-line: #e8abab;
  --red-bg: #fff1f1;
  --violet-line: #c9bee5;
  --violet-bg: #f7f3ff;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --bg: #0f1319;
    --panel: #171d25;
    --panel-alt: #1e2630;
    --line: #303948;
    --line-strong: #4a5668;
    --text: #e7edf4;
    --muted: #a3adbd;
    --blue: #78adf3;
    --green: #74c7a6;
    --orange: #e8a45d;
    --red: #f07b7b;
    --violet: #ada3e8;
    --shadow: 0 12px 30px rgba(0, 0, 0, 0.28);
    --sidebar: #0b1016;
    --sidebar-text: #edf2f7;
    --sidebar-muted: #9ca8b8;
    --sidebar-hover: #17202b;
    --sidebar-hover-line: #344052;
    --nav-active-bg: #d9e7ff;
    --nav-active-text: #08111d;
    --input-bg: #101820;
    --input-readonly: #202936;
    --primary-text: #08111d;
    --code-bg: #0b1016;
    --code-text: #e7edf4;
    --green-line: rgba(116, 199, 166, 0.55);
    --green-bg: rgba(30, 92, 72, 0.28);
    --orange-line: rgba(232, 164, 93, 0.58);
    --orange-bg: rgba(118, 76, 30, 0.28);
    --red-line: rgba(240, 123, 123, 0.58);
    --red-bg: rgba(117, 42, 48, 0.28);
    --violet-line: rgba(173, 163, 232, 0.58);
    --violet-bg: rgba(75, 64, 128, 0.28);
  }
}
* { box-sizing: border-box; }
html, body { margin: 0; min-height: 100%; background: var(--bg); color: var(--text); }
body { font-family: "Segoe UI", system-ui, sans-serif; font-size: 14px; letter-spacing: 0; }
button, input, select { font: inherit; letter-spacing: 0; }
button { cursor: pointer; }
.app {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 232px minmax(0, 1fr);
}
.sidebar {
  background: var(--sidebar);
  color: var(--sidebar-text);
  padding: 18px 14px;
  display: grid;
  grid-template-rows: auto 1fr auto;
  gap: 18px;
}
.brand { display: grid; gap: 3px; padding: 0 8px; }
.brand strong { font-size: 18px; font-weight: 700; }
.brand span { color: var(--sidebar-muted); font-size: 12px; }
.nav { display: grid; align-content: start; gap: 4px; }
.nav button {
  min-height: 40px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--sidebar-text);
  text-align: left;
  padding: 0 12px;
}
.nav button:hover { border-color: var(--sidebar-hover-line); background: var(--sidebar-hover); }
.nav button.active { background: var(--nav-active-bg); color: var(--nav-active-text); }
.sidebar-foot { color: var(--sidebar-muted); font-size: 12px; padding: 0 8px; overflow-wrap: anywhere; }
.main { min-width: 0; padding: 22px; display: grid; gap: 16px; align-content: start; }
.topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.title-block { min-width: 0; }
h1 { margin: 0; font-size: 24px; line-height: 1.2; }
.subtitle { margin-top: 4px; color: var(--muted); overflow-wrap: anywhere; }
.top-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}
.toolbar { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.language-switch {
  display: inline-grid;
  grid-template-columns: repeat(2, minmax(44px, auto));
  border: 1px solid var(--line-strong);
  border-radius: 7px;
  overflow: hidden;
  background: var(--panel);
}
.language-switch button {
  min-height: 34px;
  border: 0;
  border-right: 1px solid var(--line-strong);
  background: transparent;
  color: var(--muted);
  padding: 0 10px;
}
.language-switch button:last-child { border-right: 0; }
.language-switch button.active {
  background: var(--blue);
  color: var(--primary-text);
}
.button {
  min-height: 36px;
  border-radius: 7px;
  border: 1px solid var(--line-strong);
  background: var(--panel);
  color: var(--text);
  padding: 0 12px;
}
.button.primary { background: var(--blue); border-color: var(--blue); color: var(--primary-text); }
.button.danger { color: var(--red); border-color: var(--red-line); }
.button:disabled { opacity: 0.55; cursor: default; }
.view { display: none; gap: 16px; align-content: start; }
.view.active { display: grid; }
.grid { display: grid; gap: 14px; }
.summary-grid { grid-template-columns: repeat(4, minmax(150px, 1fr)); }
.two-col { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  box-shadow: var(--shadow);
  min-width: 0;
}
.panel-head {
  min-height: 48px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.panel-head h2 { margin: 0; font-size: 15px; }
.panel-body { padding: 14px; display: grid; gap: 12px; min-width: 0; }
.metric { display: grid; gap: 4px; padding: 14px; }
.metric span { color: var(--muted); font-size: 12px; }
.metric strong { font-size: 24px; line-height: 1.1; }
.status-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.status-item {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel-alt);
  padding: 10px;
  display: grid;
  gap: 8px;
}
.status-item span { color: var(--muted); font-size: 12px; }
.pill-row { display: flex; flex-wrap: wrap; gap: 6px; }
.pill {
  min-height: 24px;
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--panel-alt);
  padding: 0 9px;
  color: var(--muted);
  font-size: 12px;
}
.pill.green { color: var(--green); border-color: var(--green-line); background: var(--green-bg); }
.pill.orange { color: var(--orange); border-color: var(--orange-line); background: var(--orange-bg); }
.pill.red { color: var(--red); border-color: var(--red-line); background: var(--red-bg); }
.pill.violet { color: var(--violet); border-color: var(--violet-line); background: var(--violet-bg); }
.timeline-status { display: grid; gap: 5px; justify-items: start; }
.status-detail { color: var(--muted); font-size: 12px; }
.row-actions { display: flex; flex-wrap: wrap; gap: 6px; }
.mini-button {
  min-height: 30px;
  border-radius: 7px;
  border: 1px solid var(--line-strong);
  background: var(--panel);
  color: var(--text);
  padding: 0 9px;
  font-size: 12px;
}
.mini-button.primary { background: var(--blue); border-color: var(--blue); color: var(--primary-text); }
.mini-button.danger { color: var(--red); border-color: var(--red-line); }
.mini-button:disabled { opacity: 0.48; cursor: default; }
.settings-grid { display: grid; gap: 14px; }
.field-row {
  display: grid;
  grid-template-columns: minmax(160px, 230px) minmax(0, 1fr);
  gap: 12px;
  align-items: start;
  padding: 12px 0;
  border-bottom: 1px solid var(--line);
}
.field-row:last-child { border-bottom: 0; }
.field-label { display: grid; gap: 4px; }
.field-label strong { font-weight: 650; }
.field-label code { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.field-summary { color: var(--muted); font-size: 12px; line-height: 1.35; }
.field-control { display: grid; gap: 7px; min-width: 0; }
.input-line { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; }
.path-mode-line { grid-template-columns: auto minmax(0, 1fr) auto auto; align-items: center; }
input[type="text"], input[type="number"], input[type="date"], select {
  width: 100%;
  min-height: 36px;
  border-radius: 7px;
  border: 1px solid var(--line-strong);
  background: var(--input-bg);
  color: var(--text);
  padding: 0 10px;
}
input[type="checkbox"] { accent-color: var(--blue); }
input[readonly], input:disabled { background: var(--input-readonly); color: var(--muted); }
.toggle-line {
  min-height: 36px;
  display: inline-flex;
  align-items: center;
  gap: 9px;
}
.toggle-line input { width: 18px; height: 18px; }
.resolved { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.resolved.ok { color: var(--green); }
.resolved.missing { color: var(--orange); }
.message {
  display: none;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--panel-alt);
  padding: 10px 12px;
  color: var(--muted);
}
.message.show { display: block; }
.message.error { color: var(--red); border-color: var(--red-line); background: var(--red-bg); }
.message.success { color: var(--green); border-color: var(--green-line); background: var(--green-bg); }
.readonly-json {
  margin: 0;
  overflow: auto;
  background: var(--code-bg);
  color: var(--code-text);
  border-radius: 7px;
  padding: 12px;
  max-height: 240px;
}
table { width: 100%; border-collapse: collapse; table-layout: fixed; }
th, td {
  text-align: left;
  padding: 10px;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
  overflow-wrap: anywhere;
}
th { color: var(--muted); font-size: 12px; font-weight: 650; background: var(--panel-alt); }
tr:last-child td { border-bottom: 0; }
.empty { color: var(--muted); padding: 14px; }
.list-stack { display: grid; gap: 8px; }
.list-item {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px;
  display: grid;
  gap: 5px;
  background: var(--panel-alt);
}
.list-item strong { overflow-wrap: anywhere; }
.list-item code { color: var(--muted); overflow-wrap: anywhere; }
@media (max-width: 980px) {
  .app { grid-template-columns: 1fr; }
  .sidebar { position: sticky; top: 0; z-index: 2; grid-template-rows: auto auto; }
  .nav { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .sidebar-foot { display: none; }
  .summary-grid, .two-col, .status-grid { grid-template-columns: 1fr; }
}
@media (max-width: 680px) {
  .main { padding: 14px; }
  .topbar { align-items: stretch; flex-direction: column; }
  .top-actions { justify-content: flex-start; }
  .toolbar { justify-content: flex-start; }
  .field-row { grid-template-columns: 1fr; }
  .input-line { grid-template-columns: 1fr; }
  .nav { grid-template-columns: 1fr; }
  .timeline-table, .timeline-table thead, .timeline-table tbody, .timeline-table tr, .timeline-table th, .timeline-table td {
    display: block;
    width: 100% !important;
  }
  .timeline-table thead { display: none; }
  .timeline-table tr { border-bottom: 1px solid var(--line); }
  .timeline-table tr:last-child { border-bottom: 0; }
  .timeline-table td { border-bottom: 0; padding: 8px 10px; }
}
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar">
    <div class="brand"><strong>dancing-log</strong><span id="brand-subtitle">Local Web UI</span></div>
    <nav class="nav" id="nav"></nav>
    <div class="sidebar-foot" id="sidebar-path"></div>
  </aside>
  <main class="main">
    <div class="topbar">
      <div class="title-block">
        <h1 id="view-title">Settings</h1>
        <div class="subtitle" id="view-subtitle"></div>
      </div>
      <div class="top-actions">
        <div class="language-switch" id="language-switch" role="group" aria-label="Language"></div>
        <div class="toolbar" id="view-toolbar"></div>
      </div>
    </div>
    <section class="view" id="view-home"></section>
    <section class="view" id="view-timeline"></section>
    <section class="view" id="view-catalog"></section>
    <section class="view" id="view-lists"></section>
    <section class="view" id="view-insights"></section>
    <section class="view" id="view-operations"></section>
    <section class="view active" id="view-settings"></section>
  </main>
</div>
<script>
const LANGUAGE_KEY = "dancing-log.language";
const CSRF_TOKEN = "__DANCING_LOG_CSRF_TOKEN__";
const NAV = ["home", "timeline", "catalog", "lists", "insights", "operations", "settings"];
const TEXT = {
  en: {
    brandSubtitle: "Local Web UI",
    languageLabel: "Language",
    nav_home: "Home",
    nav_timeline: "Timeline",
    nav_catalog: "Catalog",
    nav_lists: "Lists",
    nav_insights: "Insights",
    nav_operations: "Data Operations",
    nav_settings: "Settings",
    title_home: "Home",
    subtitle_home: "Runtime status and recent activity",
    title_timeline: "Timeline",
    subtitle_timeline: "Chronological playback records",
    title_catalog: "Catalog",
    subtitle_catalog: "Dance tracks and local preferences",
    title_lists: "Lists",
    subtitle_lists: "Planned dance lists",
    title_insights: "Insights",
    subtitle_insights: "Confirmed-history summaries",
    title_operations: "Data Operations",
    subtitle_operations: "Controlled bulk workflows",
    title_settings: "Settings",
    subtitle_settings: "Saved local configuration",
    reset: "Reset",
    resetTitle: "Reload saved configuration",
    save: "Save",
    saveTitle: "Save configuration",
    browse: "Browse",
    browseTitle: "Open native {kind} picker",
    enabled: "Enabled",
    disabled: "Disabled",
    loadingConfig: "Loading configuration...",
    saved: "Saved",
    unsaved: "Unsaved",
    saveFailed: "Save failed",
    savedNull: "Saved as null",
    automatic: "Automatic",
    customPath: "Custom",
    useAsManual: "Use as manual",
    exists: "exists",
    missing: "missing",
    inaccessible: "inaccessible",
    detectedSources: "Automatic source path previews",
    defaultVrcxDb: "Standard VRCX database",
    defaultVrcLogDir: "Default VRChat log directory",
    unsupportedKeys: "Unsupported configuration keys",
    preserved: "Preserved",
    loading: "Loading...",
    danceTracks: "Dance tracks",
    playbackRecords: "Playback records",
    acceptedRecords: "Accepted",
    attentionRecords: "Needs attention",
    runtimeState: "Runtime state",
    dbFound: "DB found",
    noDb: "No DB",
    noLiveRow: "No live playback row",
    recentAccepted: "Recent accepted records",
    local: "local",
    noRecords: "No records",
    time: "Time",
    track: "Track",
    source: "Source",
    accepted: "Accepted",
    live: "Live-derived",
    load: "Load",
    noTimelineRecords: "No timeline records",
    record: "Record",
    reviewStatus: "Status",
    actions: "Actions",
    accept: "Accept",
    exclude: "Exclude",
    restoreDefault: "Restore default",
    manual: "Manual",
    defaultResult: "Default",
    reviewUpdateFailed: "Review update failed",
    status_accepted: "accepted",
    status_excluded: "excluded",
    status_needs_attention: "needs attention",
    status_pending: "pending",
    searchCatalog: "Search catalog",
    search: "Search",
    noTracks: "No tracks",
    title: "Title",
    artist: "Artist",
    preferences: "Preferences",
    favorite: "favorite",
    wantToLearn: "want to learn",
    queuedSelfManifests: "Queued-self manifests",
    found: "found",
    noManifests: "No manifests",
    sourceDistribution: "Source distribution",
    topTracks: "Top tracks",
    recommendations: "Recommendations",
    noData: "No data",
    name: "Name",
    count: "Count",
    liveStatus: "Live status",
    watcher: "Watcher",
    overlay: "Overlay",
    running: "Running",
    stopped: "Stopped",
    refresh: "Refresh",
    startWatcher: "Start watcher",
    stopWatcher: "Stop watcher",
    startOverlay: "Start overlay",
    stopOverlay: "Stop overlay",
    databaseState: "Database state",
    currentLiveRow: "Current live row",
    lastRuntimeError: "Last runtime error",
    lastWatcherStats: "Last watcher stats",
    noWatcherStats: "No watcher stats yet",
    liveControlFailed: "Live control failed",
    run: "Run",
    runningOperation: "Running...",
    operationComplete: "Complete",
    operationFailed: "Operation failed"
  },
  zh: {
    brandSubtitle: "本地 Web UI",
    languageLabel: "语言",
    nav_home: "首页",
    nav_timeline: "时间线",
    nav_catalog: "目录",
    nav_lists: "清单",
    nav_insights: "洞察",
    nav_operations: "数据操作",
    nav_settings: "设置",
    title_home: "首页",
    subtitle_home: "运行状态和最近活动",
    title_timeline: "时间线",
    subtitle_timeline: "按时间顺序查看播放记录",
    title_catalog: "目录",
    subtitle_catalog: "舞蹈条目和本地偏好",
    title_lists: "清单",
    subtitle_lists: "计划中的舞蹈清单",
    title_insights: "洞察",
    subtitle_insights: "基于已接受历史的汇总",
    title_operations: "数据操作",
    subtitle_operations: "受控的批量工作流",
    title_settings: "设置",
    subtitle_settings: "已保存的本地配置",
    reset: "重置",
    resetTitle: "重新载入已保存配置",
    save: "保存",
    saveTitle: "保存配置",
    browse: "浏览",
    browseTitle: "打开原生{kind}选择器",
    enabled: "已启用",
    disabled: "已禁用",
    loadingConfig: "正在加载配置...",
    saved: "已保存",
    unsaved: "未保存",
    saveFailed: "保存失败",
    savedNull: "保存为空值",
    automatic: "自动",
    customPath: "自定义",
    useAsManual: "设为手动路径",
    exists: "存在",
    missing: "缺失",
    inaccessible: "不可访问",
    detectedSources: "自动来源路径预览",
    defaultVrcxDb: "标准 VRCX 数据库",
    defaultVrcLogDir: "默认 VRChat 日志目录",
    unsupportedKeys: "不支持的配置键",
    preserved: "已保留",
    loading: "正在加载...",
    danceTracks: "舞蹈条目",
    playbackRecords: "播放记录",
    acceptedRecords: "已接受",
    attentionRecords: "需注意",
    runtimeState: "运行状态",
    dbFound: "数据库已找到",
    noDb: "无数据库",
    noLiveRow: "没有实时播放记录",
    recentAccepted: "最近已接受记录",
    local: "本地",
    noRecords: "没有记录",
    time: "时间",
    track: "条目",
    source: "来源",
    accepted: "已接受",
    live: "实时来源",
    load: "加载",
    noTimelineRecords: "没有时间线记录",
    record: "记录",
    reviewStatus: "状态",
    actions: "操作",
    accept: "接受",
    exclude: "排除",
    restoreDefault: "恢复默认",
    manual: "手动",
    defaultResult: "默认",
    reviewUpdateFailed: "更新审阅失败",
    status_accepted: "已接受",
    status_excluded: "已排除",
    status_needs_attention: "需注意",
    status_pending: "待定",
    searchCatalog: "搜索目录",
    search: "搜索",
    noTracks: "没有条目",
    title: "标题",
    artist: "艺人",
    preferences: "偏好",
    favorite: "收藏",
    wantToLearn: "想学",
    queuedSelfManifests: "自选队列清单",
    found: "已找到",
    noManifests: "没有清单",
    sourceDistribution: "来源分布",
    topTracks: "常跳条目",
    recommendations: "推荐",
    noData: "没有数据",
    name: "名称",
    count: "数量",
    liveStatus: "\u5b9e\u65f6\u72b6\u6001",
    watcher: "Watcher",
    overlay: "Overlay",
    running: "\u8fd0\u884c\u4e2d",
    stopped: "\u5df2\u505c\u6b62",
    refresh: "\u5237\u65b0",
    startWatcher: "\u542f\u52a8 watcher",
    stopWatcher: "\u505c\u6b62 watcher",
    startOverlay: "\u542f\u52a8 overlay",
    stopOverlay: "\u505c\u6b62 overlay",
    databaseState: "\u6570\u636e\u5e93\u72b6\u6001",
    currentLiveRow: "\u5f53\u524d\u5b9e\u65f6\u64ad\u653e\u8bb0\u5f55",
    lastRuntimeError: "\u6700\u8fd1\u8fd0\u884c\u9519\u8bef",
    lastWatcherStats: "\u6700\u8fd1 watcher \u7edf\u8ba1",
    noWatcherStats: "\u5c1a\u65e0 watcher \u7edf\u8ba1",
    liveControlFailed: "\u5b9e\u65f6\u63a7\u5236\u5931\u8d25",
    run: "执行",
    runningOperation: "执行中...",
    operationComplete: "已完成",
    operationFailed: "操作失败"
  }
};
const FIELD_TEXT = {
  config_version: { zh: { label: "配置版本", group: "系统", summary: "本地配置结构版本。" } },
  app_db: { zh: { label: "应用数据库", group: "应用内部路径", summary: "SQLite 运行状态。" } },
  queued_self_dir: { zh: { label: "自选队列目录", group: "应用内部路径", summary: "计划自选舞蹈的 Markdown 清单。" } },
  capture_dir: { zh: { label: "捕获目录", group: "应用内部路径", summary: "实时 watcher 捕获输出。" } },
  run_log_dir: { zh: { label: "运行日志目录", group: "应用内部路径", summary: "常规应用运行日志。" } },
  source_vrc_log_dir: { zh: { label: "VRChat 源日志归档", group: "应用内部路径", summary: "逐字节归档的源 output_log 文件。" } },
  recording_frames_dir: { zh: { label: "录像帧目录", group: "应用内部路径", summary: "用于分析的顶部裁剪帧样本。" } },
  self_user_id: { zh: { label: "本机 VRChat 用户 ID", group: "外部数据源", summary: "用于判断 VRCX 历史点歌人是否为自己。" } },
  vrcx_db_path: { zh: { label: "VRCX 数据库", group: "外部数据源", summary: "VRCX 播放历史 SQLite 文件。" } },
  vrc_log_dir: { zh: { label: "VRChat 日志目录", group: "外部数据源", summary: "包含 VRChat output_log 文件的目录。" } },
  wanna_cache_dir: { zh: { label: "WannaDance 缓存", group: "外部数据源", summary: "用于离线目录同步的本地 WannaDance 缓存。" } },
  recordings_dir: { zh: { label: "录像目录", group: "外部数据源", summary: "sample-frame 工具使用的录像文件。" } },
  auto_start_watcher: { zh: { label: "自动启动 watcher", group: "运行默认值", summary: "应用工作流启动实时捕获时使用的默认偏好。" } },
  auto_start_overlay: { zh: { label: "自动启动 overlay", group: "运行默认值", summary: "启用后会同步启用 watcher 自动启动。" } },
  overlay_port: { zh: { label: "Overlay 端口", group: "运行默认值", summary: "本地 OBS overlay 端口。" } }
};
const AUTOMATIC_SOURCE_PATH_KEYS = new Set(["vrcx_db_path", "vrc_log_dir"]);
const state = {
  active: "settings",
  lang: initialLanguage(),
  configSnapshot: null,
  operationsSnapshot: null,
  draft: {},
  operationDrafts: {},
  operationResults: {},
  operationErrors: {},
  runningOperation: null,
  fieldErrors: {},
  pathPreviews: {},
  previewTimers: {}
};

const brandSubtitleNode = document.getElementById("brand-subtitle");
const navNode = document.getElementById("nav");
const languageNode = document.getElementById("language-switch");
const toolbarNode = document.getElementById("view-toolbar");
const titleNode = document.getElementById("view-title");
const subtitleNode = document.getElementById("view-subtitle");
const sidebarPathNode = document.getElementById("sidebar-path");

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[char]));
}

function initialLanguage() {
  const saved = localStorage.getItem(LANGUAGE_KEY);
  if (saved === "en" || saved === "zh") return saved;
  return navigator.language && navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
}

function ui(key) {
  return TEXT[state.lang]?.[key] ?? TEXT.en[key] ?? key;
}

function navLabel(key) {
  return ui(`nav_${key}`);
}

function viewTitle(key) {
  return [ui(`title_${key}`), ui(`subtitle_${key}`)];
}

function fieldText(field, part) {
  return FIELD_TEXT[field.key]?.[state.lang]?.[part] || field[part] || "";
}

function operationText(operation, part) {
  return operation.text?.[state.lang]?.[part] || operation[part] || "";
}

function pickerKind(kind) {
  if (state.lang !== "zh") return kind;
  return kind === "directory" ? "文件夹" : "文件";
}

function pathStatusLabel(resolved) {
  if (resolved.error) return ui("inaccessible");
  return resolved.exists ? ui("exists") : ui("missing");
}

function reviewStatusLabel(value) {
  const key = `status_${String(value || "").replaceAll(" ", "_")}`;
  return ui(key);
}

function reviewStatusClass(value) {
  if (value === "accepted") return "green";
  if (value === "excluded") return "red";
  if (value === "pending") return "blue";
  return "orange";
}

function translatedError(message) {
  if (state.lang !== "zh") return message;
  if (message === "path is required") return "路径不能为空";
  if (message === "value must be true or false") return "值必须为 true 或 false";
  if (message === "value must be an integer") return "值必须是整数";
  const range = String(message || "").match(/^value must be between (\d+) and (\d+)$/);
  if (range) return `值必须在 ${range[1]} 到 ${range[2]} 之间`;
  return message;
}

function api(path, options = {}) {
  const init = { ...options };
  init.headers = { ...(options.headers || {}) };
  if (init.body && typeof init.body !== "string") {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(init.body);
  }
  if ((init.method || "GET").toUpperCase() !== "GET") {
    init.headers["X-Dancing-Log-CSRF"] = CSRF_TOKEN;
  }
  return fetch(path, init).then(async response => {
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.error || "request failed");
      error.data = data;
      throw error;
    }
    return data;
  });
}

function setView(next) {
  state.active = next;
  for (const key of NAV) {
    document.getElementById(`view-${key}`).classList.toggle("active", key === next);
  }
  for (const button of navNode.querySelectorAll("button")) {
    button.classList.toggle("active", button.dataset.view === next);
  }
  const [title, subtitle] = viewTitle(next);
  titleNode.textContent = title;
  subtitleNode.textContent = subtitle;
  toolbarNode.innerHTML = "";
  renderActive();
}

function renderNav() {
  navNode.innerHTML = NAV.map(key => `
    <button type="button" data-view="${key}" class="${key === state.active ? "active" : ""}">${esc(navLabel(key))}</button>
  `).join("");
  for (const button of navNode.querySelectorAll("button[data-view]")) {
    button.onclick = () => setView(button.dataset.view);
  }
}

function renderLanguageSwitch() {
  document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
  brandSubtitleNode.textContent = ui("brandSubtitle");
  languageNode.setAttribute("aria-label", ui("languageLabel"));
  languageNode.innerHTML = `
    <button type="button" data-lang="en" class="${state.lang === "en" ? "active" : ""}" aria-pressed="${state.lang === "en"}">EN</button>
    <button type="button" data-lang="zh" class="${state.lang === "zh" ? "active" : ""}" aria-pressed="${state.lang === "zh"}">中文</button>
  `;
  for (const button of languageNode.querySelectorAll("button[data-lang]")) {
    button.onclick = () => setLanguage(button.dataset.lang);
  }
}

function setLanguage(lang) {
  if (lang !== "en" && lang !== "zh") return;
  state.lang = lang;
  localStorage.setItem(LANGUAGE_KEY, lang);
  renderLanguageSwitch();
  renderNav();
  const [title, subtitle] = viewTitle(state.active);
  titleNode.textContent = title;
  subtitleNode.textContent = subtitle;
  renderActive();
}

function showMessage(id, message, kind = "") {
  const node = document.getElementById(id);
  if (!node) return;
  node.textContent = message || "";
  node.className = `message ${message ? "show" : ""} ${kind}`;
}

function renderActive() {
  if (state.active === "settings") return renderSettings();
  if (state.active === "home") return renderHome();
  if (state.active === "timeline") return renderTimeline();
  if (state.active === "catalog") return renderCatalog();
  if (state.active === "lists") return renderLists();
  if (state.active === "insights") return renderInsights();
  if (state.active === "operations") return renderOperations();
}

async function loadConfig() {
  const snapshot = await api("/api/config");
  state.configSnapshot = snapshot;
  state.draft = { ...snapshot.config };
  state.fieldErrors = {};
  updatePathPreviewsFromSnapshot(snapshot);
  sidebarPathNode.textContent = snapshot.config_path;
}

function updatePathPreviewsFromSnapshot(snapshot) {
  state.pathPreviews = {};
  for (const field of snapshot.fields || []) {
    if (field.path) state.pathPreviews[field.key] = field.path;
  }
}

function groupedFields(fields) {
  const groups = [];
  for (const field of fields) {
    const groupName = fieldText(field, "group");
    let group = groups.find(item => item.name === groupName);
    if (!group) {
      group = { name: groupName, fields: [] };
      groups.push(group);
    }
    group.fields.push(field);
  }
  return groups;
}

function renderSettings() {
  toolbarNode.innerHTML = `
    <button class="button" type="button" id="settings-reset" title="${esc(ui("resetTitle"))}">${esc(ui("reset"))}</button>
    <button class="button primary" type="button" id="settings-save" title="${esc(ui("saveTitle"))}">${esc(ui("save"))}</button>
  `;
  const node = document.getElementById("view-settings");
  if (!state.configSnapshot) {
    node.innerHTML = `<div class="panel"><div class="empty">${esc(ui("loadingConfig"))}</div></div>`;
    loadConfig().then(renderSettings).catch(error => {
      node.innerHTML = `<div class="message show error">${esc(error.message)}</div>`;
    });
    return;
  }
  const snapshot = state.configSnapshot;
  const groups = groupedFields(snapshot.fields);
  node.innerHTML = `
    <div class="message" id="settings-message"></div>
    <div class="settings-grid">
      ${groups.map(group => renderSettingsGroup(group)).join("")}
      ${renderDetectedSources(snapshot.detected_sources || [])}
      ${renderUnsupported(snapshot.unsupported || {})}
    </div>
  `;
  document.getElementById("settings-save").onclick = saveSettings;
  document.getElementById("settings-reset").onclick = () => {
    state.configSnapshot = null;
    renderSettings();
  };
  bindFieldControls();
}

function renderSettingsGroup(group) {
  return `
    <section class="panel">
      <div class="panel-head"><h2>${esc(group.name)}</h2></div>
      <div class="panel-body">
        ${group.fields.map(renderField).join("")}
      </div>
    </section>
  `;
}

function renderField(field) {
  const key = field.key;
  const value = state.draft[key];
  const error = state.fieldErrors[key];
  return `
    <div class="field-row" data-field="${esc(key)}">
      <div class="field-label">
        <strong>${esc(fieldText(field, "label"))}</strong>
        <code>${esc(key)}</code>
        <span class="field-summary">${esc(fieldText(field, "summary"))}</span>
      </div>
      <div class="field-control">
        ${renderFieldControl(field, value)}
        ${field.path ? renderPathPreview(field) : ""}
        ${error ? `<span class="resolved missing">${esc(translatedError(error))}</span>` : ""}
      </div>
    </div>
  `;
}

function renderFieldControl(field, value) {
  if (field.type === "readonly") {
    return `<input type="text" readonly value="${esc(value)}">`;
  }
  if (field.type === "boolean") {
    return `
      <label class="toggle-line">
        <input type="checkbox" data-key="${esc(field.key)}" ${value ? "checked" : ""}>
        <span>${value ? esc(ui("enabled")) : esc(ui("disabled"))}</span>
      </label>
    `;
  }
  if (field.type === "integer") {
    return `
      <input type="number" data-key="${esc(field.key)}" min="${esc(field.min)}" max="${esc(field.max)}" value="${esc(value)}">
    `;
  }
  if (field.type === "path") {
    if (isAutomaticSourcePath(field.key)) {
      return renderAutomaticSourcePathControl(field, value);
    }
    return `
      <div class="input-line">
        <input type="text" data-key="${esc(field.key)}" placeholder="${field.required ? "" : "null"}" value="${esc(value ?? "")}">
        <button class="button" type="button" data-pick="${esc(field.key)}" title="${esc(ui("browseTitle").replace("{kind}", pickerKind(field.picker)))}">${esc(ui("browse"))}</button>
      </div>
    `;
  }
  return `<input type="text" data-key="${esc(field.key)}" placeholder="${esc(field.placeholder || "")}" value="${esc(value ?? "")}">`;
}

function isAutomaticSourcePath(key) {
  return AUTOMATIC_SOURCE_PATH_KEYS.has(key);
}

function isCustomPathEnabled(key) {
  const value = state.draft[key];
  return value !== null && value !== "";
}

function renderAutomaticSourcePathControl(field, value) {
  const custom = isCustomPathEnabled(field.key);
  const automatic = automaticSourceForField(field.key);
  const displayValue = custom ? value : (automatic?.value || "");
  return `
    <div class="input-line path-mode-line">
      <label class="toggle-line">
        <input type="checkbox" data-path-custom="${esc(field.key)}" ${custom ? "checked" : ""}>
        <span>${esc(ui("customPath"))}</span>
      </label>
      <input type="text" data-key="${esc(field.key)}" placeholder="${custom ? "" : esc(ui("automatic"))}" value="${esc(displayValue ?? "")}" ${custom ? "" : "disabled"}>
      <button class="button" type="button" data-pick="${esc(field.key)}" title="${esc(ui("browseTitle").replace("{kind}", pickerKind(field.picker)))}" ${custom ? "" : "disabled"}>${esc(ui("browse"))}</button>
      ${renderFieldSaveStatus(field.key)}
    </div>
  `;
}

function normalizeDraftValue(value) {
  return value === "" ? null : value;
}

function fieldStatusId(key) {
  return `field-status-${String(key).replace(/[^a-zA-Z0-9_-]/g, "_")}`;
}

function isFieldDirty(key) {
  return normalizeDraftValue(state.draft[key]) !== normalizeDraftValue(state.configSnapshot?.config?.[key]);
}

function renderFieldSaveStatus(key) {
  const dirty = isFieldDirty(key);
  return `<span id="${fieldStatusId(key)}" class="pill ${dirty ? "orange" : "green"}">${esc(ui(dirty ? "unsaved" : "saved"))}</span>`;
}

function updateFieldStatusNode(key) {
  const node = document.getElementById(fieldStatusId(key));
  if (!node) return;
  node.outerHTML = renderFieldSaveStatus(key);
}

function renderPathPreview(field) {
  const rawValue = state.draft[field.key];
  const preview = state.pathPreviews[field.key] || field.path || {};
  if (isAutomaticSourcePath(field.key) && !isCustomPathEnabled(field.key)) {
    const automatic = automaticSourceForField(field.key);
    if (automatic) {
      const cls = automatic.exists ? "ok" : "missing";
      const suffix = pathStatusLabel(automatic);
      return `<span id="${pathPreviewId(field.key)}" class="resolved ${cls}">${esc(ui("automatic"))}: ${esc(automatic.value)} (${esc(suffix)})</span>`;
    }
    return `<span id="${pathPreviewId(field.key)}" class="resolved missing">${esc(ui("automatic"))}: ${esc(ui("missing"))}</span>`;
  }
  if ((rawValue === null || rawValue === "") && !field.required) {
    return `<span id="${pathPreviewId(field.key)}" class="resolved">${esc(ui("savedNull"))}</span>`;
  }
  if (!preview.resolved) {
    return `<span id="${pathPreviewId(field.key)}" class="resolved">${esc(ui("savedNull"))}</span>`;
  }
  const cls = preview.exists ? "ok" : "missing";
  const suffix = pathStatusLabel(preview);
  return `<span id="${pathPreviewId(field.key)}" class="resolved ${cls}">${esc(preview.resolved)} (${esc(suffix)})</span>`;
}

function automaticSourceForField(key) {
  return (state.configSnapshot?.detected_sources || []).find(candidate => candidate.field === key) || null;
}

function pathPreviewId(key) {
  return `path-preview-${String(key).replace(/[^a-zA-Z0-9_-]/g, "_")}`;
}

function updatePathPreviewNode(key) {
  const node = document.getElementById(pathPreviewId(key));
  const field = state.configSnapshot?.fields?.find(item => item.key === key);
  if (!node || !field) return;
  node.outerHTML = renderPathPreview(field);
}

function schedulePathPreview(key, value) {
  const field = state.configSnapshot?.fields?.find(item => item.key === key);
  if (!field || field.type !== "path") return;
  clearTimeout(state.previewTimers[key]);
  if ((value === null || value === "") && !field.required) {
    state.pathPreviews[key] = { resolved: null, exists: null };
    updatePathPreviewNode(key);
    return;
  }
  const requestedValue = value;
  state.previewTimers[key] = setTimeout(async () => {
    try {
      const result = await api("/api/resolve-path", {
        method: "POST",
        body: { field: key, current_value: requestedValue }
      });
      if (state.draft[key] !== requestedValue) return;
      state.pathPreviews[key] = result.path || {};
      updatePathPreviewNode(key);
    } catch (error) {
      if (state.draft[key] !== requestedValue) return;
      state.pathPreviews[key] = {
        resolved: String(requestedValue ?? ""),
        exists: false,
        kind: "inaccessible",
        error: error.message
      };
      updatePathPreviewNode(key);
    }
  }, 250);
}

function renderDetectedSources(candidates) {
  const externalCandidates = candidates.filter(candidate => !isAutomaticSourcePath(candidate.field));
  if (!externalCandidates.length) return "";
  return `
    <section class="panel">
      <div class="panel-head"><h2>${esc(ui("detectedSources"))}</h2></div>
      <div class="panel-body">
        <div class="pill-row">
          ${externalCandidates.map(renderDetectedSourceCandidate).join("")}
        </div>
      </div>
    </section>
  `;
}

function renderDetectedSourceCandidate(candidate) {
  const label = `${detectedSourceLabel(candidate)} ${candidate.exists ? "" : `(${ui(candidate.error ? "inaccessible" : "missing")})`}`;
  if (!candidate.exists) {
    return `<span class="pill orange" title="${esc(candidate.value)}">${esc(label)}</span>`;
  }
  return `
    <button class="button" type="button" data-use-detected="${esc(candidate.field)}" data-value="${esc(candidate.value)}" title="${esc(candidate.value)}">
      ${esc(ui("useAsManual"))}: ${esc(label)}
    </button>
  `;
}

function detectedSourceLabel(candidate) {
  if (candidate.field === "vrcx_db_path") return ui("defaultVrcxDb");
  if (candidate.field === "vrc_log_dir") return ui("defaultVrcLogDir");
  return candidate.label;
}

function renderUnsupported(unsupported) {
  const keys = Object.keys(unsupported);
  if (!keys.length) return "";
  return `
    <section class="panel">
      <div class="panel-head"><h2>${esc(ui("unsupportedKeys"))}</h2><span class="pill orange">${esc(ui("preserved"))}</span></div>
      <div class="panel-body">
        <pre class="readonly-json">${esc(JSON.stringify(unsupported, null, 2))}</pre>
      </div>
    </section>
  `;
}

function bindFieldControls() {
  for (const control of document.querySelectorAll("[data-key]")) {
    control.oninput = () => updateDraftFromControl(control, false);
    control.onchange = () => updateDraftFromControl(control, control.type === "checkbox");
  }
  for (const control of document.querySelectorAll("[data-path-custom]")) {
    control.onchange = () => updatePathCustomToggle(control);
  }
  for (const button of document.querySelectorAll("[data-pick]")) {
    button.onclick = () => pickPath(button.dataset.pick);
  }
  for (const button of document.querySelectorAll("[data-use-detected]")) {
    button.onclick = () => {
      state.draft[button.dataset.useDetected] = button.dataset.value;
      schedulePathPreview(button.dataset.useDetected, button.dataset.value);
      renderSettings();
    };
  }
}

function updatePathCustomToggle(control) {
  const key = control.dataset.pathCustom;
  if (!key) return;
  if (control.checked) {
    const automatic = automaticSourceForField(key);
    state.draft[key] = state.draft[key] || automatic?.value || "";
    schedulePathPreview(key, state.draft[key]);
  } else {
    state.draft[key] = null;
    state.pathPreviews[key] = { resolved: null, exists: null };
  }
  renderSettings();
}

function updateDraftFromControl(control, redraw) {
  const key = control.dataset.key;
  const field = state.configSnapshot.fields.find(item => item.key === key);
  if (control.type === "checkbox") {
    state.draft[key] = control.checked;
    if (key === "auto_start_overlay" && control.checked) state.draft.auto_start_watcher = true;
  } else if (control.type === "number") {
    state.draft[key] = Number(control.value);
  } else {
    const text = control.value;
    state.draft[key] = field && !field.required && text.trim() === "" ? null : text;
  }
  if (field?.type === "path") schedulePathPreview(key, state.draft[key]);
  if (field?.type === "path" && isAutomaticSourcePath(key)) updateFieldStatusNode(key);
  if (redraw) renderSettings();
}

async function pickPath(key) {
  showMessage("settings-message", "");
  try {
    const result = await api("/api/pick-path", {
      method: "POST",
      body: { field: key, current_value: state.draft[key] }
    });
    if (result.cancelled) return;
    state.draft[key] = result.value;
    schedulePathPreview(key, result.value);
    renderSettings();
  } catch (error) {
    showMessage("settings-message", error.message, "error");
  }
}

async function saveSettings() {
  showMessage("settings-message", "");
  state.fieldErrors = {};
  try {
    const result = await api("/api/config", {
      method: "POST",
      body: { config: state.draft }
    });
    state.configSnapshot = result.snapshot;
    state.draft = { ...result.snapshot.config };
    updatePathPreviewsFromSnapshot(result.snapshot);
    renderSettings();
    showMessage("settings-message", ui("saved"), "success");
  } catch (error) {
    if (error.data && error.data.errors) state.fieldErrors = error.data.errors;
    if (error.data && error.data.snapshot) state.configSnapshot = error.data.snapshot;
    renderSettings();
    showMessage("settings-message", ui("saveFailed"), "error");
  }
}

async function renderHome() {
  const node = document.getElementById("view-home");
  node.innerHTML = `<div class="panel"><div class="empty">${esc(ui("loading"))}</div></div>`;
  const data = await api("/api/summary").catch(error => ({ error: error.message, counts: {}, recent: [] }));
  if (state.active !== "home") return;
  toolbarNode.innerHTML = renderHomeToolbar(data.session || {});
  node.innerHTML = `
    <div class="message" id="home-message"></div>
    <div class="grid summary-grid">
      ${metric(ui("danceTracks"), data.counts?.dance_tracks ?? 0, "blue")}
      ${metric(ui("playbackRecords"), data.counts?.playback_records ?? 0, "green")}
      ${metric(ui("acceptedRecords"), data.counts?.accepted_playback_records ?? 0, "blue")}
      ${metric(ui("attentionRecords"), data.counts?.needs_attention_playback_records ?? 0, "orange")}
    </div>
    <div class="grid two-col">
      ${renderLiveStatus(data.session || {})}
      <section class="panel">
        <div class="panel-head"><h2>${esc(ui("currentLiveRow"))}</h2></div>
        <div class="panel-body">
          ${data.current_live ? `<pre class="readonly-json">${esc(JSON.stringify(data.current_live, null, 2))}</pre>` : `<div class="empty">${esc(ui("noLiveRow"))}</div>`}
        </div>
      </section>
    </div>
    <div class="grid two-col">
      <section class="panel">
        <div class="panel-head"><h2>${esc(ui("databaseState"))}</h2>${data.database_exists ? `<span class="pill green">${esc(ui("dbFound"))}</span>` : `<span class="pill orange">${esc(ui("noDb"))}</span>`}</div>
        <div class="panel-body">
          <div class="resolved">${esc(data.database_path || "")}</div>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>${esc(ui("recentAccepted"))}</h2></div>
        <div class="panel-body">${renderRecent(data.recent || [])}</div>
      </section>
    </div>
  `;
  bindHomeControls();
}

function renderHomeToolbar(session) {
  const watcherRunning = Boolean(session.watcher_running);
  const overlayRunning = Boolean(session.overlay_running);
  return `
    <button class="button" type="button" id="home-refresh">${esc(ui("refresh"))}</button>
    <button class="button ${watcherRunning ? "danger" : "primary"}" type="button" data-live-control="watcher" data-live-action="${watcherRunning ? "stop" : "start"}">
      ${esc(ui(watcherRunning ? "stopWatcher" : "startWatcher"))}
    </button>
    <button class="button ${overlayRunning ? "danger" : "primary"}" type="button" data-live-control="overlay" data-live-action="${overlayRunning ? "stop" : "start"}">
      ${esc(ui(overlayRunning ? "stopOverlay" : "startOverlay"))}
    </button>
  `;
}

function bindHomeControls() {
  const refresh = document.getElementById("home-refresh");
  if (refresh) refresh.onclick = renderHome;
  for (const button of document.querySelectorAll("[data-live-control]")) {
    button.onclick = () => controlLive(button.dataset.liveControl, button.dataset.liveAction);
  }
}

async function controlLive(kind, action) {
  const controls = [...document.querySelectorAll("[data-live-control], #home-refresh")];
  for (const control of controls) control.disabled = true;
  showMessage("home-message", "");
  try {
    await api(`/api/live/${kind}`, {
      method: "POST",
      body: { action }
    });
    await renderHome();
  } catch (error) {
    showMessage("home-message", `${ui("liveControlFailed")}: ${error.message}`, "error");
  } finally {
    for (const control of controls) control.disabled = false;
  }
}

function renderLiveStatus(session) {
  const stats = session.last_watcher_stats;
  return `
    <section class="panel">
      <div class="panel-head"><h2>${esc(ui("liveStatus"))}</h2></div>
      <div class="panel-body">
        <div class="status-grid">
          ${statusItem(ui("watcher"), Boolean(session.watcher_running))}
          ${statusItem(ui("overlay"), Boolean(session.overlay_running))}
        </div>
        ${session.last_error ? `<div class="message show error"><strong>${esc(ui("lastRuntimeError"))}</strong><br>${esc(session.last_error)}</div>` : ""}
        ${stats ? `<div><div class="resolved">${esc(ui("lastWatcherStats"))}</div><pre class="readonly-json">${esc(JSON.stringify(stats, null, 2))}</pre></div>` : `<div class="empty">${esc(ui("noWatcherStats"))}</div>`}
      </div>
    </section>
  `;
}

function statusItem(label, running) {
  return `
    <div class="status-item">
      <span>${esc(label)}</span>
      <strong><span class="pill ${running ? "green" : "orange"}">${esc(ui(running ? "running" : "stopped"))}</span></strong>
    </div>
  `;
}

function metric(label, value, color) {
  return `<section class="panel metric"><span>${esc(label)}</span><strong>${esc(value)}</strong><div class="pill-row"><span class="pill ${color}">${esc(ui("local"))}</span></div></section>`;
}

function renderRecent(rows) {
  if (!rows.length) return `<div class="empty">${esc(ui("noRecords"))}</div>`;
  return `<table><thead><tr><th>${esc(ui("time"))}</th><th>${esc(ui("track"))}</th><th>${esc(ui("source"))}</th></tr></thead><tbody>
    ${rows.map(row => `<tr><td>${esc(row.played_at)}</td><td>${esc(row.video_name || row.title || row.external_id || "")}</td><td>${esc(row.source || "")}</td></tr>`).join("")}
  </tbody></table>`;
}

async function renderTimeline() {
  toolbarNode.innerHTML = `
    <input type="date" id="timeline-date" value="${new Date().toISOString().slice(0, 10)}">
    <button class="button" type="button" id="timeline-load">${esc(ui("load"))}</button>
  `;
  const node = document.getElementById("view-timeline");
  async function load() {
    const selectedDate = document.getElementById("timeline-date").value;
    const data = await api(`/api/timeline?date=${encodeURIComponent(selectedDate)}`);
    node.innerHTML = `
      <div class="message" id="timeline-message"></div>
      <section class="panel"><div class="panel-body">${renderTimelineRows(data.records || [])}</div></section>
    `;
    bindTimelineActions(node, load);
  }
  document.getElementById("timeline-load").onclick = load;
  await load();
}

function renderTimelineRows(rows) {
  if (!rows.length) return `<div class="empty">${esc(ui("noTimelineRecords"))}</div>`;
  return `<table class="timeline-table"><thead><tr><th style="width:110px">${esc(ui("time"))}</th><th>${esc(ui("record"))}</th><th style="width:170px">${esc(ui("reviewStatus"))}</th><th style="width:240px">${esc(ui("actions"))}</th></tr></thead><tbody>
    ${rows.map(row => `<tr><td>${esc(row.time)}</td><td>${esc(row.display)}</td><td>${renderTimelineStatus(row)}</td><td>${renderTimelineActions(row)}</td></tr>`).join("")}
  </tbody></table>`;
}

function renderTimelineStatus(row) {
  const status = row.review_status || row.effective_playback_status || "";
  const defaultStatus = row.default_playback_status || status;
  const manualStatus = row.manual_decision_status || "";
  const detail = `${ui("manual")} · ${ui("defaultResult")}: ${reviewStatusLabel(defaultStatus)}`;
  return `
    <div class="timeline-status">
      <span class="pill ${reviewStatusClass(status)}">${esc(reviewStatusLabel(status))}</span>
      ${manualStatus ? `<span class="status-detail">${esc(detail)}</span>` : ""}
    </div>
  `;
}

function renderTimelineActions(row) {
  const status = row.review_status || row.effective_playback_status || "";
  const hasManual = Boolean(row.manual_decision_status);
  return `
    <div class="row-actions">
      <button class="mini-button primary" type="button" data-playback-action="accept" data-playback-id="${esc(row.id)}" ${status === "accepted" ? "disabled" : ""}>${esc(ui("accept"))}</button>
      <button class="mini-button danger" type="button" data-playback-action="exclude" data-playback-id="${esc(row.id)}" ${status === "excluded" ? "disabled" : ""}>${esc(ui("exclude"))}</button>
      <button class="mini-button" type="button" data-playback-action="restore_default" data-playback-id="${esc(row.id)}" ${hasManual ? "" : "disabled"}>${esc(ui("restoreDefault"))}</button>
    </div>
  `;
}

function bindTimelineActions(container, reload) {
  for (const button of container.querySelectorAll("[data-playback-action]")) {
    button.onclick = async () => {
      const playbackRecordId = Number(button.dataset.playbackId);
      const action = button.dataset.playbackAction;
      button.disabled = true;
      try {
        await api("/api/playback-review", {
          method: "POST",
          body: { playback_record_id: playbackRecordId, action }
        });
        await reload();
      } catch (error) {
        showMessage("timeline-message", `${ui("reviewUpdateFailed")}: ${translatedError(error.message)}`, "error");
        button.disabled = false;
      }
    };
  }
}

async function renderCatalog() {
  toolbarNode.innerHTML = `
    <input type="text" id="catalog-search" placeholder="${esc(ui("searchCatalog"))}">
    <button class="button" type="button" id="catalog-load">${esc(ui("search"))}</button>
  `;
  const node = document.getElementById("view-catalog");
  async function load() {
    const q = document.getElementById("catalog-search").value;
    const data = await api(`/api/catalog?q=${encodeURIComponent(q)}&limit=100`);
    node.innerHTML = `<section class="panel"><div class="panel-body">${renderCatalogRows(data.tracks || [])}</div></section>`;
  }
  document.getElementById("catalog-load").onclick = load;
  await load();
}

function renderCatalogRows(rows) {
  if (!rows.length) return `<div class="empty">${esc(ui("noTracks"))}</div>`;
  return `<table><thead><tr><th style="width:130px">${esc(ui("track"))}</th><th>${esc(ui("title"))}</th><th>${esc(ui("artist"))}</th><th style="width:150px">${esc(ui("preferences"))}</th></tr></thead><tbody>
    ${rows.map(row => `<tr>
      <td>${esc(row.system_key)}:${esc(row.external_id)}</td>
      <td>${esc(row.title || "")}</td>
      <td>${esc(row.artist || "")}</td>
      <td><div class="pill-row">${row.favorite ? `<span class="pill green">${esc(ui("favorite"))}</span>` : ''}${row.want_to_learn ? `<span class="pill violet">${esc(ui("wantToLearn"))}</span>` : ''}</div></td>
    </tr>`).join("")}
  </tbody></table>`;
}

async function renderLists() {
  const node = document.getElementById("view-lists");
  const data = await api("/api/lists");
  node.innerHTML = `
    <section class="panel">
      <div class="panel-head"><h2>${esc(ui("queuedSelfManifests"))}</h2>${data.exists ? `<span class="pill green">${esc(ui("found"))}</span>` : `<span class="pill orange">${esc(ui("missing"))}</span>`}</div>
      <div class="panel-body">
        <div class="resolved">${esc(data.queued_self_dir)}</div>
        ${renderManifests(data.manifests || [])}
      </div>
    </section>
  `;
}

function renderManifests(rows) {
  if (!rows.length) return `<div class="empty">${esc(ui("noManifests"))}</div>`;
  return `<div class="list-stack">${rows.map(row => `
    <div class="list-item">
      <strong>${esc(row.name)}</strong>
      <code>${esc(row.path)}</code>
      ${(row.preview || []).map(line => `<span>${esc(line)}</span>`).join("")}
    </div>
  `).join("")}</div>`;
}

async function renderInsights() {
  const node = document.getElementById("view-insights");
  const data = await api("/api/insights");
  node.innerHTML = `
    <div class="grid two-col">
      <section class="panel"><div class="panel-head"><h2>${esc(ui("sourceDistribution"))}</h2></div><div class="panel-body">${renderKeyCount(data.source_distribution || [], "source")}</div></section>
      <section class="panel"><div class="panel-head"><h2>${esc(ui("topTracks"))}</h2></div><div class="panel-body">${renderKeyCount(data.top_tracks || [], "title")}</div></section>
    </div>
    <section class="panel"><div class="panel-head"><h2>${esc(ui("recommendations"))}</h2></div><div class="panel-body">${renderCatalogRows(data.recommendations || [])}</div></section>
  `;
}

function renderKeyCount(rows, key) {
  if (!rows.length) return `<div class="empty">${esc(ui("noData"))}</div>`;
  return `<table><thead><tr><th>${esc(ui("name"))}</th><th style="width:90px">${esc(ui("count"))}</th></tr></thead><tbody>
    ${rows.map(row => `<tr><td>${esc(row[key] || row.external_id || "(none)")}</td><td>${esc(row.count || 0)}</td></tr>`).join("")}
  </tbody></table>`;
}

async function renderOperations() {
  const node = document.getElementById("view-operations");
  if (!state.operationsSnapshot) {
    node.innerHTML = `<div class="panel"><div class="empty">${esc(ui("loading"))}</div></div>`;
    api("/api/operations").then(data => {
      state.operationsSnapshot = data;
      renderOperations();
    }).catch(error => {
      node.innerHTML = `<div class="message show error">${esc(error.message)}</div>`;
    });
    return;
  }
  const operations = state.operationsSnapshot.operations || [];
  node.innerHTML = `<div class="list-stack">${operations.map(renderOperationPanel).join("")}</div>`;
  bindOperationControls(operations);
}

function renderOperationPanel(operation) {
  ensureOperationDraft(operation);
  const result = state.operationResults[operation.key];
  const error = state.operationErrors[operation.key];
  const running = state.runningOperation === operation.key;
  return `
    <section class="panel">
      <div class="panel-head">
        <h2>${esc(operationText(operation, "title"))}</h2>
        <span class="pill orange">${esc(operationText(operation, "risk"))}</span>
      </div>
      <div class="panel-body">
        <code>${esc(operation.command)}</code>
        <div class="settings-grid">
          ${renderOperationParameters(operation)}
        </div>
        <div class="toolbar">
          <button class="button primary" type="button" data-run-operation="${esc(operation.key)}" ${state.runningOperation ? "disabled" : ""}>${esc(running ? ui("runningOperation") : ui("run"))}</button>
        </div>
        ${error ? `<div class="message show error"><strong>${esc(ui("operationFailed"))}</strong><br>${esc(error)}</div>` : ""}
        ${result ? renderOperationResult(result) : ""}
      </div>
    </section>
  `;
}

function renderOperationParameters(operation) {
  if (!operation.parameters || !operation.parameters.length) return "";
  return operation.parameters.map(parameter => renderOperationParameter(operation, parameter)).join("");
}

function renderOperationParameter(operation, parameter) {
  return `
    <div class="field-row">
      <div class="field-label">
        <strong>${esc(parameter.label)}</strong>
        <code>${esc(parameter.key)}</code>
        <span class="field-summary">${esc(parameter.summary)}</span>
      </div>
      <div class="field-control">
        ${renderOperationParameterControl(operation, parameter)}
      </div>
    </div>
  `;
}

function renderOperationParameterControl(operation, parameter) {
  const value = state.operationDrafts[operation.key]?.[parameter.key];
  const dataAttrs = `data-operation-key="${esc(operation.key)}" data-param-key="${esc(parameter.key)}"`;
  if (parameter.type === "boolean") {
    return `
      <label class="toggle-line">
        <input type="checkbox" ${dataAttrs} ${value ? "checked" : ""}>
        <span>${value ? esc(ui("enabled")) : esc(ui("disabled"))}</span>
      </label>
    `;
  }
  if (parameter.type === "integer") {
    return `<input type="number" ${dataAttrs} value="${esc(value ?? "")}">`;
  }
  if (parameter.type === "choice") {
    return `
      <select ${dataAttrs}>
        ${(parameter.choices || []).map(choice => `<option value="${esc(choice)}" ${choice === value ? "selected" : ""}>${esc(choice)}</option>`).join("")}
      </select>
    `;
  }
  return `<input type="text" ${dataAttrs} value="${esc(value ?? "")}">`;
}

function renderOperationResult(result) {
  return `
    <div class="message show success"><strong>${esc(ui("operationComplete"))}</strong><br>${esc(result.summary || "")}</div>
    <pre class="readonly-json">${esc((result.lines || []).join("\n"))}</pre>
  `;
}

function ensureOperationDraft(operation) {
  if (state.operationDrafts[operation.key]) return;
  const draft = {};
  for (const parameter of operation.parameters || []) {
    if (parameter.type === "boolean") {
      draft[parameter.key] = Boolean(parameter.default);
    } else if (parameter.default !== null && parameter.default !== undefined) {
      draft[parameter.key] = parameter.default;
    } else {
      draft[parameter.key] = "";
    }
  }
  state.operationDrafts[operation.key] = draft;
}

function bindOperationControls(operations) {
  for (const control of document.querySelectorAll("[data-operation-key][data-param-key]")) {
    control.oninput = () => updateOperationDraft(control);
    control.onchange = () => {
      updateOperationDraft(control);
      renderOperations();
    };
  }
  for (const button of document.querySelectorAll("[data-run-operation]")) {
    button.onclick = () => runOperation(button.dataset.runOperation, operations);
  }
}

function updateOperationDraft(control) {
  const operationKey = control.dataset.operationKey;
  const paramKey = control.dataset.paramKey;
  const operation = (state.operationsSnapshot?.operations || []).find(item => item.key === operationKey);
  const parameter = operation?.parameters?.find(item => item.key === paramKey);
  if (!operation || !parameter) return;
  ensureOperationDraft(operation);
  if (parameter.type === "boolean") {
    state.operationDrafts[operationKey][paramKey] = control.checked;
  } else {
    state.operationDrafts[operationKey][paramKey] = control.value;
  }
}

function operationPayload(operation) {
  ensureOperationDraft(operation);
  const draft = state.operationDrafts[operation.key] || {};
  const parameters = {};
  for (const parameter of operation.parameters || []) {
    const value = draft[parameter.key];
    if (parameter.type === "boolean") {
      parameters[parameter.key] = Boolean(value);
    } else if (value !== "" && value !== null && value !== undefined) {
      parameters[parameter.key] = value;
    }
  }
  return { operation: operation.key, parameters };
}

async function runOperation(key, operations) {
  const operation = operations.find(item => item.key === key);
  if (!operation || state.runningOperation) return;
  state.runningOperation = key;
  state.operationErrors[key] = "";
  state.operationResults[key] = null;
  renderOperations();
  try {
    const response = await api("/api/operations/run", {
      method: "POST",
      body: operationPayload(operation)
    });
    state.operationResults[key] = response.result;
  } catch (error) {
    state.operationErrors[key] = error.message;
  } finally {
    state.runningOperation = null;
    renderOperations();
  }
}

renderLanguageSwitch();
renderNav();
setView("settings");
</script>
</body>
</html>
"""

def render_webui_html(csrf_token: str) -> str:
    """Render the single-page UI with the server-generated CSRF token."""
    return WEBUI_HTML.replace(CSRF_TOKEN_PLACEHOLDER, csrf_token)
