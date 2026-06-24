import unittest

from dancing_log.watcher_playback_materializer import (
    WATCHER_PLAYBACK_SOURCE_TABLE,
    watcher_playback_record,
)


class WatcherPlaybackMaterializerModuleTest(unittest.TestCase):
    def test_watcher_record_keeps_requester_user_id(self):
        record = watcher_playback_record(
            {
                "dance_system_key": "wannadance",
                "dance_external_id": "3114",
                "actual_play_at": "2026.05.17 15:30:10",
                "source_type": "player",
                "source_display_name": "Alice",
                "requester_user_id": "usr_alice",
            },
            source_event_key="watcher-event-key",
            dance_track_id=1,
            playback_status="accepted",
            counts_in_history=1,
            status_reason="observed_completion_threshold",
            completion_status="completed",
            completion_reason="observed_completion_threshold",
        )

        self.assertIsNotNone(record)
        self.assertEqual(record.source_table, WATCHER_PLAYBACK_SOURCE_TABLE)
        self.assertEqual(record.requester_display_name, "Alice")
        self.assertEqual(record.requester_user_id, "usr_alice")


if __name__ == "__main__":
    unittest.main()
