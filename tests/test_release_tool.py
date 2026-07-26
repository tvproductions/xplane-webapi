from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest import mock
import zipfile

from tools import release
from tools.release import ReleaseValidationError, check_dist, check_tag


VERSION = "4.0.0"
SCHEMAS = (
    "capture-event-v1.schema.json",
    "capture-request-v1.schema.json",
    "capture-status-v1.schema.json",
    "capture-version-v1.schema.json",
)


def metadata(*, name: str = "xpwebapi", version: str = VERSION, requires_python: str = "<3.14,>=3.12") -> str:
    return "\n".join(
        (
            "Metadata-Version: 2.4",
            f"Name: {name}",
            f"Version: {version}",
            f"Requires-Python: {requires_python}",
            "",
        )
    )


def write_archives(
    root: Path,
    *,
    wheel_omit: str | None = None,
    source_omit: str | None = None,
    wheel_metadata: str | None = None,
    source_metadata: str | None = None,
    wheel_forbidden: str | None = None,
    source_forbidden: str | None = None,
    extra_archive: bool = False,
    extra_wheel: bool = False,
) -> None:
    wheel = root / f"xpwebapi-{VERSION}-py3-none-any.whl"
    wheel_members = {
        f"xpwebapi-{VERSION}.dist-info/METADATA": (wheel_metadata or metadata()).encode(),
        f"xpwebapi-{VERSION}.dist-info/licenses/LICENSE": b"MIT",
        **{f"xpwebapi/schemas/{name}": b"{}" for name in SCHEMAS},
    }
    if wheel_omit is not None:
        del wheel_members[wheel_omit]
    if wheel_forbidden is not None:
        wheel_members[wheel_forbidden] = b"forbidden"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, contents in wheel_members.items():
            archive.writestr(name, contents)

    prefix = f"xpwebapi-{VERSION}"
    source_members = {
        f"{prefix}/LICENSE": b"MIT",
        f"{prefix}/PKG-INFO": (source_metadata or metadata()).encode(),
        **{f"{prefix}/xpwebapi/schemas/{name}": b"{}" for name in SCHEMAS},
    }
    if source_omit is not None:
        del source_members[source_omit]
    if source_forbidden is not None:
        source_members[source_forbidden] = b"forbidden"
    with tarfile.open(root / f"{prefix}.tar.gz", "w:gz") as archive:
        for name, contents in source_members.items():
            info = tarfile.TarInfo(name)
            info.size = len(contents)
            archive.addfile(info, BytesIO(contents))

    if extra_archive:
        (root / "xpwebapi-3.5.0.tar.gz").write_bytes(b"stale")
    if extra_wheel:
        (root / f"xpwebapi-{VERSION}-second.whl").write_bytes(b"duplicate")


