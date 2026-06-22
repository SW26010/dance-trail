from datetime import date, timedelta, timezone
import tempfile
import unittest
from pathlib import Path

from dancing_log.daily_report import (
    format_daily_dance_line,
    load_daily_dances,
    load_daily_live_dances,
    parse_played_at_local,
)
from dancing_log.playback_projection import (
    EFFECTIVE_PLAYBACK_ACCEPTED,
    EFFECTIVE_PLAYBACK_EXCLUDED,
    set_manual_playback_decision,
)
from dancing_log.storage import (
    WANNA_SYSTEM_KEY,
    connect_db,
    ensure_dance_track,
    upsert_live_playback_event,
)
from tests.playback_record_helpers import insert_playback_record


class DailyReportTest(unittest.TestCase):
    def test_daily_report_prints_one_local_day_in_requested_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.sqlite3"
            with connect_db(db_path) as conn:
                track_party = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "8378",
                    {
                        "title": "Party In The U.S.A.",
                        "artist": "Miley Cyrus",
                        "dancer": "Just Dance 2025",
                    },
                )
                track_mmchk = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "11253",
                    {"title": "Mmchk", "artist": "NEXZ", "dancer": "Golfy"},
                )
                insert_playback_record(
                    conn,
                    track_id=track_mmchk,
                    played_at="2026.06.07 18:12:08",
                    source_type="random",
                )
                insert_playback_record(
                    conn,
                    track_id=track_party,
                    played_at="2026.06.07 18:04:57",
                    source_type="random",
                    video_name="8378. Party In The U.S.A. - Miley Cyrus | Just Dance 2025",
                )
                insert_playback_record(
                    conn,
                    track_id=track_party,
                    played_at="2026.06.08 00:01:00",
                    source_type="random",
                )
                conn.commit()

            dances = load_daily_dances(date(2026, 6, 7), db_path)

            self.assertEqual(
                [format_daily_dance_line(dance) for dance in dances],
                [
                    "18:04:57 8378. Party In The U.S.A. - Miley Cyrus | Just Dance 2025",
                    "18:12:08 11253. Mmchk - NEXZ | Golfy",
                ],
            )

    def test_daily_report_reads_effective_accepted_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.sqlite3"
            with connect_db(db_path) as conn:
                default_track = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "100",
                    {"title": "Default Keep"},
                )
                excluded_track = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "200",
                    {"title": "Manual Drop"},
                )
                accepted_track = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "300",
                    {"title": "Manual Keep"},
                )
                insert_playback_record(
                    conn,
                    track_id=default_track,
                    played_at="2026.06.07 18:00:00",
                )
                excluded_record = insert_playback_record(
                    conn,
                    track_id=excluded_track,
                    played_at="2026.06.07 18:05:00",
                )
                accepted_record = insert_playback_record(
                    conn,
                    track_id=accepted_track,
                    played_at="2026.06.07 18:10:00",
                    playback_status="needs_attention",
                    counts_in_history=0,
                )
                set_manual_playback_decision(
                    conn,
                    excluded_record,
                    EFFECTIVE_PLAYBACK_EXCLUDED,
                )
                set_manual_playback_decision(
                    conn,
                    accepted_record,
                    EFFECTIVE_PLAYBACK_ACCEPTED,
                )
                conn.commit()

            dances = load_daily_dances(date(2026, 6, 7), db_path)

            self.assertEqual(
                [format_daily_dance_line(dance) for dance in dances],
                [
                    "18:00:00 100. Default Keep",
                    "18:10:00 300. Manual Keep",
                ],
            )

    def test_timezone_aware_timestamps_are_converted_to_local_time(self):
        local_tz = timezone(timedelta(hours=8))

        parsed = parse_played_at_local(
            "2026-06-07T10:04:57.000Z",
            local_tz=local_tz,
        )

        self.assertEqual(parsed.date(), date(2026, 6, 7))
        self.assertEqual(parsed.strftime("%H:%M:%S"), "18:04:57")

    def test_daily_live_report_prints_live_db_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.sqlite3"
            with connect_db(db_path) as conn:
                track_id = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "4062",
                    {
                        "title": "Mood (Extreme)",
                        "artist": "24kGoldn & Iann Dior",
                        "dancer": "Just Dance 2022",
                    },
                )
                upsert_live_playback_event(
                    conn,
                    {
                        "event_key": "wannadance:4062#1",
                        "actual_play_at": "2026.06.07 18:09:09",
                        "observed_mid_play": False,
                        "dance_system_key": WANNA_SYSTEM_KEY,
                        "dance_external_id": "4062",
                        "video_name": "Mood (Extreme) - 24kGoldn & Iann Dior | Just Dance 2022",
                        "signal_count": 1,
                    },
                    session_id="session-one",
                )
                upsert_live_playback_event(
                    conn,
                    {
                        "event_key": "wannadance:4062#2",
                        "actual_play_at": "2026.06.07 18:10:00",
                        "observed_mid_play": True,
                        "dance_system_key": WANNA_SYSTEM_KEY,
                        "dance_external_id": "4062",
                        "video_name": "Mood (Extreme) - 24kGoldn & Iann Dior | Just Dance 2022",
                        "signal_count": 1,
                    },
                    session_id="session-one",
                )
                insert_playback_record(
                    conn,
                    track_id=track_id,
                    played_at="2026.06.07 18:09:09",
                    source_kind="live_watcher",
                    source_table="live_playback_events",
                    source_type="player",
                    video_name="Mood (Extreme) - 24kGoldn & Iann Dior | Just Dance 2022",
                )
                conn.commit()

            dances = load_daily_live_dances(date(2026, 6, 7), db_path)

            self.assertEqual(
                [format_daily_dance_line(dance) for dance in dances],
                [
                    "18:09:09 4062. Mood (Extreme) - 24kGoldn & Iann Dior | Just Dance 2022",
                ],
            )

    def test_daily_report_does_not_create_missing_sqlite_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing" / "app.sqlite3"

            accepted = load_daily_dances(date(2026, 6, 7), db_path)
            live = load_daily_live_dances(date(2026, 6, 7), db_path)

            self.assertEqual(accepted, [])
            self.assertEqual(live, [])
            self.assertFalse(db_path.exists())
            self.assertFalse(db_path.parent.exists())


if __name__ == "__main__":
    unittest.main()
