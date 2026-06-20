import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from dancing_log.app_paths import save_app_config
from dancing_log.models import (
    SOURCE_RECOMMEND,
    add_dance_record,
    generate_daily_playlist,
)
from dancing_log.favorite_importer import FavoriteImportError, import_favorites_file
from dancing_log.queued_self_importer import sync_queued_self_manifests
from dancing_log.rebuild import archive_existing_data
from dancing_log.storage import (
    WANNA_SYSTEM_KEY,
    add_dance_event,
    connect_db,
    ensure_dance_track,
    load_dance_log,
    load_current_live_playback_event,
    load_dance_tracks,
    mark_live_playback_event_completed,
    make_live_playback_event_key,
    promote_live_playback_event,
    upsert_live_playback_event,
)
from dancing_log.vrcx_importer import import_vrcx_database
from dancing_log.wanna_catalog import sync_wanna_catalog, upsert_catalog


def favorite_map(db_path: Path | str) -> dict[tuple[str, str], int]:
    with connect_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT ds.key AS system_key, dt.external_id, dt.favorite
            FROM dance_tracks dt
            JOIN dance_systems ds ON ds.id = dt.system_id
            """
        ).fetchall()
    return {
        (row["system_key"], row["external_id"]): int(row["favorite"])
        for row in rows
    }


class SQLiteRuntimeTest(unittest.TestCase):
    def test_fresh_schema_uses_dance_tracks_not_legacy_songs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "app.sqlite3")
            with connect_db(db_path) as conn:
                tables = {
                    row["name"]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                dance_event_columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(dance_events)")
                }

            self.assertIn("dance_systems", tables)
            self.assertIn("dance_tracks", tables)
            self.assertIn("wannadance_songs", tables)
            self.assertIn("music_tracks", tables)
            self.assertIn("dance_track_music_links", tables)
            self.assertIn("live_playback_events", tables)
            self.assertNotIn("songs", tables)
            self.assertIn("dance_track_id", dance_event_columns)
            self.assertNotIn("song_id", dance_event_columns)

    def test_live_playback_upsert_is_idempotent_and_session_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.sqlite3"
            event = {
                "event_key": "wannadance:3114#1",
                "canonical_key": "wannadance:3114",
                "first_seen_at": "2026.05.17 15:30:00",
                "actual_play_at": None,
                "observed_mid_play": False,
                "video_url": "https://api.udon.dance/Api/Songs/play?id=3114",
                "dance_system_key": WANNA_SYSTEM_KEY,
                "dance_external_id": "3114",
                "video_name": "First Title",
                "source_type": "player",
                "source_display_name": "Alice",
                "signal_count": 1,
                "parser_names": ["video_playback_resolve"],
                "raw_event_types": ["resolve-attempt"],
            }

            key_one = make_live_playback_event_key("session-one", event["event_key"])
            key_two = make_live_playback_event_key("session-two", event["event_key"])
            self.assertNotEqual(key_one, key_two)

            with connect_db(db_path) as conn:
                row_id = upsert_live_playback_event(conn, event, session_id="session-one")
                event["video_name"] = "Updated Title"
                event["signal_count"] = 2
                self.assertEqual(
                    upsert_live_playback_event(conn, event, session_id="session-one"),
                    row_id,
                )
                conn.commit()
                rows = conn.execute("SELECT * FROM live_playback_events").fetchall()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["video_name"], "Updated Title")
            self.assertEqual(rows[0]["signal_count"], 2)
            self.assertEqual(json.loads(rows[0]["parser_names_json"]), ["video_playback_resolve"])
            current = load_current_live_playback_event(db_path)
            self.assertEqual(current["event"]["video_name"], "Updated Title")
            self.assertFalse(current["observed_mid_play"])

    def test_promote_live_playback_event_is_explicit_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.sqlite3"
            event = {
                "event_key": "wannadance:3114#1",
                "canonical_key": "wannadance:3114",
                "first_seen_at": "2026.05.17 15:30:00",
                "actual_play_at": "2026.05.17 15:30:10",
                "observed_mid_play": False,
                "duration_seconds": 2,
                "video_url": "https://api.udon.dance/Api/Songs/play?id=3114",
                "dance_system_key": WANNA_SYSTEM_KEY,
                "dance_external_id": "3114",
                "video_name": "Promoted Title",
                "source_type": "player",
                "source_display_name": "Alice",
                "signal_count": 3,
                "parser_names": ["usharp_delayed_video_ready"],
                "raw_event_types": ["actual-play"],
            }

            with connect_db(db_path) as conn:
                upsert_live_playback_event(conn, event, session_id="session-one")
                self.assertEqual(conn.execute("SELECT count(*) FROM dance_events").fetchone()[0], 0)
                live_key = make_live_playback_event_key("session-one", event["event_key"])
                self.assertIsNone(promote_live_playback_event(conn, live_key))
                self.assertTrue(
                    mark_live_playback_event_completed(
                        conn,
                        live_key,
                        completed_at="2026.05.17 15:30:12",
                        played_seconds=2,
                        required_played_seconds=2,
                        reason="test_complete",
                    )
                )
                first_id = promote_live_playback_event(conn, live_key)
                second_id = promote_live_playback_event(conn, live_key)
                conn.commit()
                dance_rows = conn.execute("SELECT * FROM dance_events").fetchall()
                live_row = conn.execute("SELECT * FROM live_playback_events").fetchone()

            self.assertEqual(first_id, second_id)
            self.assertEqual(len(dance_rows), 1)
            self.assertEqual(dance_rows[0]["source"], "other")
            self.assertEqual(dance_rows[0]["requester_display_name"], "Alice")
            self.assertEqual(live_row["promoted_dance_event_id"], first_id)
            self.assertEqual(live_row["completion_status"], "completed")

    def test_promote_live_playback_event_skips_mid_play(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.sqlite3"
            event = {
                "event_key": "pypydance:4678#1",
                "canonical_key": "pypydance:4678",
                "first_seen_at": "2026.05.17 17:15:30",
                "actual_play_at": "2026.05.17 17:14:12.67008",
                "observed_mid_play": True,
                "dance_system_key": "pypydance",
                "dance_external_id": "4678",
                "source_type": "player",
                "signal_count": 2,
                "parser_names": ["vrcx_video_play"],
                "raw_event_types": ["playback-progress"],
            }

            with connect_db(db_path) as conn:
                upsert_live_playback_event(conn, event, session_id="session-one")
                live_key = make_live_playback_event_key("session-one", event["event_key"])
                self.assertIsNone(promote_live_playback_event(conn, live_key))
                conn.commit()
                event_count = conn.execute("SELECT count(*) FROM dance_events").fetchone()[0]

            self.assertEqual(event_count, 0)

    def test_wanna_catalog_writes_tracks_specific_fields_and_music_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "app.sqlite3")
            song = {
                "id": 5038,
                "name": "Good Time",
                "artist": "Owl City",
                "dancer": "JAMAA",
                "player_count": 1,
                "group": "Solo",
                "major": "Just Dance",
                "cache_url": "https://example.test/video.mp4",
                "cache_flip": 1,
            }

            with connect_db(db_path) as conn:
                self.assertEqual(upsert_catalog(conn, [song]), 1)
                self.assertEqual(upsert_catalog(conn, [song]), 1)
                track_count = conn.execute("SELECT count(*) FROM dance_tracks").fetchone()[0]
                wanna_count = conn.execute("SELECT count(*) FROM wannadance_songs").fetchone()[0]
                music_count = conn.execute("SELECT count(*) FROM music_tracks").fetchone()[0]
                link_count = conn.execute("SELECT count(*) FROM dance_track_music_links").fetchone()[0]
                row = conn.execute(
                    """
                    SELECT dt.title, dt.artist, ws.cache_url, ws.cache_flip
                    FROM dance_tracks dt
                    JOIN wannadance_songs ws ON ws.dance_track_id = dt.id
                    """
                ).fetchone()

            self.assertEqual(track_count, 1)
            self.assertEqual(wanna_count, 1)
            self.assertEqual(music_count, 1)
            self.assertEqual(link_count, 1)
            self.assertEqual(row["title"], "Good Time")
            self.assertEqual(row["artist"], "Owl City")
            self.assertEqual(row["cache_url"], "https://example.test/video.mp4")
            self.assertEqual(row["cache_flip"], 1)

    def test_sync_wanna_catalog_default_loads_saved_app_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_track_dir = root / "cache" / "5038"
            cache_track_dir.mkdir(parents=True)
            (cache_track_dir / "metadata.json").write_text(
                '{"id":5038,"title":"Configured Song","artist":"Configured Artist"}',
                encoding="utf-8",
            )
            save_app_config(
                {
                    "app_db": "custom/app.sqlite3",
                    "wanna_cache_dir": "cache",
                },
                app_root=root,
            )

            with patch("dancing_log.app_paths.default_app_root", return_value=root):
                stats = sync_wanna_catalog(use_api=False)

            self.assertEqual(stats.cache_count, 1)
            self.assertTrue((root / "custom" / "app.sqlite3").exists())
            self.assertFalse((root / "data" / "dancing_log.sqlite3").exists())

    def test_manual_log_uses_system_external_id_and_preserves_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "app.sqlite3")
            with connect_db(db_path) as conn:
                upsert_catalog(
                    conn,
                    [
                        {
                            "id": 5038,
                            "name": "Good Time",
                            "artist": "Owl City",
                            "dancer": "JAMAA",
                            "player_count": 1,
                            "group": "Solo",
                            "major": "Just Dance",
                        }
                    ],
                )

            actual_source = add_dance_record(
                WANNA_SYSTEM_KEY,
                "5038",
                note="nice run",
                timestamp="2026-04-17T20:30:00+08:00",
                db_path=db_path,
            )

            self.assertEqual(actual_source, SOURCE_RECOMMEND)
            records = load_dance_log(db_path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["system_key"], WANNA_SYSTEM_KEY)
            self.assertEqual(records[0]["external_id"], "5038")
            self.assertIsInstance(records[0]["dance_track_id"], int)
            self.assertEqual(records[0]["source"], SOURCE_RECOMMEND)
            self.assertEqual(records[0]["note"], "nice run")

    def test_recommendation_uses_dance_track_ids_without_popularity(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "app.sqlite3")
            with connect_db(db_path) as conn:
                track_id = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "1",
                    {"title": "Song", "artist": "Artist"},
                )
                conn.execute(
                    "UPDATE dance_tracks SET favorite = 1, want_to_learn = 1 WHERE id = ?",
                    (track_id,),
                )
                conn.commit()

            tracks = load_dance_tracks(db_path)
            playlist = generate_daily_playlist(tracks, [], count=1)

            self.assertEqual(playlist[0]["id"], track_id)
            self.assertEqual(playlist[0]["system_key"], WANNA_SYSTEM_KEY)
            self.assertNotIn("popularity", playlist[0])

    def test_import_favorites_replaces_system_favorites_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.sqlite3"
            favorites_path = root / "favorites.txt"
            with connect_db(db_path) as conn:
                for external_id in ("1", "2", "3"):
                    ensure_dance_track(conn, WANNA_SYSTEM_KEY, external_id)
                conn.execute(
                    """
                    UPDATE dance_tracks
                    SET favorite = 1
                    WHERE external_id IN ('2', '3')
                    """
                )
                conn.commit()
            favorites_path.write_text("1\n2\n1\n", encoding="utf-8")

            stats = import_favorites_file(
                system_key=WANNA_SYSTEM_KEY,
                favorites_file=favorites_path,
                app_db_path=db_path,
            )

            self.assertEqual(stats.input_ids, 3)
            self.assertEqual(stats.unique_ids, 2)
            self.assertEqual(stats.duplicate_ids, 1)
            self.assertEqual(stats.favorites_set, 1)
            self.assertEqual(stats.favorites_cleared, 1)
            self.assertEqual(
                favorite_map(db_path),
                {
                    (WANNA_SYSTEM_KEY, "1"): 1,
                    (WANNA_SYSTEM_KEY, "2"): 1,
                    (WANNA_SYSTEM_KEY, "3"): 0,
                },
            )

    def test_import_favorites_parses_wanna_favorite_comma_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.sqlite3"
            favorites_path = root / "liked_songs_wannadance.txt"
            with connect_db(db_path) as conn:
                for external_id in ("6495", "10508", "5929"):
                    ensure_dance_track(conn, WANNA_SYSTEM_KEY, external_id)
                conn.commit()
            favorites_path.write_text(
                "WannaFavorite:6495,10508,5929,6495\n",
                encoding="utf-8",
            )

            stats = import_favorites_file(
                system_key=WANNA_SYSTEM_KEY,
                favorites_file=favorites_path,
                app_db_path=db_path,
            )

            self.assertEqual(stats.input_ids, 4)
            self.assertEqual(stats.unique_ids, 3)
            self.assertEqual(stats.duplicate_ids, 1)
            self.assertEqual(stats.favorites_set, 3)
            self.assertEqual(
                favorite_map(db_path),
                {
                    (WANNA_SYSTEM_KEY, "6495"): 1,
                    (WANNA_SYSTEM_KEY, "10508"): 1,
                    (WANNA_SYSTEM_KEY, "5929"): 1,
                },
            )

    def test_import_favorites_additive_does_not_clear_existing_favorites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.sqlite3"
            favorites_path = root / "favorites.txt"
            with connect_db(db_path) as conn:
                for external_id in ("1", "2", "3"):
                    ensure_dance_track(conn, WANNA_SYSTEM_KEY, external_id)
                conn.execute(
                    "UPDATE dance_tracks SET favorite = 1 WHERE external_id = '3'"
                )
                conn.commit()
            favorites_path.write_text("1\n2\n", encoding="utf-8")

            stats = import_favorites_file(
                system_key=WANNA_SYSTEM_KEY,
                favorites_file=favorites_path,
                app_db_path=db_path,
                additive=True,
            )

            self.assertEqual(stats.favorites_set, 2)
            self.assertEqual(stats.favorites_cleared, 0)
            self.assertEqual(
                favorite_map(db_path),
                {
                    (WANNA_SYSTEM_KEY, "1"): 1,
                    (WANNA_SYSTEM_KEY, "2"): 1,
                    (WANNA_SYSTEM_KEY, "3"): 1,
                },
            )

    def test_import_favorites_dry_run_reports_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.sqlite3"
            favorites_path = root / "favorites.txt"
            with connect_db(db_path) as conn:
                ensure_dance_track(conn, WANNA_SYSTEM_KEY, "1")
                ensure_dance_track(conn, WANNA_SYSTEM_KEY, "2")
                conn.execute(
                    "UPDATE dance_tracks SET favorite = 1 WHERE external_id = '2'"
                )
                conn.commit()
            favorites_path.write_text("1\n", encoding="utf-8")

            stats = import_favorites_file(
                system_key=WANNA_SYSTEM_KEY,
                favorites_file=favorites_path,
                app_db_path=db_path,
                dry_run=True,
            )

            self.assertTrue(stats.dry_run)
            self.assertEqual(stats.favorites_set, 1)
            self.assertEqual(stats.favorites_cleared, 1)
            self.assertEqual(
                favorite_map(db_path),
                {
                    (WANNA_SYSTEM_KEY, "1"): 0,
                    (WANNA_SYSTEM_KEY, "2"): 1,
                },
            )

    def test_import_favorites_unknown_id_fails_without_partial_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.sqlite3"
            favorites_path = root / "favorites.txt"
            with connect_db(db_path) as conn:
                ensure_dance_track(conn, WANNA_SYSTEM_KEY, "1")
                ensure_dance_track(conn, WANNA_SYSTEM_KEY, "2")
                conn.execute(
                    "UPDATE dance_tracks SET favorite = 1 WHERE external_id = '2'"
                )
                conn.commit()
            favorites_path.write_text("1\n999\n", encoding="utf-8")

            with self.assertRaisesRegex(FavoriteImportError, "999"):
                import_favorites_file(
                    system_key=WANNA_SYSTEM_KEY,
                    favorites_file=favorites_path,
                    app_db_path=db_path,
                )

            self.assertEqual(
                favorite_map(db_path),
                {
                    (WANNA_SYSTEM_KEY, "1"): 0,
                    (WANNA_SYSTEM_KEY, "2"): 1,
                },
            )

    def test_import_favorites_replace_is_scoped_to_one_system(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.sqlite3"
            favorites_path = root / "favorites.txt"
            with connect_db(db_path) as conn:
                ensure_dance_track(conn, WANNA_SYSTEM_KEY, "1")
                ensure_dance_track(conn, WANNA_SYSTEM_KEY, "2")
                ensure_dance_track(conn, "otherdance", "1")
                conn.execute("UPDATE dance_tracks SET favorite = 1")
                conn.commit()
            favorites_path.write_text("1\n", encoding="utf-8")

            stats = import_favorites_file(
                system_key=WANNA_SYSTEM_KEY,
                favorites_file=favorites_path,
                app_db_path=db_path,
            )

            self.assertEqual(stats.favorites_cleared, 1)
            self.assertEqual(
                favorite_map(db_path),
                {
                    (WANNA_SYSTEM_KEY, "1"): 1,
                    (WANNA_SYSTEM_KEY, "2"): 0,
                    ("otherdance", "1"): 1,
                },
            )

    def test_import_favorites_blank_line_fails_without_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.sqlite3"
            favorites_path = root / "favorites.txt"
            with connect_db(db_path) as conn:
                ensure_dance_track(conn, WANNA_SYSTEM_KEY, "1")
                conn.commit()
            favorites_path.write_text("1\n\n", encoding="utf-8")

            with self.assertRaisesRegex(FavoriteImportError, "line 2"):
                import_favorites_file(
                    system_key=WANNA_SYSTEM_KEY,
                    favorites_file=favorites_path,
                    app_db_path=db_path,
                )

            self.assertEqual(favorite_map(db_path), {(WANNA_SYSTEM_KEY, "1"): 0})

    def test_vrcx_import_writes_new_tables_and_skips_unsupported_systems(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vrcx_path = root / "VRCX.sqlite3"
            app_path = root / "app.sqlite3"
            with closing(sqlite3.connect(vrcx_path)) as conn:
                conn.execute(
                    """
                    CREATE TABLE gamelog_video_play (
                        created_at TEXT,
                        video_url TEXT,
                        video_name TEXT,
                        video_id TEXT,
                        location TEXT,
                        display_name TEXT,
                        user_id TEXT
                    )
                    """
                )
                conn.executemany(
                    "INSERT INTO gamelog_video_play VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            "2026-05-15T14:20:11.000Z",
                            "https://api.udon.dance/Api/Songs/play?id=3114",
                            "Song Name",
                            "",
                            "wrld_1",
                            "",
                            "",
                        ),
                        (
                            "2026-05-15T15:20:11.000Z",
                            "http://jd.pypy.moe/api/v1/videos/4051.mp4",
                            "PyPy Song",
                            "",
                            "wrld_2",
                            "",
                            "",
                        ),
                        (
                            "2026-05-15T16:20:11.000Z",
                            "https://api.dudufit.dance/api/v1/videos/1321?cdn=jpn",
                            "Dudu Song",
                            "",
                            "wrld_3",
                            "",
                            "",
                        ),
                    ],
                )
                conn.commit()

            stats = import_vrcx_database(vrcx_path, app_db_path=app_path)

            self.assertEqual(stats.dance_events_changed, 2)
            self.assertEqual(stats.skipped_unsupported, 1)
            with connect_db(app_path) as conn:
                wanna_track_count = conn.execute(
                    """
                    SELECT count(*)
                    FROM dance_tracks dt
                    JOIN dance_systems ds ON ds.id = dt.system_id
                    WHERE ds.key = ? AND dt.external_id = '3114'
                    """,
                    (WANNA_SYSTEM_KEY,),
                ).fetchone()[0]
                pypy_track_count = conn.execute(
                    """
                    SELECT count(*)
                    FROM dance_tracks dt
                    JOIN dance_systems ds ON ds.id = dt.system_id
                    WHERE ds.key = 'pypydance' AND dt.external_id = '4051'
                    """
                ).fetchone()[0]
                event_count = conn.execute("SELECT count(*) FROM dance_events").fetchone()[0]
                parsed = conn.execute(
                    """
                    SELECT parsed_external_id, parsed_dance_track_id
                    FROM vrcx_import_events
                    ORDER BY created_at
                    """
                ).fetchall()
            self.assertEqual(wanna_track_count, 1)
            self.assertEqual(pypy_track_count, 1)
            self.assertEqual(event_count, 2)
            self.assertEqual(parsed[0]["parsed_external_id"], "3114")
            self.assertEqual(parsed[1]["parsed_external_id"], "4051")
            self.assertIsInstance(parsed[0]["parsed_dance_track_id"], int)
            self.assertIsInstance(parsed[1]["parsed_dance_track_id"], int)

    def test_queued_self_uses_cli_system_for_bare_track_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "app.sqlite3"
            manifest_dir = root / "queued_self"
            manifest_dir.mkdir()
            with connect_db(db_path) as conn:
                ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "5038",
                    {"title": "Good Time", "artist": "Owl City"},
                )
                conn.commit()
            add_dance_event(
                system_key=WANNA_SYSTEM_KEY,
                external_id="5038",
                source="other",
                played_at="2026-04-17T20:30:00+08:00",
                event_source="manual",
                path=db_path,
            )
            (manifest_dir / "playlist.md").write_text(
                "# 2026-04-17\n5038 Good Time\n3114 Unmatched id\n",
                encoding="utf-8",
            )

            stats = sync_queued_self_manifests(
                app_db_path=db_path,
                manifest_dir=manifest_dir,
                system_key=WANNA_SYSTEM_KEY,
            )

            self.assertEqual(stats.entries_with_track_ref, 2)
            self.assertEqual(stats.entries_without_track_ref, 0)
            self.assertEqual(stats.matched_entries, 1)
            self.assertEqual(stats.unmatched_entries, 1)
            with connect_db(db_path) as conn:
                source = conn.execute("SELECT source FROM dance_events").fetchone()[0]
            self.assertEqual(source, "queued_self")

    def test_archive_existing_data_keeps_config_and_manifest_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "queued_self").mkdir()
            (root / "queued_self" / "playlist.md").write_text("keep", encoding="utf-8")
            (root / "local_config.json").write_text("{}", encoding="utf-8")
            for name in ("dancing_log.sqlite3", "songs.csv", "wanna_songs.json"):
                (root / name).write_text(name, encoding="utf-8")

            stats = archive_existing_data(root)

            self.assertTrue((root / "local_config.json").exists())
            self.assertTrue((root / "queued_self" / "playlist.md").exists())
            self.assertFalse((root / "dancing_log.sqlite3").exists())
            self.assertFalse((root / "songs.csv").exists())
            self.assertEqual(len(stats.archived), 3)
            self.assertTrue((stats.archive_dir / "dancing_log.sqlite3").exists())

    def test_archive_existing_data_archives_custom_app_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            custom_db = root / "runtime" / "custom.sqlite3"
            custom_db.parent.mkdir()
            custom_db.write_text("db", encoding="utf-8")
            Path(str(custom_db) + "-wal").write_text("wal", encoding="utf-8")

            stats = archive_existing_data(root, app_db_path=custom_db)

            self.assertFalse(custom_db.exists())
            self.assertFalse(Path(str(custom_db) + "-wal").exists())
            self.assertTrue((stats.archive_dir / "custom.sqlite3").exists())
            self.assertTrue((stats.archive_dir / "custom.sqlite3-wal").exists())


if __name__ == "__main__":
    unittest.main()
