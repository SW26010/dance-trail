"""dancing-log command-line entrypoint."""

from pathlib import Path, PureWindowsPath
import subprocess
import sys

from dancing_log.app_paths import AppRuntimeConfig, resolve_app_path
from dancing_log.data_operations import (
    DataOperationError,
    operation_cli_descriptions,
    parse_data_operation_cli_request,
    run_data_operation_request,
)
from dancing_log.local_config import CONFIG_FILE


def _get_runtime_config() -> AppRuntimeConfig:
    return AppRuntimeConfig.load(migrate_legacy=True)


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _executable_name() -> str:
    executable = str(sys.executable)
    if "\\" in executable or ":" in executable:
        return PureWindowsPath(executable).name
    return Path(executable).name


def _is_desktop_tray_entry() -> bool:
    return _is_frozen() and PureWindowsPath(_executable_name()).stem.casefold() == "dancinglog"


def _command_prefix() -> str:
    if _is_frozen():
        if _is_desktop_tray_entry():
            return "DancingLogCli.exe"
        return _executable_name()
    return "uv run python main.py"


def _configured_path(cli_value, config: AppRuntimeConfig, key: str) -> Path:
    return config.path(key, override=cli_value)


def _configured_db_path(cli_value, config: AppRuntimeConfig) -> Path:
    return _configured_path(cli_value, config, "app_db")


def _print_data_operation_result(result) -> None:
    for line in result.lines:
        print(line)


def _run_data_operation_command(key: str) -> None:
    request, parser = parse_data_operation_cli_request(key, sys.argv[2:])
    try:
        result = run_data_operation_request(request, config=_get_runtime_config())
    except DataOperationError as exc:
        parser.error(str(exc))
    _print_data_operation_result(result)


def _resolve_recording_path(recording, recordings_dir, app_root=None) -> Path:
    recording_path = Path(recording)
    if recording_path.is_absolute():
        return recording_path

    app_relative = resolve_app_path(recording_path, recording_path, app_root=app_root)
    if recordings_dir:
        candidate = (
            resolve_app_path(recordings_dir, recordings_dir, app_root=app_root)
            / recording_path
        )
        if candidate.exists():
            return candidate
    return app_relative


def cmd_sync_wanna():
    """Sync WannaDance tracks into SQLite."""
    _run_data_operation_command("sync-wanna")


def cmd_recommend():
    """Generate the daily recommendation playlist."""
    import argparse

    config = _get_runtime_config()
    parser = argparse.ArgumentParser(description="Generate daily recommendation playlist")
    parser.add_argument("-n", "--count", type=int, default=20, help="Number of dance tracks to recommend")
    parser.add_argument("--app-db", default=None, help="SQLite path")
    args = parser.parse_args(sys.argv[2:])
    db_path = _configured_db_path(args.app_db, config)

    from dancing_log.models import generate_daily_playlist, load_dance_log, load_dance_tracks

    tracks = load_dance_tracks(db_path)
    if not tracks:
        print(f"Error: dance_tracks table is empty. Run `{_command_prefix()} sync-wanna` first.")
        sys.exit(1)

    dance_log = load_dance_log(db_path)
    playlist = generate_daily_playlist(tracks, dance_log, count=args.count)

    print(f"Daily playlist (Top {args.count}):\n")
    for i, track in enumerate(playlist, 1):
        fav = "*" if track.get("favorite") in ("1", "true", True, 1) else " "
        want = "+" if track.get("want_to_learn") in ("1", "true", True, 1) else " "
        count = track.get("_dance_count", 0)
        days = track.get("_days_since_last")
        days_str = f"{days}d ago" if days is not None else "never"
        title = track.get("title") or "(untitled)"
        artist = track.get("artist") or ""
        track_ref = f"{track['system_key']}:{track['external_id']}"

        print(
            f"  {i:>3}. [{track_ref}] {fav}{want} {title} - {artist}"
            f"  w={track['_weight']:.1f}  danced {count}x  {days_str}"
        )


def cmd_day():
    """Print accepted playback history for one local day."""
    import argparse
    from datetime import date

    config = _get_runtime_config()
    parser = argparse.ArgumentParser(description="Print accepted playback history for one local day")
    parser.add_argument("date", help="Local date in YYYY-MM-DD format")
    parser.add_argument("--app-db", default=None, help="SQLite path")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Read live-derived accepted playback records only",
    )
    args = parser.parse_args(sys.argv[2:])

    try:
        target_date = date.fromisoformat(args.date)
    except ValueError:
        parser.error("date must use YYYY-MM-DD format")

    db_path = _configured_db_path(args.app_db, config)
    from dancing_log.daily_report import (
        format_daily_dance_line,
        load_daily_dances,
        load_daily_live_dances,
    )

    loader = load_daily_live_dances if args.live else load_daily_dances
    for dance in loader(target_date, db_path):
        print(format_daily_dance_line(dance))


