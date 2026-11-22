# Skills-first development stack

Read AGENTS.md first. Source provenance is recorded in
[.gz-starter/bundle.lock.json](.gz-starter/bundle.lock.json); native plugin
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
The supported uv minimum is 0.13.5. CI uses the exact tested uv release recorded
in its workflows.
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

Use `update-gz-template` for the starter's adoption and migration workflow.
Resolve native plugins through the project catalog and project enablement in
`.codex/config.toml`. Preserve inherited user defaults and suppress duplicate
sources in this project's configuration.

Dependency maintenance and bare `gzs-update-dependencies` invocations select
update mode. Check official release histories and verify published tags before
migrating the in-scope dependencies. Preserve the Python support policy and
required quality gates. An explicit freshness review selects assessment only.

Use the starter's [architectural decision policy](https://github.com/tvproductions/gz-starter/blob/a1c3550eac441b0a7beaddc66fb00c58ce0f1e6a/docs/engineering/architectural-decisions.md)
when work requires an architectural decision. The lock records the source and
hash. Use existing repository authorities and obtain explicit approval for any
new or replacement architectural decision before dependent implementation.

Configuration, installation and fresh-session loading are separate checks.
Verify actual discovered skills and loaded source revisions after restarting
Codex; configuration alone does not prove readiness. See the project
[adoption record](docs/superpowers/skills-first-adoption.md) for provenance,
installation steps, exceptions and verification evidence.
