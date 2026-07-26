"""Release metadata and installed-resource contracts."""

from __future__ import annotations

from importlib.resources import files
import json
from pathlib import Path
import tomllib
import unittest

import xpwebapi
from xpwebapi.schemas import SCHEMA_FILENAMES


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


class ReleaseMetadataTests(unittest.TestCase):
    def test_distribution_identity_and_supported_python(self) -> None:
        project = PROJECT["project"]
        self.assertEqual("xpwebapi", project["name"])
        self.assertEqual("4.0.0", project["version"])
        self.assertEqual(">=3.12,<3.14", project["requires-python"])
        self.assertIn("Programming Language :: Python :: 3.12", project["classifiers"])
        self.assertIn("Programming Language :: Python :: 3.13", project["classifiers"])
        self.assertNotIn(
            "License :: OSI Approved :: MIT License",
            project["classifiers"],
        )

    def test_runtime_and_distribution_versions_match(self) -> None:
        expected = PROJECT["project"]["version"]
        self.assertEqual(expected, xpwebapi.__version__)
        self.assertEqual(expected, xpwebapi.version)

    def test_authorship_maintenance_and_canonical_urls(self) -> None:
        project = PROJECT["project"]
        self.assertEqual(
            [{"name": "Pierre Mareschal", "email": "pierre@devleaks.be"}],
            project["authors"],
        )
        self.assertEqual([{"name": "Jeffry"}], project["maintainers"])
        self.assertEqual(
            {
                "Homepage": "https://tvproductions.github.io/xplane-webapi/",
                "Documentation": "https://tvproductions.github.io/xplane-webapi/",
                "Issues": "https://github.com/tvproductions/xplane-webapi/issues",
                "Repository": "https://github.com/tvproductions/xplane-webapi",
            },
            project["urls"],
        )

    def test_one_canonical_mit_license_preserves_lineage(self) -> None:
        project = PROJECT["project"]
        self.assertEqual("MIT", project["license"])
        self.assertEqual(["LICENSE"], project["license-files"])
        self.assertTrue((REPO_ROOT / "LICENSE").is_file())
        self.assertFalse((REPO_ROOT / "LICENCE").exists())

        license_text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
        for notice in (
            "Copyright (c) 2019-2024 Pierre Mareschal",
            "Copyright (c) 2025 Pierre M",
            "Copyright (c) 2026 TV Productions",
        ):
            with self.subTest(notice=notice):
                self.assertIn(notice, license_text)


class PackagedSchemaTests(unittest.TestCase):
    def test_all_capture_schemas_are_installed_package_resources(self) -> None:
        expected = {
            "capture-event-v1.schema.json",
            "capture-request-v1.schema.json",
            "capture-status-v1.schema.json",
            "capture-version-v1.schema.json",
        }
        self.assertEqual(expected, set(SCHEMA_FILENAMES))

        root = files("xpwebapi.schemas")
        for name in sorted(expected):
            with self.subTest(name=name):
                payload = json.loads(root.joinpath(name).read_text(encoding="utf-8"))
                self.assertIsInstance(payload, dict)


if __name__ == "__main__":
    unittest.main()
