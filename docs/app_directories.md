# Application Directories

`dancing-log` resolves relative runtime paths from one application root. In a
source checkout, the application root is the repository root. In a future
standalone exe build, the application root will be the folder that contains the
exe.

Configuration precedence is:

1. Command-line arguments.
2. `config/dancing-log.local.json`.
3. Auto-detected or built-in defaults.

Command-line path arguments affect only the current run and take precedence over
saved paths. Saved manual source paths take precedence over automatic source-path
detection. Automatic detection is used only when a workflow needs an external
source path and neither the current command nor saved configuration provides one.

Automatic source-path detection applies only to external source paths. The app
may preview the current detection result in Settings, but previews are not saved
configuration and a later workflow may detect a different result. When detection
finds multiple plausible candidates, the corresponding saved field remains empty
until the user explicitly chooses one.

`vrc_log_dir` defaults to automatic detection each time the watcher is enabled.
If the resolved log directory is missing or inaccessible at watcher startup, the
watcher should fail with a visible missing-path error rather than run without an
input source.

`vrcx_db_path` defaults to automatic detection each time a VRCX import or rebuild
operation needs it. The primary automatic candidate is
`%APPDATA%/VRCX/VRCX.sqlite3`, normally
`C:/Users/<user>/AppData/Roaming/VRCX/VRCX.sqlite3`. VRCX detection is
intentionally narrow and should not search for backups, migrated copies, or
other non-standard databases. If the standard database exists, the operation may
use it for the current run without saving it to configuration. If it is missing,
the saved field remains empty and the user is responsible for choosing or
passing a manual path.

`recordings_dir` is optional. Settings may offer an automatic candidate from OBS
output configuration, but missing or ambiguous OBS configuration should leave the
field empty. Recording tools can still accept absolute recording paths, and only
need `recordings_dir` when resolving relative recording file names.

## Directory Roles

- `config/`: local machine configuration. `dancing-log.local.json` is ignored by
  git; `dancing-log.example.json` documents supported keys.
- `data/`: long-lived local user data, including `dancing_log.sqlite3`,
  `queued_self/`, and favorite-list input files. A persistent
  `.dancing-log-watcher.lock` file provides the OS-backed application-scope
  watcher lock; an external SQLite database has a sibling `.<name>.watcher.lock`
  file for database-scope exclusion. The files contain no authoritative runtime
  state and may remain after a clean exit; ownership is the live OS file lock.
- `logs/`: runtime output from normal app use. `watch-vrc-log` captures now
  default to `logs/captures/`. Incremental source VRChat log archives are
  stored in `logs/source-vrc-logs/`.
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
  "recordings_dir": null,
  "auto_start_watcher": false,
  "auto_start_overlay": false,
  "overlay_port": 8765
}
```

Relative paths in this file are resolved from the application root. Absolute
paths remain absolute. Environment variables such as `%USERPROFILE%` are
expanded before resolution.

`auto_start_watcher` and `auto_start_overlay` are runtime defaults for app
workflows. Setting `auto_start_overlay` to `true` also keeps
`auto_start_watcher` enabled because the overlay depends on live watcher state.
`overlay_port` is an advanced compatibility setting used when a standalone
watcher serves the overlay without the Web UI. Desktop/Web UI mode serves
`/overlay` on the Web UI port.

`data/local_config.json` is a legacy location. The app can read it when the new
config file does not exist, then writes normalized config to
`config/dancing-log.local.json`.
