# xpwebapi 4.0.0 PyPI Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the first independently maintained TV Productions release of `xpwebapi` as version `4.0.0` on PyPI, with complete lineage, packaged capture schemas, public documentation, dual Python compatibility, and attested Trusted Publishing.

**Architecture:** Keep `xpwebapi` as one pure-Python distribution using `uv_build`. Establish synchronized distribution/runtime identity and one canonical license, move capture schemas inside the import package, and validate built wheel and source archives with repository-owned release tooling. Normal CI verifies quality, compatibility, artifacts, and docs; a tag-triggered workflow rebuilds once from the tagged commit, tests those exact artifacts, and publishes them through a protected PyPI environment.

**Tech Stack:** Python 3.12 and 3.13, `unittest`, `uv`, `uv_build`, MkDocs Material, GitHub Actions, GitHub Pages, PyPI Trusted Publishing, PyPA publish action.

## Global Constraints

- Distribution name and import package remain exactly `xpwebapi`.
- First TV Productions release is stable version `4.0.0`.
- Supported Python range is exactly `>=3.12,<3.14`.
- Python 3.13 runs the full quality gate; runtime and installed-artifact checks run on Python 3.12 and 3.13.
- `tvproductions/xplane-webapi` is the canonical public repository.
- Public documentation is `https://tvproductions.github.io/xplane-webapi/`.
- PyPI user `ahuimanu` owns the project and Trusted Publishing follows the existing `py-gzkit` pattern.
- Pierre Mareschal and `devleaks` retain visible upstream authorship and lineage credit.
- The repository and distributions contain one canonical `LICENSE`; no `LICENCE` file remains.
- All four capture protocol schemas ship inside the import package, wheel, and source distribution.
- No consumer repository, XPPython3 installation, or XPPython3 plugin is changed.
- Existing `dist/xpwebapi-3.5.0*` files are stale and must never be release inputs.
- Tests use `unittest`; do not introduce another testing framework.
- No empty placeholder, release candidate, alternate package name, or long-lived PyPI token is used.

---

## File Structure

### Created

- `xpwebapi/schemas/__init__.py` — declares the installed capture-schema resource names.
- `xpwebapi/schemas/capture-event-v1.schema.json` — installed event schema.
- `xpwebapi/schemas/capture-request-v1.schema.json` — installed request schema.
- `xpwebapi/schemas/capture-status-v1.schema.json` — installed status schema.
- `xpwebapi/schemas/capture-version-v1.schema.json` — installed version schema.
- `tests/test_release_metadata.py` — release identity, version, license, URL, and packaged-schema contracts.
- `tests/test_release_tool.py` — archive and tag validator tests.
- `tools/release.py` — validates tag/version agreement and exact release archive contents.
- `tools/installed_smoke.py` — verifies an installed wheel without importing the source checkout.
- `.github/workflows/release.yml` — tag-triggered build, compatibility, PyPI publish, and GitHub release workflow.

### Modified

- `pyproject.toml` — version, ownership, maintainer, license, URLs, Python range, classifiers, and build backend floor.
- `uv.lock` — re-resolved 3.12/3.13-compatible lock.
- `.python-version` — primary developer interpreter, Python 3.13.
- `xpwebapi/__init__.py` — canonical runtime `__version__` plus backward-compatible `version`.
- `LICENSE` — all upstream notices plus TV Productions modifications notice in one MIT file.
- `README.md` — PyPI installation, fork lineage, TV Productions links, supported Python versions, and general capture-worker positioning.
- `CHANGELOG.md` — complete `4.0.0` entry and upstream source-state note.
- `docs/usage/index.md` — current install command and canonical docs/repository links.
- `docs/usage/read-only-capture.md` — general development-tool language instead of q4xpcc ownership language.
- `docs/reference/index.md` — installed schema-resource documentation.
- `docs/reference/capture.md` — installed schema-resource names and access example.
- `examples/template.py` — PyPI installation guidance instead of the upstream Git URL.
- `examples/xpwsapp.py` — PyPI installation guidance instead of the upstream Git URL.
- `mkdocs.yml` — canonical TV Productions site/repository metadata and exclusion of internal planning documents.
- `tests/test_capture_events.py` — reads canonical event/version schemas as package resources.
- `tests/test_capture_protocol.py` — reads canonical request schema as a package resource.
- `tests/test_capture_output.py` — reads canonical status schema as a package resource.
- `tests/test_documentation.py` — public identity, lineage, docs-site, and workflow contracts.
- `.github/workflows/ci.yml` — quality once on 3.13, build once, compatibility matrix, docs deployment.

### Removed

- `LICENCE` — removed after its upstream copyright notice is preserved in `LICENSE`.
- `schemas/capture-event-v1.schema.json` — moved into `xpwebapi/schemas/`.
- `schemas/capture-request-v1.schema.json` — moved into `xpwebapi/schemas/`.
- `schemas/capture-status-v1.schema.json` — moved into `xpwebapi/schemas/`.
- `schemas/capture-version-v1.schema.json` — moved into `xpwebapi/schemas/`.

---

### Task 1: Establish Release Identity, Version, Python Range, and License

**Files:**
- Create: `tests/test_release_metadata.py`
- Modify: `pyproject.toml`
- Modify: `.python-version`
- Modify: `xpwebapi/__init__.py`
- Modify: `LICENSE`
- Modify: `uv.lock`
- Remove: `LICENCE`

**Interfaces:**
- Consumes: existing PEP 621 project metadata and `xpwebapi.version`.
- Produces: `xpwebapi.__version__: str == "4.0.0"` and backward-compatible `xpwebapi.version: str == "4.0.0"`.

- [ ] **Step 1: Write failing release-metadata tests**

Create `tests/test_release_metadata.py`:

```python
"""Release metadata and installed-resource contracts."""

from __future__ import annotations

from pathlib import Path
import tomllib
import unittest

import xpwebapi


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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused tests and confirm the expected failures**

Run:

```powershell
uv run python -m unittest tests.test_release_metadata -v
```

Expected: failures for version `3.5.0`, missing `__version__`, absent maintainer metadata, upstream URLs, Python 3.13 classifier/range, and duplicate license state.

- [ ] **Step 3: Update project metadata and runtime version**

Change the relevant `pyproject.toml` fields to:

```toml
[project]
name = "xpwebapi"
version = "4.0.0"
authors = [
  { name = "Pierre Mareschal", email = "pierre@devleaks.be" }
]
maintainers = [
  { name = "Jeffry" }
]
description = "Python client and development tools for the Laminar Research X-Plane Web API"
readme = "README.md"
license = "MIT"
license-files = ["LICENSE"]
requires-python = ">=3.12,<3.14"

classifiers = [
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Operating System :: OS Independent",
    "Topic :: Games/Entertainment :: Simulation",
]

[project.urls]
Homepage = "https://tvproductions.github.io/xplane-webapi/"
Documentation = "https://tvproductions.github.io/xplane-webapi/"
Issues = "https://github.com/tvproductions/xplane-webapi/issues"
Repository = "https://github.com/tvproductions/xplane-webapi"

[build-system]
requires = ["uv_build>=0.11.26,<0.12"]
build-backend = "uv_build"
```

Set `.python-version` to:

```text
3.13
```

In `xpwebapi/__init__.py`, export both names from one value:

```python
__version__ = "4.0.0"
version = __version__
```

Add `"__version__"` to `__all__` while retaining `"version"` for compatibility.

- [ ] **Step 4: Consolidate the MIT license**

Replace `LICENSE` with one MIT license containing these three consecutive notices before the permission paragraph:

```text
MIT License

Copyright (c) 2019-2024 Pierre Mareschal
Copyright (c) 2025 Pierre M
Copyright (c) 2026 TV Productions

Permission is hereby granted, free of charge, to any person obtaining a copy
```

Retain the complete existing MIT permission and warranty text once. Remove `LICENCE` only after confirming its `2019-2024 Pierre Mareschal` notice is in `LICENSE`.

- [ ] **Step 5: Re-resolve the lock for the supported range**

Run:

```powershell
uv lock
uv sync --frozen
```

Expected: `uv.lock` records `requires-python = ">=3.12, <3.14"` and `uv sync --frozen` succeeds under Python 3.13.

- [ ] **Step 6: Run focused and existing version-sensitive tests**

Run:

```powershell
uv run python -m unittest tests.test_release_metadata tests.test_capture_cli -v
```

Expected: all tests pass and `xpwebapi-capture --version-json` test fixtures report package version `4.0.0`. If existing fixtures still expect `3.5.0`, update only their expected package-version field to `4.0.0`.

- [ ] **Step 7: Commit**

```powershell
git add pyproject.toml uv.lock .python-version xpwebapi/__init__.py LICENSE tests/test_release_metadata.py
git add -u -- LICENCE
git commit -m "build: prepare xpwebapi 4.0.0 metadata"
```

---

### Task 2: Ship Capture Schemas as Installed Package Resources

**Files:**
- Create: `xpwebapi/schemas/__init__.py`
- Move: `schemas/capture-event-v1.schema.json` → `xpwebapi/schemas/capture-event-v1.schema.json`
- Move: `schemas/capture-request-v1.schema.json` → `xpwebapi/schemas/capture-request-v1.schema.json`
- Move: `schemas/capture-status-v1.schema.json` → `xpwebapi/schemas/capture-status-v1.schema.json`
- Move: `schemas/capture-version-v1.schema.json` → `xpwebapi/schemas/capture-version-v1.schema.json`
- Modify: `tests/test_release_metadata.py`
- Modify: `tests/test_capture_events.py`
- Modify: `tests/test_capture_protocol.py`
- Modify: `tests/test_capture_output.py`

**Interfaces:**
- Consumes: the four generated Pydantic schema contracts.
- Produces: `xpwebapi.schemas.SCHEMA_FILENAMES: tuple[str, ...]` and resources readable with `importlib.resources.files("xpwebapi.schemas")`.

- [ ] **Step 1: Add failing package-resource tests**

Add these imports to the existing standard-library and package import blocks in
`tests/test_release_metadata.py`:

```python
from importlib.resources import files
import json

from xpwebapi.schemas import SCHEMA_FILENAMES
```

Then append:

```python
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
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```powershell
uv run python -m unittest tests.test_release_metadata.PackagedSchemaTests -v
```

Expected: import failure because `xpwebapi.schemas` does not exist.

- [ ] **Step 3: Create the schema package and move canonical files**

Create `xpwebapi/schemas/__init__.py`:

```python
"""Installed JSON Schema resources for the capture protocol."""

from __future__ import annotations

SCHEMA_FILENAMES: tuple[str, ...] = (
    "capture-event-v1.schema.json",
    "capture-request-v1.schema.json",
    "capture-status-v1.schema.json",
    "capture-version-v1.schema.json",
)

__all__ = ["SCHEMA_FILENAMES"]
```

Move all four JSON files into `xpwebapi/schemas/` without changing their bytes.
Small data files inside the Python module are included by `uv_build`; do not add
an external `.data` installation target.

- [ ] **Step 4: Update schema equality tests to use package resources**

In `tests/test_capture_events.py`, `tests/test_capture_protocol.py`, and
`tests/test_capture_output.py`, import:

```python
from importlib.resources import files
```

Define:

```python
SCHEMA_ROOT = files("xpwebapi.schemas")
```

Replace every expression shaped like:

```python
REPO_ROOT / "schemas" / "capture-event-v1.schema.json"
```

with:

```python
SCHEMA_ROOT.joinpath("capture-event-v1.schema.json")
```

Apply the corresponding filename for request, status, and version schemas.
Keep the existing canonical JSON equality assertions unchanged.

- [ ] **Step 5: Run all schema and metadata tests**

Run:

```powershell
uv run python -m unittest tests.test_release_metadata tests.test_capture_events tests.test_capture_protocol tests.test_capture_output -v
```

Expected: all tests pass and no test reads the removed repository-level `schemas/` directory.

- [ ] **Step 6: Commit**