class ReleaseToolTests(unittest.TestCase):
    def test_tag_must_match_project_and_runtime_versions(self) -> None:
        check_tag("v4.0.0")
        for invalid_tag in ("v4.0.1", "4.0.0"):
            with self.subTest(tag=invalid_tag):
                with self.assertRaisesRegex(ReleaseValidationError, invalid_tag):
                    check_tag(invalid_tag)

    def test_tag_rejects_runtime_version_that_differs_from_project(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "xpwebapi").mkdir()
            (root / "pyproject.toml").write_text('[project]\nversion = "4.0.0"\n', encoding="utf-8")
            (root / "xpwebapi" / "__init__.py").write_text('__version__ = "4.0.1"\n', encoding="utf-8")
            with mock.patch.object(release, "REPO_ROOT", root):
                with self.assertRaisesRegex(ReleaseValidationError, "runtime '4.0.1'"):
                    check_tag("v4.0.0")

    def test_missing_runtime_version_declaration_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "xpwebapi").mkdir()
            (root / "xpwebapi" / "__init__.py").write_text("version = '4.0.0'\n", encoding="utf-8")
            with mock.patch.object(release, "REPO_ROOT", root):
                with self.assertRaisesRegex(ReleaseValidationError, "declaration is missing"):
                    release.runtime_version()

    def test_valid_archives_include_license_metadata_and_every_schema(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_archives(root)
            check_dist(root)

    def test_build_backend_requires_python_spacing_is_accepted(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            built_metadata = metadata(requires_python=">=3.12, <3.14")
            write_archives(root, wheel_metadata=built_metadata, source_metadata=built_metadata)
            check_dist(root)

    def test_missing_wheel_members_are_rejected(self) -> None:
        prefix = f"xpwebapi-{VERSION}.dist-info"
        required = (
            f"{prefix}/METADATA",
            f"{prefix}/licenses/LICENSE",
            *(f"xpwebapi/schemas/{name}" for name in SCHEMAS),
        )
        for missing in required:
            with self.subTest(missing=missing), TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_archives(root, wheel_omit=missing)
                with self.assertRaisesRegex(ReleaseValidationError, Path(missing).name):
                    check_dist(root)

    def test_missing_source_members_are_rejected(self) -> None:
        prefix = f"xpwebapi-{VERSION}"
        required = (
            f"{prefix}/LICENSE",
            f"{prefix}/PKG-INFO",
            *(f"{prefix}/xpwebapi/schemas/{name}" for name in SCHEMAS),
        )
        for missing in required:
            with self.subTest(missing=missing), TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_archives(root, source_omit=missing)
                with self.assertRaisesRegex(ReleaseValidationError, Path(missing).name):
                    check_dist(root)

    def test_wheel_metadata_identity_is_validated(self) -> None:
        for invalid_metadata in (metadata(name="other"), metadata(version="4.0.1")):
            with self.subTest(metadata=invalid_metadata), TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_archives(root, wheel_metadata=invalid_metadata)
                with self.assertRaisesRegex(ReleaseValidationError, "metadata identity"):
                    check_dist(root)

    def test_source_metadata_identity_is_validated(self) -> None:
        for invalid_metadata in (metadata(name="other"), metadata(version="4.0.1")):
            with self.subTest(metadata=invalid_metadata), TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_archives(root, source_metadata=invalid_metadata)
                with self.assertRaisesRegex(ReleaseValidationError, "metadata identity"):
                    check_dist(root)

    def test_wheel_requires_python_is_validated(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_archives(root, wheel_metadata=metadata(requires_python=">=3.12"))
            with self.assertRaisesRegex(ReleaseValidationError, "Requires-Python"):
                check_dist(root)

    def test_source_requires_python_is_validated(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_archives(root, source_metadata=metadata(requires_python=">=3.12"))
            with self.assertRaisesRegex(ReleaseValidationError, "Requires-Python"):
                check_dist(root)

    def test_forbidden_wheel_material_is_rejected(self) -> None:
        for forbidden in ("xpwebapi/LICENCE", "xpwebapi/superpowers/plan.md"):
            with self.subTest(forbidden=forbidden), TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_archives(root, wheel_forbidden=forbidden)
                with self.assertRaisesRegex(ReleaseValidationError, "forbidden material"):
                    check_dist(root)

    def test_forbidden_source_material_is_rejected(self) -> None:
        prefix = f"xpwebapi-{VERSION}"
        for forbidden in (f"{prefix}/LICENCE", f"{prefix}/docs/superpowers/plan.md"):
            with self.subTest(forbidden=forbidden), TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_archives(root, source_forbidden=forbidden)
                with self.assertRaisesRegex(ReleaseValidationError, "forbidden material"):
                    check_dist(root)

    def test_expected_archives_are_required(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ReleaseValidationError, "expected one"):
                check_dist(root)

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_archives(root, extra_wheel=True)
            with self.assertRaisesRegex(ReleaseValidationError, "expected one"):
                check_dist(root)

    def test_extra_archive_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_archives(root, extra_archive=True)
            with self.assertRaisesRegex(ReleaseValidationError, "unexpected files"):
                check_dist(root)

    def test_gitignore_is_allowed_in_distribution_directory(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_archives(root)
            (root / ".gitignore").write_text("*\n", encoding="utf-8")
            check_dist(root)


if __name__ == "__main__":
    unittest.main()
