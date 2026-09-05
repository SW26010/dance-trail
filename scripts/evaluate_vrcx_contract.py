"""Evaluate the conservative VRCX-only contract on a read-only database.

This is an offline contract audit, not the production adapter. It never reads
watcher output, infers playback state, or writes source data. Reports contain
aggregate counts only. Raw input rows remain in the source or private snapshot.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[1]

RULE_VERSION = "vrcx-db-conservative-v1"
POSITIVE_ID = re.compile(r"[1-9][0-9]*\Z")
EXPLICIT_TIME = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])\Z"
)
QUERY_RULES = {
    ("api.udon.dance", "/Api/Songs/play"): "wannadance",
    ("api.udon.dance", "/api/songs/play"): "wannadance",
    ("api.wannadance.online", "/Api/Songs/play"): "wannadance",
    ("api.wannadance.online", "/api/songs/play"): "wannadance",
    ("api.pypy.dance", "/video"): "pypydance",
}
PATH_RULES = {
    "jd.pypy.moe": (re.compile(r"/api/v1/videos/([1-9][0-9]*)\.mp4\Z"), "pypydance"),
    "api.dudufit.dance": (re.compile(r"/api/v1/videos/([1-9][0-9]*)\Z"), "dudu"),
}
WANNADANCE_CDN = re.compile(r"/files/[^/]+/([1-9][0-9]*)-[^/]+\.mp4\Z", re.IGNORECASE)


def stable_dance_key(raw_url: object) -> tuple[str, str] | None:
    """Explicit host/path rules; no substring host matching or fallback guesses."""
    if not isinstance(raw_url, str) or not raw_url:
        return None
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in raw_url):
        return None
    try:
        url = urlsplit(raw_url)
        if url.scheme not in {"http", "https"} or not url.hostname:
            return None
        if url.username is not None or url.password is not None:
            return None
        default_port = 80 if url.scheme == "http" else 443
        if url.port not in {None, default_port}:
            return None
        host = url.hostname.lower()
        system = QUERY_RULES.get((host, url.path))
        if system:
            values = [
                value
                for key, value in parse_qsl(
                    url.query, keep_blank_values=True, errors="strict"
                )
                if key == "id"
            ]
            if len(values) == 1 and POSITIVE_ID.fullmatch(values[0]):
                return system, values[0]
        path_rule = PATH_RULES.get(host)
        if path_rule:
            pattern, system = path_rule
            match = pattern.fullmatch(url.path)
            if match:
                return system, match.group(1)
    except (ValueError, UnicodeError):
        return None
    return None


def valid_source_time(value: object) -> bool:
    """Require a valid ISO timestamp with explicit offset; never assume local TZ."""
    if not isinstance(value, str) or not EXPLICIT_TIME.fullmatch(value):
        return False
    try:
        return datetime.fromisoformat(value).utcoffset() is not None
    except ValueError:
        return False


def unique_positive_query_id(query: str) -> str | None:
    values = [
        value
        for key, value in parse_qsl(query, keep_blank_values=True, errors="strict")
        if key == "id"
    ]
    if len(values) == 1 and POSITIVE_ID.fullmatch(values[0]):
        return values[0]
    return None


def deferred_url_reason(raw_url: object) -> str:
    """Classify a few explicitly recorded research candidates without admitting them."""
    if not isinstance(raw_url, str):
        return "unsupported_other"
    try:
        url = urlsplit(raw_url)
        host = (url.hostname or "").lower()
        if (
            host == "139.196.46.195"
            and url.port == 51886
            and url.path in {"/Api/Songs/play", "/api/songs/play"}
            and unique_positive_query_id(url.query)
        ):
            return "unverified_ip_alias"
        if host == "play.udon.dance" and WANNADANCE_CDN.fullmatch(url.path):
            return "unverified_wannadance_cdn"
        if host == "api.dudufit.dance" and url.path == "/api/v1/videos/0":
            return "unverified_zero_id"
    except (ValueError, UnicodeError):
        pass
    return "unsupported_other"


def semantic_checks() -> int:
    """Small adversarial checks for errors that would change evidence admission."""
    cases = [
        ("http://api.udon.dance/Api/Songs/play?node=cf&id=7", ("wannadance", "7")),
        ("https://api.udon.dance/api/songs/play?id=7", ("wannadance", "7")),
        ("http://api.wannadance.online/Api/Songs/play?id=7", ("wannadance", "7")),
        ("http://api.pypy.dance/video?id=7", ("pypydance", "7")),
        ("http://jd.pypy.moe/api/v1/videos/7.mp4", ("pypydance", "7")),
        ("https://api.dudufit.dance/api/v1/videos/7?cdn=global", ("dudu", "7")),
        ("https://api.udon.dance.evil.example/Api/Songs/play?id=7", None),
        ("https://api.udon.dance@evil.example/Api/Songs/play?id=7", None),
        ("https://user@api.udon.dance/Api/Songs/play?id=7", None),
        ("https://not-pypy.example/api/v1/videos/7.mp4", None),
        ("https://api.udon.dance/Api/Songs/play?id=7&id=8", None),
        ("https://api.udon.dance/Api/Songs/play?id=&id=7", None),
        ("https://api.udon.dance/Api/Songs/play?id=7abc", None),
        ("https://api.udon.dance/Api/Songs/play?id=07", None),
        ("https://api.dudufit.dance/api/v1/videos/0", None),
        ("https://139.196.46.195:51886/Api/Songs/play?id=7", None),
        ("https://play.udon.dance/files/folder/7-title.mp4", None),
        ("An ordinary video title", None),
    ]
    for value, expected in cases:
        assert stable_dance_key(value) == expected, value
    times = [
        ("2026-09-05T01:00:00.000Z", True),
        ("2026-09-05T09:00:00+08:00", True),
        ("2026-09-05T09:00:00", False),
        ("2026-09-05T09:00:00+08:99", False),
        ("2026-02-30T09:00:00Z", False),
        (None, False),
    ]
    for value, expected in times:
        assert valid_source_time(value) == expected, value
    return len(cases) + len(times)


def evaluate(source: Path) -> dict:
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        rows = list(conn.execute(
            "SELECT id, created_at, video_url, video_name, video_id, location, "
            "display_name, user_id FROM gamelog_video_play ORDER BY id"
        ))
    eligible = []
    deferred = Counter()
    host_counts = Counter()
    for row in rows:
        key = stable_dance_key(row["video_url"])
        if not key:
            deferred[deferred_url_reason(row["video_url"])] += 1
            continue
        if not valid_source_time(row["created_at"]):
            deferred["invalid_or_timezone_missing_time"] += 1
            continue
        eligible.append(row)
        host_counts[urlsplit(row["video_url"]).hostname.lower()] += 1

    gate_losses = {
        column: sum(not row[column] for row in eligible)
        for column in ("video_name", "video_id", "display_name", "user_id", "location")
    }
    return {
        "rule_version": RULE_VERSION,
        "scope": "VRCX video rows only; no watcher, catalog queries or playback state inference",
        "source_rows": len(rows),
        "grade_a_eligible_rows": len(eligible),
        "eligible_percent_of_source_rows": round(100 * len(eligible) / len(rows), 4) if rows else None,
        "deferred_rows": len(rows) - len(eligible),
        "deferred_reasons": dict(deferred),
        "research_candidate_rows": sum(
            count for reason, count in deferred.items() if reason.startswith("unverified_")
        ),
        "eligible_by_host": dict(host_counts),
        "additional_rows_lost_if_optional_field_required": gate_losses,
        "warning": "Counts are source-row eligibility, not precision, recall or actual completed plays.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    checks = semantic_checks()
    report = evaluate(args.source)
    report["semantic_checks_passed"] = checks
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = args.output.resolve()
        if not output.is_relative_to(ROOT) or output == args.source.resolve():
            parser.error("--output must be a repository file distinct from the source database")
        output.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
