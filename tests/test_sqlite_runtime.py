import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from dancing_log.models import (
    SOURCE_RECOMMEND,
    add_dance_record,
    generate_daily_playlist,
)
from dancing_log.queued_self_importer import sync_queued_self_manifests
from dancing_log.rebuild import archive_existing_data
from dancing_log.storage import (
    WANNA_SYSTEM_KEY,
    add_dance_event,
    connect_db,
    ensure_dance_track,
    load_dance_log,
    load_dance_tracks,
)
from dancing_log.vrcx_importer import import_vrcx_database
from dancing_log.wanna_catalog import upsert_catalog


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
            self.assertNotIn("songs", tables)
            self.assertIn("dance_track_id", dance_event_columns)
            self.assertNotIn("song_id", dance_event_columns)

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
                    ],
                )
                conn.commit()

            stats = import_vrcx_database(vrcx_path, app_db_path=app_path)

            self.assertEqual(stats.dance_events_changed, 1)
            self.assertEqual(stats.skipped_unsupported, 1)
            with connect_db(app_path) as conn:
                track_count = conn.execute(
                    """
                    SELECT count(*)
                    FROM dance_tracks dt
                    JOIN dance_systems ds ON ds.id = dt.system_id
                    WHERE ds.key = ? AND dt.external_id = '3114'
                    """,
                    (WANNA_SYSTEM_KEY,),
                ).fetchone()[0]
                event_count = conn.execute("SELECT count(*) FROM dance_events").fetchone()[0]
                parsed = conn.execute(
                    """
                    SELECT parsed_external_id, parsed_dance_track_id
                    FROM vrcx_import_events
                    """
                ).fetchone()
            self.assertEqual(track_count, 1)
            self.assertEqual(event_count, 1)
            self.assertEqual(parsed["parsed_external_id"], "3114")
            self.assertIsInstance(parsed["parsed_dance_track_id"], int)

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


if __name__ == "__main__":
    unittest.main()
