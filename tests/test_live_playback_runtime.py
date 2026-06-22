import unittest
from dataclasses import dataclass, field

from dancing_log.live_playback_runtime import LivePlaybackRuntime


@dataclass
class RuntimeStats:
    live_session_id: str | None = "session-1"
    last_log_timestamp: str | None = None
    live_db_updates: int = 0
    live_promotions: int = 0
    overlay_url: str | None = None
    errors: list[str] = field(default_factory=list)


class FakeLivePlaybackStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.promote_calls: list[str] = []

    def make_event_key(self, session_id: str | None, playback_event_key: str) -> str:
        return f"{session_id or ''}:{playback_event_key}"

    def upsert(self, event: dict, *, session_id: str | None, event_key: str) -> int:
        row = self.rows.setdefault(
            event_key,
            {
                "event_key": event_key,
                "session_id": session_id,
                "completion_status": "pending",
                "completion_reason": None,
                "promoted_playback_record_id": None,
            },
        )
        row.update(event)
        return 1

    def mark_completed(
        self,
        event_key: str,
        *,
        completed_at: str,
        played_seconds: float,
        required_played_seconds: float,
        reason: str,
    ) -> bool:
        row = self.rows[event_key]
        if row["completion_status"] != "pending" or row["promoted_playback_record_id"] is not None:
            return False
        row.update(
            {
                "completion_status": "completed",
                "completion_reason": reason,
                "completed_at": completed_at,
                "interrupted_at": None,
                "played_seconds": round(float(played_seconds), 3),
                "required_played_seconds": round(float(required_played_seconds), 3),
            }
        )
        return True

    def mark_interrupted(
        self,
        event_key: str,
        *,
        interrupted_at: str,
        played_seconds: float | None,
        required_played_seconds: float | None,
        reason: str,
    ) -> bool:
        row = self.rows[event_key]
        if row["completion_status"] != "pending" or row["promoted_playback_record_id"] is not None:
            return False
        row.update(
            {
                "completion_status": "interrupted",
                "completion_reason": reason,
                "interrupted_at": interrupted_at,
                "played_seconds": round(float(played_seconds), 3)
                if played_seconds is not None
                else None,
                "required_played_seconds": round(float(required_played_seconds), 3)
                if required_played_seconds is not None
                else None,
            }
        )
        return True

    def promote_completed_event(self, event_key: str) -> int | None:
        self.promote_calls.append(event_key)
        row = self.rows[event_key]
        if row["completion_status"] != "completed":
            return None
        if not row.get("actual_play_at"):
            return None
        if not row.get("dance_system_key") or not row.get("dance_external_id"):
            return None
        if row.get("duration_seconds") is None or bool(row.get("observed_mid_play")):
            return None
        row["promoted_playback_record_id"] = len(self.promote_calls)
        return row["promoted_playback_record_id"]

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class RecordingOverlay:
    url = "http://127.0.0.1:8765/overlay"

    def __init__(self) -> None:
        self.published: list[dict] = []
        self.statuses: list[dict] = []
        self.closed = False

    def publish(self, event: dict) -> dict:
        stored = dict(event)
        self.published.append(stored)
        return {"current": stored, "status": self.statuses[-1] if self.statuses else None}

    def publish_status(self, status: dict) -> dict:
        stored = dict(status)
        self.statuses.append(stored)
        return {"current": None if stored.get("clear_current") else None, "status": stored}

    def close(self) -> None:
        self.closed = True


def playback_event(
    *,
    event_key: str = "wannadance:3114#1",
    external_id: str = "3114",
    first_seen_at: str = "2026.05.17 15:30:00",
    actual_play_at: str = "2026.05.17 15:30:00",
    last_seen_at: str | None = None,
    duration_seconds: float | None = 10.0,
) -> dict:
    return {
        "event_key": event_key,
        "canonical_key": f"wannadance:{external_id}",
        "first_seen_at": first_seen_at,
        "last_seen_at": last_seen_at or actual_play_at,
        "actual_play_at": actual_play_at,
        "dance_system_key": "wannadance",
        "dance_external_id": external_id,
        "duration_seconds": duration_seconds,
        "observed_mid_play": False,
    }


