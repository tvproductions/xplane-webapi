"""Validate xpwebapi release tags and distribution archives."""

from __future__ import annotations

import argparse
from email import policy
from email.parser import BytesParser
from pathlib import Path
from pathlib import PurePosixPath
import tarfile
import tomllib
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = (
    "capture-event-v1.schema.json",
    "capture-request-v1.schema.json",
    "capture-status-v1.schema.json",
    "capture-version-v1.schema.json",
)


class ReleaseValidationError(RuntimeError):
    """Raised when a tag or distribution violates the release contract."""


def project_version() -> str:
    """Return the release version declared in project metadata."""
    document = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(document["project"]["version"])


def runtime_version() -> str:
    """Return the release version declared by the runtime package."""
    source = (REPO_ROOT / "xpwebapi" / "__init__.py").read_text(encoding="utf-8")
    for line in source.splitlines():
        if line.startswith("__version__ = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise ReleaseValidationError("xpwebapi.__version__ declaration is missing")


def check_tag(tag: str) -> None:
    """Reject a tag unless it exactly matches project and runtime versions."""
    expected = project_version()
    actual = tag.removeprefix("v")
    installed = runtime_version()
    if tag != f"v{expected}" or actual != installed:
        raise ReleaseValidationError(f"tag {tag!r}, project {expected!r}, and runtime {installed!r} must match")


def _require_members(members: set[str], required: set[str], *, archive: Path) -> None:
    missing = sorted(required - members)
    if missing:
        raise ReleaseValidationError(f"{archive.name} is missing: {', '.join(missing)}")


def _contains_sequence(path: PurePosixPath, sequence: tuple[str, ...]) -> bool:
    width = len(sequence)
    return any(path.parts[index : index + width] == sequence for index in range(len(path.parts) - width + 1))


def _check_member_policy(members: set[str], *, archive: Path, forbid_any_superpowers: bool) -> tuple[PurePosixPath, ...]:
    paths = tuple(PurePosixPath(name) for name in members)
    license_count = sum(path.name == "LICENSE" for path in paths)
    contains_licence = any(path.name == "LICENCE" for path in paths)
    if forbid_any_superpowers:
        contains_superpowers = any("superpowers" in path.parts for path in paths)
    else:
        contains_superpowers = any(_contains_sequence(path, ("docs", "superpowers")) for path in paths)
    if license_count != 1 or contains_licence or contains_superpowers:
        raise ReleaseValidationError(f"{archive.name} contains forbidden material")
    return paths


def _has_expected_source_root(path: PurePosixPath, prefix: str) -> bool:
    return ".." not in path.parts and (path == PurePosixPath(prefix) or bool(path.parts) and path.parts[0] == prefix)


def _check_metadata(metadata_bytes: bytes, *, archive: Path, version: str) -> None:
    metadata = BytesParser(policy=policy.default).parsebytes(metadata_bytes)
    if metadata["Name"] != "xpwebapi" or metadata["Version"] != version:
        raise ReleaseValidationError(f"{archive.name} metadata identity is incorrect")
    requires_python = "".join(str(metadata["Requires-Python"]).split())
    if requires_python not in {">=3.12,<3.14", "<3.14,>=3.12"}:
        raise ReleaseValidationError(f"{archive.name} Requires-Python is incorrect")


def check_dist(directory: Path) -> None:
    """Reject a distribution directory unless its release archives are valid."""
    version = project_version()
    wheels = sorted(directory.glob(f"xpwebapi-{version}-*.whl"))
    source = directory / f"xpwebapi-{version}.tar.gz"
    if len(wheels) != 1 or not source.is_file():
        raise ReleaseValidationError(f"expected one xpwebapi-{version} wheel and xpwebapi-{version}.tar.gz")

    wheel = wheels[0]
    allowed_files = {wheel.name, source.name, ".gitignore"}
    actual_files = {path.name for path in directory.iterdir() if path.is_file()}
    unexpected_files = sorted(actual_files - allowed_files)
    if unexpected_files:
        raise ReleaseValidationError(f"distribution directory contains unexpected files: {', '.join(unexpected_files)}")

    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())
        metadata_name = f"xpwebapi-{version}.dist-info/METADATA"
        required = {
            metadata_name,
            f"xpwebapi-{version}.dist-info/licenses/LICENSE",
            *(f"xpwebapi/schemas/{name}" for name in SCHEMAS),
        }
        _require_members(members, required, archive=wheel)
        _check_member_policy(members, archive=wheel, forbid_any_superpowers=True)
        _check_metadata(archive.read(metadata_name), archive=wheel, version=version)

    prefix = f"xpwebapi-{version}"
    with tarfile.open(source, "r:gz") as archive:
        members = {member.name for member in archive.getmembers()}
        metadata_name = f"{prefix}/PKG-INFO"
        required = {
            f"{prefix}/LICENSE",
            metadata_name,
            *(f"{prefix}/xpwebapi/schemas/{name}" for name in SCHEMAS),
        }
        _require_members(members, required, archive=source)
        paths = _check_member_policy(members, archive=source, forbid_any_superpowers=False)
        unexpected_roots = sorted(str(path) for path in paths if not _has_expected_source_root(path, prefix))
        if unexpected_roots:
            raise ReleaseValidationError(f"{source.name} contains members outside the expected top-level {prefix}: {', '.join(unexpected_roots)}")
        metadata_member = archive.extractfile(metadata_name)
        if metadata_member is None:
            raise ReleaseValidationError(f"{source.name} metadata is unreadable")
        _check_metadata(metadata_member.read(), archive=source, version=version)


def main() -> int:
    """Run a release validation subcommand."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    tag_parser = subparsers.add_parser("check-tag")
    tag_parser.add_argument("tag")
    dist_parser = subparsers.add_parser("check-dist")
    dist_parser.add_argument("directory", type=Path)
    arguments = parser.parse_args()

    try:
        if arguments.command == "check-tag":
            check_tag(arguments.tag)
        else:
            check_dist(arguments.directory)
    except ReleaseValidationError as error:
        parser.exit(1, f"{error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
