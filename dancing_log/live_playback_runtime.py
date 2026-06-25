"""Live playback runtime rules for folded VRChat playback events."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from dancing_log.live_playback_folding import PlaybackEventBuilder
from dancing_log.live_playback_settlement import decide_live_playback_settlement
from dancing_log.vrc_log_utils import timestamp_before
from dancing_log.watcher_playback_materializer import (
    WATCHER_GRACEFUL_STOP_REASON,
    accepted_watcher_playback_record,
    attention_watcher_playback_record,
    make_watcher_playback_event_key,
    pending_watcher_playback_record,
)

__all__ = [
    "LivePlaybackOverlay",
    "LivePlaybackRuntime",
    "LivePlaybackRuntimeStats",
    "LivePlaybackStore",
    "ObsOverlayAdapter",
    "SQLiteLivePlaybackStore",
    "SQLiteWatcherPlaybackStore",
]


class LivePlaybackRuntimeStats(Protocol):
    live_session_id: str | None
    last_log_timestamp: str | None
    live_db_updates: int
    live_promotions: int
    playback_record_updates: int
    overlay_url: str | None
    errors: list[str]


class LivePlaybackStore(Protocol):
    def make_event_key(self, session_id: str | None, playback_event_key: str) -> str:
        ...

    def upsert_pending(self, event: dict, *, session_id: str | None, event_key: str) -> int:
        ...

    def upsert_current_state(self, event: dict, *, session_id: str | None, event_key: str) -> int:
        ...

    def mark_completed(
        self,
        event_key: str,
        *,
        event: dict,
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
        event: dict,
        interrupted_at: str,
        played_seconds: float | None,
        required_played_seconds: float | None,
        reason: str,
    ) -> bool:
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


class SQLiteWatcherPlaybackStore:
    """SQLite adapter for watcher-derived playback records."""

    def __init__(self, conn) -> None:
        self.conn = conn

    @classmethod
    def open(cls, path: Path | str | None) -> "SQLiteWatcherPlaybackStore":
        from dancing_log.storage import connect_db

        return cls(connect_db(path))

    def make_event_key(self, session_id: str | None, playback_event_key: str) -> str:
        return make_watcher_playback_event_key(session_id, playback_event_key)

    def upsert_pending(self, event: dict, *, session_id: str | None, event_key: str) -> int:
        record = self._pending_record(event, event_key=event_key)
        if record is None:
            return 0
        from dancing_log.playback_record_writer import upsert_evidence_record

        return upsert_evidence_record(self.conn, record).changed

    def upsert_current_state(self, event: dict, *, session_id: str | None, event_key: str) -> int:
        completion_status = event.get("completion_status")
        completion_reason = str(event.get("completion_reason") or "")
        if completion_status == "completed":
            record = self._accepted_record(
                event,
                event_key=event_key,
                reason=completion_reason or "observed_completion_threshold",
            )
        elif completion_status == "interrupted":
            record = self._attention_record(
                event,
                event_key=event_key,
                reason=completion_reason or WATCHER_GRACEFUL_STOP_REASON,
            )
        else:
            record = self._pending_record(event, event_key=event_key)
        if record is None:
            return 0
        from dancing_log.playback_record_writer import upsert_evidence_record

        return upsert_evidence_record(self.conn, record).changed

    def mark_completed(
        self,
        event_key: str,
        *,
        event: dict,
        completed_at: str,
        played_seconds: float,
        required_played_seconds: float,
        reason: str,
    ) -> bool:
        update = dict(event)
        update.update(
            {
                "completion_status": "completed",
                "completion_reason": reason,
                "completed_at": completed_at,
                "interrupted_at": None,
                "played_seconds": round(float(played_seconds), 3),
                "required_played_seconds": round(float(required_played_seconds), 3),
            }
        )
        record = self._accepted_record(update, event_key=event_key, reason=reason)
        if record is None:
            return False
        from dancing_log.playback_record_writer import upsert_evidence_record

        return upsert_evidence_record(self.conn, record).changed > 0

    def mark_interrupted(
        self,
        event_key: str,
        *,
        event: dict,
        interrupted_at: str,
        played_seconds: float | None,
        required_played_seconds: float | None,
        reason: str,
    ) -> bool:
        update = dict(event)
        update.update(
            {
                "completion_status": "interrupted",
                "completion_reason": reason,
                "completed_at": None,
                "interrupted_at": interrupted_at,
                "played_seconds": round(float(played_seconds), 3)
                if played_seconds is not None
                else None,
                "required_played_seconds": round(float(required_played_seconds), 3)
                if required_played_seconds is not None
                else None,
            }
        )
        record = self._attention_record(update, event_key=event_key, reason=reason)
        if record is None:
            return False
        from dancing_log.playback_record_writer import upsert_evidence_record

        return upsert_evidence_record(self.conn, record).changed > 0

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def close(self) -> None:
        self.conn.close()

    def _pending_record(self, event: dict, *, event_key: str):
        dance_track_id = self._ensure_track(event)
        if dance_track_id is None:
            return None
        return pending_watcher_playback_record(
            event,
            source_event_key=event_key,
            dance_track_id=dance_track_id,
        )

    def _accepted_record(self, event: dict, *, event_key: str, reason: str):
        dance_track_id = self._ensure_track(event)
        if dance_track_id is None:
            return None
        return accepted_watcher_playback_record(
            event,
            source_event_key=event_key,
            dance_track_id=dance_track_id,
            reason=reason,
        )

    def _attention_record(self, event: dict, *, event_key: str, reason: str):
        dance_track_id = self._ensure_track(event)
        if dance_track_id is None:
            return None
        return attention_watcher_playback_record(
            event,
            source_event_key=event_key,
            dance_track_id=dance_track_id,
            reason=reason,
        )

    def _ensure_track(self, event: dict) -> int | None:
        system_key = str(event.get("dance_system_key") or "").strip()
        external_id = str(event.get("dance_external_id") or "").strip()
        if not system_key or not external_id:
            return None
        from dancing_log.storage import ensure_dance_track

        return ensure_dance_track(
            self.conn,
            system_key,
            external_id,
            {"title": event.get("video_name")},
        )


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
        event: dict | None = None,
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
        event: dict | None = None,
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
    """Own settlement and current-state rules for live playback."""

    def __init__(
        self,
        *,
        stats: LivePlaybackRuntimeStats,
        app_db_path: Path | str | None = None,
        live_db: bool = False,
        record_playback: bool = False,
        overlay_port: int | None = None,
        store: LivePlaybackStore | None = None,
        live_store: SQLiteLivePlaybackStore | None = None,
        overlay: LivePlaybackOverlay | None = None,
    ) -> None:
        self.stats = stats
        self.store = store
        self.live_store = live_store
        self.overlay = overlay
        self.playback_builder: PlaybackEventBuilder | None = None
        self.live_events: dict[str, dict] = {}
        self.finalized_live_keys: set[str] = set()
        self.current_room_name: str | None = None

        if self.store is None and self.live_store is None and (record_playback or live_db):
            from dancing_log.storage import connect_db

            conn = connect_db(app_db_path)
            if record_playback:
                self.store = SQLiteWatcherPlaybackStore(conn)
            if live_db:
                self.live_store = SQLiteLivePlaybackStore(conn)
        else:
            if self.store is None and record_playback:
                self.store = SQLiteWatcherPlaybackStore.open(app_db_path)
            if self.live_store is None and live_db:
                self.live_store = SQLiteLivePlaybackStore.open(app_db_path)
        if self.overlay is None and overlay_port is not None:
            self.overlay = ObsOverlayAdapter.start(overlay_port)
        if self.overlay is not None:
            self.stats.overlay_url = self.overlay.url

    def close(self) -> None:
        if self.overlay is not None:
            self.overlay.close()
            self.overlay = None
        stores = [store for store in (self.store, self.live_store) if store is not None]
        seen_conns: set[int] = set()
        for store in stores:
            conn = getattr(store, "conn", None)
            key = id(conn) if conn is not None else id(store)
            if key in seen_conns:
                continue
            seen_conns.add(key)
            store.close()
        self.store = None
        self.live_store = None

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
        watcher_event_key = make_watcher_playback_event_key(
            self.stats.live_session_id,
            str(event["event_key"]),
        )
        update["watcher_event_key"] = watcher_event_key
        update["live_event_key"] = watcher_event_key
        if self.store is not None or self.live_store is not None:
            try:
                existing_update = self.live_events.get(watcher_event_key)
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
                record_update = dict(event)
                for field_name in (
                    "completion_status",
                    "completion_reason",
                    "completed_at",
                    "interrupted_at",
                    "played_seconds",
                    "required_played_seconds",
                ):
                    if field_name in update:
                        record_update[field_name] = update.get(field_name)
                identity_backfill = bool(event.get("requester_user_id")) and not bool(
                    existing_update and existing_update.get("requester_user_id")
                )
                if self.store is not None and (
                    watcher_event_key not in self.finalized_live_keys or identity_backfill
                ):
                    upsert_current_state = getattr(self.store, "upsert_current_state", None)
                    if upsert_current_state is not None:
                        self.stats.playback_record_updates += upsert_current_state(
                            record_update,
                            session_id=self.stats.live_session_id,
                            event_key=watcher_event_key,
                        )
                    elif watcher_event_key not in self.finalized_live_keys:
                        self.stats.playback_record_updates += self.store.upsert_pending(
                            record_update,
                            session_id=self.stats.live_session_id,
                            event_key=watcher_event_key,
                        )
                if self.live_store is not None:
                    self.live_store.upsert(
                        event,
                        session_id=self.stats.live_session_id,
                        event_key=watcher_event_key,
                    )
                    self.stats.live_db_updates += 1
                self.live_events[watcher_event_key] = update
                actual_observed_at = event.get("actual_play_at")
                if actual_observed_at:
                    self.settle_pending_events(
                        observed_at=actual_observed_at,
                        current_live_event_key=watcher_event_key,
                        interrupt_others=True,
                    )
                else:
                    first_observed_at = event.get("first_seen_at")
                    if first_observed_at:
                        self.settle_pending_events(
                            observed_at=first_observed_at,
                            current_live_event_key=watcher_event_key,
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
                self._commit_stores()
            except Exception as exc:
                self._record_error(f"live playback update failed: {exc}")
                self._rollback_stores()
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
            "video-shutdown": "video_shutdown",
        }.get(str(event_type), "playback_stopped")

        if observed_at and (self.store is not None or self.live_store is not None):
            try:
                if self.settle_pending_events(
                    observed_at=str(observed_at),
                    interrupt_others=True,
                    completion_reason="observed_completion_threshold",
                    interrupt_reason=interrupt_reason,
                ):
                    self._commit_stores()
            except Exception as exc:
                self._record_error(f"live lifecycle settlement failed: {exc}")
                self._rollback_stores()

        if self.overlay is not None:
            status = dict(event)
            status["room_name"] = status.get("room_name") or self.current_room_name
            status["clear_current"] = True
            self.overlay.publish_status(status)

        if event_type in {"room-left", "application-quit"}:
            self.current_room_name = None

    def is_stale_observation(self, observed_at: str | None) -> bool:
        return timestamp_before(observed_at, self.stats.last_log_timestamp)

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
        if self.store is None and self.live_store is None:
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
            changed = False
            if self.store is not None:
                record_changed = self.store.mark_completed(
                    live_event_key,
                    event=event,
                    completed_at=settlement.observed_at,
                    played_seconds=settlement.played_seconds,
                    required_played_seconds=settlement.required_played_seconds,
                    reason=settlement.reason,
                )
                if record_changed:
                    self.stats.playback_record_updates += 1
                changed = record_changed or changed
            if self.live_store is not None:
                changed = (
                    self.live_store.mark_completed(
                        live_event_key,
                        event=event,
                        completed_at=settlement.observed_at,
                        played_seconds=settlement.played_seconds,
                        required_played_seconds=settlement.required_played_seconds,
                        reason=settlement.reason,
                    )
                    or changed
                )
        else:
            changed = False
            if self.store is not None:
                record_changed = self.store.mark_interrupted(
                    live_event_key,
                    event=event,
                    interrupted_at=settlement.observed_at,
                    played_seconds=settlement.played_seconds,
                    required_played_seconds=settlement.required_played_seconds,
                    reason=settlement.reason,
                )
                if record_changed:
                    self.stats.playback_record_updates += 1
                changed = record_changed or changed
            if self.live_store is not None:
                changed = (
                    self.live_store.mark_interrupted(
                        live_event_key,
                        event=event,
                        interrupted_at=settlement.observed_at,
                        played_seconds=settlement.played_seconds,
                        required_played_seconds=settlement.required_played_seconds,
                        reason=settlement.reason,
                    )
                    or changed
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

    def settle_graceful_stop(self) -> None:
        """Settle active watcher records when the watcher stops normally."""
        if self.playback_builder is not None:
            self.playback_builder.close_open_events()
        observed_at = self.stats.last_log_timestamp
        if not observed_at or (self.store is None and self.live_store is None):
            return
        try:
            if self.settle_pending_events(
                observed_at=observed_at,
                interrupt_others=True,
                completion_reason="observed_completion_threshold",
                interrupt_reason=WATCHER_GRACEFUL_STOP_REASON,
            ):
                self._commit_stores()
        except Exception as exc:
            self._record_error(f"live graceful-stop settlement failed: {exc}")
            self._rollback_stores()

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
        if self.store is None and self.live_store is None:
            return
        try:
            if self.settle_pending_events(observed_at=timestamp):
                self._commit_stores()
        except Exception as exc:
            self._record_error(f"live completion check failed: {exc}")
            self._rollback_stores()

    def _record_error(self, message: str) -> None:
        if not self.stats.errors or self.stats.errors[-1] != message:
            self.stats.errors.append(message)

    def _commit_stores(self) -> None:
        seen_conns: set[int] = set()
        for store in (self.store, self.live_store):
            if store is None:
                continue
            conn = getattr(store, "conn", None)
            key = id(conn) if conn is not None else id(store)
            if key in seen_conns:
                continue
            seen_conns.add(key)
            store.commit()

    def _rollback_stores(self) -> None:
        seen_conns: set[int] = set()
        for store in (self.store, self.live_store):
            if store is None:
                continue
            conn = getattr(store, "conn", None)
            key = id(conn) if conn is not None else id(store)
            if key in seen_conns:
                continue
            seen_conns.add(key)
            store.rollback()