```powershell
git add xpwebapi/schemas tests/test_release_metadata.py tests/test_capture_events.py tests/test_capture_protocol.py tests/test_capture_output.py
git add -u -- schemas
git commit -m "build: package capture protocol schemas"
```

---

### Task 3: Publish TV Productions Identity, Lineage, and Documentation

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/usage/index.md`
- Modify: `docs/usage/read-only-capture.md`
- Modify: `docs/reference/index.md`
- Modify: `docs/reference/capture.md`
- Modify: `examples/template.py`
- Modify: `examples/xpwsapp.py`
- Modify: `mkdocs.yml`
- Modify: `tests/test_documentation.py`

**Interfaces:**
- Consumes: version `4.0.0`, TV Productions URLs, installed schema names.
- Produces: a PyPI-renderable README and MkDocs site rooted at `https://tvproductions.github.io/xplane-webapi/`.

- [ ] **Step 1: Write failing public-documentation tests**

Add these methods to `TestDocumentationContent` in `tests/test_documentation.py`:

```python
def test_public_materials_identify_the_maintained_fork(self) -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    self.assertIn("pip install xpwebapi", readme)
    self.assertIn("TV Productions", readme)
    self.assertIn("devleaks/xplane-webapi", readme)
    self.assertIn("independently maintained fork", readme)
    self.assertIn("https://tvproductions.github.io/xplane-webapi/", readme)
    self.assertNotIn("git+https://github.com/devleaks", readme)
    self.assertNotIn("development infrastructure for q4xpcc", readme)

    self.assertIn("## 4.0.0", changelog)
    self.assertIn("upstream source reported version 3.5.0", changelog)
    self.assertIn("no corresponding upstream changelog entry or release tag", changelog)

def test_public_materials_have_no_stale_active_upstream_or_consumer_links(self) -> None:
    paths = (
        REPO_ROOT / "README.md",
        DOCS_DIR / "usage" / "index.md",
        DOCS_DIR / "usage" / "read-only-capture.md",
        DOCS_DIR / "reference" / "index.md",
        DOCS_DIR / "reference" / "capture.md",
        REPO_ROOT / "examples" / "template.py",
        REPO_ROOT / "examples" / "xpwsapp.py",
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        with self.subTest(path=path.relative_to(REPO_ROOT)):
            self.assertNotIn("devleaks.github.io/xplane-webapi", text)
            self.assertNotIn("git+https://github.com/devleaks/xplane-webapi.git", text)
            self.assertNotIn("q4xpcc", text)

def test_mkdocs_uses_tvproductions_canonical_site_and_excludes_internal_plans(self) -> None:
    mkdocs = (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8")

    self.assertIn("site_url: https://tvproductions.github.io/xplane-webapi/", mkdocs)
    self.assertIn("repo_url: https://github.com/tvproductions/xplane-webapi", mkdocs)
    self.assertIn("repo_name: tvproductions/xplane-webapi", mkdocs)
    self.assertIn("edit_uri: edit/main/docs/", mkdocs)
    self.assertIn("exclude_docs:", mkdocs)
    self.assertIn("  superpowers/**", mkdocs)

def test_capture_docs_describe_installed_schema_resources(self) -> None:
    reference = (DOCS_DIR / "reference" / "capture.md").read_text(encoding="utf-8")
    self.assertIn("xpwebapi.schemas", reference)
    for name in (
        "capture-event-v1.schema.json",
        "capture-request-v1.schema.json",
        "capture-status-v1.schema.json",
        "capture-version-v1.schema.json",
    ):
        with self.subTest(name=name):
            self.assertIn(name, reference)
```

Update the existing operational-contract expectation that currently requires
`"q4xpcc owns"` so it instead requires:

```python
"the consuming development tool owns"
```

Update `test_readme_and_changelog_announce_read_only_capture` so it requires
`"## 4.0.0"` instead of `"## Unreleased"`.

- [ ] **Step 2: Run documentation tests and confirm failures**

Run:

```powershell
uv run python -m unittest tests.test_documentation -v
```

Expected: failures for upstream installation/links, q4xpcc-only wording, missing fork lineage, missing `4.0.0`, missing MkDocs canonical fields/exclusion, and absent schema-resource docs.

- [ ] **Step 3: Replace README with public package copy**

Use this structure and exact identity statements in `README.md`, retaining
working examples from the existing usage documentation:

```markdown
# xpwebapi

`xpwebapi` is a Python client and development toolkit for the Laminar Research
X-Plane Web API, including REST, async REST, WebSocket, UDP, beacon discovery,
and a strictly read-only capture worker.

This is an independently maintained fork of
[`devleaks/xplane-webapi`](https://github.com/devleaks/xplane-webapi).
TV Productions thanks Pierre Mareschal and `devleaks` for creating the original
library. The upstream source reported version 3.5.0 when this fork's extension
work began; TV Productions maintains releases beginning with 4.0.0.

This project is not endorsed by or affiliated with the upstream maintainer or
Laminar Research. X-Plane is a trademark of Laminar Research.

## Installation

Requires Python 3.12 or 3.13.

```sh
pip install xpwebapi
```

## Quick start

```python
import xpwebapi

with xpwebapi.rest_api(api_version="v2") as api:
    clock = api.dataref("sim/cockpit2/clock_timer/local_time_seconds")
    print(api.dataref_value(clock))
```

## Read-only capture worker

The installed `xpwebapi-capture` command records a bounded, versioned stream of
configured X-Plane DataRefs without exposing command execution or DataRef
writes. WebSocket is the primary capture transport; UDP is the diagnostic
fallback.

See the [capture guide](https://tvproductions.github.io/xplane-webapi/usage/read-only-capture/)
and [capture protocol reference](https://tvproductions.github.io/xplane-webapi/reference/capture/).

## Documentation

Full documentation is available at
https://tvproductions.github.io/xplane-webapi/.

## Development

```sh
git clone https://github.com/tvproductions/xplane-webapi.git
cd xplane-webapi
uv sync
uv run python -m unittest discover -v
```

## License

MIT. See [`LICENSE`](https://github.com/tvproductions/xplane-webapi/blob/main/LICENSE).
```

