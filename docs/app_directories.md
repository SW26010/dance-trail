# Application Directories

`dancing-log` resolves relative runtime paths from one application root. In a
source checkout, the application root is the repository root. In a future
standalone exe build, the application root will be the folder that contains the
exe.

Configuration precedence is:

1. Command-line arguments.
2. `config/dancing-log.local.json`.
3. Auto-detected or built-in defaults.

## Directory Roles

- `config/`: local machine configuration. `dancing-log.local.json` is ignored by
  git; `dancing-log.example.json` documents supported keys.
- `data/`: long-lived local user data, including `dancing_log.sqlite3`,
  `queued_self/`, and favorite-list input files.
- `logs/`: runtime output from normal app use. `watch-vrc-log` captures now
  default to `logs/captures/`. `logs/source-vrc-logs/` is reserved for future
  copied source `output_log_*.txt` files.
- `analysis/`: development and forensic scratch work, such as replay baselines,
  historical raw-log corpora, and one-off comparison outputs. It is not part of
  the future exe user contract.
- `build/`: local build intermediates.
- `dist/`: local packaged outputs.
- `backups/`: local safety archives created before cleanup or migration work.

## Config Keys

The tracked example config is `config/dancing-log.example.json`.

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

Relative paths in this file are resolved from the application root. Absolute
paths remain absolute. Environment variables such as `%USERPROFILE%` are
expanded before resolution.

`data/local_config.json` is a legacy location. The app can read it when the new
config file does not exist, then writes normalized config to
`config/dancing-log.local.json`.
