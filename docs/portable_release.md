# Portable Release

The source version remains 0.8.0. The historical v0.8.0 tag is retained, but no earlier Releases are carried over.
The commands below use a future 0.9.0 release as an example.


The first supported release shape is a Windows x64 portable folder. It keeps the
same app-root path model as source runs: `config/`, `data/`, and `logs/` live
next to the executable files.

## Local Build

Prerequisites:

- Windows
- Python 3.14
- `uv` on `PATH`
- Node.js 24.x on `PATH`
- pnpm 11.9.0 on `PATH`

Install the locked Web UI dependencies, then run the build:

```powershell
pnpm install --frozen-lockfile
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1
```

The script builds the Fluent React Web UI, runs the unit tests, and uses the
locked `release` dependency group from `uv.lock` and the pnpm lockfile to build
PyInstaller onedir desktop and console apps. It then runs CLI smoke coverage and
a frozen-GUI single-instance acceptance test. The GUI test verifies one 8787
listener, exact `/home` browser activation by a quickly exiting second process,
mutex reacquisition after the first process exits, and takeover by a waiting
process when a synthetic startup owner releases the mutex before becoming
ready. It also validates the frozen `/assets/app.js` status, content type, and
non-empty payload. The build writes:

```text
dist/releases/DanceTrail-v<version>-win-x64-portable.zip
dist/releases/DanceTrail-v<version>-win-x64-portable.zip.sha256
```

Useful options:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1 -Version 0.9.0
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1 -SkipTests
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1 -SkipSmoke
```

## GitHub Release

Before creating a version tag, complete the required automated procedure in
`docs/accessibility/webui-release-checklist.md` and commit a passing report as
`docs/accessibility/release-reports/<version-tag>.md`. The report must contain an
exact `Result: Pass` line and reproducible revision/asset hashes. Manual
observations are advisory and are not required for release.

Push a version tag:

```powershell
git tag v0.9.0
git push origin v0.9.0
```

The `Release Portable` workflow verifies the matching accessibility report, runs the
Web UI accessibility acceptance suite, builds the same portable zip, uploads it
as an artifact, and attaches the zip plus SHA-256 checksum to the GitHub Release.

## Portable Folder Contents

The generated folder includes:

```text
DanceTrail.exe
DanceTrailCli.exe
_internal/
config/dance-trail.example.json
data/
logs/
docs/
README.md
README.zh-CN.md
sync-wanna.bat
start-watch-vrc-log.bat
```

User-specific settings belong in `config/dance-trail.local.json`, which is not
included in the release zip.

Double-clicking `DanceTrail.exe` starts the desktop tray entry and activates the
Local Web UI on `http://127.0.0.1:8787/` without opening a console window. Use
the tray menu to open the Web UI again, start or stop the live watcher and OBS
overlay, or quit the background app session. The tray entry is single-instance
within the current Windows session: double-clicking the executable again opens
the existing Web UI in the default browser and exits without starting another
app session or HTTP listener. If the previous owner exits during startup, the
waiting process recontends the mutex and becomes the replacement owner instead
of leaving the session with no desktop instance.

`start-watch-vrc-log.bat` starts the common OBS overlay workflow:

```bat
DanceTrailCli.exe watch-vrc-log --overlay-port 8765 %*
```

The command writes watcher-derived playback evidence into `playback_records` by
default. Extra arguments are appended, so a user can still pass options such as
`--log-dir`, `--live-db` for deprecated forensic mirroring, or another
`--overlay-port`.

Development/research commands are not part of the portable release. In
particular, `sample-frames` and its ffmpeg dependency are excluded from the zip.