- [ ] **Step 4: Add the 4.0.0 changelog boundary**

Replace the current `Unreleased` capture-only section with:

```markdown
## 4.0.0 - 2026-07-26

First independently maintained TV Productions release and first PyPI release.
The upstream source reported version 3.5.0 when extension work began, but it
contained no corresponding upstream changelog entry or release tag; no missing
upstream releases are inferred here.

### Added

- Async REST client support.
- Typed metadata caches, typed exceptions, retries, and structured logging.
- Context-managed cleanup and REST connection pooling.
- Strictly read-only capture worker, installed CLI, versioned JSON protocols,
  and packaged JSON Schemas.
- Expanded API reference, usage guidance, examples, and `unittest` coverage.

### Changed

- TV Productions is the canonical maintainer and release source.
- HTTP and WebSocket transports use current `httpx` and `websockets` clients.
- Supported Python versions are 3.12 and 3.13.
- CI, security, typing, documentation, and release verification are blocking.

### Attribution

TV Productions thanks Pierre Mareschal and `devleaks` for the original
`xplane-webapi` project. Historical entries below are retained from upstream.
```

Keep every existing historical changelog entry below this new section exactly
as found, including upstream spelling/version quirks.

- [ ] **Step 5: Generalize capture and usage documentation**

In `docs/usage/read-only-capture.md`, replace q4xpcc ownership language with:

```markdown
The consuming development tool owns watchlists, run or sortie boundaries,
worker launch, normalized evidence, and final bundles. `xpwebapi-capture` owns
only the bounded read-only observation process and its versioned outputs.
```

Generalize every other active q4xpcc reference in that page and in
`docs/reference/capture.md` to “the consuming development tool” or “consumer,”
as grammatically appropriate. Update the rendered `--version-json` example to
package version `4.0.0`. Historical internal plans under `docs/superpowers/`
remain unchanged and are excluded from the public site.

In `docs/usage/index.md`, use `pip install xpwebapi`, link the canonical TV
Productions repository, and retain the existing REST, async REST, WebSocket,
UDP, and lifecycle examples.

In `examples/template.py` and `examples/xpwsapp.py`, replace the fallback
Git-repository install instruction with:

```text
pip install xpwebapi
```

In `docs/reference/capture.md`, add:

```markdown
## Installed JSON Schemas

The four protocol-v1 schemas ship in the `xpwebapi.schemas` package:

- `capture-event-v1.schema.json`
- `capture-request-v1.schema.json`
- `capture-status-v1.schema.json`
- `capture-version-v1.schema.json`

```python
from importlib.resources import files

schema_text = (
    files("xpwebapi.schemas")
    .joinpath("capture-request-v1.schema.json")
    .read_text(encoding="utf-8")
)
```
```

Link this section from `docs/reference/index.md`.

- [ ] **Step 6: Configure canonical MkDocs metadata**

Add these top-level fields to `mkdocs.yml`:

```yaml
site_name: xpwebapi
site_url: https://tvproductions.github.io/xplane-webapi/
repo_url: https://github.com/tvproductions/xplane-webapi
repo_name: tvproductions/xplane-webapi
edit_uri: edit/main/docs/

exclude_docs: |
  superpowers/**
```

Retain the Material theme, navigation, search, mkdocstrings, capture pages, and
git revision-date plugin.

- [ ] **Step 7: Run docs tests and build**

Run:

```powershell
uv run python -m unittest tests.test_documentation -v
uv run mkdocs build --strict
```

Expected: documentation tests pass; strict build succeeds; generated `site/`
contains usage/reference pages and does not contain `site/superpowers/`.

- [ ] **Step 8: Commit**

```powershell
git add README.md CHANGELOG.md docs/usage/index.md docs/usage/read-only-capture.md docs/reference/index.md docs/reference/capture.md examples/template.py examples/xpwsapp.py mkdocs.yml tests/test_documentation.py
git commit -m "docs: establish tvproductions package identity"
```

---

### Task 4: Add Release Archive and Installed-Wheel Validation

**Files:**
- Create: `tools/release.py`
- Create: `tools/installed_smoke.py`
- Create: `tests/test_release_tool.py`

**Interfaces:**
- Consumes: `pyproject.toml`, built wheel/source archives, installed `xpwebapi`.
- Produces: `python tools/release.py check-tag <tag>` and `python tools/release.py check-dist <directory>` returning zero only for valid release inputs; `tools/installed_smoke.py 4.0.0` returning zero only for a valid installed wheel and CLI.

- [ ] **Step 1: Write failing validator tests**

Create `tests/test_release_tool.py`:

```python
from __future__ import annotations

from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
import unittest
import zipfile

from tools.release import ReleaseValidationError, check_dist, check_tag


VERSION = "4.0.0"
SCHEMAS = (
    "capture-event-v1.schema.json",
    "capture-request-v1.schema.json",
    "capture-status-v1.schema.json",
    "capture-version-v1.schema.json",
)


def write_archives(
    root: Path,
    *,
    omit_schema: str | None = None,
    extra_archive: bool = False,
) -> None:
    wheel = root / f"xpwebapi-{VERSION}-py3-none-any.whl"
    metadata = "\n".join(
        (
            "Metadata-Version: 2.4",
            "Name: xpwebapi",
            f"Version: {VERSION}",
            "Requires-Python: <3.14,>=3.12",
            "",
        )
    )
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"xpwebapi-{VERSION}.dist-info/METADATA", metadata)
        archive.writestr(f"xpwebapi-{VERSION}.dist-info/licenses/LICENSE", "MIT")
        for name in SCHEMAS:
            if name != omit_schema:
                archive.writestr(f"xpwebapi/schemas/{name}", "{}")

    source_root = root / f"xpwebapi-{VERSION}"
    source_root.mkdir()
    (source_root / "LICENSE").write_text("MIT", encoding="utf-8")
    (source_root / "PKG-INFO").write_text(metadata, encoding="utf-8")
    schema_root = source_root / "xpwebapi" / "schemas"
    schema_root.mkdir(parents=True)
    for name in SCHEMAS:
        if name != omit_schema:
            (schema_root / name).write_text("{}", encoding="utf-8")
    with tarfile.open(root / f"xpwebapi-{VERSION}.tar.gz", "w:gz") as archive:
        archive.add(source_root, arcname=source_root.name)
    if extra_archive:
        (root / "xpwebapi-3.5.0.tar.gz").write_bytes(b"stale")


class ReleaseToolTests(unittest.TestCase):
    def test_tag_must_match_project_and_runtime_versions(self) -> None:
        check_tag("v4.0.0")
        with self.assertRaisesRegex(ReleaseValidationError, "v4.0.1"):
            check_tag("v4.0.1")

    def test_valid_archives_include_license_metadata_and_every_schema(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_archives(root)
            check_dist(root)

    def test_missing_packaged_schema_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_archives(root, omit_schema=SCHEMAS[0])
            with self.assertRaisesRegex(ReleaseValidationError, SCHEMAS[0]):
                check_dist(root)

    def test_extra_archive_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_archives(root, extra_archive=True)
            with self.assertRaisesRegex(ReleaseValidationError, "unexpected files"):
                check_dist(root)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run validator tests and confirm the import failure**

Run:

```powershell
uv run python -m unittest tests.test_release_tool -v
```

Expected: import failure because `tools.release` does not exist.

- [ ] **Step 3: Implement the release validator**

Create `tools/release.py` with these complete public functions and CLI:

```python
"""Validate xpwebapi release tags and distribution archives."""

