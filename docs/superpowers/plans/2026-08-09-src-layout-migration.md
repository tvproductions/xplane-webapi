# xplane-webapi Source-Layout Migration Implementation Plan

- **Governance:** active
- **Status:** draft
- **Date:** 2026-08-09
- **Revised:** 2026-11-22
- **Source specification:** `docs/superpowers/specs/2026-08-09-src-layout-migration-design.md`
- **Release scope:** [5.0.0 PRD](../specs/2026-11-22-xpwebapi-5.0.0-prd.md)
- **Work item:** [issue #2](https://github.com/tvproductions/xplane-webapi/issues/2)
- **Approval:** —
- **Completion evidence:** —

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the forked xplane-webapi runtime package to `src/xpwebapi` while preserving public behavior, packaged schemas, command entry points, and release artifacts.

**Architecture:** Separate physical checkout paths from installed module paths. Source-aware tools target `src/xpwebapi`; imports and wheel members remain `xpwebapi`; source-archive package members gain the `src/` prefix. Preserve the upstream-derived package bytes and adjust only path-sensitive configuration, tools, tests, and documentation.

**Tech Stack:** Python 3.12.16 managed by uv, `uv_build`, Python `unittest`, Ruff, ty, coverage, Bandit, MkDocs, and repository-owned release tooling.

## Global Constraints

- Governing specification: `docs/superpowers/specs/2026-08-09-src-layout-migration-design.md`.
- The approved 5.0.0 PRD sets the supported Python range to `>=3.12,<3.13`. Use Python 3.12.16 for artifact builds and installed-wheel acceptance.
- Start implementation only after explicit approval of this revised plan.
- Import name remains `xpwebapi`; never introduce `src.xpwebapi` imports.
- Console command remains `xpwebapi-capture = "xpwebapi.capture_cli:main"`.
- Wheel members remain under `xpwebapi/`; sdist package members move under `src/xpwebapi/`.
- Preserve public API, network behavior, schemas, dependency metadata, and upstream attribution.
- Keep `examples/` unchanged.
- Use Python's `unittest` framework exclusively.
- Never force-push, tag, publish a package, or create a release while executing this plan.

---

### Task 0: Capture the flat-layout 5.0.0 baseline

- [ ] **Step 1: Identify the preparation checkpoint**

Use a clean, isolated worktree at the 5.0.0 preparation checkpoint identified
in the [handoff](../handoffs/2026-11-22-xpwebapi-5-preparation.md). Record its
SHA as `$migrationBase`. It must still have `xpwebapi/` at the root and agree
on version 5.0.0 across package, runtime, lock, changelog, and CI.

- [ ] **Step 2: Build the baseline artifacts before editing the checkout**

Run with Python 3.12.16 and retain the artifacts outside the checkout. Use the
same uv and build backend for the migration candidate.

```powershell
if (@(git status --porcelain).Count -ne 0) { throw 'The baseline checkout is dirty' }
$migrationBase = git rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'Cannot identify the preparation checkpoint' }
$baselineArtifacts = Join-Path ([System.IO.Path]::GetTempPath()) ("xpwebapi-layout-base-" + [guid]::NewGuid())
uv build --python 3.12.16 --no-sources --out-dir $baselineArtifacts
if ($LASTEXITCODE -ne 0) { throw 'Baseline build failed' }
uv run --frozen python tools/release.py check-dist $baselineArtifacts
if ($LASTEXITCODE -ne 0) { throw 'Baseline archive validation failed' }
```

Expected: the validated 5.0.0 wheel and source archive contain the flat-layout
package payload for the comparison in Task 3.

---

### Task 1: Establish the source-layout and quality-path contract

**Files:**
- Modify: `tests/test_release_metadata.py`
- Modify: `tests/test_quality_tool.py`
- Modify: `tests/test_type_annotations.py`
- Modify: `pyproject.toml`
- Modify: `tools/quality.py`
- Modify: `.pre-commit-config.yaml` and the repo-local quality and git-sync skills where they name the physical package path
- Move: `xpwebapi/` to `src/xpwebapi/`

**Interfaces:**
- Consumes: distribution/import identity `xpwebapi` and pending version `5.0.0`.
- Produces: physical source root `src/xpwebapi`, build-backend root `src`, and `tools.quality.SOURCE_PATH = "src/xpwebapi"`.

- [ ] **Step 1: Add the failing layout and installed-import contract**

Add this test to `ReleaseMetadataTests`:

```python
def test_runtime_package_uses_the_src_layout(self) -> None:
    self.assertEqual("src", PROJECT["tool"]["uv"]["build-backend"]["module-root"])
    self.assertTrue((REPO_ROOT / "src/xpwebapi/__init__.py").is_file())
    self.assertFalse((REPO_ROOT / "xpwebapi").exists())

    module_path = Path(xpwebapi.__file__).resolve()
    self.assertTrue(module_path.is_relative_to((REPO_ROOT / "src/xpwebapi").resolve()))
```

- [ ] **Step 2: Add the failing quality-path contract**

Add to `TestQualityTool`:

```python
def test_quality_targets_the_src_package(self) -> None:
    commands = " ".join(" ".join(step.command) for steps in quality.COMMANDS.values() for step in steps)
    self.assertEqual("src/xpwebapi", quality.SOURCE_PATH)
    self.assertEqual(("src/xpwebapi", "tests", "tools"), quality.SOURCE_PATHS)
    self.assertIn("src/xpwebapi", commands)
```

Update the tracked-path fixture output and expectations from `xpwebapi/ws.py`
to `src/xpwebapi/ws.py`, and use `tracked_paths=("src/xpwebapi", "tests")`.

- [ ] **Step 3: Run focused tests and verify the expected failures**

Run:

```powershell
uv run --frozen python -m unittest tests.test_release_metadata tests.test_quality_tool tests.test_type_annotations -v
```

Expected: FAIL because `module-root` is empty, `src/xpwebapi` is absent, the
root package exists, and quality/type checks still target `xpwebapi`.

- [ ] **Step 4: Move the tracked package and change the build root**

Run:

```powershell
New-Item -ItemType Directory -Path src
git mv xpwebapi src/xpwebapi
```

Change the build configuration to:

```toml
[tool.uv.build-backend]
module-root = "src"
```

- [ ] **Step 5: Centralize the physical quality path**

At the top of `tools/quality.py`, define:

```python
SOURCE_PATH = "src/xpwebapi"
SOURCE_PATHS = (SOURCE_PATH, "tests", "tools")
```

Use `SOURCE_PATHS` for source-tree Ruff and Vulture checks. Replace physical
`"xpwebapi"` arguments used by Bandit, interrogate, lizard, cohesion, wily, and
xenon with `SOURCE_PATH`. Retarget the lizard and cohesion hook commands and
the repo-local skill commands. Keep distribution names, import names, logger
names, and schema package names unchanged.

- [ ] **Step 6: Retarget source-inspection tests**

In `tests/test_type_annotations.py`, set:

```python
SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "xpwebapi"
```

Search tests, tools, workflows, and active documentation for other values used
as physical checkout paths. Change only those that open or enumerate files;
leave semantic values such as package names and imports unchanged.

- [ ] **Step 7: Synchronize the editable installation and rerun focused tests**

Run:

```powershell
uv sync --frozen
uv run --frozen python -m unittest tests.test_release_metadata tests.test_quality_tool tests.test_type_annotations -v
```

Expected: PASS; `xpwebapi.__file__` resolves beneath `src/xpwebapi`.

Continue to Task 2 before committing. The full quality gate runs the release
tests, which still expect the old package location at this point.

---

### Task 2: Preserve version, schema, wheel, and source-archive contracts

**Files:**
- Modify: `tools/release.py`
- Modify: `tests/test_release_tool.py`
- Modify: `tools/installed_smoke.py` only if a physical checkout path is found

**Interfaces:**
- Consumes: physical source root `REPO_ROOT / "src" / "xpwebapi"` from Task 1.
- Produces: unchanged wheel schema paths `xpwebapi/schemas/...` and sdist schema paths `src/xpwebapi/schemas/...`.

- [ ] **Step 1: Change the version-source fixtures before implementation**

In the temporary repositories created by
`test_tag_rejects_runtime_version_that_differs_from_project` and
`test_missing_runtime_version_declaration_is_rejected`, create
`root / "src" / "xpwebapi"` and place `__init__.py` there. Keep the patched
`release.REPO_ROOT` behavior unchanged.

- [ ] **Step 2: Change source-archive fixtures to the new package path**

In `write_archives`, change source schema members to:

```python
**{f"{prefix}/src/xpwebapi/schemas/{name}": b"{}" for name in SCHEMAS}
```

Change `test_missing_source_members_are_rejected` to require the same
`src/xpwebapi/schemas/...` members. Wheel members remain
`xpwebapi/schemas/...`.

- [ ] **Step 3: Run release tests and verify the expected failures**

Run:

```powershell
uv run --frozen python -m unittest tests.test_release_tool -v
```

Expected: FAIL because `runtime_version()` still reads
`REPO_ROOT / "xpwebapi/__init__.py"` and `check_dist()` still expects root-level
sdist schema members.

- [ ] **Step 4: Retarget runtime version and sdist schema validation**

In `tools/release.py`, have `runtime_version()` resolve
`REPO_ROOT / "src" / "xpwebapi" / "__init__.py"` at call time so the fixture's
`REPO_ROOT` override still works. In the sdist
required-member set, use:

```python
*(f"{prefix}/src/xpwebapi/schemas/{name}" for name in SCHEMAS)
```

Do not change the wheel required-member set or installed schema resource names.

- [ ] **Step 5: Audit remaining physical source paths**

Run:

```powershell
rg -n --no-heading 'REPO_ROOT / "xpwebapi"|parents\[1\] / "xpwebapi"|Path\("xpwebapi"\)' tools tests .github
```

Expected: no active physical source-root reference remains. Review every match
before changing it; semantic package-name strings remain valid.

- [ ] **Step 6: Run focused release and installed-resource tests**

Run:

```powershell
uv run --frozen python -m unittest tests.test_release_tool tests.test_release_metadata -v
```

Expected: PASS, including metadata, schema, archive-safety, and installed-smoke
unit contracts.

Continue to Task 3 for the full quality gate before committing the migration.

---

### Task 3: Verify the staged migration and its distributions

- [ ] **Step 1: Stage and identify the migration candidate**

Stage the reviewed migration files. `git mv` already stages the tracked
package move. Review `git diff --cached` and check that the index and checkout
agree before running verification.

```powershell
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'Staged diff check failed' }
git diff --quiet --
if ($LASTEXITCODE -ne 0 -or @(git ls-files --others --exclude-standard).Count -ne 0) {
    throw 'The checkout contains changes outside the staged candidate'
}
$candidateTree = git write-tree
if ($LASTEXITCODE -ne 0) { throw 'Cannot identify the staged tree' }
$baselinePackage = git rev-parse "${migrationBase}:xpwebapi"
if ($LASTEXITCODE -ne 0) { throw 'Cannot identify the baseline package tree' }
$candidatePackage = git rev-parse "${candidateTree}:src/xpwebapi"
if ($LASTEXITCODE -ne 0 -or $candidatePackage -ne $baselinePackage) {
    throw 'Tracked package files differ from the flat-layout baseline'
}
```

- [ ] **Step 2: Run the complete repository hygiene gate**

Run:

```powershell
uv sync --frozen
if ($LASTEXITCODE -ne 0) { throw 'Environment sync failed' }
uv run --frozen python .codex/skills/hygiene/scripts/hygiene.py
if ($LASTEXITCODE -ne 0) { throw 'Repository hygiene failed' }
uv run --frozen mkdocs build --strict
if ($LASTEXITCODE -ne 0) { throw 'Strict documentation build failed' }
```

Expected: lockfile, full quality, pre-commit, and documentation checks pass.

- [ ] **Step 3: Build and validate the candidate distributions**

Run:

```powershell
$artifactRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("xplane-webapi-src-layout-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $artifactRoot
uv build --python 3.12.16 --no-sources --out-dir $artifactRoot
if ($LASTEXITCODE -ne 0) { throw 'Candidate build failed' }
$archives = @(Get-ChildItem -LiteralPath $artifactRoot -File | Where-Object Name -Match '\.(whl|tar\.gz)$' | Select-Object -ExpandProperty FullName)
uv run --frozen twine check --strict @archives
if ($LASTEXITCODE -ne 0) { throw 'Twine validation failed' }
uv run --frozen python tools/release.py check-dist $artifactRoot
if ($LASTEXITCODE -ne 0) { throw 'Candidate archive validation failed' }
```

Expected: one wheel and one sdist pass the repository validator; wheel schemas
remain under `xpwebapi/schemas`, and sdist schemas are under
`src/xpwebapi/schemas`.

- [ ] **Step 4: Compare archived package paths and bytes**

Reject duplicate member paths in each archive before hashing its package
files. Compare each regular package file by path and SHA-256. In the source
archive comparison, prepend `src/` to each baseline package path.

```powershell
@'
from collections import Counter
from hashlib import sha256
from pathlib import Path, PurePosixPath
import sys
import tarfile
import zipfile

before, after = map(Path, sys.argv[1:])
wheel = "xpwebapi-5.0.0-py3-none-any.whl"
sdist = "xpwebapi-5.0.0.tar.gz"
package_roots = ("xpwebapi/", "src/xpwebapi/")


def require_unique_paths(path, names):
    counts = Counter(map(PurePosixPath, names))
    duplicates = sorted(str(name) for name, count in counts.items() if count > 1)
    if duplicates:
        sys.exit(f"{path.name} contains duplicate archive paths: {', '.join(duplicates)}")


def wheel_payload(path):
    with zipfile.ZipFile(path) as archive:
        require_unique_paths(path, archive.namelist())
        return {
            entry.filename: sha256(archive.read(entry)).hexdigest()
            for entry in archive.infolist()
            if not entry.is_dir() and entry.filename.startswith(package_roots)
        }


def source_payload(path):
    payload = {}
    with tarfile.open(path, "r:gz") as archive:
        entries = archive.getmembers()
        require_unique_paths(path, (entry.name for entry in entries))
        for entry in entries:
            name = entry.name.split("/", 1)[-1]
            if entry.isfile() and name.startswith(package_roots):
                with archive.extractfile(entry) as stream:
                    payload[name] = sha256(stream.read()).hexdigest()
    return payload


def compare(label, expected, actual):
    missing = sorted(expected.keys() - actual.keys())
    unexpected = sorted(actual.keys() - expected.keys())
    changed = sorted(name for name in expected.keys() & actual.keys() if expected[name] != actual[name])
    if not expected or missing or unexpected or changed:
        sys.exit(f"{label} mismatch: missing={missing}, unexpected={unexpected}, changed={changed}")
    print(f"{label}: matched {len(expected)} package files")


compare("wheel", wheel_payload(before / wheel), wheel_payload(after / wheel))
baseline_source = source_payload(before / sdist)
expected_source = {f"src/{name}": digest for name, digest in baseline_source.items()}
compare("source archive", expected_source, source_payload(after / sdist))
'@ | uv run --frozen python - $baselineArtifacts $artifactRoot
if ($LASTEXITCODE -ne 0) { throw 'Archive comparison failed' }
```

Expected: identical wheel package paths and bytes, or a failure listing the
affected files. The source archive must report the same package bytes under
the relocated prefix and no package files under the former prefix.

- [ ] **Step 5: Run the installed smoke test on Python 3.12.16**

Run:

```powershell
$repoRoot = git rev-parse --show-toplevel
$wheel = Get-ChildItem -LiteralPath $artifactRoot -Filter 'xpwebapi-5.0.0-py3-none-any.whl' | Select-Object -ExpandProperty FullName
$venv = Join-Path $artifactRoot 'smoke'
uv venv --python 3.12.16 $venv
if ($LASTEXITCODE -ne 0) { throw 'Smoke environment creation failed' }
$python = Join-Path $venv 'Scripts\python.exe'
uv pip install --python $python $wheel
if ($LASTEXITCODE -ne 0) { throw 'Candidate wheel installation failed' }
Push-Location $artifactRoot
try {
    & $python -I (Join-Path $repoRoot 'tools\installed_smoke.py') '5.0.0'
    $smokeExit = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($smokeExit -ne 0) { exit $smokeExit }
```

Expected: the isolated interpreter imports the installed wheel outside the
checkout, loads all schemas, and executes the environment-local capture command.

- [ ] **Step 6: Recheck the tree and commit when authorized**

```powershell
git diff --quiet --
if ($LASTEXITCODE -ne 0 -or @(git ls-files --others --exclude-standard).Count -ne 0) {
    throw 'The checkout changed during verification'
}
$stagedTree = git write-tree
if ($LASTEXITCODE -ne 0 -or $stagedTree -ne $candidateTree) {
    throw 'The staged candidate changed during verification'
}
git commit -m "build: migrate runtime package to src layout"
if ($LASTEXITCODE -ne 0) { throw 'Migration commit failed' }
$committedTree = git rev-parse 'HEAD^{tree}'
if ($LASTEXITCODE -ne 0 -or $committedTree -ne $candidateTree) {
    throw 'The committed tree differs from the verified candidate'
}
```

If the candidate changes, repeat verification on the new staged tree. Record
the verified tree ID and, when committed, the migration commit SHA.

### Task 4: Record verification and close the maintenance increment

- [ ] **Step 1: Update the existing project records**

Record the baseline SHA, candidate tree ID, migration commit if available,
exact commands, test counts, artifact names, payload comparison, Python
version, and publication status in the plan's completion evidence. Mark the
plan `completed` and the design `implemented` after verification. Reconcile
the issue index and release-scope record in `BACKLOG.md`. Run
`git diff --check` and strict MkDocs on the closeout edits. Commit the
documentation updates separately when authorized.

- [ ] **Step 2: Confirm integration before closing issue #2**

Repository synchronization is a separate `$git-sync` action after review.
After synchronization, set `$migrationCommit` to the migration commit SHA
recorded in Step 1. Fetch `origin` and confirm that commit is an ancestor of
`origin/main`.

```powershell
git fetch origin
if ($LASTEXITCODE -ne 0) { throw 'Cannot verify the current origin/main' }
git merge-base --is-ancestor $migrationCommit origin/main
if ($LASTEXITCODE -ne 0) { throw 'The verified migration commit is not on origin/main' }
```

Close issue #2 with the verified commit and acceptance evidence once the
remote check passes and the issue update is authorized.

## Plan audit — 2026-11-22

### Release intent and work-item scope

| Check | Result | Evidence |
| --- | --- | --- |
| Physical move preserves public and installed behavior | Aligned | [Source-layout design](../specs/2026-08-09-src-layout-migration-design.md) and [issue #2](https://github.com/tvproductions/xplane-webapi/issues/2) |
| Python acceptance target | Aligned | [Issue #2](https://github.com/tvproductions/xplane-webapi/issues/2), the design, and this plan use Python 3.12.16 for the [5.0.0 PRD](../specs/2026-11-22-xpwebapi-5.0.0-prd.md). |

### Work-item scope and plan

| Check | Result | Evidence |
| --- | --- | --- |
| Source tools, installed imports, wheel and sdist paths | Aligned | Tasks 1–2 retarget checkout paths while preserving wheel members and imports. |
| Verified tree and commit | Aligned | Task 0 identifies a clean 5.0.0 preparation checkpoint. Task 3 verifies the staged migration candidate and compares the committed tree with the verified tree. |
| Archive payload preservation | Aligned | Task 3 rejects duplicate archive paths before comparing package paths and hashes with the flat-layout 5.0.0 archives. |
| Release checks and closeout | Aligned | Task 3 runs hygiene, strict docs, archive validation, and isolated wheel smoke. Task 4 verifies integration on `origin/main` before issue closeout. |
| Implementation approval | Missing | This revised edition has no work-item approval yet. |

Approve this edition of the plan before implementation. Task 0 starts from the
5.0.0 preparation checkpoint once it is available.
