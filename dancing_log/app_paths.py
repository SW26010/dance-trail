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


@dataclass(frozen=True)
class ConfigField:
    key: str
    default: Any
    label: str
    group: str
    field_type: str
    required: bool
    summary: str
    picker: str | None = None
    placeholder: str | None = None
    minimum: int | None = None
    maximum: int | None = None

    def as_dict(self) -> dict[str, Any]:
        field = {
            "key": self.key,
            "label": self.label,
            "group": self.group,
            "type": self.field_type,
            "required": self.required,
            "summary": self.summary,
        }
        if self.picker is not None:
            field["picker"] = self.picker
        if self.placeholder is not None:
            field["placeholder"] = self.placeholder
        if self.minimum is not None:
            field["min"] = self.minimum
        if self.maximum is not None:
            field["max"] = self.maximum
        return field


_CONFIG_FIELD_SPECS: tuple[ConfigField, ...] = (
    ConfigField(
        key="config_version",
        default=1,
        label="Config version",
        group="System",
        field_type="readonly",
        required=True,
        summary="Local config schema version.",
    ),
    ConfigField(
        key="app_db",
        default="data/dancing_log.sqlite3",
        label="App database",
        group="Internal app paths",
        field_type="path",
        picker="file",
        required=True,
        summary="SQLite runtime state.",
    ),
    ConfigField(
        key="queued_self_dir",
        default="data/queued_self",
        label="Queued-self directory",
        group="Internal app paths",
        field_type="path",
        picker="directory",
        required=True,
        summary="Markdown manifests for planned self-picked dances.",
    ),
    ConfigField(
        key="capture_dir",
        default="logs/captures",
        label="Capture directory",
        group="Internal app paths",
        field_type="path",
        picker="directory",
        required=True,
        summary="Live watcher capture output.",
    ),
    ConfigField(
        key="run_log_dir",
        default="logs/runs",
        label="Run log directory",
        group="Internal app paths",
        field_type="path",
        picker="directory",
        required=True,
        summary="Normal app run logs.",
    ),
    ConfigField(
        key="source_vrc_log_dir",
        default="logs/source-vrc-logs",
        label="Source VRChat archive",
        group="Internal app paths",
        field_type="path",
        picker="directory",
        required=True,
        summary="Byte-for-byte source output_log archives.",
    ),
    ConfigField(
        key="recording_frames_dir",
        default="analysis/recording_frames",
        label="Recording frame directory",
        group="Internal app paths",
        field_type="path",
        picker="directory",
        required=True,
        summary="Top-cropped frame samples for analysis.",
    ),
    ConfigField(
        key="self_user_id",
        default=None,
        label="Self VRChat user ID",
        group="External sources",
        field_type="text",
        required=False,
        placeholder="usr_00000000-0000-0000-0000-000000000000",
        summary="Used to infer whether a historical VRCX requester is self.",
    ),
    ConfigField(
        key="vrcx_db_path",
        default=None,
        label="VRCX database",
        group="External sources",
        field_type="path",
        picker="file",
        required=False,
        summary="VRCX playback history SQLite file.",
    ),
    ConfigField(
        key="vrc_log_dir",
        default=None,
        label="VRChat log directory",
        group="External sources",
        field_type="path",
        picker="directory",
        required=False,
        summary="Directory containing VRChat output_log files.",
    ),
    ConfigField(
        key="wanna_cache_dir",
        default=None,
        label="WannaDance cache",
        group="External sources",
        field_type="path",
        picker="directory",
        required=False,
        summary="Local WannaDance cache for offline catalog sync.",
    ),
    ConfigField(
        key="recordings_dir",
        default=None,
        label="Recordings directory",
        group="External sources",
        field_type="path",
        picker="directory",
        required=False,
        summary="Recording files used by sample-frame tools.",
    ),
    ConfigField(
        key="auto_start_watcher",
        default=False,
        label="Auto-start watcher",
        group="Runtime defaults",
        field_type="boolean",
        required=True,
        summary="Default preference for app workflows that start live capture.",
    ),
    ConfigField(
        key="auto_start_overlay",
        default=False,
        label="Auto-start overlay",
        group="Runtime defaults",
        field_type="boolean",
        required=True,
        summary="If enabled, watcher auto-start is also enabled.",
    ),
    ConfigField(
        key="overlay_port",
        default=8765,
        label="Standalone overlay port",
        group="Advanced",
        field_type="integer",
        required=True,
        minimum=1,
        maximum=65535,
        summary="Localhost port used only when the watcher serves an overlay without the Web UI.",
    ),
)

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


