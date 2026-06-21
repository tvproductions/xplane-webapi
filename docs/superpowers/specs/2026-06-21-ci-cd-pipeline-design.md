# CI/CD Pipeline

**Date:** 2026-06-21
**Priority:** P3 - Low
**Status:** Approved

## Goal

Make the repository's automated checks match the documented local quality workflow, preserve the existing documentation deployment, and validate package build readiness without publishing to PyPI yet.

## Background

The backlog calls for a CI/CD pipeline with linting, format checks, type checking, unit tests, PyPI publishing on tagged releases, and pre-commit hooks. The repository already has:

- `.github/workflows/ci.yml`, which runs `tools/quality.py check` and deploys MkDocs documentation.
- `.pre-commit-config.yaml`, which runs the local quality gate and supporting hygiene hooks.
- `tools/quality.py`, which exposes repo-local quality commands.
- A Python package named `xpwebapi` in `pyproject.toml`.

This fork should not publish to PyPI yet. The user plans to file an upstream pull request first. If the original project does not accept the work, the package can later be renamed for independent PyPI publishing, likely to `xp-webapi`. Until that decision is made, CI should prove the package can build but should not configure `uv publish`, PyPI tokens, GitHub OIDC trusted publishing, or a new distribution name.

## Decision

Implement the CI/CD backlog item as a CI, documentation deployment, local pre-commit, and package-build-readiness pass.

Do not implement PyPI publishing in this pass. Record it as a deferred release-strategy follow-up rather than a completed automated publish path.

## Workflow Design

Keep `.github/workflows/ci.yml` as the main GitHub Actions workflow and split responsibilities clearly:

- `quality`: runs on pushes to `main` and pull requests.
- `docs`: runs after `quality` only on pushes to `main`, preserving the existing `mkdocs gh-deploy` behavior.
- `build`: runs with CI to confirm the package can be built from the checked-in metadata and lock file.

The workflow should use Python 3.12 and `uv`, consistent with `pyproject.toml`.

## CI Commands

Replace the opaque GitHub Actions invocation of `uv run python tools/quality.py check` with explicit commands matching the backlog item:

```powershell
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run python -m unittest discover -v
uv build
```

The workflow must use `unittest` as the only test runner.

`tools/quality.py` remains useful for local and pre-commit workflows. The GitHub workflow should be explicit so failures map directly to the backlog's named checks.

## Permissions

Use least-privilege permissions:

- Default workflow permissions: `contents: read`.
- Documentation deployment job: `contents: write`.

Do not grant `id-token: write` because PyPI trusted publishing is intentionally out of scope for this pass.

## Documentation Deployment

Preserve `mkdocs gh-deploy --force` on pushes to `main` after quality checks pass.

The deployment job may continue to install documentation tooling through `uv sync --frozen` because the documentation dependencies are already in the development dependency group.

## Local Pre-Commit

Keep `.pre-commit-config.yaml` in place. The existing local hooks already provide a pre-commit entry point for `uv run python tools/quality.py check` and supporting hygiene commands.

If implementation finds that the pre-commit configuration no longer matches the quality commands, update it narrowly. Do not add a new test framework or broad unrelated hooks.

## PyPI Publishing

Out of scope for this pass:

- Renaming the project from `xpwebapi`.
- Adding `uv publish`.
- Adding PyPI API tokens.
- Adding GitHub OIDC trusted publishing.
- Publishing to TestPyPI or PyPI.

Future PyPI work should start by deciding package identity. If this fork becomes independently published, update `[project].name` deliberately and then add a tag-triggered publishing workflow using PyPI Trusted Publishing.

## Backlog Update

After validation passes, update `BACKLOG.md` so:

- GitHub Actions CI checks are marked complete.
- Pre-commit hooks are marked complete.
- PyPI publishing is marked as deferred pending upstream PR and package-name strategy.

The top-level CI/CD item may be marked complete only if the backlog text clearly captures that PyPI automation is intentionally deferred and not silently completed.

## Testing

Use `unittest` only.

Existing `tests/test_quality_tool.py` covers `tools/quality.py`. Add focused tests only if implementation changes repo-owned Python code. YAML workflow behavior is validated by inspection plus local execution of the same commands used in CI.

Final local validation:

```powershell
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run python -m unittest discover -v
uv build
```

## Success Criteria

- [ ] GitHub Actions runs explicit lint, format-check, type-check, unit-test, and build-validation commands.
- [ ] Documentation deployment with `mkdocs gh-deploy --force` is preserved for pushes to `main`.
- [ ] Workflow permissions are read-only by default and write-enabled only for docs deployment.
- [ ] No PyPI publishing credentials, OIDC permissions, or `uv publish` steps are added.
- [ ] Local pre-commit support remains available.
- [ ] `BACKLOG.md` accurately records PyPI publishing as deferred pending upstream/package-name strategy.
- [ ] Local validation commands pass.
