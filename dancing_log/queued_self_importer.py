"""Overlay queued-self manifests onto existing Local Playback Evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
import sqlite3

from dancing_log.app_paths import QUEUED_SELF_DIR
from dancing_log.storage import connect_db
from dancing_log.time_utils import SQLITE_UTC_NOW
from dancing_log.vrcx_importer import SOURCE_TYPE_PRECEDENCE_SQL


SOURCE_QUEUED_SELF = "queued_self"
LOCAL_PLAYED_DATE_OFFSET_SQL = "'+8 hours'"

DATE_RE = re.compile(r"^\s*#*\s*(\d{4}-\d{2}-\d{2})\s*$")
BARE_DOTTED_TRACK_REF_RE = re.compile(
    r"(?:^|\s|[?？|])(?:\d+\s*[.、)]\s*)?"
    r"(?P<external_id>\d+)[.、)]\s*"
    r"(?P<label>.*?)(?=(?:\s|[?？|])(?:\d+\s*[.、)]\s*)?\d+[.、)]\s*|$)"
)
BARE_SPACED_TRACK_REF_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\d+\s*[.、)]\s*)?"
    r"(?P<external_id>\d+)\s+(?P<label>.*?)\s*$"
)
TRACK_REF_RE = re.compile(
    r"(?:^|\s)(?:\d+\s*[.。]\s*)?"
    r"(?P<system>[A-Za-z][A-Za-z0-9_-]*):(?P<external_id>\S+)"
    r"\s*(?P<label>.*?)(?=(?:\s+(?:\d+\s*[.。]\s*)?[A-Za-z][A-Za-z0-9_-]*:\S+)|$)"
)


@dataclass(frozen=True)
class QueuedSelfEntry:
    played_date: date
    system_key: str | None
    external_id: str | None
    label: str
    source_file: Path
    ordinal: int


@dataclass(frozen=True)
class QueuedSelfImportStats:
    files_scanned: int = 0
    entries_seen: int = 0
    entries_with_track_ref: int = 0
    entries_without_track_ref: int = 0
    matched_entries: int = 0
    unmatched_entries: int = 0
    existing_records_updated: int = 0
    stale_manifest_records_deleted: int = 0

    @property
    def existing_events_updated(self) -> int:
        """Compatibility alias for pre-playback-record callers."""
        return self.existing_records_updated

    @property
    def stale_manifest_events_deleted(self) -> int:
        """Compatibility alias for pre-playback-record callers."""
        return self.stale_manifest_records_deleted


def parse_queued_self_file(
    path: Path,
    default_system_key: str | None = None,
) -> list[QueuedSelfEntry]:
    """Parse one Markdown queued-self manifest."""
    entries: list[QueuedSelfEntry] = []
    current_date: date | None = None
    ordinal = 0
    normalized_default_system = _normalize_system_key(default_system_key)

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        date_match = DATE_RE.match(line)
        if date_match:
            current_date = date.fromisoformat(date_match.group(1))
            ordinal = 0
            continue

        if current_date is None:
            continue

        matches = list(TRACK_REF_RE.finditer(line))
        if matches:
            for match in matches:
                ordinal += 1
                entries.append(
                    QueuedSelfEntry(
                        played_date=current_date,
                        system_key=match.group("system").strip().lower(),
                        external_id=match.group("external_id").strip(),
                        label=match.group("label").strip(),
                        source_file=path,
                        ordinal=ordinal,
                    )
                )
            continue

        bare_matches = list(BARE_DOTTED_TRACK_REF_RE.finditer(line))
        if bare_matches:
            for match in bare_matches:
                ordinal += 1
                entries.append(
                    QueuedSelfEntry(
                        played_date=current_date,
                        system_key=normalized_default_system,
                        external_id=match.group("external_id").strip(),
                        label=match.group("label").strip(),
                        source_file=path,
                        ordinal=ordinal,
                    )
                )
            continue

        bare_match = BARE_SPACED_TRACK_REF_RE.match(line)
        if bare_match:
            ordinal += 1
            entries.append(
                QueuedSelfEntry(
                    played_date=current_date,
                    system_key=normalized_default_system,
                    external_id=bare_match.group("external_id").strip(),
                    label=bare_match.group("label").strip(),
                    source_file=path,
                    ordinal=ordinal,
                )
            )
            continue

        ordinal += 1
        entries.append(
            QueuedSelfEntry(
                played_date=current_date,
                system_key=None,
                external_id=None,
                label=line,
                source_file=path,
                ordinal=ordinal,
            )
        )

    return entries


def load_queued_self_entries(
    manifest_dir: Path | str | None = None,
    default_system_key: str | None = None,
) -> list[QueuedSelfEntry]:
    """Load all queued-self Markdown manifests from a directory."""
    root = Path(manifest_dir) if manifest_dir is not None else QUEUED_SELF_DIR
    if not root.exists():
        return []

    entries: list[QueuedSelfEntry] = []
    for path in sorted(root.glob("*.md")):
        entries.extend(
            parse_queued_self_file(path, default_system_key=default_system_key)
        )
    return entries


def sync_queued_self_manifests(
    app_db_path: Path | str | None = None,
    manifest_dir: Path | str | None = None,
    system_key: str | None = None,
) -> QueuedSelfImportStats:
    """Apply queued-self manifests as a source override on existing records."""
    root = Path(manifest_dir) if manifest_dir is not None else QUEUED_SELF_DIR
    entries = load_queued_self_entries(root, default_system_key=system_key)

    with connect_db(app_db_path) as conn:
        deleted = 0

        matched_entries = 0
        unmatched_entries = 0
        existing_updates = 0

        for entry in entries:
            if entry.system_key is None or entry.external_id is None:
                unmatched_entries += 1
                continue

            matched_existing = _matching_existing_record_count(conn, entry)
            if matched_existing == 0:
                unmatched_entries += 1
                continue

            matched_entries += 1
            existing_updates += _promote_existing_record(conn, entry)

        conn.commit()

    return QueuedSelfImportStats(
        files_scanned=len(list(root.glob("*.md"))) if root.exists() else 0,
        entries_seen=len(entries),
        entries_with_track_ref=sum(1 for entry in entries if entry.system_key and entry.external_id),
        entries_without_track_ref=sum(1 for entry in entries if not (entry.system_key and entry.external_id)),
        matched_entries=matched_entries,
        unmatched_entries=unmatched_entries,
        existing_records_updated=existing_updates,
        stale_manifest_records_deleted=deleted,
    )


def _promote_existing_record(conn: sqlite3.Connection, entry: QueuedSelfEntry) -> int:
    cursor = conn.execute(
        """
        UPDATE playback_records
        SET
            request_type = ?,
            updated_at = """ + SQLITE_UTC_NOW + """
        WHERE
            dance_track_id IN (
                SELECT dt.id
                FROM dance_tracks dt
                JOIN dance_systems ds ON ds.id = dt.system_id
                WHERE ds.key = ? AND dt.external_id = ?
            )
            AND """ + _played_at_local_date_sql("played_at") + """ = ?
            AND default_acceptance_status = 'accepted'
            AND (
                request_type IS NULL
                OR """ + SOURCE_TYPE_PRECEDENCE_SQL.format(column="request_type") + """
                < """ + SOURCE_TYPE_PRECEDENCE_SQL.format(column="?") + """
            )
        """,
        (
            SOURCE_QUEUED_SELF,
            entry.system_key,
            entry.external_id,
            entry.played_date.isoformat(),
            SOURCE_QUEUED_SELF,
        ),
    )
    return cursor.rowcount


def _matching_existing_record_count(
    conn: sqlite3.Connection,
    entry: QueuedSelfEntry,
) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM playback_records pr
        JOIN dance_tracks dt ON dt.id = pr.dance_track_id
        JOIN dance_systems ds ON ds.id = dt.system_id
        WHERE
            ds.key = ?
            AND dt.external_id = ?
            AND """ + _played_at_local_date_sql("pr.played_at") + """ = ?
            AND pr.default_acceptance_status = 'accepted'
        """,
        (
            entry.system_key,
            entry.external_id,
            entry.played_date.isoformat(),
        ),
    ).fetchone()
    return int(row[0])


def _normalize_system_key(system_key: str | None) -> str | None:
    if system_key is None:
        return None
    normalized = system_key.strip().lower()
    if not normalized:
        raise ValueError("system key must not be empty")
    return normalized


def _played_at_local_date_sql(column: str) -> str:
    return (
        "CASE "
        f"WHEN {column} LIKE '____.__.__ %' THEN replace(substr({column}, 1, 10), '.', '-') "
        f"ELSE date(replace({column}, 'Z', '+00:00'), {LOCAL_PLAYED_DATE_OFFSET_SQL}) "
        "END"
    )
