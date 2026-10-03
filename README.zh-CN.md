# DanceTrail

[English](README.md) | **简体中文**

**留下你的 VRChat 舞蹈足迹。**

DanceTrail 从本地 VRChat 日志记录舞蹈播放，帮助你回顾每次跳舞的经历、
找回喜欢的曲目，并决定下一首跳什么。程序在 Windows 电脑上运行，通过浏览器操作。

## 可以做什么

- **记录 WannaDance、PyPyDance 和 DuDu 的播放**：启动日志监听，记录这三个舞蹈系统中支持的播放，并查看当前正在播放的曲目。
- **回顾跳舞历史**：按天浏览时间线，复查不确定的记录，决定哪些播放计入历史。
- **寻找下一首舞蹈**：搜索 WannaDance 曲库，标记收藏和想学的曲目，获取基于历史的推荐。
- **查看统计**：在洞察页查看常跳曲目和播放来源分布。
- **导入以往记录**：从 VRCX 导入支持的历史播放记录。
- **在 OBS 展示当前曲目**：将本地 overlay 页面添加为浏览器来源。

界面支持中英文切换，以及浅色、深色和跟随系统主题。

## 开始使用

DanceTrail 当前面向 **Windows**。本仓库暂未发布可直接下载的 Release，
可以按下面的步骤从源码运行，或[自行构建便携包](docs/portable_release.zh-CN.md)。

### 从源码运行

准备 Git、Python **3.14** 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)，
打开 PowerShell：

```powershell
git clone https://github.com/SW26010/dance-trail.git
cd dance-trail
uv sync --locked
uv run --locked python main.py webui
```

浏览器会打开 **<http://127.0.0.1:8787/home>**。使用期间保持终端运行；
需要停止时，在该终端按 **Ctrl+C**。

仓库已包含构建好的浏览器界面。仅运行程序不需要安装 Node.js 或 pnpm。

### 第一次记录

1. 打开**设置**，检查 VRChat 日志目录。程序会自动检测 Windows 标准位置；
   如果日志放在其他位置，请手动设置路径。
2. 在**数据操作**中同步 WannaDance 曲库，加载曲目名称和目录。
3. 回到**首页**，点击**启动 watcher**，然后在 VRChat 中播放支持的舞蹈。
4. 在**时间线**中复查本次记录。标记为“待定”或“需注意”的记录，在接受前不会计入正常历史。

监听默认从当前日志末尾开始，只记录新活动。需要导入较早的记录时，
可以使用**数据操作**中的 VRCX 导入。实时日志记录不要求安装 VRCX。

如果经常跳到凌晨，可以在设置中调整**舞蹈日边界**，让跨午夜的记录归入你希望的日期。

### 使用便携包

如果你已有构建好的便携 ZIP，请将**整个文件夹**解压到可写的位置，然后运行
**`DanceTrail.exe`**。便携包不需要另行安装 Python。
程序会自动打开浏览器界面，并驻留在系统托盘；关闭浏览器标签页不会停止程序，
请通过托盘菜单的 **Exit** 退出。

请保留可执行文件旁的 `_internal` 文件夹。偏好命令行操作时，可使用 `DanceTrailCli.exe`。

## 界面导航

| 页面 | 用途 |
| --- | --- |
| **首页** | 查看实时播放，启动或停止 watcher 和 overlay。 |
| **时间线** | 按天浏览记录，接受或排除播放记录。 |
| **目录** | 搜索曲目，标记收藏和想学。 |
| **清单** | 查看本地计划自选的舞蹈清单。 |
| **洞察** | 查看历史统计和推荐。 |
| **数据操作** | 同步曲库、导入支持的本地数据。 |
| **设置** | 配置路径、自动启动选项和舞蹈日边界。 |

## OBS 展示

1. 启动 DanceTrail，在**首页**启用 watcher 和 overlay。
2. 在 OBS 中添加**浏览器来源**，填入：

   ```text
   http://127.0.0.1:8787/overlay
   ```

3. 使用期间保持 DanceTrail 运行。

Overlay 展示当前播放。“Waiting for playback”表示已就绪，正在等待曲目；
“Overlay inactive”表示 overlay 已停止。如果修改了 Web UI 端口，OBS 地址也需要使用对应端口。

## 数据与隐私

历史和设置保存在本机，默认位于程序目录下：

| 位置 | 内容 |
| --- | --- |
| `config/dance-trail.local.json` | 已保存的设置和路径。 |
| `data/` | 播放历史、本地曲库和清单。 |
| `logs/` | 采集的日志和诊断输出。 |

备份或移动程序目录前，请先退出 DanceTrail。保留 `config/` 和 `data/` 即可保留设置及历史。
如果设置了程序目录以外的自定义数据路径，也要单独备份这些位置。
采集日志可能包含玩家名、标识符和活动详情，提交问题报告前请先检查并去除个人信息。

界面仅监听本机地址。曲库同步会访问外部服务，需要联网。
DanceTrail 不会自动迁移旧产品名称下的配置或数据库。

自定义路径及备份说明见[应用目录与配置](docs/app_directories.zh-CN.md)。

## 支持范围与当前限制

DanceTrail 支持记录 **WannaDance（Wanna）**、**PyPyDance（PyPy）**
和 **DuDu FitDance（DuDu）** 的舞蹈播放：

| 舞蹈系统 | 从 VRChat 日志实时记录 | 导入 VRCX 历史 |
| --- | --- | --- |
| **WannaDance** | 支持 | 支持 |
| **PyPyDance** | 支持可识别的播放日志和 URL | 支持可识别的 URL |
| **DuDu FitDance** | 支持可识别的播放日志和 URL | URL 识别为实验性支持 |

WannaDance 还提供曲库同步，用于浏览和搜索曲目。PyPyDance 和 DuDu 的播放记录支持
不包含这两个系统的完整曲库同步。

- 记录依赖 VRChat 日志中的信息。检测到播放不等于你完成了整支舞，
  请在时间线中复查不确定的记录。
- 对某个舞蹈系统的支持，不代表兼容所有使用该系统的世界或视频播放器。

## 可选：命令行工具

在源码目录中运行：

```powershell
# 预览 VRCX 历史导入，不实际写入
uv run --locked python main.py import-vrcx --dry-run

# 使用 WannaDance 曲目 ID 手动添加一条记录
uv run --locked python main.py log --system wannadance 5038

# 推荐十首曲目
uv run --locked python main.py recommend -n 10

# 查看可用命令
uv run --locked python main.py
```

使用便携包时，将 `uv run --locked python main.py` 替换为 `.\DanceTrailCli.exe`。
每个命令的详细选项可通过 `--help` 查看。

## 帮助与开发文档

遇到问题或有建议时，可以[提交 Issue](https://github.com/SW26010/dance-trail/issues)。
请说明版本、预期行为和复现步骤，并清理所附日志中的个人信息。

- [构建 Windows 便携包](docs/portable_release.zh-CN.md)
- [应用目录与配置](docs/app_directories.zh-CN.md)
- [VRCX 导入说明](docs/vrcx_integration_notes.zh-CN.md)
- [WannaDance 曲库同步](docs/wanna_catalog_sync.zh-CN.md)
- [数据模型与设计](docs/dance_data_model.zh-CN.md)
- [Web UI 构建与无障碍检查](docs/accessibility/webui-release-checklist.zh-CN.md)

## 许可证

[MIT](LICENSE) · Copyright © 2026 Himalia。

第三方依赖保留各自的许可证。便携包在 `Legal/` 中附带许可文本，
详见[许可打包说明](legal/README.md)。本项目许可证不授予第三方音乐、视频或外部曲库数据的使用权。
