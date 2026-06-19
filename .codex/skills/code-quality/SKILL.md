---
name: code-quality
description: Repo-local xplane-webapi quality workflow. Use when the user asks to run quality checks, lint, format, typecheck, test, coverage, security scans, docstring coverage, dead-code checks, metrics, pre-commit, complexity, CI-equivalent checks, or to fix failures from this repository's quality gate.
---

# Code Quality

## Overview

Use the repo-local wrapper in `tools/quality.py` so agents run the same quality gates in the same order. The wrapper is based on the gzkit Python quality stack but scoped to this repository's current baseline.

## Default Gate

Run the blocking gate before commits, pushes, PRs, and after non-trivial code changes:

```powershell
uv run python tools\quality.py check
```

`check` runs:

- `ruff check xpwebapi tests tools`
- `ruff format --check xpwebapi tests tools`
- `ty check`
- `python -m unittest discover -v`
- `coverage run -m unittest discover -s tests -t .`
- `coverage report --fail-under=40`
- `bandit -q -r xpwebapi`
- `detect-secrets scan ...`
- `interrogate -v -f 40 xpwebapi`
- `vulture xpwebapi tests tools --min-confidence 80`
- `xenon --max-absolute E --max-modules B --max-average A xpwebapi`

Fix in-scope failures and rerun the failed gate or the full `check`.

## Focused Gates

Use focused gates during iteration:

```powershell
uv run python tools\quality.py lint
uv run python tools\quality.py format-check
uv run python tools\quality.py format
uv run python tools\quality.py typecheck
uv run python tools\quality.py test
uv run python tools\quality.py coverage
uv run python tools\quality.py security
uv run python tools\quality.py docs
uv run python tools\quality.py dead-code
uv run python tools\quality.py metrics
uv run python tools\quality.py pre-commit
uv run python tools\quality.py complexity
```

Use the Wily trend gate as an advisory or targeted refactor tool after the worktree is clean:

```powershell
uv run python tools\quality.py wily
```

The current complexity baseline is `E/B/A`: block rank `E`, module rank `B`, average rank `A`. This preserves the existing `XPWebsocketAPI.ws_listener` baseline while blocking any new `F`-rank block or worse module/average trend. Wily's git archiver requires a clean worktree.

## Rules

- Use stdlib `unittest` only.
- Do not invoke or add other Python test frameworks.
- Treat `tools/quality.py check` as the CI-equivalent local gate.
- Keep generated coverage data out of commits.
- If a gate fails because a required dev tool is missing, run `uv sync` and retry once.
