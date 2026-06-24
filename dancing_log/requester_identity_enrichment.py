"""Session-local requester identity enrichment for watcher playback events."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Mapping

from dancing_log.vrc_log_utils import clean_display_name, seconds_between


REQUESTER_IDENTITY_SOURCE_ACTIVE = "active"
REQUESTER_IDENTITY_SOURCE_EXPIRED = "expired"
REQUESTER_IDENTITY_SOURCE_PAYLOAD = "payload"
EXPIRED_MAPPING_GRACE_SECONDS = 60.0


@dataclass(frozen=True)
class RequesterIdentityBackfill:
    """A delayed requester-user-id fill for one folded watcher event."""

    event_key: str
    display_name: str
    requester_user_id: str
    source: str


@dataclass(frozen=True)
class _PendingRequester:
    event_key: str
    display_name: str
    room_id: int
    observed_at: str | None = None
    expired_candidate_user_id: str | None = None


class RequesterIdentityEnricher:
    """Maintain transient display-name to user-id mappings for one watcher session."""

    def __init__(
        self,
        *,
        warnings: list[str] | None = None,
        expired_mapping_grace_seconds: float = EXPIRED_MAPPING_GRACE_SECONDS,
    ) -> None:
        self.active_by_display: dict[str, str] = {}
        self.expired_by_display: dict[str, str] = {}
        self.room_state = "cleared"
        self.room_entered_at: str | None = None
        self.expired_mapping_grace_seconds = max(0.0, float(expired_mapping_grace_seconds))
        self.room_id = 0
        self.counts: Counter[str] = Counter()
        self.warnings = warnings if warnings is not None else []
        self._pending_by_display: dict[str, dict[str, _PendingRequester]] = {}
        self._warning_keys: set[tuple[str, str, str | None]] = set()

    def observe_lifecycle(self, event: Mapping[str, object]) -> None:
        event_type = str(event.get("event_type") or "")
        if event_type == "room-entering":
            self._expire_active()
            self._clear_pending()
            self.room_id += 1
            self.room_state = "active"
            self.room_entered_at = _text_or_none(event.get("observed_at") or event.get("timestamp"))
            self.counts["room_entering_events"] += 1
            return

        if event_type == "room-left":
            self._expire_active()
            self.room_state = "closing"
            self.room_entered_at = None
            self.counts["room_left_events"] += 1
            return

        if event_type in {"application-quit", "video-shutdown"}:
            self.active_by_display.clear()
            self.expired_by_display.clear()
            self._clear_pending()
            self.room_state = "cleared"
            self.room_entered_at = None
            self.counts["clear_events"] += 1

    def observe_identity(
        self,
        event: Mapping[str, object],
        *,
        warn: bool = True,
    ) -> list[RequesterIdentityBackfill]:
        display_name = clean_display_name(str(event.get("display_name") or ""))
        user_id = str(event.get("user_id") or "").strip()
        if not display_name or not user_id:
            return []

        self.counts["identity_events"] += 1
        event_type = str(event.get("event_type") or "")
        if event_type == "player-joined":
            self.room_state = "active"
            self._set_active(display_name, user_id, warn=warn)
            return self._backfills_for(
                display_name,
                user_id,
                REQUESTER_IDENTITY_SOURCE_ACTIVE,
                warn=warn,
            )

        if event_type == "user-authenticated":
            if self.room_state != "active":
                self.counts["authenticated_without_active_room"] += 1
                return []
            self._set_active(display_name, user_id, warn=warn)
            return self._backfills_for(
                display_name,
                user_id,
                REQUESTER_IDENTITY_SOURCE_ACTIVE,
                warn=warn,
            )

        if event_type == "player-left":
            if self.room_state == "cleared":
                self._record_unpaired_player_left(display_name, user_id, warn=warn)
                return []
            self._retire(display_name, user_id, warn=warn)
            return self._backfills_for(
                display_name,
                user_id,
                REQUESTER_IDENTITY_SOURCE_EXPIRED,
                warn=warn,
            )

        return []

    def enrich_record(self, record: Mapping[str, object]) -> dict:
        enriched = dict(record)
        requester_user_id = str(enriched.get("requester_user_id") or "").strip()
        if requester_user_id:
            enriched["requester_user_id"] = requester_user_id
            if not enriched.get("requester_user_id_source"):
                enriched["requester_user_id_source"] = REQUESTER_IDENTITY_SOURCE_PAYLOAD
            self.counts["payload_enrichments"] += 1
            return enriched

        display_name = clean_display_name(str(enriched.get("display_name") or ""))
        if not display_name:
            return enriched

        if self.room_state == "cleared":
            self.counts["unresolved_missing_room_context"] += 1
            self._warn(
                "missing-room-context",
                display_name,
                None,
                f"requester identity could not resolve {display_name}; watcher has no active room context",
            )
            return enriched

        if self.room_state == "closing":
            self.counts["unresolved_closing_room"] += 1
            return enriched

        active_user_id = self.active_by_display.get(display_name)
        if active_user_id:
            enriched["requester_user_id"] = active_user_id
            enriched["requester_user_id_source"] = REQUESTER_IDENTITY_SOURCE_ACTIVE
            self.counts["active_enrichments"] += 1
            return enriched

        expired_user_id = self.expired_by_display.get(display_name)
        if expired_user_id:
            if not self._expired_lookup_ready(_text_or_none(enriched.get("timestamp"))):
                self.counts["deferred_expired_enrichments"] += 1
                return enriched
            enriched["requester_user_id"] = expired_user_id
            enriched["requester_user_id_source"] = REQUESTER_IDENTITY_SOURCE_EXPIRED
            self.counts["expired_enrichments"] += 1
            self._warn(
                "expired-lookup",
                display_name,
                expired_user_id,
                f"requester identity used expired mapping for {display_name} ({expired_user_id})",
            )
            return enriched

        self.counts["unresolved_active_room"] += 1
        return enriched

    def remember_pending(self, record: Mapping[str, object], folded_event: Mapping[str, object] | None) -> None:
        if folded_event is None:
            return
        if record.get("requester_user_id"):
            return
        if folded_event.get("requester_user_id"):
            return
        if self.room_state != "active":
            return
        display_name = clean_display_name(str(record.get("display_name") or ""))
        event_key = str(folded_event.get("event_key") or "")
        if not display_name or not event_key:
            return

        expired_candidate_user_id = None
        if display_name in self.expired_by_display and not self._expired_lookup_ready(
            _text_or_none(record.get("timestamp"))
        ):
            expired_candidate_user_id = self.expired_by_display[display_name]

        pending_by_key = self._pending_by_display.setdefault(display_name, {})
        if event_key not in pending_by_key:
            pending_by_key[event_key] = _PendingRequester(
                event_key=event_key,
                display_name=display_name,
                room_id=self.room_id,
                observed_at=_text_or_none(record.get("timestamp")),
                expired_candidate_user_id=expired_candidate_user_id,
            )
            self.counts["pending_events"] += 1

    def release_deferred_expired(self, observed_at: str | None) -> list[RequesterIdentityBackfill]:
        """Backfill pending events after the cross-room expired-mapping grace window."""
        if self.room_state != "active":
            return []
        if not self._expired_lookup_ready(observed_at):
            return []

        backfills = self._release_pending_expired()
        if backfills:
            self.counts["expired_deferred_backfilled_events"] += len(backfills)
            for backfill in backfills:
                self._warn(
                    "expired-deferred-backfill",
                    backfill.display_name,
                    backfill.requester_user_id,
                    (
                        "requester identity backfilled "
                        f"{backfill.display_name} ({backfill.requester_user_id}) "
                        "from expired mapping after grace window"
                    ),
                )
        return backfills

    def release_session_end_expired(self) -> list[RequesterIdentityBackfill]:
        """Try one final expired-mapping backfill pass at normal watcher session end."""
        backfills = self._release_pending_expired()
        if backfills:
            self.counts["expired_session_end_backfilled_events"] += len(backfills)
            for backfill in backfills:
                self._warn(
                    "expired-session-end-backfill",
                    backfill.display_name,
                    backfill.requester_user_id,
                    (
                        "requester identity backfilled "
                        f"{backfill.display_name} ({backfill.requester_user_id}) "
                        "from expired mapping at session end"
                    ),
                )
        return backfills

    def _release_pending_expired(self) -> list[RequesterIdentityBackfill]:
        backfills: list[RequesterIdentityBackfill] = []
        for display_name, pending_by_key in list(self._pending_by_display.items()):
            for event_key, pending in list(pending_by_key.items()):
                if pending.room_id != self.room_id or not pending.expired_candidate_user_id:
                    continue
                backfills.append(
                    RequesterIdentityBackfill(
                        event_key=event_key,
                        display_name=display_name,
                        requester_user_id=pending.expired_candidate_user_id,
                        source=REQUESTER_IDENTITY_SOURCE_EXPIRED,
                    )
                )
                pending_by_key.pop(event_key, None)
            if not pending_by_key:
                self._pending_by_display.pop(display_name, None)
        return backfills

    def summary(self) -> dict[str, int | str]:
        pending_count = sum(len(entries) for entries in self._pending_by_display.values())
        summary = {
            "room_state": self.room_state,
            "active_mappings": len(self.active_by_display),
            "expired_mappings": len(self.expired_by_display),
            "pending_backfills": pending_count,
            "warnings": len(self.warnings),
        }
        if pending_count:
            summary["unresolved_pending_events"] = pending_count
            summary[f"unresolved_pending_{self.room_state}_room"] = pending_count
        summary.update(dict(sorted(self.counts.items())))
        return summary

    def _set_active(self, display_name: str, user_id: str, *, warn: bool) -> None:
        previous_user_id = self.active_by_display.get(display_name) or self.expired_by_display.get(display_name)
        if previous_user_id and previous_user_id != user_id:
            self.counts["display_name_user_id_changes"] += 1
            if warn:
                self._warn(
                    "display-name-user-id-changed",
                    display_name,
                    user_id,
                    (
                        "requester identity changed for "
                        f"{display_name}: {previous_user_id} -> {user_id}"
                    ),
                )
        self.active_by_display[display_name] = user_id
        self.expired_by_display.pop(display_name, None)

    def _retire(self, display_name: str, user_id: str, *, warn: bool) -> None:
        active_user_id = self.active_by_display.pop(display_name, None)
        previous_user_id = active_user_id or self.expired_by_display.get(display_name)
        if previous_user_id and previous_user_id != user_id:
            self.counts["display_name_user_id_changes"] += 1
            if warn:
                self._warn(
                    "display-name-user-id-changed",
                    display_name,
                    user_id,
                    (
                        "requester identity changed for "
                        f"{display_name}: {previous_user_id} -> {user_id}"
                    ),
                )
        elif previous_user_id is None:
            self._record_unpaired_player_left(display_name, user_id, warn=warn)
        self.expired_by_display[display_name] = user_id

    def _record_unpaired_player_left(self, display_name: str, user_id: str, *, warn: bool) -> None:
        self.counts["unpaired_player_left_events"] += 1
        if warn:
            self._warn(
                "unpaired-player-left",
                display_name,
                user_id,
                f"requester identity saw OnPlayerLeft without active mapping for {display_name} ({user_id})",
            )

    def _backfills_for(
        self,
        display_name: str,
        user_id: str,
        source: str,
        *,
        warn: bool,
    ) -> list[RequesterIdentityBackfill]:
        pending_by_key = self._pending_by_display.get(display_name)
        if not pending_by_key:
            return []

        backfills: list[RequesterIdentityBackfill] = []
        for event_key, pending in list(pending_by_key.items()):
            if pending.room_id != self.room_id:
                continue
            backfills.append(
                RequesterIdentityBackfill(
                    event_key=event_key,
                    display_name=display_name,
                    requester_user_id=user_id,
                    source=source,
                )
            )
            pending_by_key.pop(event_key, None)

        if not pending_by_key:
            self._pending_by_display.pop(display_name, None)

        if backfills:
            self.counts["backfilled_events"] += len(backfills)
            if source == REQUESTER_IDENTITY_SOURCE_EXPIRED and warn:
                self._warn(
                    "expired-backfill",
                    display_name,
                    user_id,
                    f"requester identity backfilled {display_name} ({user_id}) from expired mapping",
                )
        return backfills

    def _expire_active(self) -> None:
        self.expired_by_display.update(self.active_by_display)
        self.active_by_display.clear()

    def _expired_lookup_ready(self, timestamp: str | None) -> bool:
        if self.expired_mapping_grace_seconds <= 0:
            return True
        if self.room_state != "active":
            return True
        if not self.room_entered_at or not timestamp:
            return False
        elapsed = seconds_between(self.room_entered_at, timestamp)
        return elapsed is not None and elapsed >= self.expired_mapping_grace_seconds

    def _clear_pending(self) -> None:
        self._pending_by_display.clear()

    def _warn(
        self,
        warning_type: str,
        display_name: str,
        user_id: str | None,
        message: str,
    ) -> None:
        key = (warning_type, display_name, user_id)
        if key in self._warning_keys:
            return
        self._warning_keys.add(key)
        self.warnings.append(message)


def _text_or_none(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
