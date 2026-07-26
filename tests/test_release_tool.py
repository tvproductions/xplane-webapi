from __future__ import annotations

from contextlib import redirect_stderr
from io import BytesIO
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest import mock
import warnings
import zipfile

from tools import installed_smoke, release
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
    duplicate_wheel_license: bool = False,
    duplicate_source_license: bool = False,
) -> None:
    wheel = root / f"xpwebapi-{VERSION}-py3-none-any.whl"
    wheel_license = f"xpwebapi-{VERSION}.dist-info/licenses/LICENSE"
    wheel_members = {
        f"xpwebapi-{VERSION}.dist-info/METADATA": (wheel_metadata or metadata()).encode(),
        wheel_license: b"MIT",
        **{f"xpwebapi/schemas/{name}": b"{}" for name in SCHEMAS},
    }
    if wheel_omit is not None:
        del wheel_members[wheel_omit]
    if wheel_forbidden is not None:
        wheel_members[wheel_forbidden] = b"forbidden"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, contents in wheel_members.items():
            archive.writestr(name, contents)
        if duplicate_wheel_license:
            with warnings.catch_warnings(record=True) as duplicate_warnings:
                warnings.simplefilter("always")
                archive.writestr(wheel_license, b"duplicate MIT")
            if len(duplicate_warnings) != 1 or "Duplicate name" not in str(duplicate_warnings[0].message):
                raise AssertionError("zipfile did not report the expected duplicate-name warning")

    prefix = f"xpwebapi-{VERSION}"
    source_license = f"{prefix}/LICENSE"
    source_members = {
        source_license: b"MIT",
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
        if duplicate_source_license:
            contents = b"duplicate MIT"
            info = tarfile.TarInfo(source_license)
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

    def test_wheel_rejects_second_license_basename(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_archives(root, wheel_forbidden="xpwebapi/LICENSE")
            with self.assertRaisesRegex(ReleaseValidationError, "forbidden material"):
                check_dist(root)

    def test_wheel_rejects_duplicate_canonical_license_entry(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_archives(root, duplicate_wheel_license=True)
            with self.assertRaisesRegex(ReleaseValidationError, "forbidden material"):
                check_dist(root)

    def test_wheel_rejects_root_level_licence(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_archives(root, wheel_forbidden="LICENCE")
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

    def test_source_rejects_second_license_basename(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_archives(root, source_forbidden=f"xpwebapi-{VERSION}/docs/LICENSE")
            with self.assertRaisesRegex(ReleaseValidationError, "forbidden material"):
                check_dist(root)

    def test_source_rejects_duplicate_canonical_license_entry(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_archives(root, duplicate_source_license=True)
            with self.assertRaisesRegex(ReleaseValidationError, "forbidden material"):
                check_dist(root)

    def test_source_rejects_root_level_licence(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_archives(root, source_forbidden="LICENCE")
            with self.assertRaisesRegex(ReleaseValidationError, "forbidden material"):
                check_dist(root)

    def test_source_rejects_root_level_docs_superpowers(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_archives(root, source_forbidden="docs/superpowers/plan.md")
            with self.assertRaisesRegex(ReleaseValidationError, "forbidden material"):
                check_dist(root)

    def test_source_rejects_every_member_outside_expected_prefix(self) -> None:
        for unexpected in ("unrelated/README.txt", f"xpwebapi-{VERSION}/../README.txt"):
            with self.subTest(unexpected=unexpected), TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_archives(root, source_forbidden=unexpected)
                with self.assertRaisesRegex(ReleaseValidationError, "expected top-level"):
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

    def test_release_cli_returns_zero_for_valid_tag(self) -> None:
        with mock.patch.object(sys, "argv", ["release.py", "check-tag", "v4.0.0"]):
            self.assertEqual(0, release.main())

    def test_release_cli_exits_one_and_reports_validation_error(self) -> None:
        stderr = StringIO()
        with (
            mock.patch.object(sys, "argv", ["release.py", "check-tag", "v4.0.1"]),
            redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            release.main()
        self.assertEqual(1, raised.exception.code)
        self.assertIn("tag 'v4.0.1'", stderr.getvalue())

    def test_installed_smoke_uses_interpreter_local_capture_command(self) -> None:
        with TemporaryDirectory() as temporary:
            python = Path(temporary) / "runtime" / "python"
            suffix = ".exe" if installed_smoke.os.name == "nt" else ""
            command = python.parent / f"xpwebapi-capture{suffix}"
            payload = {
                "package_name": "xpwebapi",
                "package_version": VERSION,
                "read_only": True,
            }
            completed = subprocess.CompletedProcess(
                (str(command), "--version-json"),
                0,
                stdout=json.dumps(payload),
                stderr="",
            )
            with (
                mock.patch.object(sys, "argv", ["installed_smoke.py", VERSION]),
                mock.patch.object(installed_smoke.sys, "executable", str(python)),
                mock.patch.object(installed_smoke.subprocess, "run", return_value=completed) as run,
            ):
                self.assertEqual(0, installed_smoke.main())

            run.assert_called_once_with(
                (str(command), "--version-json"),
                check=True,
                capture_output=True,
                text=True,
            )

    def test_installed_smoke_rejects_invalid_capture_payload(self) -> None:
        payload = {
            "package_name": "xpwebapi",
            "package_version": VERSION,
            "read_only": False,
        }
        completed = subprocess.CompletedProcess(
            ("xpwebapi-capture", "--version-json"),
            0,
            stdout=json.dumps(payload),
            stderr="",
        )
        with (
            mock.patch.object(sys, "argv", ["installed_smoke.py", VERSION]),
            mock.patch.object(installed_smoke.subprocess, "run", return_value=completed),
            self.assertRaisesRegex(RuntimeError, "read-only mode"),
        ):
            installed_smoke.main()

    def test_installed_smoke_rejects_incorrect_capture_identity(self) -> None:
        invalid_fields = (
            ("package_name", "other", "package name"),
            ("package_version", "4.0.1", "package version"),
        )
        for field, value, message in invalid_fields:
            with self.subTest(field=field):
                payload = {
                    "package_name": "xpwebapi",
                    "package_version": VERSION,
                    "read_only": True,
                }
                payload[field] = value
                completed = subprocess.CompletedProcess(
                    ("xpwebapi-capture", "--version-json"),
                    0,
                    stdout=json.dumps(payload),
                    stderr="",
                )
                with (
                    mock.patch.object(sys, "argv", ["installed_smoke.py", VERSION]),
                    mock.patch.object(installed_smoke.subprocess, "run", return_value=completed),
                    self.assertRaisesRegex(RuntimeError, message),
                ):
                    installed_smoke.main()


if __name__ == "__main__":
    unittest.main()
