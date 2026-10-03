from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.collect_licenses import copy_notices, javascript_packages


class LicenseCollectionTest(unittest.TestCase):
    def test_runtime_dependencies_include_transitives_but_not_development_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "dependencies": {"runtime": "1"},
                        "devDependencies": {"devtool": "1"},
                    }
                )
            )
            for name, metadata in {
                "runtime": {
                    "dependencies": {"transitive": "1"},
                    "peerDependencies": {"absent": "1"},
                    "peerDependenciesMeta": {"absent": {"optional": True}},
                },
                "transitive": {"dependencies": {"runtime": "1"}},
                "devtool": {},
            }.items():
                package = root / "node_modules" / name
                package.mkdir(parents=True)
                (package / "package.json").write_text(
                    json.dumps(
                        {
                            "name": name,
                            "version": "1",
                            **metadata,
                        }
                    )
                )
            names = [m["name"] for m, _ in javascript_packages(root)]
            self.assertEqual(names, ["runtime", "transitive"])
            (root / "node_modules/transitive/package.json").unlink()
            with self.assertRaisesRegex(ValueError, "Missing installed"):
                javascript_packages(root)

    def test_missing_or_empty_license_prevents_packaging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "No license text"):
                copy_notices([], root / "out", "dependency")
            source = root / "LICENSE"
            source.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "Empty license"):
                copy_notices([source], root / "out", "dependency")
            source.write_bytes(b"Copyright and license\n")
            names = copy_notices([source], root / "out", "dependency")
            self.assertEqual(
                (root / "out" / names[0]).read_bytes(), source.read_bytes()
            )


if __name__ == "__main__":
    unittest.main()