def cmd_log():
    """Append one dance log record."""
    import argparse

    config = _get_runtime_config()
    parser = argparse.ArgumentParser(description="Add one dance log record")
    parser.add_argument("--system", required=True, help="Dance system key, for example wannadance")
    parser.add_argument("--app-db", default=None, help="SQLite path")
    parser.add_argument("external_id", help="External id in the selected dance system")
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--other", action="store_true", help="Picked by someone else")
    source_group.add_argument(
        "--source",
        type=str,
        choices=["queued_self", "recommend", "self", "other", "random", "unknown"],
        default=None,
        help="Playback source",
    )
    parser.add_argument("--time", type=str, default=None, help="ISO 8601 timestamp")
    parser.add_argument("--note", type=str, default="", help="Optional note")
    args = parser.parse_args(sys.argv[2:])
    db_path = _configured_db_path(args.app_db, config)

    from dancing_log.models import (
        SOURCE_LABELS,
        SOURCE_OTHER,
        SOURCE_SELF,
        add_dance_record,
    )
    from dancing_log.storage import get_dance_track

    track = get_dance_track(args.system, args.external_id, db_path)
    if track and (track.get("title") or track.get("artist")):
        print(f"Recording: {track['title']} - {track['artist']}")
    else:
        print(
            f"Warning: {args.system}:{args.external_id} is not in dance_tracks, "
            "continuing with a placeholder track."
        )

    if args.other:
        source = SOURCE_OTHER
        auto_detect = False
    elif args.source:
        source = args.source
        auto_detect = False
    else:
        source = SOURCE_SELF
        auto_detect = True

    actual_source = add_dance_record(
        system_key=args.system,
        external_id=args.external_id,
        source=source,
        note=args.note,
        timestamp=args.time,
        auto_detect=auto_detect,
        db_path=db_path,
    )
    print(
        f"Added dance record ({args.system}:{args.external_id}, "
        f"{SOURCE_LABELS.get(actual_source, actual_source)})"
    )


