---
name: git-sync
description: Repo-local workflow for safely syncing xplane-webapi changes with git. Use when the user asks to git add, commit, push, publish, sync, or otherwise send current repository changes to origin; includes scope review, unittest and ruff validation, commit creation, push, and final remote sync verification.
---

# Git Sync

## Overview

Publish the current `xplane-webapi` worktree deliberately: inspect scope, validate with the repo's approved tools, stage only intended files, commit, push, and verify local and remote are aligned.

## Workflow

1. Read `AGENTS.md` before choosing validation commands.
2. Run `git status -sb`, inspect relevant diffs, and identify the intended scope.
3. If changes are mixed or unrelated, ask which files to include. If all dirty files clearly belong to the requested work, stage the whole worktree.
4. Run validation before committing:

```powershell
uv run python -m unittest discover -v
uv run ruff check xpwebapi tests
uv run ruff format --check xpwebapi tests
```

5. Fix validation failures that are in scope, then rerun the failed command. Do not introduce or suggest other test frameworks.
6. Stage changes with explicit paths when scope is mixed; use `git add -A` only for a unified worktree.
7. Commit with a terse imperative message that summarizes the full staged diff.
8. Push the current branch:

```powershell
git push origin <branch>
```

9. Verify sync:

```powershell
git fetch origin
git status -sb
git log --oneline -3
```

Report the commit SHA, branch, pushed remote, validation results, and final sync status.

## Repo Rules

- Use `unittest`; never add or invoke other Python test frameworks.
- Keep `examples/` untouched unless the user explicitly asks.
- Do not stage unrelated user changes silently.
- If git write commands are blocked by sandbox permissions, rerun the same command with escalation and a concise approval question.
- If push is rejected because the remote has new commits, fetch and inspect. Prefer a fast-forward-only sync when possible; ask before rebasing, merging, or force pushing.
