# 应用目录规范

`dancing-log` 使用同一套应用根目录解析运行路径。源码运行时，应用根目录是仓库根目录。未来独立 exe 运行时，应用根目录会是 exe 所在文件夹。

配置优先级固定为：

1. 命令行参数。
2. `config/dancing-log.local.json`。
3. 自动检测或代码默认值。

## 目录职责

- `config/`：本机配置。`dancing-log.local.json` 被 git 忽略；`dancing-log.example.json` 记录支持的字段。
- `data/`：长期用户数据，例如 `dancing_log.sqlite3`、`queued_self/`、喜欢清单输入文件。
- `logs/`：正常运行产生的输出。`watch-vrc-log` 默认写入 `logs/captures/`。`logs/source-vrc-logs/` 预留给未来复制的源 `output_log_*.txt`。
- `analysis/`：开发和排查用实验区，例如 replay 基准、历史原始日志集合、一次性对比输出。它不属于未来 exe 的用户交付承诺。
- `build/`：本机构建中间产物。
- `dist/`：本地打包输出。
- `backups/`：清理或迁移前生成的本地安全备份。

## 配置字段

可提交的示例配置是 `config/dancing-log.example.json`。

```json
{
  "config_version": 1,
  "app_db": "data/dancing_log.sqlite3",
  "queued_self_dir": "data/queued_self",
  "capture_dir": "logs/captures",
  "run_log_dir": "logs/runs",
  "source_vrc_log_dir": "logs/source-vrc-logs",
  "recording_frames_dir": "analysis/recording_frames",
  "self_user_id": null,
  "vrcx_db_path": null,
  "vrc_log_dir": null,
  "wanna_cache_dir": null,
  "recordings_dir": null
}
```

配置中的相对路径都按应用根目录解析。绝对路径保持不变。`%USERPROFILE%` 这类环境变量会在解析前展开。

`data/local_config.json` 是旧配置位置。新配置不存在时，程序会兼容读取它，并把规范化后的配置写入 `config/dancing-log.local.json`。
