# Portable 发布流程

第一版发布形态是 Windows x64 portable 文件夹。它沿用源码运行时的
app-root 路径模型：`config/`、`data/`、`logs/` 都放在
`DancingLog.exe` 同级目录。

## 本地构建

前置条件：

- Windows
- Python 3.14
- `uv` 在 `PATH` 中

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1
```

脚本会运行单元测试、构建 PyInstaller onedir 程序、对 exe 做 smoke
test，然后输出：

```text
dist/releases/DancingLog-v<version>-win-x64-portable.zip
dist/releases/DancingLog-v<version>-win-x64-portable.zip.sha256
```

常用选项：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1 -Version 0.1.0
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1 -SkipTests
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1 -SkipSmoke
```

## GitHub Release

推送版本 tag：

```powershell
git tag v0.1.0
git push origin v0.1.0
```

`Release Portable` workflow 会构建同一个 portable zip，上传 artifact，并把
zip 和 SHA-256 checksum 附到 GitHub Release。

## Portable 文件夹内容

生成的文件夹包含：

```text
DancingLog.exe
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

`start-watch-vrc-log.bat` 默认启动常用的 OBS overlay 流程：

```bat
DancingLog.exe watch-vrc-log --live-db --overlay-port 8765 %*
```

额外参数会继续追加在后面，所以仍然可以传 `--promote-live`、`--log-dir`，
或者用另一个 `--overlay-port` 覆盖端口。

开发/研究命令不是 portable release 的一部分。特别是 `sample-frames` 以及
它依赖的 ffmpeg 不会包含在 zip 里。
