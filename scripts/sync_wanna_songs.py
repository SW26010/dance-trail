"""Synchronize Wanna Dance songs into local SQLite and CSV/JSON artifacts.

Usage:
    uv run python main.py sync-wanna
    uv run python main.py sync-wanna --offline
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dancing_log.wanna_catalog import sync_wanna_catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Wanna Dance catalog into SQLite")
    parser.add_argument("--app-db", default=None, help="SQLite database path")
    parser.add_argument("--cache-dir", default=None, help="Local wannadance-song cache directory")
    parser.add_argument("--offline", action="store_true", help="Use local cache only; skip the public API")
    parser.add_argument("--no-files", action="store_true", help="Do not update data/*.csv/json artifacts")
    args = parser.parse_args()

    stats = sync_wanna_catalog(
        db_path=args.app_db,
        cache_dir=args.cache_dir,
        use_api=not args.offline,
        write_files=not args.no_files,
    )
    source = "API + cache" if stats.used_api else "cache only"
    print("Wanna Dance catalog sync complete")
    print(f"  source: {source}")
    print(f"  API songs: {stats.api_count}")
    print(f"  cached songs: {stats.cache_count}")
    print(f"  database songs before: {stats.db_before}")
    print(f"  database songs after: {stats.db_after}")
    print(f"  inserted: {stats.inserted}")
    print(f"  updated/touched: {stats.updated}")
    print(f"  catalog rows without local cache: {stats.missing_in_cache}")


if __name__ == "__main__":
    main()
