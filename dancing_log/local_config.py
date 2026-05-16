"""Local machine-specific configuration stored under data/."""

from __future__ import annotations

from pathlib import Path
import json

from dancing_log.storage import DATA_DIR


CONFIG_FILE = DATA_DIR / "local_config.json"

DEFAULT_CONFIG = {
    "self_user_id": None,
    "vrcx_db_path": None,
    "wanna_cache_dir": None,
    "recordings_dir": None,
}


def load_local_config(path: Path | str | None = None) -> dict:
    """Load local config, returning defaults when the file is missing."""
    config_path = Path(path) if path is not None else CONFIG_FILE
    config = dict(DEFAULT_CONFIG)
    if not config_path.exists():
        return config

    with open(config_path, encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Local config must be a JSON object: {config_path}")

    for key in DEFAULT_CONFIG:
        if key in raw:
            config[key] = raw[key]
    return config


def save_local_config(
    config: dict,
    path: Path | str | None = None,
) -> Path:
    """Write a normalized local config file."""
    config_path = Path(path) if path is not None else CONFIG_FILE
    config_path.parent.mkdir(parents=True, exist_ok=True)

    normalized = dict(DEFAULT_CONFIG)
    for key in DEFAULT_CONFIG:
        if key in config:
            normalized[key] = config[key]

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=True, indent=2)
        f.write("\n")

    return config_path
