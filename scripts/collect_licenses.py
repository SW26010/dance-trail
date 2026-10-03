"""Collect redistributable notices from the installed release dependencies.

Run with the release Python environment, after pnpm install --frozen-lockfile.
No network requests or build-machine paths are included in the output.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import shutil
import sys
from pathlib import Path


def notice_name(name: str) -> bool:
    return name.lower().startswith(("license", "licence", "copying", "notice"))


def package_directory(start: Path, name: str) -> Path:
    for parent in (start, *start.parents):
        candidate = parent / "node_modules" / name
        if (candidate / "package.json").is_file():
            return candidate.resolve()
    raise ValueError(f"Missing installed JavaScript dependency: {name}")


def javascript_packages(root: Path) -> list[tuple[dict, Path]]:
    manifest = json.loads((root / "package.json").read_text(encoding="utf-8"))
    pending = [package_directory(root, name) for name in manifest["dependencies"]]
    seen: set[Path] = set()
    packages = []
    while pending:
        directory = pending.pop()
        if directory in seen:
            continue
        seen.add(directory)
        metadata = json.loads((directory / "package.json").read_text(encoding="utf-8"))
        packages.append((metadata, directory))
        for name in metadata.get("dependencies", {}):
            pending.append(package_directory(directory, name))
        for name in metadata.get("peerDependencies", {}) | metadata.get(
            "optionalDependencies", {}
        ):
            try:
                pending.append(package_directory(directory, name))
            except ValueError:
                # Uninstalled optional peers are not part of the release bundle.
                optional = name in metadata.get(
                    "optionalDependencies", {}
                ) or metadata.get("peerDependenciesMeta", {}).get(name, {}).get(
                    "optional", False
                )
                if not optional:
                    raise
    return sorted(packages, key=lambda pair: (pair[0]["name"], pair[0]["version"]))


def copy_notices(files: list[Path], destination: Path, package: str) -> list[str]:
    if not files:
        raise ValueError(
            f"No license text found for {package}; release packaging stopped"
        )
    destination.mkdir(parents=True, exist_ok=True)
    names = []
    for index, source in enumerate(sorted(files)):
        if not source.read_bytes().strip():
            raise ValueError(f"Empty license text for {package}")
        name = f"{index + 1}-{source.name}"
        shutil.copyfile(source, destination / name)
        names.append(name)
    return names


def collect(repo: Path, output: Path, node_root: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    if any(path.is_file() for path in output.rglob("*ffmpeg*.exe")):
        raise ValueError("Bundled FFmpeg requires a separate distribution review")
    shutil.copyfile(repo / "LICENSE", output / "LICENSE")
    legal = output / "Legal"
    legal.mkdir(exist_ok=True)
    entries = []

    def add(name: str, version: str, category: str, files: list[Path]) -> None:
        folder = category + "/" + re.sub(r"[^A-Za-z0-9._-]", "_", name + "-" + version)
        names = copy_notices(files, legal / folder, name)
        entries.append(
            {
                "name": name,
                "version": version,
                "category": category,
                "notices": [folder + "/" + file for file in names],
            }
        )

    for name in ("tzlocal", "tzdata", "pyinstaller"):
        dist = importlib.metadata.distribution(name)
        files = [
            Path(dist.locate_file(file))
            for file in (dist.files or [])
            if notice_name(Path(file).name)
        ]
        add(name, dist.version, "python", files)
    add(
        "CPython",
        sys.version.split()[0],
        "python",
        [Path(sys.base_prefix) / "LICENSE.txt"],
    )
    fallbacks = repo / "legal" / "javascript"
    sources = json.loads((fallbacks / "sources.json").read_text(encoding="utf-8"))
    for metadata, directory in javascript_packages(node_root):
        files = [
            file
            for file in directory.iterdir()
            if file.is_file() and notice_name(file.name)
        ]
        key = metadata["name"] + "@" + metadata["version"]
        if not files and key in sources:
            files = [fallbacks / sources[key]["file"]]
        add(metadata["name"], metadata["version"], "javascript", files)
    shutil.copyfile(fallbacks / "sources.json", legal / "javascript-sources.json")
    runtime = repo / "legal" / "runtime"
    # Keep the reviewed native-library notices alongside the distribution notices.
    required = {
        "bzip2",
        "expat",
        "libffi",
        "liblzma",
        "mpdecimal",
        "openssl-3",
        "sqlite",
        "zlib",
        "zstd",
        "microsoft-runtime",
    }
    for name in sorted(required):
        source = runtime / f"LICENSE.{name}.txt"
        if not source.is_file():
            raise ValueError(f"Missing native runtime notice: {name}")
    shutil.copytree(runtime, legal / "runtime", dirs_exist_ok=True)
    (legal / "manifest.json").write_text(
        json.dumps(entries, indent=2) + "\n", encoding="utf-8"
    )
    (legal / "README.txt").write_text(
        "DanceTrail is MIT licensed; see ../LICENSE.\n"
        "Bundled dependencies retain their own licenses and copyright notices.\n"
        "manifest.json lists installed Python runtime dependencies, PyInstaller's\n"
        "bootloader exception, and the frontend runtime dependency closure.\n"
        "The frontend list conservatively includes transitive dependencies that\n"
        "may be removed by bundler tree shaking; development tools are excluded.\n"
        "runtime/ contains additional notices for native Python libraries.\n"
        "FFmpeg is not included in this portable distribution.\n",
        encoding="utf-8",
    )
    print(
        f"Collected notices for {len(entries)} dependency distributions and native runtime libraries"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--node-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    collect(
        args.repo_root.resolve(),
        args.output.resolve(),
        (args.node_root or args.repo_root).resolve(),
    )


if __name__ == "__main__":
    main()
