# Strong Hygiene and Dependency Maintenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh every stale direct dependency and add a script-backed, contract-tested hygiene workflow with both local dependency inquiry and weekly Dependabot updates.

**Architecture:** Keep `tools/quality.py` as the single quality-gate engine. Add a standard-library orchestrator under the existing hygiene skill for workflow sequencing and `uv` JSON interpretation, then add a grouped `uv` Dependabot configuration as the remote maintenance surface.

**Tech Stack:** Python 3.12 standard library, `unittest`, `uv`, existing repository quality tools, GitHub Dependabot.

## Global Constraints

- Source design: `docs/superpowers/specs/2026-07-19-strong-hygiene-and-dependency-maintenance-design.md`.
- Use standard-library `unittest` exclusively; never add or invoke another Python test runner.
- Do not replace or duplicate `tools/quality.py`.
- Normal hygiene must remain deterministic and usable without network access.
- Dependency inquiry must be explicit, network-backed, read-only, and fail on stale direct dependencies.
- The hygiene script must not clean, format, update, stage, or otherwise mutate files itself.
- Target `websockets==16.1.1`, `packaging==26.2`, `coverage==7.15.2`, `mkdocs-material==9.7.7`, `mkdocstrings==1.0.6`, `ruff==0.15.22`, and `ty==0.0.61` in `uv.lock`.
- Raise the direct `packaging` constraint to the 26.x line; do not raise unrelated minimum-version constraints without a demonstrated need.
- Dependabot must check the root `uv` project weekly and group production and development updates separately.

## File Structure

- Create `.codex/skills/hygiene/scripts/hygiene.py`: orchestrate local hygiene and interpret direct-dependency freshness from `uv tree` JSON.
- Modify `.codex/skills/hygiene/SKILL.md`: make the script the canonical full-strength hygiene entrypoint and document dependency-chore behavior.
- Create `tests/test_hygiene_skill.py`: contract-test orchestration, failure propagation, dependency classification, skill instructions, and Dependabot policy.
- Create `.github/dependabot.yml`: schedule grouped weekly `uv` dependency updates.
- Modify `pyproject.toml`: move the `packaging` requirement to the 26.x line.
- Modify `uv.lock`: resolve the seven approved direct updates and any resolver-required transitive changes.

---

### Task 1: Script-backed local hygiene and dependency inquiry

**Files:**
- Create: `.codex/skills/hygiene/scripts/hygiene.py`
- Create: `tests/test_hygiene_skill.py`

**Interfaces:**
- Produces: `OutdatedDependency(name: str, current: str, latest: str, group: str)`.
- Produces: `find_outdated_dependencies(payload: dict[str, object]) -> list[OutdatedDependency]`.
- Produces: `run_local_hygiene(runner: Runner = subprocess.run) -> int`.
- Produces: `audit_dependencies(runner: Runner = subprocess.run) -> int`.
- Produces: `main(argv: Sequence[str] | None = None) -> int` with additive `--dependencies`.
- Consumes: `tools/quality.py` command-line gates; does not import their internals.

- [ ] **Step 1: Write failing orchestration and dependency tests**

Create `tests/test_hygiene_skill.py` with a module loader, a representative `uv tree --format json` fixture, and these initial tests:

