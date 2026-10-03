import unittest

from dance_trail.watcher_playback_materializer import (
    WATCHER_PLAYBACK_EVENT_SOURCE,
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
            status_reason="observed_completion_threshold",
            completion_status="completed",
            completion_reason="observed_completion_threshold",
        )

        self.assertIsNotNone(record)
        self.assertEqual(record.evidence_source, WATCHER_PLAYBACK_EVENT_SOURCE)
        self.assertEqual(record.requester_display_name, "Alice")
        self.assertEqual(record.requester_user_id, "usr_alice")
        origin = record.origins[0]
        self.assertEqual(origin.origin_source, "vrchat_log")
        self.assertEqual(origin.origin_table, WATCHER_PLAYBACK_SOURCE_TABLE)
        self.assertEqual(
            origin.origin_json["watcher_playback_event"]["requester_user_id"],
            "usr_alice",
        )


if __name__ == "__main__":
    unittest.main()
