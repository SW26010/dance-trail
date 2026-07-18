"""Run an isolated Local Web UI instance for browser acceptance tests."""

from __future__ import annotations

import argparse
from pathlib import Path

from dancing_log.webui_server import run_webui_server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--app-root", type=Path, required=True)
    args = parser.parse_args()
    run_webui_server(
        port=args.port,
        open_browser=False,
        app_root=args.app_root.resolve(),
    )


if __name__ == "__main__":
    main()