def cmd_import_favorites():
    """Import favorite flags from a text file."""
    import argparse

    config = _get_runtime_config()
    parser = argparse.ArgumentParser(description="Import favorite dance tracks from a text file")
    parser.add_argument(
        "favorites_file",
        help="UTF-8 text file: one external id per line, or WannaFavorite:id,id,...",
    )
    parser.add_argument("--system", required=True, help="Dance system key, for example wannadance")
    parser.add_argument("--app-db", default=None, help="SQLite path")
    parser.add_argument(
        "--additive",
        action="store_true",
        help="Only add favorites; default replaces the system's favorite list",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate and report changes without writing")
    args = parser.parse_args(sys.argv[2:])
    db_path = _configured_db_path(args.app_db, config)
    favorites_file = config.resolve_path(args.favorites_file)

    from dancing_log.favorite_importer import FavoriteImportError, import_favorites_file

    try:
        stats = import_favorites_file(
            system_key=args.system,
            favorites_file=favorites_file,
            app_db_path=db_path,
            additive=args.additive,
            dry_run=args.dry_run,
        )
    except FavoriteImportError as exc:
        parser.error(str(exc))

    print("Favorite import dry run complete" if stats.dry_run else "Favorite import complete")
    print(f"  system: {stats.system_key}")
    print(f"  mode: {'additive' if stats.additive else 'replace'}")
    print(f"  dry run: {'yes' if stats.dry_run else 'no'}")
    print(f"  input IDs: {stats.input_ids}")
    print(f"  unique IDs: {stats.unique_ids}")
    print(f"  duplicate IDs: {stats.duplicate_ids}")
    print(f"  favorites set: {stats.favorites_set}")
    print(f"  favorites cleared: {stats.favorites_cleared}")


def cmd_import_vrcx():
    """Import historical playback rows from VRCX SQLite."""
    _run_data_operation_command("import-vrcx")


def cmd_sync_queued_self():
    """Overlay queued-self manifests onto existing events."""
    _run_data_operation_command("sync-queued-self")


def cmd_sample_recording_frames():
    """Sample top-cropped frames from a recording for overlay checks."""
    import argparse

    config = _get_runtime_config()
    parser = argparse.ArgumentParser(description="Sample top-cropped frames from a recording")
    parser.add_argument(
        "recording",
        help="Recording file path; relative paths are resolved against recordings_dir when configured",
    )
    parser.add_argument("--output-dir", default=None, help="Output directory")
    parser.add_argument(
        "--at",
        nargs="+",
        type=float,
        default=[60.0, 300.0, 600.0],
        help="Timestamps in seconds",
    )
    parser.add_argument("--top-ratio", type=float, default=0.22, help="Top crop ratio")
    parser.add_argument("--width", type=int, default=1920, help="Output width")
    args = parser.parse_args(sys.argv[2:])
    output_dir = _configured_path(args.output_dir, config, "recording_frames_dir")

    recording_path = _resolve_recording_path(
        args.recording,
        config.get("recordings_dir"),
        app_root=config.app_root,
    )

    from dancing_log.recordings import sample_top_frames

    outputs = sample_top_frames(
        recording_path=recording_path,
        output_dir=output_dir,
        timestamps=args.at,
        top_ratio=args.top_ratio,
        width=args.width,
    )

    print("Sampled frames:")
    for path in outputs:
        print(f"  {path}")


def cmd_watch_vrc_log():
    """Capture live VRChat output logs for video playback forensics."""
    import argparse

    parser = argparse.ArgumentParser(description="Watch VRChat output logs for video playback lines")
    parser.add_argument(
        "--log-dir",
        default=None,
        help=f"VRChat log directory; falls back to {CONFIG_FILE} or the default LocalLow path",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Capture root directory; default is logs/captures",
    )
    parser.add_argument("--session-name", default=None, help="Capture session directory name")
    parser.add_argument(
        "--from-start",
        action="store_true",
        help="Read the current log file from the beginning instead of tailing from EOF",
    )
    parser.add_argument(
        "--no-raw",
        action="store_true",
        help="Do not mirror all raw log lines; candidate and parsed JSONL files are still written",
    )
    parser.add_argument(
        "--source-log-dir",
        default=None,
        help="Directory for byte-for-byte source output_log_*.txt archives",
    )
    parser.add_argument(
        "--no-source-archive",
        action="store_true",
        help="Do not incrementally archive source VRChat output logs",
    )
    parser.add_argument("--app-db", default=None, help="SQLite path for live DB writes")
    parser.add_argument(
        "--live-db",
        action="store_true",
        help="Upsert folded playback state into live_playback_events",
    )
    parser.add_argument(
        "--promote-live",
        action="store_true",
        help="Promote eligible live events into dance_events; implies --live-db",
    )
    parser.add_argument(
        "--overlay-port",
        type=int,
        default=None,
        help="Start a local OBS overlay server on 127.0.0.1 at this port",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=0.25,
        help="Polling interval while waiting for new lines",
    )
    parser.add_argument(
        "--stop-after-idle-seconds",
        type=float,
        default=None,
        help="Stop after this many seconds without new lines; default runs until Ctrl+C",
    )
    args = parser.parse_args(sys.argv[2:])

    from dancing_log.live_app_session import LiveAppSessionRuntime, LiveWatcherRunOptions

    options = LiveWatcherRunOptions(
        log_dir=args.log_dir,
        output_dir=args.output_dir,
        session_name=args.session_name,
        source_log_dir=args.source_log_dir,
        app_db_path=args.app_db,
        from_start=args.from_start,
        include_raw=not args.no_raw,
        live_db=args.live_db,
        promote_live=args.promote_live,
        overlay_port=args.overlay_port,
        poll_seconds=args.poll_seconds,
        stop_after_idle_seconds=args.stop_after_idle_seconds,
        archive_source_logs=not args.no_source_archive,
    )
    runtime = LiveAppSessionRuntime(migrate_legacy_config=True)
    print(f"Watching VRChat logs: {runtime.resolved_log_dir(options)}")
    print("Press Ctrl+C to stop.")

    stats = runtime.run_watcher(options)

    print("VRChat log capture complete")
    print(f"  session dir: {stats.session_dir}")
    print(f"  raw lines: {stats.raw_lines}")
    print(f"  candidate lines: {stats.candidate_lines}")
    print(f"  parsed events: {stats.parsed_events}")
    print(f"  playback events: {stats.playback_events}")
    if stats.live_db_updates:
        print(f"  live DB updates: {stats.live_db_updates}")
    if args.promote_live:
        print(f"  live promotions: {stats.live_promotions}")
    if stats.overlay_url:
        print(f"  overlay URL: {stats.overlay_url}")
    if stats.source_log_dir:
        print(f"  source log archive: {stats.source_log_dir}")
        print(f"  source log bytes copied: {stats.source_log_bytes}")
    if stats.delay_metrics:
        print(
            "  delay to actual play: "
            f"count={stats.delay_metrics.get('count')} "
            f"avg={stats.delay_metrics.get('avg_seconds')}s "
            f"min={stats.delay_metrics.get('min_seconds')}s "
            f"max={stats.delay_metrics.get('max_seconds')}s"
        )
    print(f"  summary: {stats.session_dir / 'summary.json'}")


def cmd_webui():
    """Start the local Web UI server."""
    import argparse

    parser = argparse.ArgumentParser(description="Start the local dancing-log Web UI")
    parser.add_argument("--port", type=int, default=8787, help="Localhost port")
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the system browser after starting",
    )
    args = parser.parse_args(sys.argv[2:])

    from dancing_log.webui_server import run_webui_server

    run_webui_server(port=args.port, open_browser=not args.no_open)


