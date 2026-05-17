"""Deprecated CSV-to-songs initializer.

The runtime database no longer has a `songs` table. Use:

    uv run python main.py sync-wanna
"""


def main() -> None:
    raise SystemExit(
        "scripts/init_songs.py is deprecated. "
        "Use `uv run python main.py sync-wanna` to populate dance_tracks."
    )


if __name__ == "__main__":
    main()
