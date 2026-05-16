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
    parser.add_argument("-n", "--count", type=int, default=20, help="Number of songs to recommend")
    args = parser.parse_args(sys.argv[2:])

    from dancing_log.models import generate_daily_playlist, load_dance_log, load_songs

    songs = load_songs()
    if not songs:
        print("Error: songs data is empty. Run `uv run python main.py init` first.")
        sys.exit(1)

    dance_log = load_dance_log()
    playlist = generate_daily_playlist(songs, dance_log, count=args.count)

    print(f"Daily playlist (Top {args.count}):\n")
    for i, song in enumerate(playlist, 1):
        fav = "*" if song.get("favorite") in ("1", "true", True) else " "
        want = "+" if song.get("want_to_learn") in ("1", "true", True) else " "
        pop = song.get("popularity", "")
        pop_str = f"pop={pop}" if pop else ""
        count = song.get("_dance_count", 0)
        days = song.get("_days_since_last")
        days_str = f"{days}d ago" if days is not None else "never"

        print(
            f"  {i:>3}. [{song['id']:>5}] {fav}{want} {song['name']} - {song['artist']}"
            f"  w={song['_weight']:.1f}  {pop_str}  danced {count}x  {days_str}"
        )


def cmd_log():
    """Append one dance log record."""
    import argparse

    parser = argparse.ArgumentParser(description="Add one dance log record")
    parser.add_argument("song_id", type=int, help="Song ID")
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
        load_songs,
    )

    songs = load_songs()
    song = next((s for s in songs if str(s.get("id")) == str(args.song_id)), None)
    if song:
        print(f"Recording: {song['name']} - {song['artist']}")
    else:
        print(f"Warning: song id {args.song_id} is not in songs.csv, continuing anyway.")

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
        song_id=args.song_id,
        source=source,
        note=args.note,
        timestamp=args.time,
        auto_detect=auto_detect,
    )
    print(f"Added dance record (id={args.song_id}, {SOURCE_LABELS.get(actual_source, actual_source)})")


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
    print(f"  skipped without song id: {stats.skipped_without_song_id}")
    if not args.dry_run:
        print(f"  staging inserts/updates: {stats.staging_changed}")
        print(f"  dance_events inserts/updates: {stats.dance_events_changed}")


def cmd_sync_queued_self():
    """Overlay queued-self manifests onto existing events."""
    import argparse

    parser = argparse.ArgumentParser(description="Sync queued_self Markdown manifests")
    parser.add_argument("--app-db", default=None, help="SQLite path")
    parser.add_argument("--manifest-dir", default=None, help="Manifest directory")
    args = parser.parse_args(sys.argv[2:])

    from dancing_log.queued_self_importer import sync_queued_self_manifests

    stats = sync_queued_self_manifests(
        app_db_path=args.app_db,
        manifest_dir=args.manifest_dir,
    )

    print("queued_self sync complete")
    print(f"  scanned files: {stats.files_scanned}")
    print(f"  manifest entries: {stats.entries_seen}")
    print(f"  entries with song id: {stats.entries_with_song_id}")
    print(f"  entries without song id: {stats.entries_without_song_id}")
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


def main():
    script_commands = {
        "scrape": ("Fetch Wanna Dance song metadata", "scripts/scrape_wanna.py"),
        "match": ("Match NetEase popularity data", "scripts/match_netease.py"),
        "init": ("Build songs.csv from scraped data", "scripts/init_songs.py"),
        "test-apis": ("Test music APIs", "scripts/test_music_apis.py"),
    }
    builtin_commands = {
        "recommend": ("Generate daily recommendation playlist", cmd_recommend),
        "log": ("Append one dance log record", cmd_log),
        "import-vrcx": ("Import historical playback rows from VRCX SQLite", cmd_import_vrcx),
        "sync-queued-self": ("Sync queued_self manifests", cmd_sync_queued_self),
        "sample-frames": ("Sample overlay verification frames from a recording", cmd_sample_recording_frames),
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
        print("  uv run python main.py init")
        print("  uv run python main.py log 5038")
        print("  uv run python main.py log 5038 --other")
        print("  uv run python main.py recommend -n 10")
        print("  uv run python main.py import-vrcx path/to/vrcx-snapshot/VRCX.sqlite3")
        print("  uv run python main.py import-vrcx")
        print("  uv run python main.py sync-queued-self")
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
