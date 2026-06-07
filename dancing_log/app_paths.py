"""Application-root path and local configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import sys
from typing import Any


CONFIG_FILENAME = "dancing-log.local.json"
EXAMPLE_CONFIG_FILENAME = "dancing-log.example.json"


def default_app_root() -> Path:
    """Return the root used for resolving app-relative paths."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class AppPaths:
    app_root: Path

    @classmethod
    def from_root(cls, app_root: Path | str | None = None) -> "AppPaths":
        root = Path(app_root) if app_root is not None else default_app_root()
        return cls(root.resolve())

    @property
    def config_dir(self) -> Path:
        return self.app_root / "config"

    @property
    def data_dir(self) -> Path:
        return self.app_root / "data"

    @property
    def logs_dir(self) -> Path:
        return self.app_root / "logs"

    @property
    def analysis_dir(self) -> Path:
        return self.app_root / "analysis"

    @property
    def local_config_file(self) -> Path:
        return self.config_dir / CONFIG_FILENAME

    @property
    def example_config_file(self) -> Path:
        return self.config_dir / EXAMPLE_CONFIG_FILENAME

    @property
    def legacy_local_config_file(self) -> Path:
        return self.data_dir / "local_config.json"

    @property
    def db_file(self) -> Path:
        return self.data_dir / "dancing_log.sqlite3"

    @property
    def queued_self_dir(self) -> Path:
        return self.data_dir / "queued_self"

    @property
    def capture_dir(self) -> Path:
        return self.logs_dir / "captures"

    @property
    def run_log_dir(self) -> Path:
        return self.logs_dir / "runs"

    @property
    def source_vrc_log_dir(self) -> Path:
        return self.logs_dir / "source-vrc-logs"

    @property
    def recording_frames_dir(self) -> Path:
        return self.analysis_dir / "recording_frames"


PATHS = AppPaths.from_root()
APP_ROOT = PATHS.app_root
CONFIG_DIR = PATHS.config_dir
CONFIG_FILE = PATHS.local_config_file
LEGACY_CONFIG_FILE = PATHS.legacy_local_config_file
DATA_DIR = PATHS.data_dir
DB_FILE = PATHS.db_file
LOGS_DIR = PATHS.logs_dir
ANALYSIS_DIR = PATHS.analysis_dir
QUEUED_SELF_DIR = PATHS.queued_self_dir
DEFAULT_CAPTURE_ROOT = PATHS.capture_dir
RUN_LOG_DIR = PATHS.run_log_dir
SOURCE_VRC_LOG_DIR = PATHS.source_vrc_log_dir
RECORDING_FRAMES_DIR = PATHS.recording_frames_dir


DEFAULT_CONFIG: dict[str, Any] = {
    "config_version": 1,
    "app_db": "data/dancing_log.sqlite3",
    "queued_self_dir": "data/queued_self",
    "capture_dir": "logs/captures",
    "run_log_dir": "logs/runs",
    "source_vrc_log_dir": "logs/source-vrc-logs",
    "recording_frames_dir": "analysis/recording_frames",
    "self_user_id": None,
    "vrcx_db_path": None,
    "vrc_log_dir": None,
    "wanna_cache_dir": None,
    "recordings_dir": None,
}


def resolve_app_path(
    value: Path | str | None,
    default: Path | str,
    *,
    app_root: Path | str | None = None,
) -> Path:
    """Resolve a path using app-root-relative semantics."""
    selected: Path | str = default if value in (None, "") else value
    path = Path(os.path.expandvars(os.path.expanduser(str(selected))))
    if path.is_absolute():
        return path
    root = Path(app_root) if app_root is not None else APP_ROOT
    return root / path


def load_app_config(
    path: Path | str | None = None,
    *,
    app_root: Path | str | None = None,
    migrate_legacy: bool = False,
) -> dict[str, Any]:
    """Load local app configuration, with one-way compatibility for legacy data config."""
    paths = AppPaths.from_root(app_root)
    config_path = Path(path) if path is not None else paths.local_config_file
    legacy_path = paths.legacy_local_config_file

    if config_path.exists():
        config = _read_config(config_path)
    elif path is None and legacy_path.exists():
        config = _read_config(legacy_path)
        if migrate_legacy:
            save_app_config(config, app_root=paths.app_root)
    else:
        config = {}

    return normalize_config(config)


def save_app_config(
    config: dict[str, Any],
    path: Path | str | None = None,
    *,
    app_root: Path | str | None = None,
) -> Path:
    """Write normalized local app configuration to the current config directory."""
    paths = AppPaths.from_root(app_root)
    config_path = Path(path) if path is not None else paths.local_config_file
    config_path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_config(config)
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(normalized, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return config_path


def normalize_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a config containing only supported keys and defaults."""
    if not isinstance(raw, dict):
        raise ValueError("App config must be a JSON object")

    config = dict(DEFAULT_CONFIG)
    for key in DEFAULT_CONFIG:
        if key in raw:
            config[key] = raw[key]
    config["config_version"] = 1
    return config


def _read_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"App config must be a JSON object: {path}")
    return raw
