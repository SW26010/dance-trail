"""Controlled bulk data-operation workflows."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Callable

from dancing_log.app_paths import AppRuntimeConfig
from dancing_log.local_config import CONFIG_FILE


DEFAULT_COMMAND_PREFIX = "uv run python main.py"
DEFAULT_QUEUED_SYSTEM = "wannadance"


class DataOperationError(ValueError):
    """Raised when a data operation cannot be configured safely."""


@dataclass(frozen=True)
class OperationParameter:
    key: str
    label: str
    value_type: str
    summary: str
    default: Any = None
    required: bool = False
    flag: str | None = None
    config_key: str | None = None
    choices: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        parameter = {
            "key": self.key,
            "label": self.label,
            "type": self.value_type,
            "summary": self.summary,
            "default": self.default,
            "required": self.required,
        }
        if self.flag is not None:
            parameter["flag"] = self.flag
        if self.config_key is not None:
            parameter["default_config_key"] = self.config_key
        if self.choices:
            parameter["choices"] = list(self.choices)
        return parameter


@dataclass(frozen=True)
class DataOperation:
    key: str
    title: str
    cli_description: str
    risk: str
    summary: str
    command_args: tuple[str, ...]
    title_zh: str
    risk_zh: str
    summary_zh: str
    parameters: tuple[OperationParameter, ...] = ()

    def command(self, command_prefix: str = DEFAULT_COMMAND_PREFIX) -> str:
        return " ".join((command_prefix, *self.command_args))

    def as_dict(self, command_prefix: str = DEFAULT_COMMAND_PREFIX) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "command": self.command(command_prefix),
            "risk": self.risk,
            "summary": self.summary,
            "parameters": [parameter.as_dict() for parameter in self.parameters],
            "text": {
                "zh": {
                    "title": self.title_zh,
                    "risk": self.risk_zh,
                    "summary": self.summary_zh,
                }
            },
        }


@dataclass(frozen=True)
class DataOperationRequest:
    operation_key: str
    params: dict[str, Any]


@dataclass(frozen=True)
class DataOperationResult:
    operation_key: str
    title: str
    status: str
    summary: str
    lines: tuple[str, ...]
    metrics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation_key": self.operation_key,
            "title": self.title,
            "status": self.status,
            "summary": self.summary,
            "lines": list(self.lines),
            "metrics": _json_safe_value(self.metrics),
        }


APP_DB_PARAMETER = OperationParameter(
    key="app_db",
    label="App database",
    value_type="path",
    flag="--app-db",
    config_key="app_db",
    summary="SQLite runtime state to read or write; defaults to the Saved Configuration.",
)

DATA_OPERATIONS: tuple[DataOperation, ...] = (
    DataOperation(
        key="import-vrcx",
        title="Import VRCX history",
        cli_description="Import historical playback rows from VRCX SQLite",
        risk="writes playback history",
        summary="Import supported dance playback rows from the saved, supplied, or standard VRCX SQLite database.",
        command_args=("import-vrcx",),
        title_zh="导入 VRCX 历史",
        risk_zh="写入播放历史",
        summary_zh="从已保存或指定的 VRCX SQLite 数据库导入支持的舞蹈播放记录。",
        parameters=(
            OperationParameter(
                key="vrcx_db",
                label="VRCX database",
                value_type="path",
                flag="<vrcx_db>",
                config_key="vrcx_db_path",
                summary="Source VRCX SQLite database; defaults to Saved Configuration, then the standard VRCX path.",
            ),
            APP_DB_PARAMETER,
            OperationParameter(
                key="self_user_id",
                label="Self VRChat user ID",
                value_type="text",
                flag="--self-user-id",
                config_key="self_user_id",
                summary="Used to infer self-picked playback when VRCX requester data is present.",
            ),
            OperationParameter(
                key="blank_requester_source",
                label="Blank requester source",
                value_type="choice",
                flag="--blank-requester-source",
                default="random",
                choices=("unknown", "random"),
                summary="Source to infer when VRCX requester fields are blank.",
            ),
            OperationParameter(
                key="limit",
                label="Row limit",
                value_type="integer",
                flag="--limit",
                summary="Maximum candidate rows to import.",
            ),
            OperationParameter(
                key="dry_run",
                label="Dry run",
                value_type="boolean",
                flag="--dry-run",
                default=False,
                summary="Scan without writing to the app database.",
            ),
        ),
    ),
    DataOperation(
        key="sync-wanna",
        title="Sync WannaDance catalog",
        cli_description="Sync WannaDance tracks into SQLite",
        risk="updates catalog rows",
        summary="Refresh the local WannaDance Catalog rows from the public API, local cache, or both.",
        command_args=("sync-wanna",),
        title_zh="同步 WannaDance 目录",
        risk_zh="更新目录记录",
        summary_zh="从公开 API、本地缓存或两者刷新本地 WannaDance 目录记录。",
        parameters=(
            APP_DB_PARAMETER,
            OperationParameter(
                key="cache_dir",
                label="WannaDance cache",
                value_type="path",
                flag="--cache-dir",
                config_key="wanna_cache_dir",
                summary="Local WannaDance cache directory used for offline metadata.",
            ),
            OperationParameter(
                key="offline",
                label="Offline",
                value_type="boolean",
                flag="--offline",
                default=False,
                summary="Use local cache only and skip the public API.",
            ),
            OperationParameter(
                key="write_files",
                label="Write files",
                value_type="boolean",
                flag="--write-files",
                default=False,
                summary="Also export generated catalog CSV and JSON artifacts.",
            ),
        ),
    ),
    DataOperation(
        key="sync-queued-self",
        title="Sync queued-self manifests",
        cli_description="Sync queued_self manifests",
        risk="updates planned-list derived rows",
        summary="Apply queued-self Markdown manifests as source overrides on existing playback events.",
        command_args=("sync-queued-self", "--system", DEFAULT_QUEUED_SYSTEM),
        title_zh="同步自选队列清单",
        risk_zh="更新清单派生记录",
        summary_zh="把 queued-self Markdown 清单应用为既有播放记录的来源覆盖。",
        parameters=(
            APP_DB_PARAMETER,
            OperationParameter(
                key="manifest_dir",
                label="Manifest directory",
                value_type="path",
                flag="--manifest-dir",
                config_key="queued_self_dir",
                summary="Directory containing queued-self Markdown manifests.",
            ),
            OperationParameter(
                key="system",
                label="Default dance system",
                value_type="text",
                flag="--system",
                default=DEFAULT_QUEUED_SYSTEM,
                summary="Dance system key for bare manifest IDs.",
            ),
        ),
    ),
    DataOperation(
        key="rebuild-data",
        title="Rebuild generated data",
        cli_description="Archive and rebuild generated local data",
        risk="archives and recreates generated database state",
        summary="Archive generated data files, then rebuild Catalog, VRCX history, and queued-self derived state.",
        command_args=("rebuild-data", "--archive-existing"),
        title_zh="重建生成数据",
        risk_zh="归档并重建生成的数据库状态",
        summary_zh="先归档生成数据文件，再重建目录、VRCX 历史和 queued-self 派生状态。",
        parameters=(
            OperationParameter(
                key="archive_existing",
                label="Archive existing data",
                value_type="boolean",
                flag="--archive-existing",
                default=False,
                required=True,
                summary="Required confirmation before generated files are moved aside.",
            ),
            OperationParameter(
                key="offline",
                label="Offline",
                value_type="boolean",
                flag="--offline",
                default=False,
                summary="Use local WannaDance cache only.",
            ),
            APP_DB_PARAMETER,
            OperationParameter(
                key="limit_vrcx",
                label="VRCX row limit",
                value_type="integer",
                flag="--limit-vrcx",
                summary="Maximum VRCX rows to import during rebuild.",
            ),
            OperationParameter(
                key="queued_system",
                label="Queued-self default system",
                value_type="text",
                flag="--queued-system",
                default=DEFAULT_QUEUED_SYSTEM,
                summary="Dance system key for bare queued-self manifest IDs.",
            ),
        ),
    ),
)

DATA_OPERATION_BY_KEY = {operation.key: operation for operation in DATA_OPERATIONS}
DataOperationRunner = Callable[[DataOperation, AppRuntimeConfig, dict[str, Any]], DataOperationResult]


def list_data_operations() -> tuple[DataOperation, ...]:
    return DATA_OPERATIONS


def operation_catalog_snapshot(command_prefix: str = DEFAULT_COMMAND_PREFIX) -> dict[str, Any]:
    return {
        "operations": [
            operation.as_dict(command_prefix=command_prefix)
            for operation in DATA_OPERATIONS
        ]
    }


def operation_cli_descriptions() -> dict[str, str]:
    return {
        operation.key: operation.cli_description
        for operation in DATA_OPERATIONS
    }


def data_operation_arg_parser(
    key: str,
    *,
    prog: str | None = None,
) -> argparse.ArgumentParser:
    operation = _require_operation(key)
    parser = argparse.ArgumentParser(prog=prog, description=operation.cli_description)
    for parameter in operation.parameters:
        _add_cli_parameter(parser, parameter)

    if key == "sync-wanna":
        parser.add_argument(
            "--no-files",
            action="store_true",
            dest="_no_files",
            help=argparse.SUPPRESS,
        )
    return parser


def parse_data_operation_cli_request(
    key: str,
    argv: list[str],
    *,
    prog: str | None = None,
) -> tuple[DataOperationRequest, argparse.ArgumentParser]:
    parser = data_operation_arg_parser(key, prog=prog)
    namespace = parser.parse_args(argv)
    params = vars(namespace)
    if key == "sync-wanna" and params.pop("_no_files", False):
        params["write_files"] = False
    try:
        request = build_data_operation_request(key, params)
    except DataOperationError as exc:
        parser.error(str(exc))
    return request, parser


def build_data_operation_request(
    key: str,
    params: dict[str, Any] | None = None,
) -> DataOperationRequest:
    operation = _require_operation(str(key or ""))
    raw_params = dict(params or {})
    parameter_by_key = {parameter.key: parameter for parameter in operation.parameters}
    unknown_keys = sorted(set(raw_params) - set(parameter_by_key))
    if unknown_keys:
        joined = ", ".join(unknown_keys)
        raise DataOperationError(f"Unknown parameter(s) for {operation.key}: {joined}")

    normalized: dict[str, Any] = {}
    for parameter in operation.parameters:
        value = _normalize_parameter_value(parameter, raw_params.get(parameter.key))
        if value is None and parameter.default is not None:
            value = parameter.default
        if parameter.required:
            _validate_required_parameter(parameter, value)
        if value is not None:
            normalized[parameter.key] = value

    return DataOperationRequest(operation_key=operation.key, params=normalized)


def build_data_operation_request_from_payload(payload: dict[str, Any]) -> DataOperationRequest:
    if not isinstance(payload, dict):
        raise DataOperationError("request body must be a JSON object")
    key = payload.get("operation") or payload.get("operation_key") or payload.get("key")
    if not isinstance(key, str) or not key:
        raise DataOperationError("Missing data operation key")
    params = payload.get("parameters", payload.get("params", {}))
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise DataOperationError("operation parameters must be a JSON object")
    return build_data_operation_request(key, params)


def run_data_operation(
    key: str,
    *,
    config: AppRuntimeConfig | None = None,
    **params: Any,
) -> DataOperationResult:
    request = build_data_operation_request(key, params)
    return run_data_operation_request(request, config=config)


def run_data_operation_request(
    request: DataOperationRequest,
    *,
    config: AppRuntimeConfig | None = None,
) -> DataOperationResult:
    operation = _require_operation(request.operation_key)
    runtime_config = config or AppRuntimeConfig.load(migrate_legacy=True)
    return _RUNNERS[operation.key](operation, runtime_config, dict(request.params))


def _run_import_vrcx(
    operation: DataOperation,
    config: AppRuntimeConfig,
    params: dict[str, Any],
) -> DataOperationResult:
    vrcx_db_path = config.resolve_vrcx_db_path(override=params.get("vrcx_db"))
    if not vrcx_db_path:
        raise DataOperationError(
            "Missing VRCX database path. Pass it explicitly, set "
            f"`vrcx_db_path` in {CONFIG_FILE}, or install VRCX at the standard "
            "%APPDATA%\\VRCX\\VRCX.sqlite3 location."
        )

    from dancing_log.vrcx_importer import import_vrcx_database

    dry_run = bool(params.get("dry_run", False))
    stats = import_vrcx_database(
        vrcx_db_path=vrcx_db_path,
        app_db_path=config.path("app_db", override=params.get("app_db")),
        self_user_id=_pick_value(params.get("self_user_id"), config.self_user_id),
        blank_requester_source=params.get("blank_requester_source") or "random",
        limit=_optional_int(params.get("limit"), "limit"),
        dry_run=dry_run,
    )

    lines = [
        "VRCX dry run complete" if dry_run else "VRCX import complete",
        f"  scanned candidate rows: {stats.scanned}",
        f"  candidate events: {stats.candidate_events}",
        f"  skipped unsupported URLs: {stats.skipped_unsupported}",
    ]
    if not dry_run:
        lines.extend(
            [
                f"  staging inserts/updates: {stats.staging_changed}",
                f"  dance_events inserts/updates: {stats.dance_events_changed}",
            ]
        )

    return _result(
        operation,
        status="dry-run" if dry_run else "completed",
        summary=lines[0],
        lines=lines,
        metrics={"import_vrcx": asdict(stats)},
    )


def _run_sync_wanna(
    operation: DataOperation,
    config: AppRuntimeConfig,
    params: dict[str, Any],
) -> DataOperationResult:
    from dancing_log.wanna_catalog import sync_wanna_catalog

    stats = sync_wanna_catalog(
        config=config,
        db_path=config.path("app_db", override=params.get("app_db")),
        cache_dir=config.optional_path("wanna_cache_dir", override=params.get("cache_dir")),
        use_api=not bool(params.get("offline", False)),
        write_files=bool(params.get("write_files", False)),
    )
    source = "API + cache" if stats.used_api else "cache only"
    lines = [
        "WannaDance catalog sync complete",
        f"  source: {source}",
        f"  API songs: {stats.api_count}",
        f"  cached songs: {stats.cache_count}",
        f"  database tracks before: {stats.db_before}",
        f"  database tracks after: {stats.db_after}",
        f"  inserted: {stats.inserted}",
        f"  updated/touched: {stats.updated}",
        f"  catalog rows without local cache: {stats.missing_in_cache}",
    ]
    return _result(
        operation,
        status="completed",
        summary=lines[0],
        lines=lines,
        metrics={"sync_wanna": asdict(stats), "source": source},
    )


def _run_sync_queued_self(
    operation: DataOperation,
    config: AppRuntimeConfig,
    params: dict[str, Any],
) -> DataOperationResult:
    from dancing_log.queued_self_importer import sync_queued_self_manifests

    stats = sync_queued_self_manifests(
        app_db_path=config.path("app_db", override=params.get("app_db")),
        manifest_dir=config.path("queued_self_dir", override=params.get("manifest_dir")),
        system_key=params.get("system") or params.get("system_key") or DEFAULT_QUEUED_SYSTEM,
    )
    lines = [
        "queued_self sync complete",
        f"  scanned files: {stats.files_scanned}",
        f"  manifest entries: {stats.entries_seen}",
        f"  entries with track ref: {stats.entries_with_track_ref}",
        f"  entries without track ref: {stats.entries_without_track_ref}",
        f"  matched entries: {stats.matched_entries}",
        f"  unmatched entries: {stats.unmatched_entries}",
        f"  existing events updated: {stats.existing_events_updated}",
        f"  stale manifest events deleted: {stats.stale_manifest_events_deleted}",
    ]
    return _result(
        operation,
        status="completed",
        summary=lines[0],
        lines=lines,
        metrics={"sync_queued_self": asdict(stats)},
    )


def _run_rebuild_data(
    operation: DataOperation,
    config: AppRuntimeConfig,
    params: dict[str, Any],
) -> DataOperationResult:
    if not bool(params.get("archive_existing", False)):
        raise DataOperationError("--archive-existing is required to avoid accidental data loss")

    from dancing_log.queued_self_importer import sync_queued_self_manifests
    from dancing_log.rebuild import archive_existing_data
    from dancing_log.vrcx_importer import import_vrcx_database
    from dancing_log.wanna_catalog import sync_wanna_catalog

    db_path = config.path("app_db", override=params.get("app_db"))
    archive = archive_existing_data(data_dir=config.paths.data_dir, app_db_path=db_path)
    lines = [f"Archived generated data to: {archive.archive_dir}"]
    lines.extend(f"  {path.name}" for path in archive.archived)

    sync_stats = sync_wanna_catalog(
        config=config,
        db_path=db_path,
        cache_dir=config.wanna_cache_dir,
        use_api=not bool(params.get("offline", False)),
    )
    lines.extend(
        [
            "WannaDance catalog sync complete",
            f"  database tracks after: {sync_stats.db_after}",
        ]
    )

    vrcx_db_path = config.resolve_vrcx_db_path()
    import_stats = None
    if vrcx_db_path:
        import_stats = import_vrcx_database(
            vrcx_db_path=vrcx_db_path,
            app_db_path=db_path,
            self_user_id=config.self_user_id,
            limit=_optional_int(params.get("limit_vrcx"), "limit_vrcx"),
        )
        lines.extend(
            [
                "VRCX import complete",
                f"  dance_events inserts/updates: {import_stats.dance_events_changed}",
                f"  skipped unsupported URLs: {import_stats.skipped_unsupported}",
            ]
        )
    else:
        lines.append("VRCX import skipped: no saved or standard VRCX database path found")

    queued_stats = sync_queued_self_manifests(
        app_db_path=db_path,
        manifest_dir=config.queued_self_dir,
        system_key=params.get("queued_system") or DEFAULT_QUEUED_SYSTEM,
    )
    lines.extend(
        [
            "queued_self sync complete",
            f"  matched entries: {queued_stats.matched_entries}",
            f"  unmatched entries: {queued_stats.unmatched_entries}",
        ]
    )

    metrics = {
        "archive": {
            "archive_dir": archive.archive_dir,
            "archived": archive.archived,
        },
        "sync_wanna": asdict(sync_stats),
        "sync_queued_self": asdict(queued_stats),
    }
    if import_stats is not None:
        metrics["import_vrcx"] = asdict(import_stats)

    return _result(
        operation,
        status="completed",
        summary="Rebuild generated data complete",
        lines=lines,
        metrics=metrics,
    )


def _require_operation(key: str) -> DataOperation:
    try:
        return DATA_OPERATION_BY_KEY[key]
    except KeyError as exc:
        raise DataOperationError(f"Unknown data operation: {key}") from exc


def _add_cli_parameter(
    parser: argparse.ArgumentParser,
    parameter: OperationParameter,
) -> None:
    kwargs: dict[str, Any] = {
        "default": None,
        "help": _cli_parameter_help(parameter),
    }
    if _is_positional_parameter(parameter):
        kwargs["nargs"] = "?" if not parameter.required else None
        parser.add_argument(parameter.key, **{key: value for key, value in kwargs.items() if value is not None})
        return

    if parameter.value_type == "boolean":
        kwargs["action"] = "store_true"
    parser.add_argument(parameter.flag or f"--{parameter.key.replace('_', '-')}", **kwargs)


def _is_positional_parameter(parameter: OperationParameter) -> bool:
    return bool(parameter.flag and parameter.flag.startswith("<") and parameter.flag.endswith(">"))


def _cli_parameter_help(parameter: OperationParameter) -> str:
    parts = [parameter.summary]
    if parameter.config_key:
        parts.append(f"Falls back to {CONFIG_FILE} `{parameter.config_key}` when omitted.")
    if parameter.choices:
        parts.append(f"Choices: {', '.join(parameter.choices)}.")
    if parameter.default not in (None, False):
        parts.append(f"Default: {parameter.default}.")
    return " ".join(parts)


def _normalize_parameter_value(parameter: OperationParameter, value: Any) -> Any:
    if parameter.value_type == "boolean":
        return _normalize_bool(value, parameter.key)
    if value in (None, ""):
        return None
    if parameter.value_type == "integer":
        return _normalize_int(value, parameter.key)
    if parameter.value_type == "choice":
        text = str(value)
        if parameter.choices and text not in parameter.choices:
            joined = ", ".join(parameter.choices)
            raise DataOperationError(f"{parameter.key} must be one of: {joined}")
        return text
    if parameter.value_type in {"path", "text"}:
        return str(value)
    return value


def _normalize_bool(value: Any, key: str) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise DataOperationError(f"{key} must be true or false")


def _normalize_int(value: Any, key: str) -> int:
    if isinstance(value, bool):
        raise DataOperationError(f"{key} must be an integer")
    if isinstance(value, float) and not value.is_integer():
        raise DataOperationError(f"{key} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise DataOperationError(f"{key} must be an integer") from exc


def _validate_required_parameter(parameter: OperationParameter, value: Any) -> None:
    if parameter.value_type == "boolean":
        if value is not True:
            raise DataOperationError(f"{parameter.flag or parameter.key} is required")
        return
    if value in (None, ""):
        raise DataOperationError(f"{parameter.flag or parameter.key} is required")


def _result(
    operation: DataOperation,
    *,
    status: str,
    summary: str,
    lines: list[str],
    metrics: dict[str, Any],
) -> DataOperationResult:
    return DataOperationResult(
        operation_key=operation.key,
        title=operation.title,
        status=status,
        summary=summary,
        lines=tuple(lines),
        metrics=metrics,
    )


def _pick_value(cli_value: Any, config_value: Any) -> Any:
    return cli_value if cli_value is not None else config_value


def _optional_int(value: Any, key: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise DataOperationError(f"{key} must be an integer") from exc


def _json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _json_safe_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    return str(value)


_RUNNERS: dict[str, DataOperationRunner] = {
    "import-vrcx": _run_import_vrcx,
    "sync-wanna": _run_sync_wanna,
    "sync-queued-self": _run_sync_queued_self,
    "rebuild-data": _run_rebuild_data,
}
