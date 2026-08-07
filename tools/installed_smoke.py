"""Smoke-test an installed xpwebapi wheel outside its source checkout."""

from __future__ import annotations

import argparse
from importlib.resources import files
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import xpwebapi
import xpwebapi.fdr as fdr
from xpwebapi.schemas import SCHEMA_FILENAMES


REPO_ROOT = Path(__file__).resolve().parents[1]
_FDR_PUBLIC_NAMES = frozenset(
    (
        "FDRDataref",
        "FDRHeader",
        "FDRLegacyColumn",
        "FDRMetadata",
        "FDRNormalizationResult",
        "FDRParseError",
        "FDRRecording",
        "FDRReader",
        "FDRRecorder",
        "FDRRecordResult",
        "FDRSample",
        "FDRSampleSink",
        "FDRSampleSource",
        "FDRSourceSample",
        "FDRStreamWriter",
        "FDRValidationError",
        "FDRWriter",
        "LiveFDRSampleSource",
        "recording_to_geojson",
    )
)
_MINIMAL_FDR_V4 = b"""A
4
DATE, 2026-08-07
12:00:00, -87.9048, 41.9742, 1000, 270, 2, -1
12:00:01, -87.9047, 41.9743, 1001, 271, 1, 0
"""


def _check_installed_import() -> None:
    package_file = xpwebapi.__file__
    if package_file is None:
        raise RuntimeError("installed package has no filesystem location")
    if Path(package_file).resolve().is_relative_to(REPO_ROOT.resolve()):
        raise RuntimeError("xpwebapi was imported from the source checkout")
    missing = sorted(_FDR_PUBLIC_NAMES - set(fdr.__all__))
    if missing:
        raise RuntimeError(f"installed FDR public API is missing: {', '.join(missing)}")
    for name in _FDR_PUBLIC_NAMES:
        getattr(fdr, name)


def _installed_command(name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    scripts = Path(sys.executable).resolve().parent
    preferred = scripts / f"{name}{suffix}"
    alternate = scripts / (name if suffix else f"{name}.exe")
    return alternate if not preferred.is_file() and alternate.is_file() else preferred


def _run(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _check_capture_cli(command: Path, expected_version: str) -> None:
    result = _run((str(command), "--version-json"))
    payload = json.loads(result.stdout)
    if payload["package_name"] != "xpwebapi":
        raise RuntimeError("capture CLI package name is incorrect")
    if payload["package_version"] != expected_version:
        raise RuntimeError("capture CLI package version is incorrect")
    if payload["read_only"] is not True:
        raise RuntimeError("capture CLI does not report read-only mode")


def _check_geojson(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("type") != "FeatureCollection":
        raise RuntimeError("FDR CLI did not create a GeoJSON FeatureCollection")
    features = document.get("features")
    if not isinstance(features, list) or not features:
        raise RuntimeError("FDR CLI GeoJSON contains no features")
    points = [feature for feature in features if feature.get("geometry", {}).get("type") == "Point"]
    if len(points) != 2:
        raise RuntimeError("FDR CLI GeoJSON does not contain the expected points")
    for point in points:
        coordinates = point["geometry"].get("coordinates")
        properties = point.get("properties", {})
        if not isinstance(coordinates, list) or len(coordinates) != 2:
            raise RuntimeError("FDR CLI GeoJSON point coordinates are not two-dimensional")
        if "altitude_msl_ft" not in properties or "altitude_msl_m" not in properties:
            raise RuntimeError("FDR CLI GeoJSON point is missing MSL altitude properties")


def _check_fdr_cli(command: Path) -> None:
    with TemporaryDirectory(prefix="xpwebapi-installed-smoke-") as temporary:
        root = Path(temporary).resolve()
        if root.is_relative_to(REPO_ROOT.resolve()):
            raise RuntimeError("FDR smoke workspace is inside the source checkout")
        source = root / "minimal-v4.fdr"
        destination = root / "minimal-v4.geojson"
        source.write_bytes(_MINIMAL_FDR_V4)
        _run((str(command), "validate", str(source)))
        _run((str(command), "to-geojson", str(source), str(destination)))
        _check_geojson(destination)


def main() -> int:
    """Validate the installed package, schemas, capture CLI, and FDR CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected_version")
    arguments = parser.parse_args()

    _check_installed_import()
    if xpwebapi.__version__ != arguments.expected_version:
        raise RuntimeError(f"installed version is {xpwebapi.__version__}")
    if xpwebapi.version != arguments.expected_version:
        raise RuntimeError(f"compatibility version is {xpwebapi.version}")

    schema_root = files("xpwebapi.schemas")
    for name in SCHEMA_FILENAMES:
        json.loads(schema_root.joinpath(name).read_text(encoding="utf-8"))

    _check_capture_cli(_installed_command("xpwebapi-capture"), arguments.expected_version)
    _check_fdr_cli(_installed_command("xpwebapi-fdr"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