from __future__ import annotations

import argparse
from email import policy
from email.parser import BytesParser
from pathlib import Path
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
    document = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(document["project"]["version"])


def runtime_version() -> str:
    source = (REPO_ROOT / "xpwebapi" / "__init__.py").read_text(encoding="utf-8")
    for line in source.splitlines():
        if line.startswith("__version__ = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise ReleaseValidationError("xpwebapi.__version__ declaration is missing")


def check_tag(tag: str) -> None:
    expected = project_version()
    actual = tag.removeprefix("v")
    if tag != f"v{expected}" or actual != runtime_version():
        raise ReleaseValidationError(
            f"tag {tag!r}, project {expected!r}, and runtime {runtime_version()!r} must match"
        )


def _require_members(members: set[str], required: set[str], *, archive: Path) -> None:
    missing = sorted(required - members)
    if missing:
        raise ReleaseValidationError(f"{archive.name} is missing: {', '.join(missing)}")


def check_dist(directory: Path) -> None:
    version = project_version()
    wheels = sorted(directory.glob(f"xpwebapi-{version}-*.whl"))
    source = directory / f"xpwebapi-{version}.tar.gz"
    if len(wheels) != 1 or not source.is_file():
        raise ReleaseValidationError(
            f"expected one xpwebapi-{version} wheel and xpwebapi-{version}.tar.gz"
        )

    wheel = wheels[0]
    allowed_files = {wheel.name, source.name, ".gitignore"}
    actual_files = {path.name for path in directory.iterdir() if path.is_file()}
    unexpected_files = sorted(actual_files - allowed_files)
    if unexpected_files:
        raise ReleaseValidationError(
            f"distribution directory contains unexpected files: {', '.join(unexpected_files)}"
        )

    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())
        metadata_name = f"xpwebapi-{version}.dist-info/METADATA"
        required = {
            metadata_name,
            f"xpwebapi-{version}.dist-info/licenses/LICENSE",
            *(f"xpwebapi/schemas/{name}" for name in SCHEMAS),
        }
        _require_members(members, required, archive=wheel)
        if any(name.endswith("/LICENCE") or "/superpowers/" in name for name in members):
            raise ReleaseValidationError(f"{wheel.name} contains forbidden material")
        metadata = BytesParser(policy=policy.default).parsebytes(archive.read(metadata_name))
        if metadata["Name"] != "xpwebapi" or metadata["Version"] != version:
            raise ReleaseValidationError(f"{wheel.name} metadata identity is incorrect")
        if metadata["Requires-Python"] not in {">=3.12,<3.14", "<3.14,>=3.12"}:
            raise ReleaseValidationError(f"{wheel.name} Requires-Python is incorrect")

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
        if any(name.endswith("/LICENCE") or "/docs/superpowers/" in name for name in members):
            raise ReleaseValidationError(f"{source.name} contains forbidden material")
        metadata_member = archive.extractfile(metadata_name)
        if metadata_member is None:
            raise ReleaseValidationError(f"{source.name} metadata is unreadable")
        metadata = BytesParser(policy=policy.default).parsebytes(metadata_member.read())
        if metadata["Name"] != "xpwebapi" or metadata["Version"] != version:
            raise ReleaseValidationError(f"{source.name} metadata identity is incorrect")
        if metadata["Requires-Python"] not in {">=3.12,<3.14", "<3.14,>=3.12"}:
            raise ReleaseValidationError(f"{source.name} Requires-Python is incorrect")


def main() -> int:
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
```

- [ ] **Step 4: Implement installed-wheel smoke verification**

Create `tools/installed_smoke.py`:

```python
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
```

- [ ] **Step 5: Run validator tests**

Run:

```powershell
uv run python -m unittest tests.test_release_tool -v
uv run python tools/release.py check-tag v4.0.0
```

Expected: all tests pass and tag validation exits zero.

- [ ] **Step 6: Commit**

```powershell
git add tools/release.py tools/installed_smoke.py tests/test_release_tool.py
git commit -m "build: add release artifact validation"
```

---

### Task 5: Split CI Quality, Package, Compatibility, and Docs Gates

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_documentation.py`

**Interfaces:**
- Consumes: `tools/release.py`, `tools/installed_smoke.py`, `4.0.0` metadata.
- Produces: one normal-CI artifact set validated on both Python versions and a gated `gh-pages` deployment.

- [ ] **Step 1: Add failing CI contract test**

Add to `TestDocumentationContent`:

