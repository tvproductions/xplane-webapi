# Skills-first development stack

Read AGENTS.md first. Source provenance is recorded in
[.skills-first/bundle.lock.json](.skills-first/bundle.lock.json); native plugin
sources are pinned in [.agents/plugins/marketplace.json](.agents/plugins/marketplace.json).
Use one active discovery source per upstream plugin; do not vendor upstream skills.

Use the installed Superpowers `using-superpowers` workflow for feature design,
planning, implementation and verification. Use gz-skills `gzs-router` for portable
engineering workflow selection. Project operations use the existing `code-quality`,
`hygiene` and `git-sync` skills in .codex/skills. Keep project-owned operational
skills and records separate from native plugin caches.

The GovZero profile is **lite**. BACKLOG.md and existing handoff records retain
their roles. Superpowers Backplane is pinned but disabled pending readiness,
compatibility review and explicit adoption. Lite can be promoted to heavy later.

## Python and uv policy

This project supports Python `>=3.12,<3.13`, selected by the user for its
XPPython-adjacent context. uv manages the exact development interpreter in
.python-version, all virtual environments, dependencies, builds and execution.
Use `uv python install`, `uv sync --frozen` and `uv run --frozen` for routine work.
Use `uv add`, `uv remove` and `uv lock` for authorized dependency changes; commit
pyproject.toml and uv.lock together. Do not hand-edit uv.lock or use standalone
pip, Poetry, Conda, manually created virtualenvs or an unselected system Python.
Use `uv venv` and `uv pip` for isolated installed-wheel verification.
Shipped command-line tools run normally in the consumer's installed environment.

Keep the existing development dependencies and quality thresholds. All routine
tools, including Twine, are resolved in uv.lock and run through the project uv
environment. Run `uv run --frozen python tools/quality.py check`, the full hygiene
workflow and `uv run --frozen mkdocs build --strict` for adoption verification.
Use standard-library unittest only. The current deep checks remain part of CI
and pre-commit; that project-owned contract overrides the starter's suggestion
to run deeper checks only on demand.

Python 3.12 is an explicit project policy departure from the starter's ordinary
Python 3.14 baseline. Do not infer actual XPPython3 embedding from adjacency.
If code runs in XPPython3, inspect its embedded runtime and verify startup in the
real host separately; a passing uv environment does not establish host support.
Review code against relevant Python 3.12 idioms, stdlib APIs and deprecations
using official versioned documentation, with bounded changes and compatibility
evidence. Use gz-skills portability and Pythonic-pattern workflows where applicable.

## Maintenance and loading

Review starter, Superpowers, Backplane and gz-skills independently at adoption,
scoped updates and quarterly on-demand maintenance. Use gz-skills maintenance
workflows composed with project-owned quality commands; preserve project additions
and policy exceptions. Record official release evidence, full source SHAs,
adopt/defer decisions and revisit conditions. Keep rollback sources and distinguish
policy changes from version refreshes. No automatic schedules are created.

Configuration, installation and fresh-session loading are separate checks.
Verify actual discovered skills and loaded source revisions after restarting
Codex; configuration alone does not prove readiness. See the project
[adoption record](docs/superpowers/skills-first-adoption.md) for provenance,
installation steps, exceptions and verification evidence.
