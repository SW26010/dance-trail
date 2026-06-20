"""Settings read/write interface for the Local Web UI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

from dancing_log.app_paths import (
    AppRuntimeConfig,
    AppPaths,
    CONFIG_FIELD_BY_KEY,
    CONFIG_FIELDS,
    CONFIG_KEYS,
    resolve_config_path,
    save_app_config,
    validate_supported_config,
)
from dancing_log.vrc_log_watcher import default_vrc_log_dir
from dancing_log.windows_picker import pick_windows_path


class WebUiSettingsRuntime(Protocol):
    app_root: Path

    @property
    def paths(self) -> AppPaths: ...


def load_config_snapshot(runtime: WebUiSettingsRuntime) -> dict:
    """Return saved configuration plus editor metadata."""
    raw = _read_saved_config(runtime)
    config = AppRuntimeConfig.load(app_root=runtime.app_root)
    unsupported = {
        key: value
        for key, value in raw.items()
        if key not in CONFIG_KEYS
    }
    warnings = []
    if unsupported:
        warnings.append("Unsupported keys are preserved as read-only values.")

    return {
        "app_root": str(runtime.app_root),
        "config_path": str(runtime.paths.local_config_file),
        "config": config.supported_values(),
        "fields": [_field_snapshot(field, config.get(field["key"]), runtime) for field in CONFIG_FIELDS],
        "unsupported": unsupported,
        "detected_sources": _detected_source_paths(),
        "warnings": warnings,
    }


def save_config_from_payload(runtime: WebUiSettingsRuntime, payload: dict) -> tuple[dict, int]:
    """Validate and save supported config fields while preserving unsupported keys."""
    draft = payload.get("config")
    if not isinstance(draft, dict):
        return {"errors": {"config": "config must be a JSON object"}}, 400

    supported, errors = validate_supported_config(draft)
    if errors:
        return {"errors": errors, "snapshot": load_config_snapshot(runtime)}, 400

    existing = _read_saved_config(runtime)
    merged = dict(existing)
    for key in CONFIG_KEYS:
        merged[key] = supported[key]
    save_app_config(merged, app_root=runtime.app_root)
    return {"saved": True, "snapshot": load_config_snapshot(runtime)}, 200


def pick_path_from_payload(runtime: WebUiSettingsRuntime, payload: dict) -> tuple[dict, int]:
    """Open a field-driven native Windows file/folder picker."""
    field_key = str(payload.get("field") or "")
    field = CONFIG_FIELD_BY_KEY.get(field_key)
    if not field or field.get("type") != "path":
        return {"error": "unsupported path field"}, 400
    if os.name != "nt":
        return {"error": "native picker is only available on Windows"}, 501

    current_value = payload.get("current_value")
    initial = _path_value_preview(field, current_value, runtime).get("resolved")
    selected = pick_windows_path(field, initial)
    if selected is None:
        return {"cancelled": True}, 200
    path = Path(selected)
    if not path.exists():
        return {"error": "selected path does not exist"}, 400
    if field.get("picker") == "directory" and not path.is_dir():
        return {"error": "selected path is not a directory"}, 400
    if field.get("picker") == "file" and not path.is_file():
        return {"error": "selected path is not a file"}, 400
    return {"field": field_key, "value": str(path)}, 200


def resolve_path_from_payload(runtime: WebUiSettingsRuntime, payload: dict) -> tuple[dict, int]:
    """Resolve a draft path value for Settings preview without saving it."""
    field_key = str(payload.get("field") or "")
    field = CONFIG_FIELD_BY_KEY.get(field_key)
    if not field or field.get("type") != "path":
        return {"error": "unsupported path field"}, 400
    return {
        "field": field_key,
        "path": _path_value_preview(field, payload.get("current_value"), runtime),
    }, 200


def _field_snapshot(field: dict[str, Any], value: Any, runtime: WebUiSettingsRuntime) -> dict:
    snapshot = dict(field)
    snapshot["value"] = value
    if field.get("type") == "path":
        snapshot["path"] = _path_value_preview(field, value, runtime)
    return snapshot


def _path_value_preview(field: dict[str, Any], value: Any, runtime: WebUiSettingsRuntime) -> dict:
    resolved = resolve_config_path(field["key"], value, app_root=runtime.app_root)
    if resolved is None:
        return {"resolved": None, "exists": None}
    return _safe_path_preview(resolved)


def _read_saved_config(runtime: WebUiSettingsRuntime) -> dict:
    paths = runtime.paths
    config_path = paths.local_config_file
    if config_path.exists():
        return _read_json_file(config_path)
    legacy_path = paths.legacy_local_config_file
    if legacy_path.exists():
        return _read_json_file(legacy_path)
    return {}


def _read_json_file(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"config file must contain a JSON object: {path}")
    return raw


def _detected_source_paths() -> list[dict[str, Any]]:
    candidates = []
    try:
        vrc_log_dir = default_vrc_log_dir()
        preview = _safe_path_preview(vrc_log_dir)
        candidates.append(
            {
                "field": "vrc_log_dir",
                "label": "Default VRChat log directory",
                "value": str(vrc_log_dir),
                "exists": preview["exists"],
                "kind": preview["kind"],
                "error": preview.get("error"),
            }
        )
    except Exception:
        pass
    return candidates


def _safe_path_preview(path: Path) -> dict:
    try:
        exists = path.exists()
        if path.is_dir():
            kind = "directory"
        elif path.is_file():
            kind = "file"
        else:
            kind = "missing"
        return {"resolved": str(path), "exists": exists, "kind": kind}
    except OSError as exc:
        return {
            "resolved": str(path),
            "exists": False,
            "kind": "inaccessible",
            "error": str(exc),
        }
