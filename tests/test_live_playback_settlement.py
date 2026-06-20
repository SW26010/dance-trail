import unittest

from dancing_log.live_playback_settlement import (
    decide_live_playback_settlement,
    is_live_playback_promotable,
)


class LivePlaybackSettlementModuleTest(unittest.TestCase):
    def test_completes_known_duration_after_threshold(self):
        decision = decide_live_playback_settlement(
            {
                "actual_play_at": "2026.05.17 15:30:00",
                "duration_seconds": 100.0,
                "dance_system_key": "wannadance",
                "dance_external_id": "3114",
            },
            observed_at="2026.05.17 15:31:20",
            interrupt_if_incomplete=False,
            completion_reason="observed_completion_threshold",
            interrupt_reason="superseded_before_completion",
        )

        self.assertEqual(decision.completion_status, "completed")
        self.assertEqual(decision.played_seconds, 80.0)
        self.assertEqual(decision.required_played_seconds, 80.0)
        self.assertEqual(decision.reason, "observed_completion_threshold")

    def test_mid_play_observation_is_interrupted_and_not_promotable(self):
        decision = decide_live_playback_settlement(
            {
                "actual_play_at": "2026.05.17 15:30:00",
                "duration_seconds": 100.0,
                "dance_system_key": "wannadance",
                "dance_external_id": "3114",
                "observed_mid_play": True,
            },
            observed_at="2026.05.17 15:31:20",
            interrupt_if_incomplete=True,
            completion_reason="observed_completion_threshold",
            interrupt_reason="room_left",
        )

        self.assertEqual(decision.completion_status, "interrupted")
        self.assertEqual(decision.reason, "observed_mid_play")
        self.assertFalse(
            is_live_playback_promotable(
                {
                    "completion_status": "completed",
                    "actual_play_at": "2026.05.17 15:30:00",
                    "dance_system_key": "wannadance",
                    "dance_external_id": "3114",
                    "duration_seconds": 100.0,
                    "observed_mid_play": 1,
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
