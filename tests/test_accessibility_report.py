from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.verify_accessibility_changes import verify_accessibility_changes
from scripts.verify_accessibility_report import (
    AccessibilityReport,
    REQUIRED_ASSETS,
    ReportValidationError,
    sha256_bytes,
    verify_report,
)


class AccessibilityReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.contents = {
            REQUIRED_ASSETS[0]: b"final application bundle\n",
            REQUIRED_ASSETS[1]: b"<main>final shell</main>\n",
        }
        for asset, content in self.contents.items():
            path = self.root / asset
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def write_report(
        self,
        *,
        result: str = "Pass",
        app_hash: str | None = None,
        revision: str = "working-tree@test",
        relative_path: Path = Path("report.md"),
    ) -> Path:
        hashes = {
            asset: sha256_bytes(content)
            for asset, content in self.contents.items()
        }
        if app_hash is not None:
            hashes[REQUIRED_ASSETS[0]] = app_hash
        report = self.root / relative_path
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            "\n".join(
                [
                    "# Report",
                    f"Evaluated revision: `{revision}`",
                    f"Asset SHA-256 (`{REQUIRED_ASSETS[0].as_posix()}`): "
                    f"`{hashes[REQUIRED_ASSETS[0]]}`",
                    f"Asset SHA-256 (`{REQUIRED_ASSETS[1].as_posix()}`): "
                    f"`{hashes[REQUIRED_ASSETS[1]]}`",
                    f"Result: {result}",
                ]
            ),
            encoding="utf-8",
        )
        return report

    def test_accepts_report_bound_to_current_assets(self) -> None:
        report = verify_report(self.write_report(), self.root, require_pass=True)
        self.assertEqual(report.result, "Pass")

    def test_rejects_asset_hash_mismatch(self) -> None:
        with self.assertRaisesRegex(ReportValidationError, "Current .* SHA-256"):
            verify_report(self.write_report(app_hash="0" * 64), self.root)

    def test_release_rejects_non_commit_revision(self) -> None:
        with self.assertRaisesRegex(
            ReportValidationError, "40-character commit SHA"
        ):
            verify_report(
                self.write_report(),
                self.root,
                revision_must_be_ancestor_of="1" * 40,
            )

    @patch("scripts.verify_accessibility_report._git")
    def test_release_binds_ancestor_revision_assets(self, git) -> None:
        report_path = self.write_report()
        report_path.write_text(
            report_path.read_text(encoding="utf-8").replace(
                "working-tree@test", "1" * 40
            ),
            encoding="utf-8",
        )
        git.side_effect = [
            b"",
            self.contents[REQUIRED_ASSETS[0]],
            self.contents[REQUIRED_ASSETS[1]],
        ]

        report = verify_report(
            report_path,
            self.root,
            require_pass=True,
            revision_must_be_ancestor_of="2" * 40,
        )

        self.assertEqual(report.revision, "1" * 40)
        self.assertEqual(git.call_count, 3)

    def test_release_requires_explicit_pass(self) -> None:
        with self.assertRaisesRegex(ReportValidationError, "release requires Pass"):
            verify_report(
                self.write_report(result="Pending"),
                self.root,
                require_pass=True,
            )

    def test_material_change_requires_changed_passing_report(self) -> None:
        with self.assertRaisesRegex(ReportValidationError, "Material Web UI"):
            verify_accessibility_changes(
                ["webui/src/main.tsx"],
                self.root,
                head_revision="2" * 40,
            )

    @patch("scripts.verify_accessibility_changes.verify_report")
    def test_material_change_accepts_immutable_changed_report(self, verify) -> None:
        relative_report = Path(
            "docs/accessibility/change-reports/2026-07-18-test.md"
        )
        report_path = self.write_report(
            revision="1" * 40,
            relative_path=relative_report,
        )
        verify.return_value = AccessibilityReport("1" * 40, "Pass", {})

        reports = verify_accessibility_changes(
            ["webui/src/main.tsx", relative_report.as_posix()],
            self.root,
            head_revision="2" * 40,
        )

        self.assertEqual(reports, (relative_report,))
        verify.assert_called_once_with(
            report_path,
            self.root,
            require_pass=True,
            revision_must_be_ancestor_of="2" * 40,
        )

    @patch("scripts.verify_accessibility_changes.verify_report")
    def test_report_only_change_still_verifies_passing_report(self, verify) -> None:
        relative_report = Path(
            "docs/accessibility/change-reports/2026-07-18-test.md"
        )
        self.write_report(
            revision="1" * 40,
            relative_path=relative_report,
        )
        verify.return_value = AccessibilityReport("1" * 40, "Pass", {})

        reports = verify_accessibility_changes(
            [relative_report.as_posix()],
            self.root,
            head_revision="2" * 40,
        )

        self.assertEqual(reports, (relative_report,))
        self.assertEqual(verify.call_count, 1)


if __name__ == "__main__":
    unittest.main()