```python
def test_ci_separates_quality_package_compatibility_and_docs(self) -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    for job in ("quality:", "package:", "compatibility:", "docs:"):
        with self.subTest(job=job):
            self.assertIn(job, workflow)
    self.assertIn('python-version: "3.13"', workflow)
    self.assertIn('python-version: ["3.12", "3.13"]', workflow)
    self.assertIn("uv run python tools/release.py check-dist dist", workflow)
    self.assertIn("actions/upload-artifact@v7", workflow)
    self.assertIn("actions/download-artifact@v8", workflow)
    self.assertIn("python -m unittest discover -v", workflow)
    self.assertIn("tools/installed_smoke.py 4.0.0", workflow)
    self.assertIn("uv run mkdocs gh-deploy --force", workflow)
```

- [ ] **Step 2: Run the CI contract test and confirm failure**

Run:

```powershell
uv run python -m unittest tests.test_documentation.TestDocumentationContent.test_ci_separates_quality_package_compatibility_and_docs -v
```

Expected: failure because the current workflow has only `quality` and `docs`.

- [ ] **Step 3: Replace CI with four gated jobs**

Implement `.github/workflows/ci.yml` with this job structure:

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: astral-sh/setup-uv@v8
        with:
          enable-cache: true
      - run: uv python install 3.13
      - run: uv sync --frozen --python 3.13
      - run: uv run --python 3.13 python tools/quality.py check
      - run: uv run --python 3.13 mkdocs build --strict

  package:
    needs: quality
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: astral-sh/setup-uv@v8
      - run: uv python install 3.13
      - run: uv build --no-sources
      - run: uv tool run twine check --strict dist/*
      - run: uv run --python 3.13 python tools/release.py check-dist dist
      - uses: actions/upload-artifact@v7
        with:
          name: python-distributions
          path: dist/
          if-no-files-found: error

  compatibility:
    needs: package
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.12", "3.13"]
    steps:
      - uses: actions/checkout@v6
      - uses: astral-sh/setup-uv@v8
      - run: uv python install ${{ matrix.python-version }}
      - run: uv sync --frozen --python ${{ matrix.python-version }}
      - run: uv run --python ${{ matrix.python-version }} python -m unittest discover -v
      - uses: actions/download-artifact@v8
        with:
          name: python-distributions
          path: dist/
      - run: uv venv --python ${{ matrix.python-version }} .smoke
      - run: uv pip install --python .smoke/bin/python dist/*.whl
      - run: cd "$RUNNER_TEMP" && "$GITHUB_WORKSPACE/.smoke/bin/python" "$GITHUB_WORKSPACE/tools/installed_smoke.py" 4.0.0

  docs:
    needs: [quality, compatibility]
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    permissions:
      contents: write
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v8
      - run: uv python install 3.13
      - run: uv sync --frozen --python 3.13
      - run: uv run --python 3.13 mkdocs gh-deploy --force
```

- [ ] **Step 4: Run CI/documentation contract tests**

Run:

```powershell
uv run python -m unittest tests.test_documentation -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add .github/workflows/ci.yml tests/test_documentation.py
git commit -m "ci: verify package on python 3.12 and 3.13"
```

---

### Task 6: Add Tag-Triggered Trusted Publishing Workflow

**Files:**
- Create: `.github/workflows/release.yml`
- Modify: `tests/test_documentation.py`

**Interfaces:**
- Consumes: annotated tag `v4.0.0`, protected GitHub environment `pypi`, pending PyPI publisher.
- Produces: one verified wheel, one verified source archive, PyPI provenance attestations, and a GitHub release.

- [ ] **Step 1: Add failing release-workflow contract test**

Add to `TestDocumentationContent`:

```python
def test_release_workflow_builds_once_and_publishes_exact_artifacts(self) -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    self.assertIn('tags: ["v*"]', workflow)
    self.assertEqual(1, workflow.count("uv build --no-sources"))
    self.assertIn("python tools/release.py check-tag ${{ github.ref_name }}", workflow)
    self.assertIn('test "${{ github.sha }}" = "$(git rev-parse origin/main)"', workflow)
    self.assertIn("python tools/release.py check-dist dist", workflow)
    self.assertIn("python-version: [\"3.12\", \"3.13\"]", workflow)
    self.assertIn("environment: pypi", workflow)
    self.assertIn("id-token: write", workflow)
    self.assertIn("contents: write", workflow)
    self.assertIn("pypa/gh-action-pypi-publish@release/v1", workflow)
    self.assertIn("attestations: true", workflow)
    self.assertIn("softprops/action-gh-release@v3", workflow)
```

- [ ] **Step 2: Run the workflow test and confirm missing-file failure**

Run:

```powershell
uv run python -m unittest tests.test_documentation.TestDocumentationContent.test_release_workflow_builds_once_and_publishes_exact_artifacts -v
```

Expected: error because `.github/workflows/release.yml` does not exist.

- [ ] **Step 3: Create the release workflow**

Create `.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    tags: ["v*"]

permissions:
  contents: read

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v8
      - run: uv python install 3.13
      - run: test "${{ github.sha }}" = "$(git rev-parse origin/main)"
      - run: uv run --python 3.13 python tools/release.py check-tag ${{ github.ref_name }}
      - run: uv build --no-sources
      - run: uv tool run twine check --strict dist/*
      - run: uv run --python 3.13 python tools/release.py check-dist dist
      - uses: actions/upload-artifact@v7
        with:
          name: python-distributions
          path: dist/
          if-no-files-found: error

  compatibility:
    needs: build
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.12", "3.13"]
    steps:
      - uses: actions/checkout@v6
      - uses: astral-sh/setup-uv@v8
      - run: uv python install ${{ matrix.python-version }}
      - uses: actions/download-artifact@v8
        with:
          name: python-distributions
          path: dist/
      - run: uv venv --python ${{ matrix.python-version }} .smoke
      - run: uv pip install --python .smoke/bin/python dist/*.whl
      - run: cd "$RUNNER_TEMP" && "$GITHUB_WORKSPACE/.smoke/bin/python" "$GITHUB_WORKSPACE/tools/installed_smoke.py" 4.0.0

  pypi:
    needs: compatibility
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v8
        with:
          name: python-distributions
          path: dist/
      - uses: pypa/gh-action-pypi-publish@release/v1
        with:
          packages-dir: dist/
          attestations: true
          verbose: true

  github-release:
    needs: pypi
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/download-artifact@v8
        with:
          name: python-distributions
          path: dist/
      - uses: softprops/action-gh-release@v3
        with:
          generate_release_notes: true
          files: dist/*
```

- [ ] **Step 4: Run workflow/documentation tests**

Run:

```powershell
uv run python -m unittest tests.test_documentation -v
```

Expected: all workflow contract tests pass.

- [ ] **Step 5: Commit**

```powershell
git add .github/workflows/release.yml tests/test_documentation.py
git commit -m "ci: add attested pypi release workflow"
```

---

### Task 7: Run Complete Local Release Verification

**Files:**
- Modify only if verification exposes a defect in files already listed by Tasks 1-6.

**Interfaces:**
- Consumes: completed Tasks 1-6.
- Produces: a clean, evidence-backed release commit ready to push; no external publication.

- [ ] **Step 1: Confirm exact worktree and upstream divergence**

Run:

```powershell
git status --short --branch
git rev-list --left-right --count upstream/main...main
git log -8 --oneline --decorate
```

Expected: no uncommitted files; `main` is intentionally ahead of upstream and contains the release-hardening commits.

- [ ] **Step 2: Invoke the full repository hygiene contract on Python 3.13**

Use the `hygiene` skill. Inspect first, synchronize the Python 3.13
environment, then run its full-strength workflow and the strict site build:

```powershell
git status --short --branch
git diff --stat
git diff --cached --stat
uv sync --frozen --python 3.13
uv run python .codex/skills/hygiene/scripts/hygiene.py
uv run --python 3.13 mkdocs build --strict
```

Expected: offline lock validation, every blocking quality step, repository
pre-commit hooks, and the strict docs build pass. Record test counts, warnings,
and generated-but-untracked files as required by the skill.

- [ ] **Step 3: Run the full runtime suite on Python 3.12**

Run:

```powershell
uv run --python 3.12 python -m unittest discover -v
```

Expected: the complete suite passes on Python 3.12.

- [ ] **Step 4: Remove only the two known stale local archives**

First verify exact targets:

```powershell
Get-ChildItem -LiteralPath dist | Select-Object FullName,Length,LastWriteTime
```

Expected targets:

```text
dist\xpwebapi-3.5.0-py3-none-any.whl
dist\xpwebapi-3.5.0.tar.gz
```

Remove only those exact files with native PowerShell:

```powershell
Remove-Item -LiteralPath dist\xpwebapi-3.5.0-py3-none-any.whl
Remove-Item -LiteralPath dist\xpwebapi-3.5.0.tar.gz
```

The ignored `dist/.gitignore` may remain. Do not recursively delete `dist/`.

- [ ] **Step 5: Build and validate fresh archives**

Run:

```powershell
uv build --no-sources
uv tool run twine check --strict dist\*
uv run --python 3.13 python tools\release.py check-dist dist
tar -tf dist\xpwebapi-4.0.0-py3-none-any.whl
tar -tf dist\xpwebapi-4.0.0.tar.gz
```

Expected: one `4.0.0` wheel and one source archive; both include `LICENSE` and
all four `xpwebapi/schemas/*.json`; neither includes `LICENCE` or
`docs/superpowers/`.

- [ ] **Step 6: Smoke-test the built wheel outside the checkout on both minors**

Run:

```powershell
$smoke312 = Join-Path ([System.IO.Path]::GetTempPath()) "xpwebapi-4.0.0-312-$([guid]::NewGuid().ToString('N'))"
uv venv --python 3.12 $smoke312
uv pip install --python "$smoke312\Scripts\python.exe" dist\xpwebapi-4.0.0-py3-none-any.whl
Push-Location C:\tmp
& "$smoke312\Scripts\python.exe" C:\Users\Jeff\source\repos\xp\xplane-webapi\tools\installed_smoke.py 4.0.0
Pop-Location

$smoke313 = Join-Path ([System.IO.Path]::GetTempPath()) "xpwebapi-4.0.0-313-$([guid]::NewGuid().ToString('N'))"
uv venv --python 3.13 $smoke313
uv pip install --python "$smoke313\Scripts\python.exe" dist\xpwebapi-4.0.0-py3-none-any.whl
Push-Location C:\tmp
& "$smoke313\Scripts\python.exe" C:\Users\Jeff\source\repos\xp\xplane-webapi\tools\installed_smoke.py 4.0.0
Pop-Location
```

Expected: both smoke scripts exit zero and both installed capture commands emit valid `4.0.0` read-only version JSON.

- [ ] **Step 7: Invoke verification-before-completion**

Use the `verification-before-completion` skill. Re-run any command it requires
and record fresh output before claiming the release commit is ready.

---

### Task 8: Push Main and Activate TV Productions Documentation

**Files:**
- External GitHub state: `tvproductions/xplane-webapi` main branch, Actions, Pages.

**Interfaces:**
- Consumes: verified local main from Task 7.
- Produces: synchronized public source and live canonical documentation; no PyPI project yet.

- [ ] **Step 1: Invoke the repository git-sync workflow**

Use the `git-sync` skill to review scope, rerun its required checks, push
`main`, and verify `origin/main` equals local `main`.

Expected: all intended commits are present at
`https://github.com/tvproductions/xplane-webapi`; no unrelated files are pushed.

- [ ] **Step 2: Wait for normal CI**

Inspect the pushed commit's GitHub Actions checks.

Expected: `quality`, `package`, Python 3.12 compatibility, Python 3.13
compatibility, and `docs` all succeed.

- [ ] **Step 3: Configure GitHub Pages**

In `tvproductions/xplane-webapi` repository settings:

1. Open **Settings → Pages**.
2. Select **Deploy from a branch**.
3. Select branch **gh-pages** and folder **/(root)**.
4. Save.

