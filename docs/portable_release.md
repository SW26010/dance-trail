# Portable Release

The first supported release shape is a Windows x64 portable folder. It keeps the
same app-root path model as source runs: `config/`, `data/`, and `logs/` live
next to the executable files.

## Local Build

Prerequisites:

- Windows
- Python 3.14
- `uv` on `PATH`

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1
```

The script runs the unit tests, builds a PyInstaller onedir desktop app plus a
console CLI app, runs an exe smoke test, and writes:

```text
dist/releases/DancingLog-v<version>-win-x64-portable.zip
dist/releases/DancingLog-v<version>-win-x64-portable.zip.sha256
```

Useful options:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1 -Version 0.1.0
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1 -SkipTests
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1 -SkipSmoke
```

## GitHub Release

Push a version tag:

```powershell
git tag v0.1.0
git push origin v0.1.0
```

The `Release Portable` workflow builds the same portable zip, uploads it as an
artifact, and attaches the zip plus SHA-256 checksum to the GitHub Release.

## Portable Folder Contents

The generated folder includes:

```text
DancingLog.exe
DancingLogCli.exe
_internal/
config/dancing-log.example.json
data/
logs/
docs/
README.md
README.zh-CN.md
sync-wanna.bat
start-watch-vrc-log.bat
```

User-specific settings belong in `config/dancing-log.local.json`, which is not
included in the release zip.

Double-clicking `DancingLog.exe` starts the desktop tray entry and activates the
Local Web UI on `http://127.0.0.1:8787/` without opening a console window. Use
the tray menu to open the Web UI again, start or stop the live watcher and OBS
overlay, or quit the background app session.

`start-watch-vrc-log.bat` starts the common OBS overlay workflow:

```bat
DancingLogCli.exe watch-vrc-log --overlay-port 8765 %*
```

The command writes watcher-derived playback evidence into `playback_records` by
default. Extra arguments are appended, so a user can still pass options such as
`--log-dir`, `--live-db` for deprecated forensic mirroring, or another
`--overlay-port`.

Development/research commands are not part of the portable release. In
particular, `sample-frames` and its ffmpeg dependency are excluded from the zip.
