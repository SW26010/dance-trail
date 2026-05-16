"""Overlay queued-self manifests onto existing dance events."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
import sqlite3

from dancing_log.storage import DATA_DIR, connect_db
from dancing_log.vrcx_importer import SOURCE_PRIORITY_SQL


QUEUED_SELF_DIR = DATA_DIR / "queued_self"
SOURCE_QUEUED_SELF = "queued_self"
EVENT_SOURCE = "queued_self_manifest"

DATE_RE = re.compile(r"^\s*#*\s*(\d{4}-\d{2}-\d{2})\s*$")
NUMBERED_ENTRY_RE = re.compile(
    r"(?P<song_id>\d+)\s*[.。]\s*(?P<label>.*?)(?=(?:\s+\d+\s*[.。]\s*)|$)"
)


@dataclass(frozen=True)
class QueuedSelfEntry:
    played_date: date
    song_id: int | None
    label: str
    source_file: Path
    ordinal: int


@dataclass(frozen=True)
class QueuedSelfImportStats:
    files_scanned: int = 0
    entries_seen: int = 0
    entries_with_song_id: int = 0
    entries_without_song_id: int = 0
    matched_entries: int = 0
    unmatched_entries: int = 0
    existing_events_updated: int = 0
    stale_manifest_events_deleted: int = 0


def parse_queued_self_file(path: Path) -> list[QueuedSelfEntry]:
    """Parse one Markdown queued-self manifest."""
    entries: list[QueuedSelfEntry] = []
    current_date: date | None = None
    ordinal = 0

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

        numbered = list(NUMBERED_ENTRY_RE.finditer(line))
        if numbered:
            for match in numbered:
                ordinal += 1
                entries.append(
                    QueuedSelfEntry(
                        played_date=current_date,
                        song_id=int(match.group("song_id")),
                        label=match.group("label").strip(),
                        source_file=path,
                        ordinal=ordinal,
                    )
                )
            continue

        ordinal += 1
        entries.append(
            QueuedSelfEntry(
                played_date=current_date,
                song_id=None,
                label=line,
                source_file=path,
                ordinal=ordinal,
            )
        )

    return entries


def load_queued_self_entries(
    manifest_dir: Path | str | None = None,
) -> list[QueuedSelfEntry]:
    """Load all queued-self Markdown manifests from a directory."""
    root = Path(manifest_dir) if manifest_dir is not None else QUEUED_SELF_DIR
    if not root.exists():
        return []

    entries: list[QueuedSelfEntry] = []
    for path in sorted(root.glob("*.md")):
        entries.extend(parse_queued_self_file(path))
    return entries


def sync_queued_self_manifests(
    app_db_path: Path | str | None = None,
    manifest_dir: Path | str | None = None,
) -> QueuedSelfImportStats:
    """Apply queued-self manifests as a source override on existing events."""
    root = Path(manifest_dir) if manifest_dir is not None else QUEUED_SELF_DIR
    entries = load_queued_self_entries(root)

    with connect_db(app_db_path) as conn:
        deleted = conn.execute(
            "DELETE FROM dance_events WHERE event_source = ?",
            (EVENT_SOURCE,),
        ).rowcount

        matched_entries = 0
        unmatched_entries = 0
        existing_updates = 0

        for entry in entries:
            if entry.song_id is None:
                unmatched_entries += 1
                continue

            matched_existing = _matching_existing_event_count(conn, entry)
            if matched_existing == 0:
                unmatched_entries += 1
                continue

            matched_entries += 1
            existing_updates += _promote_existing_event(conn, entry)

        conn.commit()

    return QueuedSelfImportStats(
        files_scanned=len(list(root.glob("*.md"))) if root.exists() else 0,
        entries_seen=len(entries),
        entries_with_song_id=sum(1 for entry in entries if entry.song_id is not None),
        entries_without_song_id=sum(1 for entry in entries if entry.song_id is None),
        matched_entries=matched_entries,
        unmatched_entries=unmatched_entries,
        existing_events_updated=existing_updates,
        stale_manifest_events_deleted=deleted,
    )


def _promote_existing_event(conn: sqlite3.Connection, entry: QueuedSelfEntry) -> int:
    cursor = conn.execute(
        """
        UPDATE dance_events
        SET
            source = ?,
            confidence = 1.0
        WHERE
            song_id = ?
            AND substr(played_at, 1, 10) = ?
            AND (
                """ + SOURCE_PRIORITY_SQL.format(column="source") + """
                < """ + SOURCE_PRIORITY_SQL.format(column="?") + """
                OR (source = ? AND confidence < 1.0)
            )
        """,
        (
            SOURCE_QUEUED_SELF,
            entry.song_id,
            entry.played_date.isoformat(),
            SOURCE_QUEUED_SELF,
            SOURCE_QUEUED_SELF,
        ),
    )
    return cursor.rowcount


def _matching_existing_event_count(
    conn: sqlite3.Connection,
    entry: QueuedSelfEntry,
) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM dance_events
        WHERE
            event_source != ?
            AND song_id = ?
            AND substr(played_at, 1, 10) = ?
        """,
        (EVENT_SOURCE, entry.song_id, entry.played_date.isoformat()),
    ).fetchone()
    return int(row[0])
