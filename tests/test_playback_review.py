import tempfile
import unittest
from pathlib import Path

from dancing_log.playback_projection import (
    EFFECTIVE_PLAYBACK_ACCEPTED,
    EFFECTIVE_PLAYBACK_EXCLUDED,
    EFFECTIVE_PLAYBACK_NEEDS_ATTENTION,
)
from dancing_log.playback_review import (
    PlaybackReviewError,
    clear_playback_record_manual_decision,
    read_playback_review_state,
    set_playback_record_manual_decision,
)
from dancing_log.storage import WANNA_SYSTEM_KEY, connect_db, ensure_dance_track
from tests.playback_record_helpers import insert_playback_record


class PlaybackReviewTest(unittest.TestCase):
    def test_set_and_clear_manual_decision_preserves_default_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "dancing_log.sqlite3"
            with connect_db(db_path) as conn:
                track_id = ensure_dance_track(
                    conn,
                    WANNA_SYSTEM_KEY,
                    "800",
                    {"title": "Manual Review"},
                )
                playback_record_id = insert_playback_record(
                    conn,
                    track_id=track_id,
                    played_at="2026-06-18T21:00:00+08:00",
                    playback_status=EFFECTIVE_PLAYBACK_NEEDS_ATTENTION,
                    counts_in_history=0,
                )

                accepted = set_playback_record_manual_decision(
                    conn,
                    playback_record_id,
                    EFFECTIVE_PLAYBACK_ACCEPTED,
                    reason="test_accept",
                )

                self.assertEqual(accepted.playback_record_id, playback_record_id)
                self.assertEqual(
                    accepted.default_playback_status,
                    EFFECTIVE_PLAYBACK_NEEDS_ATTENTION,
                )
                self.assertEqual(
                    accepted.manual_decision_status,
                    EFFECTIVE_PLAYBACK_ACCEPTED,
                )
                self.assertEqual(
                    accepted.effective_playback_status,
                    EFFECTIVE_PLAYBACK_ACCEPTED,
                )

                excluded = set_playback_record_manual_decision(
                    conn,
                    playback_record_id,
                    EFFECTIVE_PLAYBACK_EXCLUDED,
                    reason="test_exclude",
                )
                active_rows = conn.execute(
                    """
                    SELECT decision_status
                    FROM manual_playback_decisions
                    WHERE playback_record_id = ? AND active = 1
                    """,
                    (playback_record_id,),
                ).fetchall()
                self.assertEqual([row["decision_status"] for row in active_rows], ["excluded"])
                self.assertEqual(
                    excluded.effective_playback_status,
                    EFFECTIVE_PLAYBACK_EXCLUDED,
                )

                restored = clear_playback_record_manual_decision(conn, playback_record_id)

                self.assertIsNone(restored.manual_decision_status)
                self.assertEqual(
                    restored.effective_playback_status,
                    EFFECTIVE_PLAYBACK_NEEDS_ATTENTION,
                )

    def test_review_rejects_missing_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "dancing_log.sqlite3"
            with connect_db(db_path) as conn:
                with self.assertRaisesRegex(PlaybackReviewError, "playback record not found"):
                    read_playback_review_state(conn, 999)

                with self.assertRaisesRegex(PlaybackReviewError, "manual playback decision"):
                    set_playback_record_manual_decision(conn, 999, "pending")


if __name__ == "__main__":
    unittest.main()
