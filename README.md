# DanceTrail

**English** | [简体中文](README.zh-CN.md)

**Keep a trail of your VRChat dance sessions.**

DanceTrail records dance playback from local VRChat logs and gives you a place
to revisit your sessions, find tracks you enjoyed, and decide what to dance next.
It runs on your Windows PC, with an interface in your browser.

## What you can do

- **Record WannaDance, PyPyDance, and DuDu sessions.** Start the log watcher
  to capture supported playback from all three dance systems and see what is
  currently playing.
- **Review your history.** Browse a daily timeline, review uncertain records,
  and choose which plays count toward your history.
- **Find your next dance.** Search the WannaDance catalog, mark favorites and
  tracks you want to learn, and get suggestions based on your dance history.
- **Look back at your sessions.** View frequently played tracks and playback
  source statistics in Insights.
- **Bring in earlier sessions.** Import supported playback history from VRCX.
- **Show the current track in OBS.** Add the local overlay as a Browser Source.

The interface supports English and Chinese, with light, dark, and system themes.

## Get started

DanceTrail currently targets **Windows**. This repository does not yet have a
published downloadable Release; use the source instructions below or
[build a portable copy](docs/portable_release.md).

### Run from source

You need Git, Python **3.14**, and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Open PowerShell and run:

```powershell
git clone https://github.com/SW26010/dance-trail.git
cd dance-trail
uv sync --locked
uv run --locked python main.py webui
```

Your browser opens at **<http://127.0.0.1:8787/home>**. Keep the terminal running
while using DanceTrail; press **Ctrl+C** in that terminal to stop it.

The built browser interface is included in the repository. You do not need
Node.js or pnpm just to run the app from source.

### First session

1. Open **Settings** and check the VRChat log directory. The standard Windows
   location is detected automatically; set a custom path if needed.
2. Open **Data Operations** and sync the WannaDance catalog to populate track
   names and the catalog browser.
3. Return to **Home**, start the **watcher**, and play a supported dance in VRChat.
4. Open **Timeline** to review the session. Records marked *Pending* or
   *Needs attention* are not counted in normal history until accepted.

The watcher normally starts at the end of the current log, so it records new
activity. To bring in older sessions, use the VRCX import in **Data Operations**.
VRCX is optional for live log capture.

If you dance past midnight, set the **dance day boundary** in Settings to keep
late-night activity in the day you prefer.

### Using a portable build

If you have a built portable ZIP, extract the **whole folder** to a writable
location and open **`DanceTrail.exe`**. Python is not required for that build.
The browser interface opens automatically, and the app remains in the system
tray. Closing the browser tab does not stop the app; choose **Exit** from the tray menu.

Keep the `_internal` folder beside the executable. Use `DanceTrailCli.exe` if
you prefer command-line tools.

## Find your way around

| Page | Use it to |
| --- | --- |
| **Home** | Check live playback and start or stop the watcher and overlay. |
| **Timeline** | Browse sessions by day and accept or exclude playback records. |
| **Catalog** | Search tracks and mark favorites or tracks you want to learn. |
| **Lists** | View local lists of planned self-picked dances. |
| **Insights** | Explore your history and recommendations. |
| **Data Operations** | Sync the catalog and import supported local data. |
| **Settings** | Set paths, startup options, and your dance day boundary. |

## OBS overlay

1. Start DanceTrail and enable the watcher and overlay from **Home**.
2. In OBS, add a **Browser Source** with this URL:

   ```text
   http://127.0.0.1:8787/overlay
   ```

3. Keep DanceTrail running while using the overlay.

The overlay shows the current playback. *Waiting for playback* means it is
ready but has no current track; *Overlay inactive* means overlay publication
is stopped. If you use a custom Web UI port, use that port in the OBS URL too.

## Data and privacy

Your history and settings are stored locally, under the application folder:

| Location | Contents |
| --- | --- |
| `config/dance-trail.local.json` | Your saved settings and paths. |
| `data/` | Playback history, local catalog data, and lists. |
| `logs/` | Captured logs and diagnostic output. |

Close DanceTrail before backing up or moving the application folder. Keep
`config/` and `data/` to preserve your settings and history. If you configured
paths outside that folder, back up those locations too. Captured logs may
contain player names, identifiers, and activity details; review them before
sharing a bug report.

The interface listens only on your own computer. Catalog synchronization
contacts external services and needs an internet connection. DanceTrail does
not automatically migrate configuration or databases from its former product
name.

See [application folders and configuration](docs/app_directories.md) for custom
paths and backup details.

## Supported sources and current limits

DanceTrail supports recording from **WannaDance (Wanna)**, **PyPyDance (PyPy)**,
and **DuDu FitDance (DuDu)**:

| Dance system | Live recording from VRChat logs | VRCX history import |
| --- | --- | --- |
| **WannaDance** | Supported | Supported |
| **PyPyDance** | Supported for recognized playback logs and URLs | Supported for recognized URLs |
| **DuDu FitDance** | Supported for recognized playback logs and URLs | Experimental URL recognition |

WannaDance also provides the catalog integration for browsing and searching
tracks. Recording support for PyPyDance and DuDu does not include full catalog
synchronization for those systems.

- Capture depends on the information present in VRChat logs. A detected play
  is not proof that you completed the dance; review uncertain records in
  Timeline.
- Support for one dance system does not imply support for every world or video
  player that uses it.

## Optional command-line tools

From the source folder:

```powershell
# Preview a VRCX history import before applying it
uv run --locked python main.py import-vrcx --dry-run

# Add a manual record using a WannaDance track ID
uv run --locked python main.py log --system wannadance 5038

# Suggest ten tracks
uv run --locked python main.py recommend -n 10

# List available commands
uv run --locked python main.py
```

In a portable build, replace `uv run --locked python main.py` with
`.\DanceTrailCli.exe`. Command-specific options are available with `--help`.

## Help and development

For a problem or suggestion, [open an issue](https://github.com/SW26010/dance-trail/issues).
Include the app version, what you expected, and steps to reproduce the problem.
Remove personal information from any logs you attach.

- [Build a Windows portable package](docs/portable_release.md)
- [Application folders and configuration](docs/app_directories.md)
- [VRCX import details](docs/vrcx_integration_notes.md)
- [WannaDance catalog synchronization](docs/wanna_catalog_sync.md)
- [Data model and design](docs/dance_data_model.md)
- [Web UI build and accessibility checks](docs/accessibility/webui-release-checklist.md)

## License

[MIT](LICENSE) · Copyright © 2026 Himalia.

Third-party dependencies retain their own licenses. Portable builds include
notices in `Legal/`; see [license packaging](legal/README.md). The project license
does not grant rights to third-party music, videos, or external catalog data.
