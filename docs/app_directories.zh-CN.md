# 应用目录规范

`dance-trail` 使用同一套应用根目录解析运行路径。源码运行时，应用根目录是仓库根目录。未来独立 exe 运行时，应用根目录会是 exe 所在文件夹。

配置优先级固定为：

1. 命令行参数。
2. `config/dance-trail.local.json`。
3. 自动检测或代码默认值。

命令行路径参数只影响本次运行，并且优先于已保存路径。已保存的手动来源路径优先于自动来源路径检测。只有当工作流需要外部来源路径，并且本次命令和已保存配置都没有提供该路径时，才使用自动检测。

自动来源路径检测只适用于外部来源路径。Settings 可以预览当前环境的检测结果，但预览不是已保存配置，也不承诺之后的工作流会检测到同一个结果。检测到多个合理候选时，对应的已保存字段保持为空，直到用户明确选择其中一个。

`vrc_log_dir` 默认在每次启用 watcher 时自动检测。watcher 启动时，如果解析出的日志目录缺失或不可访问，应当以可见的缺失路径错误失败，而不是在没有输入源的情况下继续运行。

`vrcx_db_path` 默认在每次 VRCX 导入或重建操作需要它时自动检测。自动候选是 `%APPDATA%/VRCX/VRCX.sqlite3`，通常是 `C:/Users/<user>/AppData/Roaming/VRCX/VRCX.sqlite3`。VRCX 检测应当刻意保持收窄，不搜索备份、迁移副本或其他非标准数据库。标准数据库存在时，操作可以把它作为本次运行输入使用，但不写入配置。标准数据库缺失时，已保存字段保持为空，由用户负责选择或传入手动路径。

`recordings_dir` 是可选字段。Settings 可以从 OBS 输出配置提供自动候选，但找不到 OBS 配置或候选有歧义时应保持为空。录像工具仍可接受绝对录像路径；只有在解析相对录像文件名时才需要 `recordings_dir`。

## 目录职责

- `config/`：本机配置。`dance-trail.local.json` 被 git 忽略；`dance-trail.example.json` 记录支持的字段。
- `data/`：长期用户数据，例如 `dance_trail.sqlite3`、`queued_self/`、喜欢清单输入文件。持久存在的 `.dance-trail-watcher.lock` 提供操作系统级应用范围 watcher 锁；外部 SQLite 数据库旁的 `.<名称>.watcher.lock` 提供数据库范围排他。锁文件本身不表示运行状态，正常退出后也可以保留；真正的所有权来自当前进程持有的操作系统文件锁。
- `logs/`：正常运行产生的输出。`watch-vrc-log` 默认写入 `logs/captures/`。增量源 VRChat 日志归档存放在 `logs/source-vrc-logs/`。
- `analysis/`：开发和排查用实验区，例如 replay 基准、历史原始日志集合、一次性对比输出。它不属于未来 exe 的用户交付承诺。
- `build/`：本机构建中间产物。
- `dist/`：本地打包输出。
- `backups/`：清理或迁移前生成的本地安全备份。

## 配置字段

可提交的示例配置是 `config/dance-trail.example.json`。

```json
{
  "config_version": 1,
  "app_db": "data/dance_trail.sqlite3",
  "queued_self_dir": "data/queued_self",
  "capture_dir": "logs/captures",
  "run_log_dir": "logs/runs",
  "source_vrc_log_dir": "logs/source-vrc-logs",
  "recording_frames_dir": "analysis/recording_frames",
  "self_user_id": null,
  "vrcx_db_path": null,
  "vrc_log_dir": null,
  "wanna_cache_dir": null,
  "recordings_dir": null,
  "dance_day_boundary_time": "00:00",
  "auto_start_watcher": false,
  "auto_start_overlay": false,
  "overlay_port": 8765
}
```

配置中的相对路径都按应用根目录解析。绝对路径保持不变。`%USERPROFILE%` 这类环境变量会在解析前展开。

`dance_day_boundary_time` 是必填的本地墙钟 `HH:MM` 值，允许范围为 `00:00` 至 `06:00`。Local Dance Day 计算使用操作系统的真实本地时区规则。

`auto_start_watcher` 和 `auto_start_overlay` 是应用工作流的运行时默认值。`auto_start_overlay` 设为 `true` 时，也会保持 `auto_start_watcher` 启用，因为 overlay 依赖实时 watcher 状态。`overlay_port` 是不启动 Web UI、由独立 watcher 提供 overlay 时使用的高级兼容配置；桌面/Web UI 模式在 Web UI 端口提供 `/overlay`。

DanceTrail 仅读取 `config/dance-trail.local.json`；文件不存在时使用默认值，不迁移旧产品的配置或数据库。
