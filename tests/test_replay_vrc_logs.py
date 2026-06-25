import sqlite3
import unittest

from scripts.replay_vrc_logs import _decode_playback_record_row, _index_rows, _matches_manual_row


class ReplayVrcLogsTest(unittest.TestCase):
    def test_manual_gt_matching_accepts_iso_utc_playback_times(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(
                """
                CREATE TABLE playback_records (
                    played_at TEXT,
                    dance_system_key TEXT,
                    dance_external_id TEXT,
                    playback_status TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO playback_records VALUES (?, ?, ?, ?)",
                ("2026-05-17T07:30:10Z", "wannadance", "3114", "accepted"),
            )
            rows = conn.execute("SELECT * FROM playback_records").fetchall()
        finally:
            conn.close()

        self.assertTrue(
            _matches_manual_row(
                rows,
                {"time": "15:30", "external_id": "3114"},
                system_field="dance_system_key",
                external_id_field="dance_external_id",
                time_field="played_at",
                status_field="playback_status",
                status="accepted",
            )
        )

    def test_playback_record_diff_key_keeps_multiple_origins(self):
        rows = [
            _decode_playback_record_row(
                {
                    "evidence_key": "same-record",
                    "origin_key": "origin-a",
                    "origin_json": "{}",
                }
            ),
            _decode_playback_record_row(
                {
                    "evidence_key": "same-record",
                    "origin_key": "origin-b",
                    "origin_json": "{}",
                }
            ),
        ]

        indexed = _index_rows(rows, "evidence_origin_key")

        self.assertEqual(len(indexed), 2)


if __name__ == "__main__":
    unittest.main()
