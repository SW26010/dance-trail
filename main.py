"""dancing-log command-line entrypoint."""

from pathlib import Path
import subprocess
import sys

from dancing_log.local_config import CONFIG_FILE, load_local_config


def _get_local_config() -> dict:
    return load_local_config()


def _pick_value(cli_value, config_value):
    return cli_value if cli_value is not None else config_value


def cmd_recommend():
    """Generate the daily recommendation playlist."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate daily recommendation playlist")
    parser.add_argument("-n", "--count", type=int, default=20, help="Number of dance tracks to recommend")
    args = parser.parse_args(sys.argv[2:])

    from dancing_log.models import generate_daily_playlist, load_dance_log, load_dance_tracks

    tracks = load_dance_tracks()
    if not tracks:
        print("Error: dance_tracks table is empty. Run `uv run python main.py sync-wanna` first.")
        sys.exit(1)

    dance_log = load_dance_log()
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


def cmd_log():
    """Append one dance log record."""
    import argparse

    parser = argparse.ArgumentParser(description="Add one dance log record")
    parser.add_argument("--system", required=True, help="Dance system key, for example wannadance")
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

    from dancing_log.models import (
        SOURCE_LABELS,
        SOURCE_OTHER,
        SOURCE_SELF,
        add_dance_record,
    )
    from dancing_log.storage import get_dance_track

    track = get_dance_track(args.system, args.external_id)
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
    )
    print(
        f"Added dance record ({args.system}:{args.external_id}, "
        f"{SOURCE_LABELS.get(actual_source, actual_source)})"
    )


def cmd_import_favorites():
    """Import favorite flags from a text file."""
    import argparse

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

    from dancing_log.favorite_importer import FavoriteImportError, import_favorites_file

    try:
        stats = import_favorites_file(
            system_key=args.system,
            favorites_file=args.favorites_file,
            app_db_path=args.app_db,
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
    import argparse

    config = _get_local_config()
    parser = argparse.ArgumentParser(description="Import historical playback rows from VRCX SQLite")
    parser.add_argument(
        "vrcx_db",
        nargs="?",
        default=None,
        help="Path to VRCX.sqlite3; falls back to data/local_config.json when omitted",
    )
    parser.add_argument("--app-db", default=None, help="Output app SQLite path")
    parser.add_argument(
        "--self-user-id",
        default=None,
        help="Local VRChat user id; falls back to data/local_config.json when omitted",
    )
    parser.add_argument(
        "--blank-requester-source",
        choices=["unknown", "random"],
        default="random",
        help="Source to infer when VRCX requester fields are blank",
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum candidate rows to import")
    parser.add_argument("--dry-run", action="store_true", help="Scan only, do not write to the app database")
    args = parser.parse_args(sys.argv[2:])

    vrcx_db_path = _pick_value(args.vrcx_db, config.get("vrcx_db_path"))
    self_user_id = _pick_value(args.self_user_id, config.get("self_user_id"))
    if not vrcx_db_path:
        parser.error(
            f"Missing VRCX database path. Pass it explicitly or set `vrcx_db_path` in {CONFIG_FILE}."
        )

    from dancing_log.vrcx_importer import import_vrcx_database

    stats = import_vrcx_database(
        vrcx_db_path=vrcx_db_path,
        app_db_path=args.app_db,
        self_user_id=self_user_id,
        blank_requester_source=args.blank_requester_source,
        limit=args.limit,
        dry_run=args.dry_run,
    )

    print("VRCX dry run complete" if args.dry_run else "VRCX import complete")
    print(f"  scanned candidate rows: {stats.scanned}")
    print(f"  candidate events: {stats.candidate_events}")
    print(f"  skipped unsupported URLs: {stats.skipped_unsupported}")
    if not args.dry_run:
        print(f"  staging inserts/updates: {stats.staging_changed}")
        print(f"  dance_events inserts/updates: {stats.dance_events_changed}")


def cmd_sync_queued_self():
    """Overlay queued-self manifests onto existing events."""
    import argparse

    parser = argparse.ArgumentParser(description="Sync queued_self Markdown manifests")
    parser.add_argument("--app-db", default=None, help="SQLite path")
    parser.add_argument("--manifest-dir", default=None, help="Manifest directory")
    parser.add_argument("--system", required=True, help="Dance system key for bare manifest ids")
    args = parser.parse_args(sys.argv[2:])

    from dancing_log.queued_self_importer import sync_queued_self_manifests

    stats = sync_queued_self_manifests(
        app_db_path=args.app_db,
        manifest_dir=args.manifest_dir,
        system_key=args.system,
    )

    print("queued_self sync complete")
    print(f"  scanned files: {stats.files_scanned}")
    print(f"  manifest entries: {stats.entries_seen}")
    print(f"  entries with track ref: {stats.entries_with_track_ref}")
    print(f"  entries without track ref: {stats.entries_without_track_ref}")
    print(f"  matched entries: {stats.matched_entries}")
    print(f"  unmatched entries: {stats.unmatched_entries}")
    print(f"  existing events updated: {stats.existing_events_updated}")
    print(f"  stale manifest events deleted: {stats.stale_manifest_events_deleted}")


def cmd_sample_recording_frames():
    """Sample top-cropped frames from a recording for overlay checks."""
    import argparse

    config = _get_local_config()
    parser = argparse.ArgumentParser(description="Sample top-cropped frames from a recording")
    parser.add_argument(
        "recording",
        help="Recording file path; relative paths are resolved against recordings_dir when configured",
    )
    parser.add_argument("--output-dir", default="analysis/recording_frames", help="Output directory")
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

    recording_path = Path(args.recording)
    recordings_dir = config.get("recordings_dir")
    if not recording_path.is_absolute() and recordings_dir:
        candidate = Path(recordings_dir) / recording_path
        if candidate.exists():
            recording_path = candidate

    from dancing_log.recordings import sample_top_frames

    outputs = sample_top_frames(
        recording_path=recording_path,
        output_dir=args.output_dir,
        timestamps=args.at,
        top_ratio=args.top_ratio,
        width=args.width,
    )

    print("Sampled frames:")
    for path in outputs:
        print(f"  {path}")


def cmd_rebuild_data():
    """Archive generated local data and rebuild the current SQLite database."""
    import argparse

    parser = argparse.ArgumentParser(description="Archive old generated data and rebuild local SQLite")
    parser.add_argument(
        "--archive-existing",
        action="store_true",
        help="Required: archive generated data files before rebuilding",
    )
    parser.add_argument("--offline", action="store_true", help="Use local WannaDance cache only")
    parser.add_argument("--limit-vrcx", type=int, default=None, help="Limit imported VRCX rows")
    parser.add_argument(
        "--queued-system",
        default="wannadance",
        help="Dance system key for bare queued_self manifest ids",
    )
    args = parser.parse_args(sys.argv[2:])

    if not args.archive_existing:
        parser.error("--archive-existing is required to avoid accidental data loss")

    config = _get_local_config()
    from dancing_log.queued_self_importer import sync_queued_self_manifests
    from dancing_log.rebuild import archive_existing_data
    from dancing_log.vrcx_importer import import_vrcx_database
    from dancing_log.wanna_catalog import sync_wanna_catalog

    archive = archive_existing_data()
    print(f"Archived generated data to: {archive.archive_dir}")
    for path in archive.archived:
        print(f"  {path.name}")

    sync_stats = sync_wanna_catalog(use_api=not args.offline)
    print("WannaDance catalog sync complete")
    print(f"  database tracks after: {sync_stats.db_after}")

    vrcx_db_path = config.get("vrcx_db_path")
    if vrcx_db_path:
        import_stats = import_vrcx_database(
            vrcx_db_path=vrcx_db_path,
            self_user_id=config.get("self_user_id"),
            limit=args.limit_vrcx,
        )
        print("VRCX import complete")
        print(f"  dance_events inserts/updates: {import_stats.dance_events_changed}")
        print(f"  skipped unsupported URLs: {import_stats.skipped_unsupported}")
    else:
        print("VRCX import skipped: vrcx_db_path is not configured")

    queued_stats = sync_queued_self_manifests(system_key=args.queued_system)
    print("queued_self sync complete")
    print(f"  matched entries: {queued_stats.matched_entries}")
    print(f"  unmatched entries: {queued_stats.unmatched_entries}")


def main():
    script_commands = {
        "scrape": ("Fetch Wanna Dance song metadata", "scripts/scrape_wanna.py"),
        "sync-wanna": ("Sync WannaDance tracks into SQLite", "scripts/sync_wanna_songs.py"),
        "test-apis": ("Test music APIs", "scripts/test_music_apis.py"),
    }
    builtin_commands = {
        "recommend": ("Generate daily recommendation playlist", cmd_recommend),
        "log": ("Append one dance log record", cmd_log),
        "import-favorites": ("Import favorite track flags from text", cmd_import_favorites),
        "import-vrcx": ("Import historical playback rows from VRCX SQLite", cmd_import_vrcx),
        "sync-queued-self": ("Sync queued_self manifests", cmd_sync_queued_self),
        "sample-frames": ("Sample overlay verification frames from a recording", cmd_sample_recording_frames),
        "rebuild-data": ("Archive and rebuild generated local data", cmd_rebuild_data),
    }

    all_names = list(script_commands) + list(builtin_commands)

    if len(sys.argv) < 2 or sys.argv[1] not in all_names:
        print("dancing-log - local dance playback timeline toolkit\n")
        print("Usage: uv run python main.py <command> [args...]\n")
        print("Data collection:")
        for name, (desc, _) in script_commands.items():
            print(f"  {name:<16} {desc}")
        print("\nDaily workflow:")
        for name, (desc, _) in builtin_commands.items():
            print(f"  {name:<16} {desc}")
        print("\nExamples:")
        print("  uv run python main.py scrape")
        print("  uv run python main.py sync-wanna")
        print("  uv run python main.py log --system wannadance 5038")
        print("  uv run python main.py log --system wannadance 5038 --other")
        print("  uv run python main.py recommend -n 10")
        print("  uv run python main.py import-favorites --system wannadance data/favorites.txt")
        print("  uv run python main.py import-vrcx path/to/vrcx-snapshot/VRCX.sqlite3")
        print("  uv run python main.py import-vrcx")
        print("  uv run python main.py sync-queued-self --system wannadance")
        print("  uv run python main.py rebuild-data --archive-existing")
        print("  uv run python main.py sample-frames path/to/recordings/example.mkv --at 60 300")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd in script_commands:
        _, script = script_commands[cmd]
        subprocess.run([sys.executable, script] + sys.argv[2:], check=False)
    else:
        _, func = builtin_commands[cmd]
        func()


if __name__ == "__main__":
    main()
