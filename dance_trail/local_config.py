"""Local machine-specific DanceTrail configuration."""

from __future__ import annotations

from pathlib import Path

from dance_trail.app_paths import (
    CONFIG_FILE,
    DEFAULT_CONFIG,
    load_app_config,
    save_app_config,
)

__all__ = ["CONFIG_FILE", "DEFAULT_CONFIG", "load_local_config", "save_local_config"]


def load_local_config(path: Path | str | None = None) -> dict:
    """Load local config, returning defaults when the file is missing.

    When called without an explicit path, this reads the current config location
    under config/. Existing configuration from other products is not imported.
    """
    return load_app_config(path)


def save_local_config(
    config: dict,
    path: Path | str | None = None,
) -> Path:
    """Write a normalized local config file."""
    return save_app_config(config, path)
