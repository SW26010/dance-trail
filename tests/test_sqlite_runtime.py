import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from dancing_log.models import SOURCE_RECOMMEND, add_dance_record
from dancing_log.storage import connect_db, load_dance_log, load_songs
from dancing_log.vrcx_importer import import_vrcx_database


class SQLiteRuntimeTest(unittest.TestCase):
    def test_manual_log_writes_to_sqlite_and_preserves_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "app.sqlite3")
            with connect_db(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO songs (
                        id, name, artist, dancer, player_count, song_group, major,
                        favorite, want_to_learn, popularity
                    )
                    VALUES (5038, 'Good Time', 'Owl City', 'JAMAA', 1, 'Solo', 'Just Dance', 1, 0, 80)
                    """
                )
                conn.commit()

            actual_source = add_dance_record(
                5038,
                note="很好玩",
                timestamp="2026-04-17T20:30:00+08:00",
                db_path=db_path,
            )

            self.assertEqual(actual_source, SOURCE_RECOMMEND)
            records = load_dance_log(db_path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["song_id"], "5038")
            self.assertEqual(records[0]["source"], SOURCE_RECOMMEND)
            self.assertEqual(records[0]["note"], "很好玩")

    def test_load_songs_reads_sqlite_shape_for_recommendations(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "app.sqlite3")
            with connect_db(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO songs (id, name, artist, song_group, favorite)
                    VALUES (1, 'Song', 'Artist', 'Group', 1)
                    """
                )
                conn.commit()

            songs = load_songs(db_path)

            self.assertEqual(songs[0]["id"], 1)
            self.assertEqual(songs[0]["group"], "Group")
            self.assertEqual(songs[0]["favorite"], 1)

    def test_vrcx_import_does_not_need_csv_song_master(self):
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
                conn.execute(
                    """
                    INSERT INTO gamelog_video_play
                    VALUES (
                        '2026-05-15T14:20:11.000Z',
                        'https://api.udon.dance/Api/Songs/play?id=3114',
                        'Song Name',
                        '',
                        'wrld_1',
                        '',
                        ''
                    )
                    """
                )
                conn.commit()

            stats = import_vrcx_database(vrcx_path, app_db_path=app_path)

            self.assertEqual(stats.dance_events_changed, 1)
            with connect_db(app_path) as conn:
                song_count = conn.execute("SELECT count(*) FROM songs WHERE id = 3114").fetchone()[0]
                event_count = conn.execute("SELECT count(*) FROM dance_events WHERE song_id = 3114").fetchone()[0]
            self.assertEqual(song_count, 1)
            self.assertEqual(event_count, 1)


if __name__ == "__main__":
    unittest.main()
