# Agent Instructions

Read [AGENTS.skills-first.md](AGENTS.skills-first.md) for the adopted workflow
stack, Python 3.12 policy and mandatory uv-managed environment.

## Testing

- **NO pytest. EVER.** Do not add, suggest, or assume pytest as a testing framework.
- Do not reference the "Add test suite" backlog item that specifies pytest.

## Release planning and version advancement

PRDs guide major releases; selected work and requirements drive minor releases;
fixes drive patch releases. Follow the canonical starter policy at
https://github.com/tvproductions/gz-skills-first-starter/blob/main/docs/versioning.md#plan-releases-from-their-governing-work
and this project binding. Every major, including 1.0.0, requires a newly written
PRD defining that major's outcomes, requirements and acceptance criteria.

Before implementation planning, identify the release scope served by the work.
Keep a current release-scope record in this project's existing backlog, roadmap
or release authority: actual last published version/tag/revision (or evidence of
no prior release), proposed next version, governing PRD/requirements/fixes,
included completed and remaining work, deferred work, compatibility impact and
acceptance gates. Reconcile completed changes into that record before closeout.
Missing scope/version evidence blocks release-preparation acceptance. Do not
silently shrink approved scope or include the entire future backlog in one release.

Apply SemVer to the complete selected scope since the published baseline.
After 1.0, incompatible contracts require major, compatible requirements/capability
or public deprecations require minor, and compatible fixes require patch. During
0.x, requirements/capability and incompatible changes require minor; compatible
fixes require patch. Multiple tasks in one release share its pending version.
An initial unpublished 0.1.0 may cover an explicitly selected first-release scope;
review scope growth instead of using unpublished status to avoid release accounting.
Keep metadata/runtime mirrors, affected lock metadata and changelog aligned when
the pending version is selected. Preserve published versions/tags, independent
product/template/plugin versions and existing release gates. These instructions
do not authorize publication or enable deferred Backplane.

### Required version decision checks

At requirements intake, planning and closeout, agents MUST derive the pending
target from the actual published baseline and the complete pending scope.
Identify the new major PRD, selected minor requirements or commitment corrected
by a patch. A ticket labeled fix cannot turn new requirements into patch work.
Use the highest required increment and reset lower components: 1.4.2 becomes
1.4.3 for fixes, 1.5.0 for compatible requirements, or 2.0.0 for a breaking
major guided by a newly written PRD. During 0.x, requirements drive 0.4.2 to
0.5.0; compatible fixes drive 0.4.3. Reuse an adequate pending target rather
than incrementing once per task. Reconcile version mirrors and changelog in
the same authorized change; do not ask the maintainer to choose routine numbers.

Require a finite release outcome, included requirements, exclusions and an
acceptance gate, including for the initial 0.1.0. Assign future requirements
to later minor bundles. Preserve approved scope; ask only for unresolved
product decisions. Missing required PRD, scope or consistent version evidence
blocks the applicable planning and closeout claims as well as release preparation.
Report published baseline -> pending target, governing source, compatibility,
version agreement, completed/remaining/deferred work and publication status.
A selected target does not assert readiness or authorize publication. Use the
canonical policy's required-version-decision-procedure; keep the record in
existing project authorities rather than creating another tracker.

### November 1, 2026 local release-accounting review

Published baseline is v4.0.0 (2026-07-26). Its requires-python contract is
>=3.12,<3.14; the pending working tree narrows it to >=3.12,<3.13 while retaining
version 4.0.0. Dropping supported Python 3.13 is incompatible: either retain
published support or select a new-PRD-guided 5.0.0 scope before shipping that
removal. Compatible new API/FDR requirements instead drive a selected 4.1.0
bundle; compatible fixes alone drive 4.0.1. BACKLOG.md and linked issues/specs
retain scope authority. These are conditional classifications, not approval of a
new major or a reversal of the approved runtime decision. Preserve the existing
dirty adoption work and immutable v4.0.0 history.

Reviewed source: starter base commit
`8d090f88bf45b9a755808a62c1445beeb005daff` plus the authorized, uncommitted
0.8.1 clarification. This is development guidance, not a published template
upgrade. Reviewed `docs/versioning.md` SHA-256:
`960cc4052cb87696980be23a393553079f254ac8105240dbcbac5244a52c4460`;
`templates/AGENTS.skills-first.md` SHA-256:
`0383bc3330756600b2d9e0ae2393af0143836b7e6bc3b5b8d407e39f361b51b4`.
No adoption lock, component pin, plugin activation or product version is changed.
