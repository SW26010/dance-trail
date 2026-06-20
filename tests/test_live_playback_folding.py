import unittest

from dancing_log.live_playback_folding import PlaybackEventBuilder, playback_delay_metrics


class LivePlaybackFoldingModuleTest(unittest.TestCase):
    def test_folds_request_metadata_and_actual_play(self):
        builder = PlaybackEventBuilder()
        video_url = "http://api.udon.dance/Api/Songs/play?id=3114"

        builder.observe(
            {
                "timestamp": "2026.05.17 15:30:00",
                "event_type": "metadata",
                "video_url": video_url,
                "parser_name": "wannadance_queue_info",
                "dance_system_key": "wannadance",
                "dance_external_id": "3114",
                "video_name": "Test Song",
                "duration_seconds": 120.0,
                "duration_source": "wanna_queue_json",
            }
        )
        builder.observe(
            {
                "timestamp": "2026.05.17 15:30:01",
                "event_type": "request",
                "video_url": video_url,
                "display_name": "Alice",
                "parser_name": "user_added_url",
                "dance_system_key": "wannadance",
                "dance_external_id": "3114",
            }
        )
        builder.observe(
            {
                "timestamp": "2026.05.17 15:30:11",
                "event_type": "actual-play",
                "parser_name": "usharp_delayed_video_ready",
            }
        )

        records = builder.records()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["event_key"], "wannadance:3114#1")
        self.assertEqual(records[0]["video_name"], "Test Song")
        self.assertEqual(records[0]["duration_source"], "wanna_queue_json")
        self.assertEqual(records[0]["source_type"], "player")
        self.assertEqual(records[0]["source_display_name"], "Alice")
        self.assertEqual(records[0]["delay_to_actual_seconds"], 10.0)
        self.assertEqual(playback_delay_metrics(records)["avg_seconds"], 10.0)


if __name__ == "__main__":
    unittest.main()