DEFAULT_CONFIG: dict[str, Any] = {field.key: field.default for field in _CONFIG_FIELD_SPECS}
CONFIG_KEYS = tuple(DEFAULT_CONFIG)
CONFIG_FIELDS: tuple[dict[str, Any], ...] = tuple(field.as_dict() for field in _CONFIG_FIELD_SPECS)
CONFIG_FIELD_BY_KEY = {field["key"]: field for field in CONFIG_FIELDS}
PATH_FIELD_KEYS = {
    field["key"]
    for field in CONFIG_FIELDS
    if field.get("type") == "path"
}


def default_vrcx_db_path() -> Path:
    """Return the intentionally narrow standard VRCX SQLite location."""
    appdata = os.environ.get("APPDATA")
    root = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return root / "VRCX" / "VRCX.sqlite3"


def detect_vrcx_db_path() -> Path | None:
    """Return the standard VRCX database only when it currently exists."""
    candidate = default_vrcx_db_path()
    try:
        return candidate if candidate.is_file() else None
    except OSError:
        return None


@dataclass(frozen=True)
class WatcherRuntimeConfig:
    log_dir: Path
    output_dir: Path
    app_db_path: Path
    source_log_dir: Path
    overlay_port: int


@dataclass(frozen=True)
class AppRuntimeConfig:
    """Saved configuration resolved against one application root."""

    app_root: Path
    config: dict[str, Any]

    @classmethod
    def load(
        cls,
        path: Path | str | None = None,
        *,
        app_root: Path | str | None = None,
        migrate_legacy: bool = False,
    ) -> "AppRuntimeConfig":
        paths = AppPaths.from_root(app_root)
        config = load_app_config(path, app_root=paths.app_root, migrate_legacy=migrate_legacy)
        return cls(paths.app_root, config)

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any],
        *,
        app_root: Path | str | None = None,
    ) -> "AppRuntimeConfig":
        paths = AppPaths.from_root(app_root)
        return cls(paths.app_root, normalize_config(config))

    @property
    def paths(self) -> AppPaths:
        return AppPaths.from_root(self.app_root)

    @property
    def app_db_path(self) -> Path:
        return self.path("app_db")

    @property
    def queued_self_dir(self) -> Path:
        return self.path("queued_self_dir")

    @property
    def capture_dir(self) -> Path:
        return self.path("capture_dir")

    @property
    def run_log_dir(self) -> Path:
        return self.path("run_log_dir")

    @property
    def source_vrc_log_dir(self) -> Path:
        return self.path("source_vrc_log_dir")

    @property
    def recording_frames_dir(self) -> Path:
        return self.path("recording_frames_dir")

    @property
    def vrcx_db_path(self) -> Path | None:
        return self.optional_path("vrcx_db_path")

    def resolve_vrcx_db_path(
        self,
        *,
        override: Path | str | None = None,
        auto_detect: bool = True,
    ) -> Path | None:
        configured = self.optional_path("vrcx_db_path", override=override)
        if configured is not None:
            return configured
        if not auto_detect:
            return None
        return detect_vrcx_db_path()

    @property
    def vrc_log_dir(self) -> Path | None:
        return self.optional_path("vrc_log_dir")

    @property
    def wanna_cache_dir(self) -> Path | None:
        return self.optional_path("wanna_cache_dir")

    @property
    def recordings_dir(self) -> Path | None:
        return self.optional_path("recordings_dir")

    @property
    def self_user_id(self) -> str | None:
        return self.config.get("self_user_id")

    @property
    def overlay_port(self) -> int:
        return int(self.config.get("overlay_port") or DEFAULT_CONFIG["overlay_port"])

    @property
    def auto_start_watcher(self) -> bool:
        return bool(self.config.get("auto_start_watcher"))

    @property
    def auto_start_overlay(self) -> bool:
        return bool(self.config.get("auto_start_overlay"))

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def supported_values(self) -> dict[str, Any]:
        return {key: self.config.get(key) for key in CONFIG_KEYS}

    def path(self, key: str, *, override: Path | str | None = None) -> Path:
        if key not in PATH_FIELD_KEYS:
            raise KeyError(f"Not a configured path field: {key}")
        value = override if override is not None else self.config.get(key)
        default = self.config.get(key) or DEFAULT_CONFIG[key]
        if default is None:
            default = ""
        return resolve_app_path(value, default, app_root=self.app_root)

    def optional_path(
        self,
        key: str,
        *,
        override: Path | str | None = None,
    ) -> Path | None:
        if key not in PATH_FIELD_KEYS:
            raise KeyError(f"Not a configured path field: {key}")
        value = override if override is not None else self.config.get(key)
        if value in (None, ""):
            return None
        return resolve_app_path(value, value, app_root=self.app_root)

    def resolve_path(self, value: Path | str, default: Path | str | None = None) -> Path:
        return resolve_app_path(value, default if default is not None else value, app_root=self.app_root)

    def preview_path(self, key: str, value: Any) -> Path | None:
        return resolve_config_path(key, value, app_root=self.app_root)

    def watcher_config(
        self,
        *,
        default_log_dir: Path | str,
        log_dir: Path | str | None = None,
        output_dir: Path | str | None = None,
        source_log_dir: Path | str | None = None,
        app_db_path: Path | str | None = None,
    ) -> WatcherRuntimeConfig:
        resolved_log_dir = self.optional_path("vrc_log_dir", override=log_dir)
        if resolved_log_dir is None:
            resolved_log_dir = Path(default_log_dir)
        return WatcherRuntimeConfig(
            log_dir=resolved_log_dir,
            output_dir=self.path("capture_dir", override=output_dir),
            app_db_path=self.path("app_db", override=app_db_path),
            source_log_dir=self.path("source_vrc_log_dir", override=source_log_dir),
            overlay_port=self.overlay_port,
        )


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


