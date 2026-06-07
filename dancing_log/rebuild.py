"""Local data archive and rebuild helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil

from dancing_log.storage import DATA_DIR


ARCHIVE_NAMES = (
    "dancing_log.sqlite3",
    "dancing_log.sqlite3-wal",
    "dancing_log.sqlite3-shm",
    "songs.csv",
    "wanna_songs.csv",
    "wanna_songs.json",
)


@dataclass(frozen=True)
class ArchiveStats:
    archive_dir: Path
    archived: tuple[Path, ...]


def archive_existing_data(
    data_dir: Path | str | None = None,
    app_db_path: Path | str | None = None,
) -> ArchiveStats:
    """Move old generated data files into data/archive/<timestamp>."""
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    archive_dir = root / "archive" / timestamp
    archived: list[Path] = []
    seen: set[Path] = set()

    sources = [root / name for name in ARCHIVE_NAMES]
    if app_db_path is not None:
        db_path = Path(app_db_path)
        sources.extend(
            [
                db_path,
                Path(str(db_path) + "-wal"),
                Path(str(db_path) + "-shm"),
            ]
        )

    for source in sources:
        if not source.exists():
            continue
        resolved_source = source.resolve()
        if resolved_source in seen:
            continue
        seen.add(resolved_source)
        archive_dir.mkdir(parents=True, exist_ok=True)
        target = _unique_archive_target(archive_dir, source.name)
        shutil.move(str(source), str(target))
        archived.append(target)

    return ArchiveStats(archive_dir=archive_dir, archived=tuple(archived))


def _unique_archive_target(archive_dir: Path, name: str) -> Path:
    target = archive_dir / name
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    counter = 2
    while True:
        candidate = archive_dir / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
