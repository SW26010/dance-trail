from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REQUIRED_ASSETS = (
    Path("dancing_log/webui_dist/app.js"),
    Path("dancing_log/webui_dist/index.html"),
)
REVISION_PATTERN = re.compile(r"^Evaluated revision: `([^`]+)`$")
RESULT_PATTERN = re.compile(r"^Result: (Pending|Pass|Fail)$")
ASSET_PATTERN = re.compile(
    r"^Asset SHA-256 \(`([^`]+)`\): `([0-9a-fA-F]{64})`$"
)
COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")


class ReportValidationError(ValueError):
    pass


@dataclass(frozen=True)
class AccessibilityReport:
    revision: str
    result: str
    assets: dict[Path, str]


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def report_result(content: str) -> str:
    results = [
        match.group(1)
        for line in content.splitlines()
        if (match := RESULT_PATTERN.fullmatch(line))
    ]
    if len(results) != 1:
        raise ReportValidationError("Report must contain exactly one Result line")
    return results[0]


def parse_report(content: str) -> AccessibilityReport:
    revisions: list[str] = []
    assets: dict[Path, str] = {}
    for line in content.splitlines():
        if match := REVISION_PATTERN.fullmatch(line):
            revisions.append(match.group(1))
        if match := ASSET_PATTERN.fullmatch(line):
            asset = Path(match.group(1))
            if asset in assets:
                raise ReportValidationError(
                    f"Duplicate asset hash entry: {asset.as_posix()}"
                )
            assets[asset] = match.group(2).lower()

    if len(revisions) != 1:
        raise ReportValidationError(
            "Report must contain exactly one evaluated revision"
        )
    result = report_result(content)
    missing = [
        asset.as_posix() for asset in REQUIRED_ASSETS if asset not in assets
    ]
    if missing:
        raise ReportValidationError(
            f"Report is missing required asset hashes: {', '.join(missing)}"
        )
    return AccessibilityReport(revisions[0], result, assets)


def _git(repo_root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ReportValidationError(
            f"git {' '.join(arguments)} failed with exit code {completed.returncode}: {detail}"
        )
    return completed.stdout


def verify_report(
    report_path: Path,
    repo_root: Path,
    *,
    require_pass: bool = False,
    revision_must_be_ancestor_of: str | None = None,
) -> AccessibilityReport:
    report = parse_report(report_path.read_text(encoding="utf-8"))
    if require_pass and report.result != "Pass":
        raise ReportValidationError(
            f"Accessibility report result is {report.result}; release requires Pass"
        )

    for asset in REQUIRED_ASSETS:
        asset_path = repo_root / asset
        if not asset_path.is_file():
            raise ReportValidationError(
                f"Required Web UI asset is missing: {asset.as_posix()}"
            )
        actual = sha256_bytes(asset_path.read_bytes())
        if actual != report.assets[asset]:
            raise ReportValidationError(
                f"Current {asset.as_posix()} SHA-256 is {actual}, "
                f"but the report records {report.assets[asset]}"
            )

    if revision_must_be_ancestor_of is not None:
        if not COMMIT_PATTERN.fullmatch(report.revision):
            raise ReportValidationError(
                "Passing reports must identify the evaluated revision with a "
                "full 40-character commit SHA"
            )
        _git(
            repo_root,
            "merge-base",
            "--is-ancestor",
            report.revision,
            revision_must_be_ancestor_of,
        )
        for asset in REQUIRED_ASSETS:
            revision_content = _git(
                repo_root,
                "show",
                f"{report.revision}:{asset.as_posix()}",
            )
            revision_hash = sha256_bytes(revision_content)
            if revision_hash != report.assets[asset]:
                raise ReportValidationError(
                    f"Evaluated revision {report.revision} contains {asset.as_posix()} "
                    f"with SHA-256 {revision_hash}, but the report records "
                    f"{report.assets[asset]}"
                )

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bind an accessibility report to reproducible Web UI assets and "
            "revision evidence."
        )
    )
    parser.add_argument("report", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--require-pass", action="store_true")
    parser.add_argument("--revision-must-be-ancestor-of")
    arguments = parser.parse_args(argv)
    try:
        report = verify_report(
            arguments.report,
            arguments.repo_root.resolve(),
            require_pass=arguments.require_pass,
            revision_must_be_ancestor_of=arguments.revision_must_be_ancestor_of,
        )
    except (OSError, ReportValidationError) as error:
        print(
            f"Accessibility report verification failed: {error}",
            file=sys.stderr,
        )
        return 1
    print(
        f"Accessibility report verified: {arguments.report} "
        f"({report.result}, revision {report.revision})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
