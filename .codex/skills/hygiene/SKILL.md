---
name: hygiene
description: Repo-local xplane-webapi hygiene workflow for safe mechanical cleanup. Use when the user asks for hygiene, tidy, cleanup, maintainability cleanup, dead-code cleanup, docstring hygiene, security hygiene, pre-commit cleanup, or a low-risk quality-tools pass using this repository's code quality tools.
---

# Hygiene

## Overview

Run a focused cleanup pass using the repository quality tools. Hygiene work is mechanical and low-risk: formatting, obvious lint fixes, unused code review, docstring/security findings, cache cleanup, and validation. It is not a license for broad refactors or behavior changes.

## Workflow

1. Inspect scope first:

```powershell
git status -sb
```

2. Run the default quality gate:

```powershell
uv run python tools\quality.py check
```

3. Fix only safe, in-scope findings:

- `ruff format` formatting changes.
- Ruff lint fixes that preserve behavior.
- Bandit findings with direct mechanical replacements, such as replacing production `assert` with explicit exceptions.
- Vulture findings only when the symbol is truly unreachable; otherwise leave it and explain why.
- Interrogate/docstring gaps only for public or confusing surfaces; do not add empty docstring noise.
- Xenon findings only when a local mechanical simplification can reduce complexity; otherwise report them as refactor candidates.

4. Run the repository hook aggregation:

```powershell
uv run python tools\quality.py pre-commit
```

5. Use focused tools for diagnosis:

```powershell
uv run python tools\quality.py security
uv run python tools\quality.py docs
uv run python tools\quality.py dead-code
uv run python tools\quality.py metrics
uv run python tools\quality.py complexity
```

6. Run Wily only after the worktree is clean, because its git archiver rejects dirty repositories:

```powershell
uv run python tools\quality.py wily
```

7. Rerun the default gate after edits:

```powershell
uv run python tools\quality.py check
```

## Boundaries

- Use stdlib `unittest` only.
- Do not add or invoke other Python test frameworks.
- Do not touch `examples/` unless the user explicitly asks.
- Do not delete code solely because a tool reports it; inspect references and public API exposure first.
- Keep generated files such as `.coverage`, `.wily/`, `.ruff_cache/`, and `.ty_cache/` out of commits.
- If a hygiene pass reveals broad design debt, report it separately instead of mixing it into mechanical cleanup.