def run_desktop_tray_entry():
    """Run the frozen desktop tray entry."""
    from dancing_log.tray_app import run_tray_webui_app

    run_tray_webui_app()


def cmd_rebuild_data():
    """Archive generated local data and rebuild the current SQLite database."""
    _run_data_operation_command("rebuild-data")


def main():
    if _is_desktop_tray_entry() and len(sys.argv) < 2:
        run_desktop_tray_entry()
        return

    operation_descriptions = operation_cli_descriptions()
    user_script_commands = {}
    user_builtin_commands = {
        "sync-wanna": (operation_descriptions["sync-wanna"], cmd_sync_wanna),
        "recommend": ("Generate daily recommendation playlist", cmd_recommend),
        "day": ("Print accepted playback history for one local day", cmd_day),
        "log": ("Append one dance log record", cmd_log),
        "import-favorites": ("Import favorite track flags from text", cmd_import_favorites),
        "import-vrcx": (operation_descriptions["import-vrcx"], cmd_import_vrcx),
        "sync-queued-self": (operation_descriptions["sync-queued-self"], cmd_sync_queued_self),
        "watch-vrc-log": ("Capture live VRChat output logs", cmd_watch_vrc_log),
        "webui": ("Start the local Web UI", cmd_webui),
        "rebuild-data": (operation_descriptions["rebuild-data"], cmd_rebuild_data),
    }
    research_script_commands = {}
    if not _is_frozen():
        research_script_commands = {
            "scrape": ("Fetch Wanna Dance song metadata into local files", "scripts/scrape_wanna.py"),
            "test-apis": ("Test music APIs", "scripts/test_music_apis.py"),
        }
    research_builtin_commands = {}
    if not _is_frozen():
        research_builtin_commands = {
            "sample-frames": (
                "Sample overlay verification frames from a recording",
                cmd_sample_recording_frames,
            ),
        }

    script_commands = {**user_script_commands, **research_script_commands}
    builtin_commands = {**user_builtin_commands, **research_builtin_commands}

    all_names = list(script_commands) + list(builtin_commands)

    if len(sys.argv) < 2 or sys.argv[1] not in all_names:
        prefix = _command_prefix()
        print("dancing-log - local dance playback timeline toolkit\n")
        print(f"Usage: {prefix} <command> [args...]\n")
        print("User workflow:")
        for name, (desc, _) in {**user_script_commands, **user_builtin_commands}.items():
            print(f"  {name:<18} {desc}")
        if research_script_commands or research_builtin_commands:
            print("\nDevelopment/research:")
            for name, (desc, _) in {**research_script_commands, **research_builtin_commands}.items():
                print(f"  {name:<16} {desc}")
        print("\nExamples:")
        print(f"  {prefix} sync-wanna")
        print(f"  {prefix} log --system wannadance 5038")
        print(f"  {prefix} log --system wannadance 5038 --other")
        print(f"  {prefix} recommend -n 10")
        print(f"  {prefix} day 2026-06-07")
        print(f"  {prefix} day 2026-06-07 --live")
        print(f"  {prefix} import-favorites --system wannadance data/favorites.txt")
        print(f"  {prefix} import-vrcx path/to/vrcx-snapshot/VRCX.sqlite3")
        print(f"  {prefix} import-vrcx")
        print(f"  {prefix} sync-queued-self --system wannadance")
        print(f"  {prefix} watch-vrc-log")
        print(f"  {prefix} webui")
        print(f"  {prefix} rebuild-data --archive-existing")
        if not _is_frozen():
            print(f"  {prefix} scrape")
            print(f"  {prefix} sample-frames path/to/recordings/example.mkv --at 60 300")
        sys.exit(0 if len(sys.argv) < 2 else 2)

    cmd = sys.argv[1]
    if cmd in script_commands:
        _, script = script_commands[cmd]
        subprocess.run([sys.executable, script] + sys.argv[2:], check=False)
    else:
        _, func = builtin_commands[cmd]
        func()


if __name__ == "__main__":
    main()
