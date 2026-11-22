# Skills-first adoption design

Status: approved on 2026-10-11; user selected lite and Python 3.12 only.

## Goal and source

Adopt the skills-first starter into xplane-webapi while preserving its Python
client API, project operational workflows and existing user changes. The user
selected Python 3.12 only on 2026-10-11 because the project is XPPython-adjacent;
this supersedes the initial proposal to retain Python 3.12/3.13 support.
Use starter v0.3.0 at `a7550a6e29b88349041e70e3dbba4778be4b8235`,
verified against its published GitHub release and checked-out tag on 2026-10-11.

Source: https://github.com/tvproductions/gz-skills-first-starter/releases/tag/v0.3.0

The starter supplies policy, provenance and configuration; upstream plugins own
their skills. Backplane remains disabled and BACKLOG.md remains authoritative.

## Current evidence

- AGENTS.md requires standard-library unittest and prohibits pytest.
- pyproject.toml publishes Python `>=3.12,<3.14`; local development uses 3.13.
  CI verifies 3.12 and 3.13, wheel installation and documentation.
- Project-owned code-quality, git-sync and hygiene skills live in .codex/skills.
- Superpowers 6.0.3 was copied into .codex/skills and .codex/plugins/superpowers.
- .agents/skills contains empty legacy gzs-git-sync, gzs-router and
  gzs-update-dependencies directory trees. The starter preview refuses adoption
  at the first of these paths.
- Native Codex inventory reports gz-skills@gz-skills 0.6.0 installed;
  this session discovers that plugin and project-local Superpowers skills.
  Native remote inventory was unavailable in the restricted environment.
- No .gzkit directory or .gz-skills/settings.json exists.
- BACKLOG.md has pre-existing user edits, outside the adoption change.

## Alternatives

1. Recommended: adopt native plugin configuration and provenance, reconcile
   legacy discovery, and document project-specific engineering exceptions.
   This adopts the user's Python 3.12 support policy and provides one discovery
   source per plugin.
2. Documentation-only adoption: retain existing copies and add routing guidance.
   This changes less but leaves duplicate sources and fails the native starter
   adoption contract.
3. Wholesale baseline adoption: migrate runtime support to Python 3.14 and replace
   the quality policy. This expands scope and changes published compatibility;
   it requires a separate product and toolchain migration.

## Recommended change

### Configuration and sources

Record template version, exact SHA and independently pinned component sources
in .skills-first/bundle.lock.json. Add project Codex marketplace and enablement
configuration, with Superpowers and gz-skills enabled and Backplane disabled.
The adapted project binding uses a local `xplane-webapi-skills-first` catalog
with the reviewed component SHAs, registered through the native manager.
Correct the starter helper's hardcoded `tvproductions/skills-first-starter.git`
origin in the project adoption binding to the actual
`tvproductions/gz-skills-first-starter.git` repository. Preserve the upstream
checkout; do not modify managed plugin caches.

Initially select the reviewed starter catalog: Superpowers v6.4.1 at
`5bf4e78011075bcfc0dc295f0724994cd123ee71`, gz-skills v0.7.0 at
`6ebf803e4a2775d3742c84984a03548275b7c926`, and disabled Backplane at
`d0eeee829c491da02351e793544aa16ad96461bf`.
The latest Superpowers release is v7.0.0. Record its deferral as limiting the
initial migration to the starter's reviewed catalog; revisit it after native
discovery verification through an independent, bounded plugin update.
Do not describe v6.4.1 as latest or claim combined-stack compatibility.

Reconcile the already-installed gz-skills source with project configuration
before adding a second source. Native manager changes must preserve unrelated
projects' enablement. If the host cannot isolate activation, document that
limitation and leave that installation step pending.

### Discovery migration and recovery

Compare local Superpowers skill copies with their recorded source and identify
project edits before retiring them. Preserve any useful project customization
in project-owned instructions or operational skills. Keep recovery material
outside active discovery and retain git history for tracked files.
Remove the inspected empty legacy gzs directory trees only after rechecking
their contents and resolved workspace paths. Retire copied upstream Superpowers
discovery once native source configuration is established. Preserve code-quality,
git-sync and hygiene and their scripts.

### Project instructions and policy

Link a project-adapted AGENTS.skills-first.md from AGENTS.md without changing its
testing prohibition. Route feature design and implementation to Superpowers,
portable engineering reviews to gz-skills, and repository operations to the
existing project-owned skills.

Use Python 3.12 only for package support, development, quality checks and CI.
Set requires-python to `>=3.12,<3.13`, remove the Python 3.13 classifier, and
update installation/development documentation and CI selectors consistently.
Verify the latest stable compatible 3.12 patch from official sources and pin
that exact patch in .python-version and CI. Target supported Python 3.12 syntax
in Ruff and ty. Refresh uv.lock through uv for the revised support range while
preserving application dependencies and existing development tools wherever
compatible. Verify the installed wheel under the selected 3.12 interpreter.

Preserve the existing quality gate and pre-commit contract; update interpreter
references in project-owned operational skills and scripts as needed. Document
Python 3.12 as the user's XPPython-adjacent compatibility policy and the existing
deep-check CI contract as a departure from the starter's on-demand-only policy.
Adjacency does not establish actual XPPython3 embedding or host compatibility:
verify the embedded interpreter and plugin startup separately if code is loaded
in that host. Review incompatible dependency/tool constraints with evidence;
do not silently widen Python support or remove quality checks to make setup pass.
Document version-aware Python review, portability, independent source maintenance
and the distinction between configured, installed and actually loaded plugins.

### Explicit profile choice

Recommend lite: portable engineering skills alongside existing Superpowers and
project backlog/handoff practice, without adopting project-wide requirements or
release management. Heavy is also possible, but Backplane remains deferred and
heavy environment readiness cannot be claimed from a profile selection.
Record only the user's explicit choice through the upstream settings helper;
do not infer it from installed plugins. Application configuration remains separate.

## Verification and completion

Validate JSON/TOML, immutable pins, correct repository URL, Backplane disablement,
instruction links and the selected profile. Compare the final diff with the
initial inventory to confirm product dependencies, operational skills and user
BACKLOG.md edits are preserved, and all runtime declarations implement the user's
Python 3.12-only choice consistently. Run unittest and wheel installation checks
on that interpreter; record the intentional narrowing of published support.

Run the project's required full hygiene workflow and strict documentation build
for the final change. Follow native manager help for installation and inventory.
Check actual identities and loaded sources in a fresh Codex session. Report
configuration checks, installation and fresh-session discovery separately;
fresh-session discovery remains UNKNOWN until performed. No publication,
Backplane issue operations or schedules are part of adoption.

The user approved implementation with lite. Execute the bounded implementation
plan with migration, configuration, policy adaptation and verification in order.
