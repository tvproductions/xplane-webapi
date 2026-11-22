# Skills-first Adoption Implementation Plan

> **For agentic workers:** Execute inline with the executing-plans workflow;
> use verification-before-completion and the project quality contract.

**Goal:** Adopt the approved skills-first stack with lite and Python 3.12 only.

**Architecture:** Native plugins own upstream skills. Project configuration pins
sources; project instructions own runtime and quality exceptions. Preserve the
working checkout and pre-existing BACKLOG.md changes.

**Tech Stack:** Python 3.12.15, uv, unittest, Ruff, ty, Codex native plugins.

## Global constraints

- requires-python is `>=3.12,<3.13`; exact execution pin is `3.12.15`.
- Preserve application dependencies, operational skills and quality thresholds.
- GovZero profile is lite; Backplane remains disabled.
- Starter is v0.3.0 at `a7550a6e29b88349041e70e3dbba4778be4b8235`.
- Preserve user BACKLOG.md edits and upstream caches; no publishing.

## Task 1: Python support and release validation

- [x] Update existing tests in tests/test_release_metadata.py,
  tests/test_release_tool.py and tests/test_documentation.py to require Python
  3.12 only, classifiers and CI selectors at 3.12.15. Add an archive rejection
  case for the former `>=3.12,<3.14` metadata contract.
- [x] Run `uv run --python 3.12.15 python -m unittest
  tests.test_release_metadata tests.test_release_tool tests.test_documentation -q`
  before implementation and inspect assertion failures for the changed contracts.
- [x] Update pyproject.toml, .python-version, tools/release.py,
  .github/workflows/ci.yml, .github/workflows/release.yml and README.md.
  Set Ruff target-version to py312 and ty environment.python-version to 3.12.
- [x] Run `uv lock --python 3.12.15` and `uv sync --frozen --python 3.12.15`.
  Preserve existing locked packages unless resolution requires otherwise.
- [x] Repeat focused tests; all tests must pass.

## Task 2: Native stack adoption and project policy

- [x] Compare local copied Superpowers skill bodies, preserving differences
  outside discovery in .worktrees/adoption-recovery before retiring copies.
  Recheck and remove only empty legacy gzs directory trees.
- [x] Create .codex/config.toml, .skills-first/bundle.lock.json and
  AGENTS.skills-first.md using the reviewed starter catalog and corrected starter
  repository URL. Link the fragment from AGENTS.md. Keep the upstream checkout
  untouched; document the helper-origin and existing-source reconciliation.
- [x] Run the upstream project_settings.py initialize/select helper with an
  explicit project path and `--profile lite`; inspect its resulting JSON.
- [x] Install the selected native pair, preserving unrelated global enablement
  and disabling the old gz-skills source only in this project. Inspect native
  inventory and source pins. Keep Backplane disabled.
- [x] Record provenance, independent update/defer decisions, Python 3.12 policy,
  existing quality-gate exception, rollback and fresh-session loading limits in
  docs/superpowers/skills-first-adoption.md.

## Task 3: Verification and handoff

- [x] Run `uv run --frozen python .codex/skills/hygiene/scripts/hygiene.py` and
  `uv run --frozen mkdocs build --strict`; inspect exit codes and test counts.
- [x] Build into an isolated ignored distribution directory with `uv build
  --no-sources --out-dir .worktrees/adoption-dist`; validate archives using
  `uv run --frozen python tools/release.py check-dist .worktrees/adoption-dist`.
- [x] Install the wheel in an isolated 3.12.15 environment and run
  tools/installed_smoke.py from outside the source tree.
- [x] Review final diff and validate JSON/TOML, component pins, lite, Backplane
  disablement, current interpreter and user-change preservation.
- [x] Report actual checks; fresh-session discovery is pending until observed.

Execution completed on 2026-10-11. `uv add --dev twine --python 3.12.15`
regenerated the lock; full hygiene verified it offline. Native fresh-session
discovery requires a restart and is explicitly UNKNOWN in the adoption record.
