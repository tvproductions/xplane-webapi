# xplane-webapi Source-Layout Migration Implementation Plan

- **Governance:** active
- **Status:** draft
- **Date:** 2026-08-09
- **Source specification:** `docs/superpowers/specs/2026-08-09-src-layout-migration-design.md`
- **Approval:** —
- **Completion evidence:** —

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the forked xplane-webapi runtime package to `src/xpwebapi` while preserving public behavior, packaged schemas, command entry points, and release artifacts.

**Architecture:** Separate physical checkout paths from installed module paths. Source-aware tools target `src/xpwebapi`; imports and wheel members remain `xpwebapi`; source-archive package members gain the `src/` prefix. Preserve the upstream-derived package bytes and adjust only path-sensitive configuration, tools, tests, and documentation.

**Tech Stack:** Python 3.12–3.13, `uv`/`uv_build`, Python `unittest`, Ruff, ty, coverage, Bandit, MkDocs, and repository-owned release tooling.

## Global Constraints

- Governing specification: `docs/superpowers/specs/2026-08-09-src-layout-migration-design.md`.
- Import name remains `xpwebapi`; never introduce `src.xpwebapi` imports.
- Console command remains `xpwebapi-capture = "xpwebapi.capture_cli:main"`.
- Wheel members remain under `xpwebapi/`; sdist package members move under `src/xpwebapi/`.
- Preserve public API, network behavior, schemas, dependency metadata, and upstream attribution.
- Keep `examples/` unchanged.
- Use Python's `unittest` framework exclusively.
- Never force-push, tag, publish a package, or create a release while executing this plan.

---

### Task 1: Establish the source-layout and quality-path contract

**Files:**
- Modify: `tests/test_release_metadata.py`
- Modify: `tests/test_quality_tool.py`
- Modify: `tests/test_type_annotations.py`
- Modify: `pyproject.toml`
- Modify: `tools/quality.py`
- Move: `xpwebapi/` to `src/xpwebapi/`

**Interfaces:**
- Consumes: distribution/import identity `xpwebapi` and version `4.0.0`.
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
uv run python -m unittest tests.test_release_metadata tests.test_quality_tool tests.test_type_annotations -v
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

Replace physical `"xpwebapi"` arguments used by Bandit, interrogate, lizard,
cohesion, wily, and xenon with `SOURCE_PATH`. Keep distribution names, import
names, logger names, and schema package names unchanged.

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
uv run python -m unittest tests.test_release_metadata tests.test_quality_tool tests.test_type_annotations -v
```

Expected: PASS; `xpwebapi.__file__` resolves beneath `src/xpwebapi`.

- [ ] **Step 8: Commit the source-layout foundation**

Run:

```powershell
git add -- pyproject.toml src/xpwebapi tools/quality.py tests/test_release_metadata.py tests/test_quality_tool.py tests/test_type_annotations.py
git diff --cached --check
git commit -m "build: move runtime package under src"
```

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
uv run python -m unittest tests.test_release_tool -v
```

Expected: FAIL because `runtime_version()` still reads
`REPO_ROOT / "xpwebapi/__init__.py"` and `check_dist()` still expects root-level
sdist schema members.

- [ ] **Step 4: Retarget runtime version and sdist schema validation**

In `tools/release.py`, define:

```python
SOURCE_ROOT = REPO_ROOT / "src" / "xpwebapi"
```

Change `runtime_version()` to read `SOURCE_ROOT / "__init__.py"`. In the sdist
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
uv run python -m unittest tests.test_release_tool tests.test_release_metadata -v
```

Expected: PASS, including metadata, schema, archive-safety, and installed-smoke
unit contracts.

- [ ] **Step 7: Commit artifact-path preservation**

Run:

```powershell
git add -- tools/release.py tools/installed_smoke.py tests/test_release_tool.py tests/test_release_metadata.py
git diff --cached --check
git commit -m "build: preserve src layout artifact contracts"
```

If `tools/installed_smoke.py` has no physical checkout-path change, omit it from
the staged path list.

---

### Task 3: Verify distributions and close the maintenance increment

**Files:**
- Create: `.superpowers/sdd/2026-08-09-src-layout-migration/verification.md`
- Modify: `BACKLOG.md`
- Modify: `docs/superpowers/specs/2026-08-09-src-layout-migration-design.md`
- Modify: `docs/superpowers/plans/2026-08-09-src-layout-migration.md`

**Interfaces:**
- Consumes: passing source-layout and artifact contracts from Tasks 1–2.
- Produces: committed verification evidence and a completed maintenance record.

- [ ] **Step 1: Run the complete repository hygiene gate**

Run:

```powershell
uv sync --frozen
uv run python .codex/skills/hygiene/scripts/hygiene.py
uv run mkdocs build --strict
```

Expected: lockfile, full quality, pre-commit, and documentation checks pass.

- [ ] **Step 2: Build and validate fresh distributions**

Run:

```powershell
$artifactRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("xplane-webapi-src-layout-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $artifactRoot
uv build --no-sources --out-dir $artifactRoot
uv run python tools/release.py check-dist $artifactRoot
```

Expected: one wheel and one sdist pass the repository validator; wheel schemas
remain under `xpwebapi/schemas`, and sdist schemas are under
`src/xpwebapi/schemas`.

- [ ] **Step 3: Run installed smoke tests on supported Python versions**

Run:

```powershell
$repoRoot = git rev-parse --show-toplevel
$wheel = Get-ChildItem -LiteralPath $artifactRoot -Filter 'xpwebapi-4.0.0-py3-none-any.whl' | Select-Object -ExpandProperty FullName
foreach ($version in @('3.12', '3.13')) {
    $venv = Join-Path $artifactRoot "venv-$version"
    uv venv --python $version $venv
    $python = Join-Path $venv 'Scripts\python.exe'
    uv pip install --python $python $wheel
    Push-Location $artifactRoot
    & $python (Join-Path $repoRoot 'tools\installed_smoke.py') '4.0.0'
    Pop-Location
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
```

Expected: both interpreters import the installed wheel outside the checkout,
load all schemas, and execute the environment-local capture command.

- [ ] **Step 4: Record verification and update project state**

Create the verification report with exact commands, test counts, built artifact
names, supported Python versions, and confirmation that no tag, package
publication, or release occurred.

Mark the plan `completed` with the verification link and the specification
`implemented`. Add this exact section immediately after the backlog title:

```markdown
## Active maintenance

### [x] Migrate the runtime package to the src layout

- [x] Runtime sources exist only under `src/xpwebapi`.
- [x] Quality and release tooling use the new physical source root.
- [x] Wheel paths remain stable and source-archive paths include `src/`.
- [x] Full quality, documentation, artifact, and installed-smoke checks pass.
```

- [ ] **Step 5: Run final scope checks**

Run:

```powershell
git diff --check
uv run python -m unittest tests.test_release_metadata tests.test_quality_tool tests.test_type_annotations tests.test_release_tool -v
git status --short
```

Expected: checks pass, `examples/` is untouched, and only migration-scoped
files are modified.

- [ ] **Step 6: Commit the completed migration**

Run:

```powershell
git add -- .superpowers/sdd/2026-08-09-src-layout-migration/verification.md BACKLOG.md docs/superpowers/specs/2026-08-09-src-layout-migration-design.md docs/superpowers/plans/2026-08-09-src-layout-migration.md
git diff --cached --check
git commit -m "docs: record src layout migration evidence"
git status -sb
```

Expected: clean worktree with the migration implemented and locally verified.
Repository synchronization is a separate `$git-sync` action after review.
