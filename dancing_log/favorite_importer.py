"""Import local favorite flags from a plain text track list."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from dancing_log.storage import DB_FILE, connect_db


WANNA_FAVORITE_PREFIX = "WannaFavorite:"


class FavoriteImportError(ValueError):
    """Raised when a favorite import cannot be applied safely."""


@dataclass
class FavoriteImportStats:
    system_key: str
    input_ids: int
    unique_ids: int
    duplicate_ids: int
    favorites_set: int
    favorites_cleared: int
    additive: bool
    dry_run: bool


def import_favorites_file(
    *,
    system_key: str,
    favorites_file: Path | str,
    app_db_path: Path | str | None = None,
    additive: bool = False,
    dry_run: bool = False,
) -> FavoriteImportStats:
    """Import favorite flags for one dance system from a newline-delimited file."""
    normalized_system_key = _normalize_system_key(system_key)
    parsed = _parse_favorite_file(favorites_file)
    imported_ids = set(parsed.ids)

    with connect_db(app_db_path or DB_FILE) as conn:
        system = conn.execute(
            "SELECT id FROM dance_systems WHERE key = ?",
            (normalized_system_key,),
        ).fetchone()
        if system is None:
            raise FavoriteImportError(f"Unknown dance system: {normalized_system_key}")

        rows = conn.execute(
            """
            SELECT dt.external_id, dt.favorite
            FROM dance_tracks dt
            WHERE dt.system_id = ?
            """,
            (int(system["id"]),),
        ).fetchall()
        existing = {str(row["external_id"]): int(row["favorite"]) for row in rows}
        unknown_ids = sorted(imported_ids - set(existing), key=_external_id_sort_key)
        if unknown_ids:
            sample = ", ".join(unknown_ids[:10])
            suffix = "" if len(unknown_ids) <= 10 else f", ... ({len(unknown_ids)} total)"
            raise FavoriteImportError(
                f"Unknown track id(s) for {normalized_system_key}: {sample}{suffix}"
            )

        favorites_set = sum(
            1 for external_id in imported_ids if existing.get(external_id, 0) != 1
        )
        favorites_cleared = 0
        if not additive:
            favorites_cleared = sum(
                1
                for external_id, favorite in existing.items()
                if favorite == 1 and external_id not in imported_ids
            )

        if not dry_run:
            if imported_ids:
                conn.executemany(
                    """
                    UPDATE dance_tracks
                    SET favorite = 1,
                        updated_at = datetime('now')
                    WHERE system_id = ? AND external_id = ? AND favorite != 1
                    """,
                    [(int(system["id"]), external_id) for external_id in imported_ids],
                )
            if not additive:
                if imported_ids:
                    conn.execute(
                        """
                        UPDATE dance_tracks
                        SET favorite = 0,
                            updated_at = datetime('now')
                        WHERE system_id = ?
                          AND favorite != 0
                          AND external_id NOT IN (
                        """
                        + ",".join("?" for _ in imported_ids)
                        + ")",
                        (int(system["id"]), *imported_ids),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE dance_tracks
                        SET favorite = 0,
                            updated_at = datetime('now')
                        WHERE system_id = ?
                          AND favorite != 0
                        """,
                        (int(system["id"]),),
                    )
            conn.commit()

    return FavoriteImportStats(
        system_key=normalized_system_key,
        input_ids=parsed.input_ids,
        unique_ids=len(parsed.ids),
        duplicate_ids=parsed.duplicate_ids,
        favorites_set=favorites_set,
        favorites_cleared=favorites_cleared,
        additive=additive,
        dry_run=dry_run,
    )


@dataclass
class _ParsedFavoriteFile:
    ids: list[str]
    input_ids: int
    duplicate_ids: int


def _parse_favorite_file(path: Path | str) -> _ParsedFavoriteFile:
    input_path = Path(path)
    try:
        text = input_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise FavoriteImportError(f"Could not read favorites file: {input_path}") from exc

    if text.lstrip().startswith(WANNA_FAVORITE_PREFIX):
        return _parse_prefixed_comma_list(text)

    seen: set[str] = set()
    ids: list[str] = []
    input_ids = 0
    duplicate_ids = 0
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        external_id = raw_line.strip()
        if not external_id:
            raise FavoriteImportError(f"Missing track id on line {line_number}")
        if re.search(r"\s", external_id):
            raise FavoriteImportError(
                f"Line {line_number} must contain one track id only"
            )
        input_ids += 1
        if external_id in seen:
            duplicate_ids += 1
            continue
        seen.add(external_id)
        ids.append(external_id)
    return _ParsedFavoriteFile(ids=ids, input_ids=input_ids, duplicate_ids=duplicate_ids)


def _parse_prefixed_comma_list(text: str) -> _ParsedFavoriteFile:
    leading_stripped = text.lstrip()
    payload = leading_stripped.removeprefix(WANNA_FAVORITE_PREFIX).strip()
    if not payload:
        raise FavoriteImportError("WannaFavorite list does not contain any track ids")

    tokens = payload.split(",")
    seen: set[str] = set()
    ids: list[str] = []
    duplicate_ids = 0
    for index, raw_token in enumerate(tokens, 1):
        external_id = raw_token.strip()
        if not external_id:
            raise FavoriteImportError(f"Missing track id in WannaFavorite list at position {index}")
        if re.search(r"\s", external_id):
            raise FavoriteImportError(
                f"WannaFavorite list position {index} must contain one track id only"
            )
        if external_id in seen:
            duplicate_ids += 1
            continue
        seen.add(external_id)
        ids.append(external_id)
    return _ParsedFavoriteFile(
        ids=ids,
        input_ids=len(tokens),
        duplicate_ids=duplicate_ids,
    )


def _normalize_system_key(system_key: str) -> str:
    normalized = system_key.strip().lower()
    if not normalized:
        raise FavoriteImportError("Dance system key must not be empty")
    return normalized


def _external_id_sort_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)
