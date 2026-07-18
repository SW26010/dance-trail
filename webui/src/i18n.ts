import type { ViewKey } from "./api";

export type Language = "en" | "zh";
export type ThemeChoice = "system" | "light" | "dark";

export const LANGUAGE_KEY = "dancing-log.language";
export const THEME_KEY = "dancing-log.theme";

const en = {
  brandSubtitle: "Local Web UI", languageLabel: "Language", themeLabel: "Theme",
  themeSystem: "System", themeLight: "Light", themeDark: "Dark",
  skipToMain: "Skip to main content", applicationNavigation: "Application navigation", primaryNavigation: "Primary",
  nav_home: "Home", nav_timeline: "Timeline", nav_catalog: "Catalog", nav_lists: "Lists",
  nav_insights: "Insights", nav_operations: "Data Operations", nav_settings: "Settings",
  title_home: "Home", subtitle_home: "Runtime status and recent activity",
  title_timeline: "Timeline", subtitle_timeline: "Chronological playback records",
  title_catalog: "Catalog", subtitle_catalog: "Dance tracks and local preferences",
  title_lists: "Lists", subtitle_lists: "Planned dance lists",
  title_insights: "Insights", subtitle_insights: "Confirmed-history summaries",
  title_operations: "Data Operations", subtitle_operations: "Controlled bulk workflows",
  title_settings: "Settings", subtitle_settings: "Saved local configuration",
  reset: "Reset", save: "Save", browse: "Browse", enabled: "Enabled", disabled: "Disabled",
  loadingConfig: "Loading configuration...", loading: "Loading...", saved: "Saved", unsaved: "Unsaved",
  saveFailed: "Save failed", savedNull: "Saved as null", automatic: "Automatic", customPath: "Custom",
  useAsManual: "Use as manual", exists: "exists", missing: "missing", inaccessible: "inaccessible",
  detectedSources: "Automatic source path previews", unsupportedKeys: "Unsupported configuration keys", preserved: "Preserved",
  danceTracks: "Dance tracks", playbackRecords: "Playback records", acceptedRecords: "Accepted",
  attentionRecords: "Needs attention", runtimeState: "Runtime state", dbFound: "DB found", noDb: "No DB",
  noLiveRow: "No live playback row", recentAccepted: "Recent accepted records", local: "local", noRecords: "No records",
  time: "Time", track: "Track", source: "Source", accepted: "Accepted", live: "Live-derived",
  load: "Load", timelineDate: "Timeline date", openDatePicker: "Open date picker", previousMonth: "Previous month",
  previousDay: "Previous day", nextDay: "Next day", nextMonth: "Next month", timelineSortChronological: "Chronological",
  timelineSortReverse: "Reverse", reverseTimelineOrder: "Reverse timeline order", copyDailyDancesTitle: "Copy valid events",
  copiedDailyDances: "Copied valid events", noAcceptedTimelineRecords: "No valid dance events for this day",
  timelineLoadFailed: "Timeline load failed", copyDailyDancesFailed: "Copy failed", sourceRandom: "Random",
  sourceOther: "Other", sourceSelf: "Self", sourceRecommend: "Recommended", sourceQueuedSelf: "Reserved",
  sourceUnknown: "Unknown", noTimelineRecords: "No timeline records", record: "Record", reviewStatus: "Status",
  actions: "Actions", accept: "Accept", exclude: "Exclude", restoreDefault: "Restore default", manual: "Manual",
  defaultResult: "Default", reviewUpdateFailed: "Review update failed", status_accepted: "accepted",
  status_excluded: "excluded", status_needs_attention: "needs attention", status_pending: "pending",
  searchCatalog: "Search catalog", search: "Search", noTracks: "No tracks", title: "Title", artist: "Artist",
  preferences: "Preferences", favorite: "favorite", wantToLearn: "want to learn",
  queuedSelfManifests: "Queued-self manifests", found: "found", noManifests: "No manifests",
  sourceDistribution: "Source distribution", topTracks: "Top tracks", recommendations: "Recommendations",
  noData: "No data", name: "Name", count: "Count", liveStatus: "Live status", watcher: "Watcher",
  overlay: "Overlay", running: "Running", stopping: "Stopping", stopped: "Stopped", refresh: "Refresh",
  startWatcher: "Start watcher", stopWatcher: "Stop watcher", startOverlay: "Start overlay", stopOverlay: "Stop overlay",
  databaseState: "Database state", currentLiveRow: "Current live row", lastRuntimeError: "Last runtime error",
  lastWatcherStats: "Last watcher stats", noWatcherStats: "No watcher stats yet", liveControlFailed: "Live control failed",
  run: "Run", runningOperation: "Running...", operationComplete: "Complete", operationFailed: "Operation failed",
} as const;

