"""Live playback runtime rules for folded VRChat playback events."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from dancing_log.live_playback_folding import PlaybackEventBuilder
from dancing_log.live_playback_settlement import decide_live_playback_settlement
from dancing_log.vrc_log_utils import timestamp_before

__all__ = [
    "LivePlaybackOverlay",
    "LivePlaybackRuntime",
    "LivePlaybackRuntimeStats",
    "LivePlaybackStore",
    "ObsOverlayAdapter",
    "SQLiteLivePlaybackStore",
]


class LivePlaybackRuntimeStats(Protocol):
    live_session_id: str | None
    last_log_timestamp: str | None
    live_db_updates: int
    live_promotions: int
    overlay_url: str | None
    errors: list[str]


class LivePlaybackStore(Protocol):
    def make_event_key(self, session_id: str | None, playback_event_key: str) -> str:
        ...

    def upsert(self, event: dict, *, session_id: str | None, event_key: str) -> int:
        ...

    def mark_completed(
        self,
        event_key: str,
        *,
        completed_at: str,
        played_seconds: float,
        required_played_seconds: float,
        reason: str,
    ) -> bool:
        ...

    def mark_interrupted(
        self,
        event_key: str,
        *,
        interrupted_at: str,
        played_seconds: float | None,
        required_played_seconds: float | None,
        reason: str,
    ) -> bool:
        ...

    def promote_completed_event(self, event_key: str) -> int | None:
        ...

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...

    def close(self) -> None:
        ...


class LivePlaybackOverlay(Protocol):
    url: str | None

    def publish(self, event: dict) -> dict:
        ...

    def publish_status(self, status: dict) -> dict:
        ...

    def close(self) -> None:
        ...


class SQLiteLivePlaybackStore:
    """SQLite adapter for durable live playback rows and promotion."""

    def __init__(self, conn) -> None:
        self.conn = conn

    @classmethod
    def open(cls, path: Path | str | None) -> "SQLiteLivePlaybackStore":
        from dancing_log.storage import connect_db

        return cls(connect_db(path))

    def make_event_key(self, session_id: str | None, playback_event_key: str) -> str:
        from dancing_log.storage import make_live_playback_event_key

        return make_live_playback_event_key(session_id or "", playback_event_key)

    def upsert(self, event: dict, *, session_id: str | None, event_key: str) -> int:
        from dancing_log.storage import upsert_live_playback_event

        return upsert_live_playback_event(
            self.conn,
            event,
            session_id=session_id or "",
            event_key=event_key,
        )

    def mark_completed(
        self,
        event_key: str,
        *,
        completed_at: str,
        played_seconds: float,
        required_played_seconds: float,
        reason: str,
    ) -> bool:
        from dancing_log.storage import mark_live_playback_event_completed

        return mark_live_playback_event_completed(
            self.conn,
            event_key,
            completed_at=completed_at,
            played_seconds=played_seconds,
            required_played_seconds=required_played_seconds,
            reason=reason,
        )

    def mark_interrupted(
        self,
        event_key: str,
        *,
        interrupted_at: str,
        played_seconds: float | None,
        required_played_seconds: float | None,
        reason: str,
    ) -> bool:
        from dancing_log.storage import mark_live_playback_event_interrupted

        return mark_live_playback_event_interrupted(
            self.conn,
            event_key,
            interrupted_at=interrupted_at,
            played_seconds=played_seconds,
            required_played_seconds=required_played_seconds,
            reason=reason,
        )

    def promote_completed_event(self, event_key: str) -> int | None:
        from dancing_log.storage import promote_live_playback_event

        return promote_live_playback_event(self.conn, event_key)

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def close(self) -> None:
        self.conn.close()


class ObsOverlayAdapter:
    """OBS overlay adapter for current live playback state."""

    def __init__(self, server) -> None:
        self.server = server

    @classmethod
    def start(cls, port: int) -> "ObsOverlayAdapter":
        from dancing_log.overlay_server import OverlayServer

        server = OverlayServer(port=port)
        server.start()
        return cls(server)

    @property
    def url(self) -> str | None:
        return self.server.url

    def publish(self, event: dict) -> dict:
        return self.server.publish(event)

    def publish_status(self, status: dict) -> dict:
        return self.server.publish_status(status)

    def close(self) -> None:
        self.server.stop()


class LivePlaybackRuntime:
    """Own settlement, promotion, and current-state rules for live playback."""

    def __init__(
        self,
        *,
        stats: LivePlaybackRuntimeStats,
        app_db_path: Path | str | None = None,
        live_db: bool = False,
        promote_live: bool = False,
        overlay_port: int | None = None,
        store: LivePlaybackStore | None = None,
        overlay: LivePlaybackOverlay | None = None,
    ) -> None:
        self.stats = stats
        self.promote_live = promote_live
        self.store = store
        self.overlay = overlay
        self.playback_builder: PlaybackEventBuilder | None = None
        self.live_events: dict[str, dict] = {}
        self.finalized_live_keys: set[str] = set()
        self.promoted_keys: set[str] = set()
        self.current_room_name: str | None = None

        if self.store is None and (live_db or promote_live):
            self.store = SQLiteLivePlaybackStore.open(app_db_path)
        if self.overlay is None and overlay_port is not None:
            self.overlay = ObsOverlayAdapter.start(overlay_port)
        if self.overlay is not None:
            self.stats.overlay_url = self.overlay.url

    def close(self) -> None:
        if self.overlay is not None:
            self.overlay.close()
            self.overlay = None
        if self.store is not None:
            self.store.close()
            self.store = None

    def create_playback_builder(self) -> PlaybackEventBuilder:
        self.playback_builder = PlaybackEventBuilder(update_callback=self.observe_playback_event)
        return self.playback_builder

    def playback_records(self) -> list[dict]:
        if self.playback_builder is None:
            return []
        return self.playback_builder.records()

    def observe_playback_event(self, event: dict) -> None:
        update = dict(event)
        update["live_session_id"] = self.stats.live_session_id
        if self.store is not None:
            live_event_key = self.store.make_event_key(
                self.stats.live_session_id,
                str(event["event_key"]),
            )
            update["live_event_key"] = live_event_key
            try:
                self.store.upsert(
                    event,
                    session_id=self.stats.live_session_id,
                    event_key=live_event_key,
                )
                self.stats.live_db_updates += 1
                existing_update = self.live_events.get(live_event_key)
                if existing_update is not None and existing_update.get("completion_status"):
                    for field_name in (
                        "completion_status",
                        "completion_reason",
                        "completed_at",
                        "interrupted_at",
                        "played_seconds",
                        "required_played_seconds",
                    ):
                        update[field_name] = existing_update.get(field_name)
                self.live_events[live_event_key] = update
                actual_observed_at = event.get("actual_play_at")
                if actual_observed_at:
                    self.settle_pending_events(
                        observed_at=actual_observed_at,
                        current_live_event_key=live_event_key,
                        interrupt_others=True,
                    )
                else:
                    first_observed_at = event.get("first_seen_at")
                    if first_observed_at:
                        self.settle_pending_events(
                            observed_at=first_observed_at,
                            current_live_event_key=live_event_key,
                            interrupt_started_others=True,
                        )
                current_observed_at = event.get("last_seen_at") or actual_observed_at
                if current_observed_at and not self.is_stale_observation(current_observed_at):
                    self.settle_live_event(
                        update,
                        observed_at=current_observed_at,
                        interrupt_if_incomplete=False,
                        completion_reason="observed_completion_threshold",
                        interrupt_reason="superseded_before_completion",
                    )
                self.store.commit()
            except Exception as exc:
                self._record_error(f"live DB update failed: {exc}")
                self.store.rollback()
        if self.overlay is not None:
            self.overlay.publish(update)

    def observe_lifecycle_event(self, event: dict) -> None:
        event_type = event.get("event_type")
        if event_type == "log-progress":
            observed_at = event.get("observed_at") or event.get("timestamp")
            if observed_at:
                self._handle_log_progress(str(observed_at))
            return

        if event.get("room_name"):
            self.current_room_name = event.get("room_name")

        if event_type == "room-entering":
            if self.overlay is not None:
                self.overlay.publish_status(event)
            return

        if event_type not in {"room-left", "application-quit", "video-shutdown"}:
            return

        if self.playback_builder is not None:
            self.playback_builder.close_open_events()

        observed_at = event.get("observed_at") or event.get("timestamp") or self.stats.last_log_timestamp
        interrupt_reason = {
            "room-left": "room_left",
            "application-quit": "application_quit",
            "video-shutdown": "application_quit",
        }.get(str(event_type), "playback_stopped")

        if observed_at and self.store is not None:
            try:
                if self.settle_pending_events(
                    observed_at=str(observed_at),
                    interrupt_others=True,
                    completion_reason="observed_completion_threshold",
                    interrupt_reason=interrupt_reason,
                ):
                    self.store.commit()
            except Exception as exc:
                self._record_error(f"live lifecycle settlement failed: {exc}")
                self.store.rollback()

        if self.overlay is not None:
            status = dict(event)
            status["room_name"] = status.get("room_name") or self.current_room_name
            status["clear_current"] = True
            self.overlay.publish_status(status)

        if event_type in {"room-left", "application-quit"}:
            self.current_room_name = None

    def is_stale_observation(self, observed_at: str | None) -> bool:
        return timestamp_before(observed_at, self.stats.last_log_timestamp)

    def promote_completed_event(self, live_event_key: str) -> None:
        if not self.promote_live or self.store is None:
            return
        dance_event_id = self.store.promote_completed_event(live_event_key)
        if dance_event_id is not None and live_event_key not in self.promoted_keys:
            self.promoted_keys.add(live_event_key)
            self.stats.live_promotions += 1

    def publish_live_settlement(
        self,
        event: dict,
        *,
        completion_status: str,
        observed_at: str,
        played_seconds: float | None,
        required_played_seconds: float | None,
        reason: str,
    ) -> None:
        event["completion_status"] = completion_status
        event["completion_reason"] = reason
        event["played_seconds"] = played_seconds
        event["required_played_seconds"] = required_played_seconds
        if completion_status == "completed":
            event["completed_at"] = observed_at
            event["interrupted_at"] = None
        else:
            event["completed_at"] = None
            event["interrupted_at"] = observed_at
        if self.overlay is not None:
            self.overlay.publish(event)

    def settle_live_event(
        self,
        event: dict,
        *,
        observed_at: str,
        interrupt_if_incomplete: bool,
        completion_reason: str,
        interrupt_reason: str,
    ) -> bool:
        if self.store is None:
            return False
        live_event_key = event.get("live_event_key")
        if not live_event_key or live_event_key in self.finalized_live_keys:
            return False

        settlement = decide_live_playback_settlement(
            event,
            observed_at=observed_at,
            interrupt_if_incomplete=interrupt_if_incomplete,
            completion_reason=completion_reason,
            interrupt_reason=interrupt_reason,
        )
        if settlement is None:
            return False

        if settlement.completion_status == "completed":
            changed = self.store.mark_completed(
                live_event_key,
                completed_at=settlement.observed_at,
                played_seconds=settlement.played_seconds,
                required_played_seconds=settlement.required_played_seconds,
                reason=settlement.reason,
            )
            self.promote_completed_event(live_event_key)
        else:
            changed = self.store.mark_interrupted(
                live_event_key,
                interrupted_at=settlement.observed_at,
                played_seconds=settlement.played_seconds,
                required_played_seconds=settlement.required_played_seconds,
                reason=settlement.reason,
            )
        self.finalized_live_keys.add(live_event_key)
        if changed:
            self.publish_live_settlement(
                event,
                completion_status=settlement.completion_status,
                observed_at=settlement.observed_at,
                played_seconds=settlement.played_seconds,
                required_played_seconds=settlement.required_played_seconds,
                reason=settlement.reason,
            )
        return changed

    def settle_pending_events(
        self,
        *,
        observed_at: str,
        current_live_event_key: str | None = None,
        interrupt_others: bool = False,
        interrupt_started_others: bool = False,
        completion_reason: str = "observed_completion_threshold",
        interrupt_reason: str = "superseded_before_completion",
    ) -> bool:
        if self.is_stale_observation(observed_at):
            return False
        changed = False
        for live_event_key, event in list(self.live_events.items()):
            if live_event_key == current_live_event_key:
                continue
            interrupt_if_incomplete = interrupt_others or (
                interrupt_started_others and bool(event.get("actual_play_at"))
            )
            changed = (
                self.settle_live_event(
                    event,
                    observed_at=observed_at,
                    interrupt_if_incomplete=interrupt_if_incomplete,
                    completion_reason=completion_reason,
                    interrupt_reason=interrupt_reason,
                )
                or changed
            )
        return changed

    def _handle_log_progress(self, timestamp: str) -> None:
        self.stats.last_log_timestamp = timestamp
        if self.store is None:
            return
        try:
            if self.settle_pending_events(observed_at=timestamp):
                self.store.commit()
        except Exception as exc:
            self._record_error(f"live completion check failed: {exc}")
            self.store.rollback()

    def _record_error(self, message: str) -> None:
        if not self.stats.errors or self.stats.errors[-1] != message:
            self.stats.errors.append(message)
