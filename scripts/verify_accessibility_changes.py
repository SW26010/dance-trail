from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

if __package__:
    from scripts.verify_accessibility_report import (
        ReportValidationError,
        report_result,
        verify_report,
    )
else:
    from verify_accessibility_report import (  # type: ignore[no-redef]
        ReportValidationError,
        report_result,
        verify_report,
    )


CHANGE_REPORT_DIRECTORY = Path("docs/accessibility/change-reports")
MATERIAL_WEBUI_FILES = frozenset(
    {
        "dance_trail/webui_assets.py",
        "dance_trail/webui_routes.py",
        "package.json",
        "pnpm-lock.yaml",
        "tsconfig.json",
        "vite.config.ts",
    }
)
MATERIAL_WEBUI_DIRECTORIES = (
    "dance_trail/webui_dist/",
    "webui/",
)
ZERO_REVISION_PATTERN = re.compile(r"^0{40}$")


def _git(repo_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode:
        detail = completed.stderr.strip()
        raise ReportValidationError(
            f"git {' '.join(arguments)} failed with exit code "
            f"{completed.returncode}: {detail}"
        )
    return completed.stdout


def changed_paths(
    repo_root: Path, base_revision: str, head_revision: str
) -> tuple[str, ...]:
    if ZERO_REVISION_PATTERN.fullmatch(base_revision):
        output = _git(
            repo_root,
            "ls-tree",
            "--name-only",
            "-r",
            head_revision,
        )
    else:
        output = _git(
            repo_root,
            "diff",
            "--name-only",
            "--diff-filter=ACMRT",
            base_revision,
            head_revision,
            "--",
        )
    return tuple(
        line.strip().replace("\\", "/") for line in output.splitlines() if line.strip()
    )


def is_material_webui_change(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized in MATERIAL_WEBUI_FILES or normalized.startswith(
        MATERIAL_WEBUI_DIRECTORIES
    )


def is_change_report(path: str) -> bool:
    normalized = Path(path.replace("\\", "/"))
    return (
        normalized.parent == CHANGE_REPORT_DIRECTORY
        and normalized.suffix == ".md"
        and normalized.name != "README.md"
    )


def verify_accessibility_changes(
    paths: tuple[str, ...] | list[str],
    repo_root: Path,
    *,
    head_revision: str,
    snapshot: bool = False,
) -> tuple[Path, ...]:
    material_changes = tuple(path for path in paths if is_material_webui_change(path))
    passing_reports: list[Path] = []

    for path in sorted(path for path in paths if is_change_report(path)):
        report_path = repo_root / Path(path)
        content = report_path.read_text(encoding="utf-8")
        try:
            if report_result(content) != "Pass":
                continue
            verify_report(
                report_path,
                repo_root,
                require_pass=True,
                revision_must_be_ancestor_of=head_revision,
            )
        except ReportValidationError:
            if not snapshot:
                raise
            # A snapshot includes superseded reports for earlier asset versions.
            # At least one report must still verify against the current assets.
            continue
        passing_reports.append(Path(path))

    if material_changes and not passing_reports:
        changed = ", ".join(material_changes)
        raise ReportValidationError(
            "Material Web UI changes require a changed accessibility report "
            "with Result: Pass and an immutable evaluated revision. "
            f"Material paths: {changed}"
        )

    return tuple(passing_reports)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Require reproducible accessibility evidence when a change set "
            "modifies material Local Web UI files."
        )
    )
    parser.add_argument("--base-revision", required=True)
    parser.add_argument("--head-revision", required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    arguments = parser.parse_args(argv)
    repo_root = arguments.repo_root.resolve()
    try:
        _git(repo_root, "rev-parse", "--verify", arguments.head_revision + "^{commit}")
        base = arguments.base_revision
        snapshot = bool(ZERO_REVISION_PATTERN.fullmatch(base))
        if not snapshot:
            available = subprocess.run(
                ["git", "cat-file", "-e", base + "^{commit}"],
                cwd=repo_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            snapshot = available.returncode != 0
        if snapshot:
            print("Base unavailable; verifying the complete current snapshot.")
            base = "0" * 40
        paths = changed_paths(
            repo_root,
            base,
            arguments.head_revision,
        )
        reports = verify_accessibility_changes(
            paths,
            repo_root,
            head_revision=arguments.head_revision,
            snapshot=snapshot,
        )
    except (OSError, ReportValidationError) as error:
        print(
            f"Accessibility change verification failed: {error}",
            file=sys.stderr,
        )
        return 1

    material_count = sum(is_material_webui_change(path) for path in paths)
    print(
        "Accessibility change verification passed: "
        f"{material_count} material path(s), {len(reports)} passing report(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
