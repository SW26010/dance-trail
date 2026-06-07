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
from dancing_log.storage import (
    WANNA_SYSTEM_KEY,
    add_dance_event,
    connect_db,
    ensure_dance_track,
    upsert_live_playback_event,
)


class DailyReportTest(unittest.TestCase):
    def test_daily_report_prints_one_local_day_in_requested_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "app.sqlite3"
            with connect_db(db_path) as conn:
                ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "8378",
                    {
                        "title": "Party In The U.S.A.",
                        "artist": "Miley Cyrus",
                        "dancer": "Just Dance 2025",
                    },
                )
                ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "11253",
                    {"title": "Mmchk", "artist": "NEXZ", "dancer": "Golfy"},
                )
                conn.commit()

            add_dance_event(
                system_key=WANNA_SYSTEM_KEY,
                external_id="11253",
                source="random",
                played_at="2026.06.07 18:12:08",
                event_source="manual",
                path=db_path,
            )
            add_dance_event(
                system_key=WANNA_SYSTEM_KEY,
                external_id="8378",
                source="random",
                played_at="2026.06.07 18:04:57",
                event_source="manual",
                video_name="8378. Party In The U.S.A. - Miley Cyrus | Just Dance 2025",
                path=db_path,
            )
            add_dance_event(
                system_key=WANNA_SYSTEM_KEY,
                external_id="8378",
                source="random",
                played_at="2026.06.08 00:01:00",
                event_source="manual",
                path=db_path,
            )

            dances = load_daily_dances(date(2026, 6, 7), db_path)

            self.assertEqual(
                [format_daily_dance_line(dance) for dance in dances],
                [
                    "18:04:57 8378. Party In The U.S.A. - Miley Cyrus | Just Dance 2025",
                    "18:12:08 11253. Mmchk - NEXZ | Golfy",
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
                conn.commit()

            dances = load_daily_live_dances(date(2026, 6, 7), db_path)

            self.assertEqual(
                [format_daily_dance_line(dance) for dance in dances],
                [
                    "18:09:09 4062. Mood (Extreme) - 24kGoldn & Iann Dior | Just Dance 2022",
                ],
            )


if __name__ == "__main__":
    unittest.main()