const zh: Record<keyof typeof en, string> = {
  brandSubtitle: "本地 Web UI", languageLabel: "语言", themeLabel: "主题",
  themeSystem: "跟随系统", themeLight: "浅色", themeDark: "深色",
  skipToMain: "跳到主要内容", applicationNavigation: "应用导航", primaryNavigation: "主导航",
  nav_home: "首页", nav_timeline: "时间线", nav_catalog: "目录", nav_lists: "清单",
  nav_insights: "洞察", nav_operations: "数据操作", nav_settings: "设置",
  title_home: "首页", subtitle_home: "运行状态和最近活动",
  title_timeline: "时间线", subtitle_timeline: "按时间顺序查看播放记录",
  title_catalog: "目录", subtitle_catalog: "舞蹈条目和本地偏好",
  title_lists: "清单", subtitle_lists: "计划中的舞蹈清单",
  title_insights: "洞察", subtitle_insights: "基于已接受历史的汇总",
  title_operations: "数据操作", subtitle_operations: "受控的批量工作流",
  title_settings: "设置", subtitle_settings: "已保存的本地配置",
  reset: "重置", save: "保存", browse: "浏览", enabled: "已启用", disabled: "已禁用",
  loadingConfig: "正在加载配置...", loading: "正在加载...", saved: "已保存", unsaved: "未保存",
  saveFailed: "保存失败", savedNull: "保存为空值", automatic: "自动", customPath: "自定义",
  useAsManual: "设为手动路径", exists: "存在", missing: "缺失", inaccessible: "不可访问",
  detectedSources: "自动来源路径预览", unsupportedKeys: "不支持的配置键", preserved: "已保留",
  danceTracks: "舞蹈条目", playbackRecords: "播放记录", acceptedRecords: "已接受",
  attentionRecords: "需注意", runtimeState: "运行状态", dbFound: "数据库已找到", noDb: "无数据库",
  noLiveRow: "没有实时播放记录", recentAccepted: "最近已接受记录", local: "本地", noRecords: "没有记录",
  time: "时间", track: "条目", source: "来源", accepted: "已接受", live: "实时来源",
  load: "加载", timelineDate: "时间线日期", openDatePicker: "打开日期选择器", previousMonth: "上个月",
  previousDay: "前一天", nextDay: "后一天", nextMonth: "下个月", timelineSortChronological: "时间顺序",
  timelineSortReverse: "倒序", reverseTimelineOrder: "倒序显示时间线", copyDailyDancesTitle: "复制有效事件",
  copiedDailyDances: "已复制有效事件", noAcceptedTimelineRecords: "这一天没有有效跳舞事件",
  timelineLoadFailed: "时间线加载失败", copyDailyDancesFailed: "复制失败", sourceRandom: "随机",
  sourceOther: "他人", sourceSelf: "自己", sourceRecommend: "推荐", sourceQueuedSelf: "预定",
  sourceUnknown: "未知", noTimelineRecords: "没有时间线记录", record: "记录", reviewStatus: "状态",
  actions: "操作", accept: "接受", exclude: "排除", restoreDefault: "恢复默认", manual: "手动",
  defaultResult: "默认", reviewUpdateFailed: "更新审阅失败", status_accepted: "已接受",
  status_excluded: "已排除", status_needs_attention: "需注意", status_pending: "待定",
  searchCatalog: "搜索目录", search: "搜索", noTracks: "没有条目", title: "标题", artist: "艺人",
  preferences: "偏好", favorite: "收藏", wantToLearn: "想学",
  queuedSelfManifests: "自选队列清单", found: "已找到", noManifests: "没有清单",
  sourceDistribution: "来源分布", topTracks: "常跳条目", recommendations: "推荐",
  noData: "没有数据", name: "名称", count: "数量", liveStatus: "实时状态", watcher: "Watcher",
  overlay: "Overlay", running: "运行中", stopping: "正在停止", stopped: "已停止", refresh: "刷新",
  startWatcher: "启动 watcher", stopWatcher: "停止 watcher", startOverlay: "启动 overlay", stopOverlay: "停止 overlay",
  databaseState: "数据库状态", currentLiveRow: "当前实时播放记录", lastRuntimeError: "最近运行错误",
  lastWatcherStats: "最近 watcher 统计", noWatcherStats: "尚无 watcher 统计", liveControlFailed: "实时控制失败",
  run: "执行", runningOperation: "执行中...", operationComplete: "已完成", operationFailed: "操作失败",
};

export type TranslationKey = keyof typeof en;
export type Translator = (key: TranslationKey) => string;

export function translator(language: Language): Translator {
  const dictionary = language === "zh" ? zh : en;
  return (key) => dictionary[key];
}

export function initialLanguage(): Language {
  return localStorage.getItem(LANGUAGE_KEY) === "zh" ? "zh" : "en";
}

export function initialTheme(): ThemeChoice {
  const saved = localStorage.getItem(THEME_KEY);
  return saved === "light" || saved === "dark" ? saved : "system";
}

export function viewTitle(view: ViewKey, t: Translator): [string, string] {
  return [t(`title_${view}`), t(`subtitle_${view}`)];
}
