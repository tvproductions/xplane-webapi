"""Smoke-test an installed xpwebapi wheel outside its source checkout."""

from __future__ import annotations

import argparse
from importlib.resources import files
import json
import os
from pathlib import Path
import subprocess
import sys

import xpwebapi
from xpwebapi.schemas import SCHEMA_FILENAMES


def main() -> int:
    """Validate the installed package, schemas, and capture CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected_version")
    arguments = parser.parse_args()

    if xpwebapi.__version__ != arguments.expected_version:
        raise RuntimeError(f"installed version is {xpwebapi.__version__}")
    if xpwebapi.version != arguments.expected_version:
        raise RuntimeError(f"compatibility version is {xpwebapi.version}")

    schema_root = files("xpwebapi.schemas")
    for name in SCHEMA_FILENAMES:
        json.loads(schema_root.joinpath(name).read_text(encoding="utf-8"))

    suffix = ".exe" if os.name == "nt" else ""
    command = Path(sys.executable).parent / f"xpwebapi-capture{suffix}"
    result = subprocess.run(
        (str(command), "--version-json"),
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    if payload["package_name"] != "xpwebapi":
        raise RuntimeError("capture CLI package name is incorrect")
    if payload["package_version"] != arguments.expected_version:
        raise RuntimeError("capture CLI package version is incorrect")
    if payload["read_only"] is not True:
        raise RuntimeError("capture CLI does not report read-only mode")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
