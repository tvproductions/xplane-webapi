# CI/CD Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make GitHub Actions run the repo's explicit quality gates, preserve docs deployment, validate package builds, and defer PyPI publishing until package identity is decided.

**Architecture:** Keep one GitHub Actions workflow with separate `quality` and `docs` jobs. The `quality` job runs explicit `uv` commands for lint, format check, type check, unit tests, and package build validation. The `docs` job runs only after quality succeeds on pushes to `main` and keeps `mkdocs gh-deploy --force`.

**Tech Stack:** GitHub Actions, Python 3.12, `uv`, `ruff`, `ty`, stdlib `unittest`, MkDocs, `uv_build`, pre-commit.

## Global Constraints

- Use `unittest` as the only test runner.
- Preserve docs deployment with `mkdocs gh-deploy --force` on pushes to `main`.
- Do not rename `[project].name` from `xpwebapi`.
- Do not add PyPI credentials, GitHub OIDC publishing permissions, or publish commands.
- Keep default workflow permissions read-only; grant `contents: write` only to the docs deployment job.
- Keep `.pre-commit-config.yaml` available for local development.

---

## File Structure

- Modify `.github/workflows/ci.yml`: replace the current workflow with explicit quality/build checks and a preserved docs deployment job.
- Modify `pyproject.toml`: add the MkDocs plugin that `mkdocs.yml` requires but the project metadata does not currently declare.
- Modify `uv.lock`: refresh after the docs dependency metadata change.
- Modify `BACKLOG.md`: mark CI checks and pre-commit complete while recording PyPI publishing as deferred.
- Do not modify `.pre-commit-config.yaml` unless implementation discovers it is broken; the current config already provides local hooks.

### Task 1: Declare Required Docs Deployment Dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: `mkdocs.yml` plugin entry `git-revision-date-localized`.
- Produces: a frozen `uv` environment that can run `uv run mkdocs gh-deploy --force` without ad hoc pip installs.

- [ ] **Step 1: Add the missing docs plugin dependency**

In `pyproject.toml`, update `[dependency-groups].dev` so this dependency appears with the other MkDocs dependencies:

```toml
    "mkdocs-git-revision-date-localized-plugin",
```

The resulting MkDocs-related block should include:

```toml
    "mkdocs",
    "mkdocs-git-revision-date-localized-plugin",
    "mkdocs-material",
    "mkdocstrings",
    "mkdocstrings-python",
```

- [ ] **Step 2: Refresh the lock file**

Run:

```powershell
uv lock
```

Expected: `uv.lock` updates successfully and contains `mkdocs-git-revision-date-localized-plugin`.

- [ ] **Step 3: Verify docs dependencies are tracked**

Run:

```powershell
rg -n "mkdocs-git-revision-date-localized-plugin|git-revision-date-localized" pyproject.toml uv.lock mkdocs.yml
```

Expected: matches appear in `pyproject.toml`, `uv.lock`, and `mkdocs.yml`.

- [ ] **Step 4: Commit dependency alignment**

Run:

```powershell
git add pyproject.toml uv.lock
git commit -m "build: declare docs deployment dependency"
```

### Task 2: Replace CI Workflow With Explicit Quality And Build Checks

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: project commands `uv sync --frozen`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, `uv run python -m unittest discover -v`, `uv build`, and `uv run mkdocs gh-deploy --force`.
- Produces: GitHub Actions workflow with read-only default permissions and docs-only write permissions.

- [ ] **Step 1: Replace the workflow content**

Replace `.github/workflows/ci.yml` with:

```yaml
name: ci

on:
  push:
    branches:
      - main
  pull_request:

permissions:
  contents: read

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install uv
      - run: uv sync --frozen
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run ty check
      - run: uv run python -m unittest discover -v
      - run: uv build

  docs:
    needs: quality
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    permissions:
      contents: write
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install uv
      - run: uv sync --frozen
      - run: uv run mkdocs gh-deploy --force
```

- [ ] **Step 2: Inspect for intentionally absent publish configuration**

Run:

```powershell
rg -n "publish|PYPI|id-token|trusted" .github\workflows\ci.yml
```

Expected: no matches.

- [ ] **Step 3: Inspect for explicit quality commands**