```python
"""Contract tests for the repository hygiene skill."""

from __future__ import annotations

import importlib.util
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".codex" / "skills" / "hygiene" / "scripts" / "hygiene.py"


def load_hygiene_module():
    spec = importlib.util.spec_from_file_location("xplane_webapi_hygiene", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def dependency_payload(*, stale: bool = True) -> dict[str, object]:
    packaging = {
        "name": "packaging",
        "version": "25.0",
        "kind": "package",
    }
    coverage = {
        "name": "coverage",
        "version": "7.14.1",
        "kind": "package",
    }
    if stale:
        packaging["latest_version"] = "26.2"
        coverage["latest_version"] = "7.15.2"

    return {
        "roots": ["project:dev", "project"],
        "resolution": {
            "project": {
                "name": "xpwebapi",
                "kind": "package",
                "dependencies": [{"id": "packaging"}],
            },
            "project:dev": {
                "name": "xpwebapi",
                "kind": {"group": "dev"},
                "dependencies": [{"id": "coverage"}],
            },
            "packaging": packaging,
            "coverage": coverage,
        },
    }


class HygieneSkillTests(unittest.TestCase):
    def test_local_hygiene_runs_full_deterministic_sequence(self) -> None:
        hygiene = load_hygiene_module()
        runner = MagicMock(return_value=SimpleNamespace(returncode=0))

        result = hygiene.run_local_hygiene(runner=runner)

        self.assertEqual(result, 0)
        self.assertEqual(
            [call.args[0] for call in runner.call_args_list],
            [
                ("git", "status", "--short", "--branch"),
                ("uv", "lock", "--check", "--offline"),
                ("uv", "run", "python", "tools/quality.py", "check"),
                ("uv", "run", "python", "tools/quality.py", "pre-commit"),
            ],
        )

    def test_local_hygiene_stops_on_first_failure(self) -> None:
        hygiene = load_hygiene_module()
        runner = MagicMock(
            side_effect=[
                SimpleNamespace(returncode=0),
                SimpleNamespace(returncode=7),
                SimpleNamespace(returncode=0),
            ]
        )

        result = hygiene.run_local_hygiene(runner=runner)

        self.assertEqual(result, 7)
        self.assertEqual(runner.call_count, 2)

    def test_dependency_parser_classifies_runtime_and_development_drift(self) -> None:
        hygiene = load_hygiene_module()

        outdated = hygiene.find_outdated_dependencies(dependency_payload())

        self.assertEqual(
            [(item.name, item.current, item.latest, item.group) for item in outdated],
            [
                ("coverage", "7.14.1", "7.15.2", "development"),
                ("packaging", "25.0", "26.2", "runtime"),
            ],
        )

    def test_dependency_parser_accepts_current_direct_dependencies(self) -> None:
        hygiene = load_hygiene_module()

        self.assertEqual(hygiene.find_outdated_dependencies(dependency_payload(stale=False)), [])

    def test_dependency_audit_distinguishes_registry_failure_from_drift(self) -> None:
        hygiene = load_hygiene_module()
        registry_runner = MagicMock(
            return_value=SimpleNamespace(returncode=9, stdout="", stderr="registry unavailable")
        )

        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            result = hygiene.audit_dependencies(runner=registry_runner)

        self.assertEqual(result, 9)
        self.assertIn("registry unavailable", stderr.getvalue())

    def test_dependency_audit_fails_when_direct_dependencies_are_stale(self) -> None:
        hygiene = load_hygiene_module()
        import json

        runner = MagicMock(
            return_value=SimpleNamespace(
                returncode=0,
                stdout=json.dumps(dependency_payload()),
                stderr="",
            )
        )

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            result = hygiene.audit_dependencies(runner=runner)

        self.assertEqual(result, 1)
        self.assertIn("development: coverage 7.14.1 -> 7.15.2", stdout.getvalue())
        self.assertIn("runtime: packaging 25.0 -> 26.2", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify the missing-script failure**

Run:

```powershell
uv run python -m unittest tests.test_hygiene_skill -v
```

Expected: ERROR while loading `.codex/skills/hygiene/scripts/hygiene.py` because the script does not exist.

- [ ] **Step 3: Implement the minimum standard-library hygiene script**

Create `.codex/skills/hygiene/scripts/hygiene.py` with the following implementation:

```python
"""Run deterministic repository hygiene and optional dependency inquiry."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
Runner = Callable[..., subprocess.CompletedProcess[str]]
LOCAL_COMMANDS = (
    ("git", "status", "--short", "--branch"),
    ("uv", "lock", "--check", "--offline"),
    ("uv", "run", "python", "tools/quality.py", "check"),
    ("uv", "run", "python", "tools/quality.py", "pre-commit"),
)
DEPENDENCY_COMMAND = (
    "uv",
    "tree",
    "--outdated",
    "--depth",
    "1",
    "--locked",
    "--format",
    "json",
)


@dataclass(frozen=True, order=True)
class OutdatedDependency:
    """Describe one stale direct dependency."""

    name: str
    current: str
    latest: str
    group: str


def find_outdated_dependencies(payload: dict[str, Any]) -> list[OutdatedDependency]:
    """Return stale dependencies referenced directly by workspace roots."""
    resolution = payload.get("resolution", {})
    if not isinstance(resolution, dict):
        raise ValueError("uv dependency data has no resolution mapping")

    outdated: list[OutdatedDependency] = []
    for root_id in payload.get("roots", []):
        root = resolution.get(root_id, {})
        if not isinstance(root, dict):
            continue
        kind = root.get("kind")
        group = "development" if isinstance(kind, dict) and kind.get("group") else "runtime"
        for dependency in root.get("dependencies", []):
            if not isinstance(dependency, dict):
                continue
            record = resolution.get(dependency.get("id"), {})
            if not isinstance(record, dict):
                continue
            latest = record.get("latest_version")
            current = record.get("version")
            name = record.get("name")
            if not isinstance(name, str) or not isinstance(current, str) or not isinstance(latest, str):
                continue
            outdated.append(
                OutdatedDependency(
                    name=name,
                    current=current,
                    latest=latest,
                    group=group,
                )
            )
    return sorted(set(outdated))


def run_local_hygiene(runner: Runner = subprocess.run) -> int:
    """Run the full deterministic local hygiene sequence."""
    for command in LOCAL_COMMANDS:
        print("+ " + " ".join(command), flush=True)
        result = runner(command, cwd=ROOT, check=False)
        if result.returncode != 0:
            return result.returncode
    return 0


def audit_dependencies(runner: Runner = subprocess.run) -> int:
    """Query and report stale direct dependencies without changing files."""
    print("+ " + " ".join(DEPENDENCY_COMMAND), flush=True)
    result = runner(
        DEPENDENCY_COMMAND,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr or "dependency registry inquiry failed", file=sys.stderr)
        return result.returncode

    try:
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            raise ValueError("uv dependency data is not an object")
        outdated = find_outdated_dependencies(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"invalid uv dependency data: {exc}", file=sys.stderr)
        return 2

    if outdated:
        print("Outdated direct dependencies:")
        for item in outdated:
            print(f"  {item.group}: {item.name} {item.current} -> {item.latest}")
        return 1

    print("All direct dependencies are current.")
    return 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse hygiene command-line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dependencies",
        action="store_true",
        help="Query PyPI for stale direct dependencies before local hygiene.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the requested hygiene workflow."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.dependencies:
        dependency_result = audit_dependencies()
        if dependency_result != 0:
            return dependency_result
    return run_local_hygiene()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the focused tests and verify green**

Run:

```powershell
uv run python -m unittest tests.test_hygiene_skill -v
```

Expected: six tests pass with no failures or skips.

- [ ] **Step 5: Run focused lint and type checks**

Run:

```powershell
uv run ruff check .codex/skills/hygiene/scripts/hygiene.py tests/test_hygiene_skill.py
uv run ruff format --check .codex/skills/hygiene/scripts/hygiene.py tests/test_hygiene_skill.py
uv run ty check .codex/skills/hygiene/scripts/hygiene.py tests/test_hygiene_skill.py
```

Expected: all commands exit 0. If formatting is required, run `uv run ruff format` on only these two files, inspect the diff, and rerun all three commands.

- [ ] **Step 6: Commit the executable hygiene contract**

```powershell
git add .codex/skills/hygiene/scripts/hygiene.py tests/test_hygiene_skill.py
git commit -m "feat: make hygiene workflow executable"
```

### Task 2: Canonical skill instructions and weekly Dependabot policy

**Files:**
- Modify: `.codex/skills/hygiene/SKILL.md`
- Modify: `tests/test_hygiene_skill.py`
- Create: `.github/dependabot.yml`

**Interfaces:**
- Consumes: `.codex/skills/hygiene/scripts/hygiene.py` from Task 1.
- Produces: canonical commands `uv run python .codex/skills/hygiene/scripts/hygiene.py` and `uv run python .codex/skills/hygiene/scripts/hygiene.py --dependencies`.
- Produces: weekly root-level Dependabot updates for package ecosystem `uv`.

- [ ] **Step 1: Add failing documentation and Dependabot contract tests**

Add these methods to `HygieneSkillTests` in `tests/test_hygiene_skill.py`:

```python
    def test_skill_uses_script_as_canonical_full_strength_workflow(self) -> None:
        skill = (ROOT / ".codex" / "skills" / "hygiene" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn(
            "uv run python .codex/skills/hygiene/scripts/hygiene.py",
            skill,
        )
        self.assertIn(
            "uv run python .codex/skills/hygiene/scripts/hygiene.py --dependencies",
            skill,
        )
        self.assertIn("full-strength", skill)
        self.assertIn("stdlib `unittest` only", skill)

    def test_dependabot_config_matches_weekly_grouped_uv_policy(self) -> None:
        config = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        expected = """version: 2
