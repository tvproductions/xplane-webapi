---
name: hygiene
description: Run the full-strength xplane-webapi repository hygiene contract for workspace state, lockfile validity, quality gates, pre-commit verification, and optional direct-dependency freshness. Use for hygiene, cleanup, tidy, dependency chores, maintenance checks, or pre-handoff verification.
---

# Hygiene

## Overview

Run the executable project-local hygiene contract. The script sequences repository checks and delegates quality details to `tools/quality.py`; do not reproduce its command list manually.

## Full-strength local workflow

Inspect the worktree, then run the deterministic workflow:

```powershell
git status --short --branch
git diff --stat
git diff --cached --stat
uv run python .codex/skills/hygiene/scripts/hygiene.py
```

Always use the full-strength workflow. It validates the lockfile offline, runs the complete quality gate, and runs repository pre-commit hooks.

## Dependency chores

For dependency freshness requests and before completing a dependency chore, run:

```powershell
uv run python .codex/skills/hygiene/scripts/hygiene.py --dependencies
```

This mode queries package metadata, reports stale direct runtime and development dependencies separately, and then runs the full local workflow when dependency versions are current.

When updates are approved:

1. Review constraint changes in `pyproject.toml` intentionally.
2. Update selected packages with `uv lock --upgrade-package <name>`; do not hand-edit `uv.lock`.
3. Inspect both `pyproject.toml` and `uv.lock` diffs.
4. Rerun dependency inquiry until it reports all direct dependencies current.
5. Rerun the full-strength workflow after every edit required by updated tools or libraries.

## Boundaries

- Use stdlib `unittest` only.
- Do not use or introduce another Python test framework.
- Do not touch `examples/` unless the user explicitly asks.
- Do not silently clean, format, update, stage, or delete files.
- Do not make the default hygiene workflow depend on network access.
- Do not delete code solely because a tool reports it; inspect references and public API exposure first.
- Keep generated `.coverage`, `.wily/`, `.ruff_cache/`, `.ty_cache/`, and pre-commit artifacts out of commits.
- Treat broad design debt as a separate tracked change rather than mixing it into mechanical hygiene.

## Evidence

Report commands run, exit status, test counts, warnings, dependency drift, skipped checks, and changed-file scope.