def resolve_config_path(
    key: str,
    value: Any,
    *,
    app_root: Path | str | None = None,
) -> Path | None:
    """Resolve one saved config path value, preserving optional-path null semantics."""
    field = CONFIG_FIELD_BY_KEY.get(key)
    if not field or field.get("type") != "path":
        raise KeyError(f"Not a configured path field: {key}")
    if value in (None, "") and not field.get("required"):
        return None
    default = DEFAULT_CONFIG.get(key)
    if default is None:
        default = ""
    return resolve_app_path(value, default, app_root=app_root)


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
    """Return a config with supported defaults while preserving unknown keys."""
    if not isinstance(raw, dict):
        raise ValueError("App config must be a JSON object")

    config = dict(raw)
    for key in DEFAULT_CONFIG:
        if key not in config:
            config[key] = DEFAULT_CONFIG[key]
    config["config_version"] = 1
    if config.get("auto_start_overlay"):
        config["auto_start_watcher"] = True
    return config


def validate_supported_config(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Coerce supported config fields from a Settings draft without runtime checks."""
    config: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key, default in DEFAULT_CONFIG.items():
        field = CONFIG_FIELD_BY_KEY.get(key)
        value = raw.get(key, default)
        if key == "config_version":
            config[key] = 1
            continue
        if field is None:
            config[key] = value
            continue
        field_type = field.get("type")
        if field_type == "path":
            config[key] = _validate_path_field(field, value, errors)
        elif field_type == "text":
            config[key] = _validate_text_field(field, value, errors)
        elif field_type == "boolean":
            if isinstance(value, bool):
                config[key] = value
            else:
                errors[key] = "value must be true or false"
                config[key] = bool(default)
        elif field_type == "integer":
            config[key] = _validate_integer_field(field, value, errors)
        else:
            config[key] = value
    if config.get("auto_start_overlay"):
        config["auto_start_watcher"] = True
    return config, errors


def _validate_path_field(field: dict[str, Any], value: Any, errors: dict[str, str]) -> str | None:
    key = field["key"]
    if value is None or value == "":
        if field.get("required"):
            errors[key] = "path is required"
            return DEFAULT_CONFIG.get(key)
        return None
    if not isinstance(value, str):
        errors[key] = "path must be text"
        return DEFAULT_CONFIG.get(key)
    cleaned = value.strip()
    if not cleaned:
        if field.get("required"):
            errors[key] = "path is required"
            return DEFAULT_CONFIG.get(key)
        return None
    return cleaned


def _validate_text_field(field: dict[str, Any], value: Any, errors: dict[str, str]) -> str | None:
    key = field["key"]
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        errors[key] = "value must be text"
        return None
    return value.strip() or None


def _validate_integer_field(field: dict[str, Any], value: Any, errors: dict[str, str]) -> int:
    key = field["key"]
    default = int(DEFAULT_CONFIG[key])
    if isinstance(value, bool) or not isinstance(value, int):
        errors[key] = "value must be an integer"
        return default
    minimum = int(field.get("min", 1))
    maximum = int(field.get("max", 65535))
    if value < minimum or value > maximum:
        errors[key] = f"value must be between {minimum} and {maximum}"
        return default
    return value


def _read_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"App config must be a JSON object: {path}")
    return raw
