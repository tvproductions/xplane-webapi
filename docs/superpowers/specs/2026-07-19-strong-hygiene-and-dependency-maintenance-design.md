# Strong Hygiene and Dependency Maintenance Design

**Status:** Approved for implementation on 2026-07-19.

## Context

The repository already has a comprehensive quality runner in `tools/quality.py`
and a documentation-only hygiene skill. Dependency freshness is currently an
ad hoc inquiry: `uv.lock` can be valid while direct dependencies are behind
versions available from PyPI. The neighboring `q4xpcc` repository demonstrates
a stronger pattern in which a project-local hygiene skill is backed by a
standard-library script and `unittest` contract tests.

The repository needs both local, agent-invoked dependency inquiry and recurring
GitHub-hosted dependency maintenance. These surfaces must complement the
existing quality runner rather than duplicate it.

## Goals

- Refresh all currently stale direct runtime and development dependencies.
- Turn the hygiene skill into an executable, tested repository contract.
- Keep the normal hygiene gate deterministic and usable without network access.
- Provide an explicit local dependency-freshness inquiry backed by `uv` and
  PyPI metadata.
- Configure Dependabot to propose grouped `uv` dependency updates weekly.
- Preserve the repository's exclusive use of standard-library `unittest`.

## Non-goals

- Do not replace or duplicate `tools/quality.py`.
- Do not add an alternate Python test runner.
- Do not make routine offline quality checks depend on PyPI availability.
- Do not silently mutate dependency constraints or the lockfile from the
  hygiene checker.
- Do not add unrelated source refactors or package changes.

## Dependency Refresh

Update the direct dependency set identified on 2026-07-19:

| Dependency | Locked version | Target version | Treatment |
| --- | ---: | ---: | --- |
| `websockets` | 16.0 | 16.1.1 | Refresh within the existing constraint |
| `packaging` | 25.0 | 26.2 | Raise the direct constraint to the 26.x line |
| `coverage` | 7.14.1 | 7.15.2 | Refresh development dependency |
| `mkdocs-material` | 9.7.6 | 9.7.7 | Refresh development dependency |
| `mkdocstrings` | 1.0.4 | 1.0.6 | Refresh development dependency |
| `ruff` | 0.15.18 | 0.15.22 | Refresh development dependency |
| `ty` | 0.0.51 | 0.0.61 | Refresh development dependency |

Regenerate `uv.lock` through `uv` after changing the `packaging` constraint.
The update is accepted only if the complete repository quality gate passes.

## Local Hygiene Architecture

Add `.codex/skills/hygiene/scripts/hygiene.py` as a standard-library command
orchestrator. It owns workflow sequencing and reporting; `tools/quality.py`
continues to own the individual quality commands.

The default invocation performs the full deterministic local workflow:

1. Report `git status --short --branch`.
2. Validate that `uv.lock` matches `pyproject.toml` in offline/check-only mode.
3. Run `uv run python tools/quality.py check`.
4. Run `uv run python tools/quality.py pre-commit`.

The script stops at the first required command failure and returns that exit
status. It does not clean, format, update, stage, or otherwise mutate files on
its own; any mutation performed by an existing pre-commit hook remains visible
and requires a deliberate rerun.

An additive `--dependencies` option performs a network-backed freshness inquiry
before the deterministic gate. It asks `uv` for the locked dependency tree in
JSON form, limited to direct dependencies, and reports stale runtime and
development dependencies separately. Any stale direct dependency makes the
command fail after printing its locked and available versions. Network or
registry failures are reported distinctly from version drift.

The hygiene skill documentation will require:

- Default full-strength hygiene for ordinary cleanup and pre-handoff checks.
- `--dependencies` for dependency chores and explicit freshness requests.
- Intentional constraint review followed by `uv lock --upgrade` when updates
  are approved.
- A final dependency inquiry and full hygiene rerun after dependency changes.

## Dependabot Configuration

Add `.github/dependabot.yml` using the `uv` package ecosystem at repository
root. Run version updates weekly and group production and development
dependencies separately so update intent remains reviewable while avoiding one
pull request per package. Limit concurrent dependency pull requests to a small,
explicit number.

Dependabot is advisory and change-producing; it does not replace local
verification. Every Dependabot update must still satisfy the same hygiene and
quality gates before merge.

## Contract Tests

Add `tests/test_hygiene_skill.py` using `unittest`. Tests will load the hygiene
script directly and replace its subprocess runner with a recording fake.

The tests cover:

- Exact sequencing of default status, offline lock, quality, and pre-commit
  commands.
- Propagation of the first required command failure.
- Classification and reporting of stale runtime and development dependencies
  from representative `uv` JSON.
- Success when all direct dependencies are current.
- Failure distinction between registry errors and dependency drift.
- Presence of the required weekly `uv` Dependabot configuration and grouping.

Implementation follows red-green-refactor: write and observe each relevant
`unittest` failure before adding the minimum script or configuration needed to
pass.

## Verification

Run the following after implementation:

```powershell
uv run python -m unittest tests.test_hygiene_skill -v
uv run python .codex/skills/hygiene/scripts/hygiene.py --dependencies
uv run python tools/quality.py check
uv run python tools/quality.py pre-commit
git diff --check
```

The dependency inquiry must report no stale direct dependencies after the
refresh. The final handoff reports exact commands, outcomes, any warnings, and
the resulting changed-file scope.