This is needed because the populated `gh-pages` branch currently exists while
the TV Productions Pages endpoint returns GitHub's site-not-found response.

- [ ] **Step 4: Verify the public site and exclusion boundary**

Verify:

```powershell
$home = Invoke-WebRequest -Uri 'https://tvproductions.github.io/xplane-webapi/'
$usage = Invoke-WebRequest -Uri 'https://tvproductions.github.io/xplane-webapi/usage/'
$reference = Invoke-WebRequest -Uri 'https://tvproductions.github.io/xplane-webapi/reference/'
$internal = Invoke-WebRequest -Uri 'https://tvproductions.github.io/xplane-webapi/superpowers/' -SkipHttpErrorCheck
[int]$home.StatusCode
[int]$usage.StatusCode
[int]$reference.StatusCode
[int]$internal.StatusCode
```

Expected: home, usage, and reference return 200; `superpowers/` returns 404.
Rendered pages link to TV Productions and contain no active upstream install,
issue, or release links.

---

### Task 9: Configure Pending Publisher and Publish Immutable 4.0.0

**Files:**
- External GitHub state: protected `pypi` environment and annotated `v4.0.0` tag.
- External PyPI state: pending publisher converted into project `xpwebapi` and immutable release `4.0.0`.

**Interfaces:**
- Consumes: green public commit, live documentation, `.github/workflows/release.yml`.
- Produces: `https://pypi.org/project/xpwebapi/`, PyPI attestations, and GitHub release `v4.0.0`.