updates:
  - package-ecosystem: "uv"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "09:00"
      timezone: "America/Chicago"
    open-pull-requests-limit: 4
    groups:
      runtime-dependencies:
        dependency-type: "production"
      development-dependencies:
        dependency-type: "development"
"""
        self.assertEqual(config, expected)
```

- [ ] **Step 2: Run the two tests and verify their expected failures**

Run:

```powershell
uv run python -m unittest tests.test_hygiene_skill.HygieneSkillTests.test_skill_uses_script_as_canonical_full_strength_workflow tests.test_hygiene_skill.HygieneSkillTests.test_dependabot_config_matches_weekly_grouped_uv_policy -v
```

Expected: the skill test fails because the canonical commands are absent, and the Dependabot test errors because `.github/dependabot.yml` is absent.

- [ ] **Step 3: Replace the hygiene skill with the canonical workflow**

Replace `.codex/skills/hygiene/SKILL.md` with:

````markdown
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
````

- [ ] **Step 4: Add the weekly grouped `uv` Dependabot configuration**

Create `.github/dependabot.yml` with:

```yaml
version: 2
updates:
  - package-ecosystem: "uv"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "09:00"
      timezone: "America/Chicago"
    open-pull-requests-limit: 4
    groups:
      runtime-dependencies:
        dependency-type: "production"
      development-dependencies:
        dependency-type: "development"
```

- [ ] **Step 5: Run focused tests and verify green**

Run:

```powershell
uv run python -m unittest tests.test_hygiene_skill -v
```

Expected: eight tests pass with no failures or skips.

- [ ] **Step 6: Validate skill and configuration formatting**

Run:

```powershell
git diff --check
uv run ruff check tests/test_hygiene_skill.py .codex/skills/hygiene/scripts/hygiene.py
uv run ruff format --check tests/test_hygiene_skill.py .codex/skills/hygiene/scripts/hygiene.py
python C:/Users/Jeff/.codex/skills/.system/skill-creator/scripts/quick_validate.py .codex/skills/hygiene
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit the skill and automation policy**

```powershell
git add .codex/skills/hygiene/SKILL.md .github/dependabot.yml tests/test_hygiene_skill.py
git commit -m "chore: strengthen repository hygiene"
```

### Task 3: Refresh all stale direct dependencies

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: dependency audit implemented in Task 1.
- Produces: a lockfile with no stale direct dependencies as of 2026-07-19.
- Preserves: the existing Python requirement `>=3.12,<3.13` and all runtime APIs.

- [ ] **Step 1: Run the local dependency audit and observe red**

Run:

```powershell
uv run python .codex/skills/hygiene/scripts/hygiene.py --dependencies
```

Expected: exit 1 before local quality gates and a report containing exactly these stale direct packages: `websockets 16.0 -> 16.1.1`, `packaging 25.0 -> 26.2`, `coverage 7.14.1 -> 7.15.2`, `mkdocs-material 9.7.6 -> 9.7.7`, `mkdocstrings 1.0.4 -> 1.0.6`, `ruff 0.15.18 -> 0.15.22`, and `ty 0.0.51 -> 0.0.61`.

- [ ] **Step 2: Raise only the required direct constraint**

Change this line in `pyproject.toml`:

```toml
    "packaging~=25.0",
```

to:

```toml
    "packaging~=26.2",
```

Keep all other declared lower bounds unchanged.

- [ ] **Step 3: Resolve only the approved package upgrades**

Run:

```powershell
uv lock --upgrade-package packaging --upgrade-package websockets --upgrade-package coverage --upgrade-package mkdocs-material --upgrade-package mkdocstrings --upgrade-package ruff --upgrade-package ty
```

Expected: `uv.lock` is rewritten with the seven target direct versions and only resolver-required transitive changes.

- [ ] **Step 4: Inspect dependency metadata and lockfile scope**

Run:

```powershell
git diff -- pyproject.toml uv.lock
uv tree --depth 1 --locked --color never
```

Expected: `packaging` is constrained and locked at 26.2; the other six targets match the Global Constraints; no unapproved direct dependency changes appear.

- [ ] **Step 5: Run compatibility-focused unit tests**

Run:

```powershell
uv run python -m unittest tests.test_ws tests.test_rest tests.test_async_rest tests.test_quality_tool tests.test_documentation -v
```

Expected: all selected compatibility and tooling tests pass with no failures or skips.

- [ ] **Step 6: Rerun dependency inquiry and observe green**

Run:

```powershell
uv run python .codex/skills/hygiene/scripts/hygiene.py --dependencies
```

Expected: `All direct dependencies are current.` followed by successful full local hygiene.

- [ ] **Step 7: Commit the dependency refresh**

```powershell
git add pyproject.toml uv.lock
git commit -m "chore: refresh project dependencies"
```

### Task 4: Full repository verification and handoff evidence

**Files:**
- Verify only; modify files only if a required formatter or hook makes an intentional, reviewed correction.

**Interfaces:**
- Consumes: all deliverables from Tasks 1-3.
- Produces: fresh evidence that dependency inquiry, the CI-equivalent gate, pre-commit, and diff hygiene pass together.

- [ ] **Step 1: Run the complete `unittest` suite explicitly**

Run:

```powershell
uv run python -m unittest discover -v
```

Expected: all tests pass with zero failures, errors, or skips.

- [ ] **Step 2: Run the network-backed dependency inquiry**

Run:

```powershell
uv run python .codex/skills/hygiene/scripts/hygiene.py --dependencies
```

Expected: no stale direct dependencies, followed by successful offline lock, quality, and pre-commit gates.

- [ ] **Step 3: Run the CI-equivalent gate directly**

Run:

```powershell
uv run python tools/quality.py check
```

Expected: ruff, format check, ty, `unittest`, coverage, Bandit, detect-secrets, Interrogate, Vulture, and Xenon all exit 0.

- [ ] **Step 4: Run the pre-commit aggregation directly**

Run:

```powershell
uv run python tools/quality.py pre-commit
```

Expected: all repository hooks pass. If a hook changes a file, inspect it, rerun Steps 1-4, and commit only the reviewed correction.

- [ ] **Step 5: Verify diff and repository scope**

Run:

```powershell
git diff --check
git status --short --branch
git log --oneline -5
```

Expected: no whitespace errors or uncommitted generated artifacts; commits are limited to the approved spec, plan, hygiene workflow, Dependabot configuration, tests, and dependency refresh.

- [ ] **Step 6: Prepare the final evidence summary**

Report:

- Exact dependency versions resolved.
- Exact test count and exit result.
- Results of dependency inquiry, quality, and pre-commit commands.
- Any warnings or hook-produced corrections.
- Final changed-file and commit scope.