class LivePlaybackRuntimeModuleTest(unittest.TestCase):
    def test_room_left_interrupts_pending_event_and_clears_overlay(self):
        stats = RuntimeStats()
        store = FakeLivePlaybackStore()
        overlay = RecordingOverlay()
        runtime = LivePlaybackRuntime(stats=stats, store=store, overlay=overlay)

        runtime.observe_lifecycle_event(
            {"event_type": "room-entering", "timestamp": "2026.05.17 15:29:55", "room_name": "WannaDance"}
        )
        runtime.observe_playback_event(playback_event())
        runtime.observe_lifecycle_event(
            {"event_type": "room-left", "timestamp": "2026.05.17 15:30:05"}
        )

        row = store.rows["session-1:wannadance:3114#1"]
        self.assertEqual(row["completion_status"], "interrupted")
        self.assertEqual(row["completion_reason"], "room_left")
        self.assertEqual(row["played_seconds"], 5.0)
        self.assertEqual(overlay.statuses[-1]["room_name"], "WannaDance")
        self.assertTrue(overlay.statuses[-1]["clear_current"])

    def test_application_quit_interrupts_pending_event(self):
        stats = RuntimeStats()
        store = FakeLivePlaybackStore()
        runtime = LivePlaybackRuntime(stats=stats, store=store)

        runtime.observe_playback_event(playback_event())
        runtime.observe_lifecycle_event(
            {
                "event_type": "application-quit",
                "timestamp": "2026.05.17 15:30:04",
            }
        )

        row = store.rows["session-1:wannadance:3114#1"]
        self.assertEqual(row["completion_status"], "interrupted")
        self.assertEqual(row["completion_reason"], "application_quit")
        self.assertEqual(row["played_seconds"], 4.0)

    def test_preview_video_is_suppressed_before_runtime_store_or_overlay(self):
        stats = RuntimeStats()
        store = FakeLivePlaybackStore()
        overlay = RecordingOverlay()
        runtime = LivePlaybackRuntime(stats=stats, store=store, overlay=overlay)
        builder = runtime.create_playback_builder()

        builder.observe(
            {
                "timestamp": "2026.05.17 22:49:02",
                "event_type": "preview",
                "parser_name": "wannadance_preview",
                "video_url": "http://api.udon.dance/Api/Songs/play?id=3335",
                "dance_system_key": "wannadance",
                "dance_external_id": "3335",
            }
        )
        builder.observe(
            {
                "timestamp": "2026.05.17 22:49:03",
                "event_type": "load-start",
                "parser_name": "usharp_load_start",
                "video_url": "http://api.udon.dance/Api/Songs/play?id=3335",
                "dance_system_key": "wannadance",
                "dance_external_id": "3335",
            }
        )

        self.assertEqual(store.rows, {})
        self.assertEqual(overlay.published, [])
        self.assertEqual(stats.live_db_updates, 0)

    def test_vrcx_play_after_preview_marker_reaches_runtime(self):
        stats = RuntimeStats()
        store = FakeLivePlaybackStore()
        runtime = LivePlaybackRuntime(stats=stats, store=store)
        builder = runtime.create_playback_builder()

        builder.observe(
            {
                "timestamp": "2026.05.17 22:49:02",
                "event_type": "preview",
                "parser_name": "wannadance_preview",
                "video_url": "http://api.udon.dance/Api/Songs/play?id=3335",
                "dance_system_key": "wannadance",
                "dance_external_id": "3335",
            }
        )
        builder.observe(
            {
                "timestamp": "2026.05.17 22:49:10",
                "event_type": "actual-play",
                "parser_name": "vrcx_video_play",
                "video_url": "http://api.udon.dance/Api/Songs/play?id=3335",
                "video_name": "Real Song",
                "dance_system_key": "wannadance",
                "dance_external_id": "3335",
                "duration_seconds": 10.0,
            }
        )

        row = store.rows["session-1:wannadance:3335#1"]
        self.assertEqual(row["dance_external_id"], "3335")
        self.assertEqual(row["video_name"], "Real Song")
        self.assertEqual(stats.live_db_updates, 1)

    def test_progress_lifecycle_event_completes_and_promotes_when_enabled(self):
        stats = RuntimeStats()
        store = FakeLivePlaybackStore()
        runtime = LivePlaybackRuntime(stats=stats, store=store, promote_live=True)

        runtime.observe_playback_event(playback_event(duration_seconds=10.0))
        runtime.observe_lifecycle_event(
            {
                "event_type": "log-progress",
                "timestamp": "2026.05.17 15:30:08",
                "observed_at": "2026.05.17 15:30:08",
            }
        )

        row = store.rows["session-1:wannadance:3114#1"]
        self.assertEqual(row["completion_status"], "completed")
        self.assertEqual(row["completion_reason"], "observed_completion_threshold")
        self.assertEqual(row["played_seconds"], 8.0)
        self.assertEqual(stats.live_promotions, 1)
        self.assertEqual(store.promote_calls, ["session-1:wannadance:3114#1"])

    def test_completed_event_does_not_promote_without_explicit_flag(self):
        stats = RuntimeStats()
        store = FakeLivePlaybackStore()
        runtime = LivePlaybackRuntime(stats=stats, store=store, promote_live=False)

        runtime.observe_playback_event(playback_event(duration_seconds=10.0))
        runtime.observe_lifecycle_event(
            {
                "event_type": "log-progress",
                "timestamp": "2026.05.17 15:30:08",
                "observed_at": "2026.05.17 15:30:08",
            }
        )

        row = store.rows["session-1:wannadance:3114#1"]
        self.assertEqual(row["completion_status"], "completed")
        self.assertEqual(stats.live_promotions, 0)
        self.assertEqual(store.promote_calls, [])


if __name__ == "__main__":
    unittest.main()