- [ ] **Step 1: Reconfirm the PyPI name immediately before setup**

Run a read-only request:

```powershell
$response = Invoke-WebRequest -Uri 'https://pypi.org/pypi/xpwebapi/json' -SkipHttpErrorCheck
[int]$response.StatusCode
```

Expected: 404. If it is not 404, stop for an explicit ownership/name review.

- [ ] **Step 2: Create and protect the GitHub `pypi` environment**

In repository **Settings → Environments**:

1. Create environment `pypi`.
2. Add `ahuimanu` as a required reviewer.
3. Prevent self-review only if another authorized reviewer is available;
   otherwise retain the explicit manual approval gate.
4. Limit deployment branches/tags to protected tags or the `v*` release-tag pattern.

Expected: the release workflow's `pypi` job cannot run without environment approval.

- [ ] **Step 3: Register the pending PyPI publisher**

While signed in to PyPI as `ahuimanu`, open account **Publishing** and add:

```text
PyPI project name: xpwebapi
GitHub owner: tvproductions
GitHub repository: xplane-webapi
Workflow filename: release.yml
Environment name: pypi
```

Expected: PyPI shows a pending publisher. Remember that this does not reserve
the project name; continue directly to the tag after verifying every field.

- [ ] **Step 4: Create and push the annotated release tag**

From the verified, synchronized `main` commit:

```powershell
git status --short --branch
git tag -a v4.0.0 -m "xpwebapi 4.0.0"
git show --no-patch --decorate v4.0.0
git push origin v4.0.0
```

Expected: tag points to the exact green release commit and triggers
`.github/workflows/release.yml`.

- [ ] **Step 5: Inspect build and compatibility jobs before approval**

Wait for release workflow jobs:

- `build`
- compatibility on Python 3.12
- compatibility on Python 3.13

Expected: all three succeed. If any fails, do not approve `pypi`; fix the
problem under `4.0.0`, move the unpublished tag only with explicit approval,
and rerun all release gates.

- [ ] **Step 6: Approve the protected PyPI deployment**

Approve the `pypi` environment deployment only after inspecting the successful
jobs and confirming the tag SHA.

Expected: the pending publisher creates `xpwebapi`, publishes wheel and source
archive once, converts to a normal publisher, and records attestations.

- [ ] **Step 7: Verify PyPI and GitHub release state**

Verify the PyPI JSON endpoint and installed package:

```powershell
$project = Invoke-RestMethod -Uri 'https://pypi.org/pypi/xpwebapi/json'
$project.info.name
$project.info.version
$project.info.requires_python
$project.info.project_urls

uv run --no-project --python 3.12 --with xpwebapi==4.0.0 python -c "import xpwebapi; print(xpwebapi.__version__)"
uv run --no-project --python 3.13 --with xpwebapi==4.0.0 python -c "import xpwebapi; print(xpwebapi.__version__)"
```

Expected:

```text
xpwebapi
4.0.0
>=3.12,<3.14
4.0.0
4.0.0
```

On the PyPI project page verify:

- maintainer/owner is `ahuimanu`;
- repository is `tvproductions/xplane-webapi`;
- documentation links to the TV Productions Pages site;
- README renders correctly;
- both files show Trusted Publishing and provenance for `release.yml`,
  `refs/tags/v4.0.0`, the public repository, and the exact tag commit;
- wheel and source hashes match the release workflow artifacts.

Verify the GitHub `v4.0.0` release exists and contains the same two
distribution files.

- [ ] **Step 8: Add the courteous upstream PR note**

Post this comment to `devleaks/xplane-webapi` PR #2:

```markdown
Thank you again for creating `xplane-webapi`. After leaving this modernization
PR open for a month without maintainer feedback, I have continued the work as
an independently maintained fork at
https://github.com/tvproductions/xplane-webapi.

The original authorship and MIT notices remain intact, and the project clearly
credits this upstream repository. TV Productions now publishes maintained
releases as `xpwebapi` on PyPI:
https://pypi.org/project/xpwebapi/

I am leaving this PR open for now in case the upstream project would still like
to use the initial modernization work.
```

Expected: comment is visible on PR #2. Do not close the PR automatically.

---

## Final Completion Evidence

Before declaring the work complete, invoke `verification-before-completion` and
confirm all of the following with fresh evidence:

- local and `origin/main` commit SHAs match;
- tag `v4.0.0` points to that commit;
- normal CI and release workflow are green;
- GitHub Pages home, usage, and reference pages return 200;
- internal `superpowers/` docs return 404;
- PyPI JSON reports `xpwebapi` version `4.0.0` and Python `>=3.12,<3.14`;
- PyPI wheel and source archive have Trusted Publishing provenance;
- clean installs and version checks pass on Python 3.12 and 3.13;
- packaged schemas are accessible after installation;
- upstream PR comment is present;
- no required work remains.
