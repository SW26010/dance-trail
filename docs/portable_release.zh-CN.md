# Portable 发布流程

第一版发布形态是 Windows x64 portable 文件夹。它沿用源码运行时的
app-root 路径模型：`config/`、`data/`、`logs/` 都放在可执行文件同级目录。

## 本地构建

前置条件：

- Windows
- Python 3.14
- `uv` 在 `PATH` 中
- Node.js 24.x 在 `PATH` 中
- pnpm 11.9.0 在 `PATH` 中

先安装锁定的 Web UI 依赖，再运行构建：

```powershell
pnpm install --frozen-lockfile
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1
```

脚本会构建 Fluent React Web UI、运行单元测试，并使用 `uv.lock` 中锁定的
`release` dependency group 与 pnpm lockfile 构建 PyInstaller onedir 桌面托盘
程序和 console CLI 程序；之后对 exe 做 smoke test，并输出：

```text
dist/releases/DancingLog-v<version>-win-x64-portable.zip
dist/releases/DancingLog-v<version>-win-x64-portable.zip.sha256
```

常用选项：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1 -Version 0.7.0
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1 -SkipTests
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1 -SkipSmoke
```

## GitHub Release

创建版本 tag 前，先按 `docs/accessibility/webui-release-checklist.zh-CN.md`
完成必要的自动化检查，并把通过报告提交为
`docs/accessibility/release-reports/<版本标签>.md`。报告必须包含一行精确的
`Result: Pass` 和可复算的 revision/资产哈希。人工复核是建议项，不是发布
前置条件。

推送版本 tag：

```powershell
git tag v0.7.0
git push origin v0.7.0
```

`Release Portable` workflow 会先验证对应无障碍报告并运行 Web UI 无障碍验收，
再构建同一个 portable zip、上传 artifact，并把 zip 和 SHA-256 checksum 附到
GitHub Release。

## Portable 文件夹内容

生成的文件夹包含：

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

本机配置放在 `config/dancing-log.local.json`，不会包含在 release zip 里。

双击 `DancingLog.exe` 会启动桌面托盘入口，并在不打开控制台窗口的情况下激活
`http://127.0.0.1:8787/` 上的 Local Web UI。可以通过托盘菜单重新打开 Web
UI，启动或停止 live watcher 和 OBS overlay，或退出后台应用会话。

`start-watch-vrc-log.bat` 默认启动常用的 OBS overlay 流程：

```bat
DancingLogCli.exe watch-vrc-log --overlay-port 8765 %*
```

这个命令默认会把 watcher-derived playback evidence 写入 `playback_records`。额外参数
会继续追加在后面，所以仍然可以传 `--log-dir`、用于 deprecated 取证镜像的
`--live-db`，或者用另一个 `--overlay-port` 覆盖端口。

开发/研究命令不是 portable release 的一部分。特别是 `sample-frames` 以及
它依赖的 ffmpeg 不会包含在 zip 里。