Run:

```powershell
rg -n "ruff check|ruff format --check|ty check|unittest discover|uv build|mkdocs gh-deploy|contents: write|contents: read" .github\workflows\ci.yml
```

Expected: matches for every command and both permission levels.

- [ ] **Step 4: Commit the workflow change**

Run:

```powershell
git add .github/workflows/ci.yml
git commit -m "ci: run explicit quality checks"
```

### Task 3: Validate Locally And Update The Backlog

**Files:**
- Modify: `BACKLOG.md`

**Interfaces:**
- Consumes: completed Tasks 1 and 2.
- Produces: backlog text that marks CI checks, pre-commit, docs preservation, and build validation complete while deferring PyPI publishing.

- [ ] **Step 1: Run the CI-equivalent local checks**

Run:

```powershell
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run python -m unittest discover -v
uv build
```

Expected:

```text
ruff check: All checks passed.
ruff format --check: no files would be reformatted.
ty check: no errors.
unittest: OK.
uv build: source distribution and wheel are built in dist/.
```

- [ ] **Step 2: Update the backlog item**

In `BACKLOG.md`, replace the current CI/CD section:

```markdown
### [ ] CI/CD pipeline
- [ ] GitHub Actions: lint (`ruff check`), format (`ruff format --check`), type check (`ty check`), test (`python -m unittest discover -v`)
- [ ] Publish to PyPI on tagged release via `uv publish`
- [ ] Pre-commit hooks for local development
```

with:

```markdown
### [x] CI/CD pipeline
- [x] GitHub Actions: lint (`ruff check`), format (`ruff format --check`), type check (`ty check`), test (`python -m unittest discover -v`), and package build validation (`uv build`)
- [ ] Publish to PyPI on tagged release via `uv publish` — deferred pending upstream PR outcome and package-name strategy
- [x] Pre-commit hooks for local development
- [x] Preserve MkDocs deployment on pushes to `main`
```

- [ ] **Step 3: Verify the backlog records the deferral**

Run:

```powershell
rg -n "CI/CD pipeline|deferred pending upstream PR outcome|uv build|Preserve MkDocs" BACKLOG.md
```

Expected: matches show the top-level item complete, the PyPI publishing subitem still unchecked and deferred, build validation listed, and MkDocs deployment listed.

- [ ] **Step 4: Re-run the unit test suite after the docs-only backlog edit**

Run:

```powershell
uv run python -m unittest discover -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the backlog update**

Run:

```powershell
git add BACKLOG.md
git commit -m "docs: complete ci cd backlog item"
```

### Task 4: Final Verification And Status

**Files:**
- Inspect only unless a validation failure identifies a needed fix.

**Interfaces:**
- Consumes: completed Tasks 1 through 3.
- Produces: final validation evidence and a clean working tree.

- [ ] **Step 1: Run final validation**

Run:

```powershell
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run python -m unittest discover -v
uv build
```

Expected:

```text
ruff check: All checks passed.
ruff format --check: no files would be reformatted.
ty check: no errors.
unittest: OK.
uv build: source distribution and wheel are built in dist/.
```

- [ ] **Step 2: Inspect final workflow for publish configuration absence**

Run:

```powershell
rg -n "publish|PYPI|id-token|trusted" .github\workflows BACKLOG.md pyproject.toml
```

Expected: matches may appear only in `BACKLOG.md` text describing deferred PyPI publishing and in the spec/plan if those files are included manually. No matches should appear in `.github/workflows/ci.yml` or `pyproject.toml`.

- [ ] **Step 3: Inspect final git status and recent commits**

Run:

```powershell
git status --short
git log --oneline -5
```

Expected: working tree is clean. Recent commits include the CI/CD design spec, docs dependency declaration, workflow update, and backlog completion.

## Self-Review

- Spec coverage: Task 1 covers docs deployment dependencies; Task 2 covers explicit CI commands, build validation, docs deployment, and least-privilege permissions; Task 3 covers backlog deferral language and pre-commit status; Task 4 covers final validation and publish-configuration absence.
- Placeholder scan: no placeholder implementation steps are intentionally left.
- Type consistency: no new Python interfaces are introduced; commands and workflow job names are consistent across tasks.
