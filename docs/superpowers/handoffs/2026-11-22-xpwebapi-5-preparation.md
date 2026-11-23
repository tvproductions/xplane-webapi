# xpwebapi 5.0.0 preparation handoff

## Resume here

Start at [issue #2](https://github.com/tvproductions/xplane-webapi/issues/2)
and [Task 0 of the source-layout plan](../plans/2026-08-09-src-layout-migration.md#task-0-capture-the-flat-layout-500-baseline).
Issue #2 is open and now specifies Python 3.12.16. The plan is still a draft.
Verify the checkpoint and the current approval record before taking action.
Obtain explicit approval of this plan before starting implementation. Once
approved, build the flat-layout baseline artifacts from the checkpoint in an
isolated worktree. Expect one validated 5.0.0 wheel and one source archive with
the package under the original archive paths.

## Checkpoint and authority

This handoff was prepared on 2026-11-22 in the xplane-webapi checkout on
`main`, based on `ede999f`. The commit that introduces this file identifies
the flat-layout 5.0.0 preparation checkpoint. Locate it from the repository
root and check the current branch and working tree.

```powershell
git status -sb
git log --diff-filter=A -1 --format=%H -- docs/superpowers/handoffs/2026-11-22-xpwebapi-5-preparation.md
```

The maintainer approved the finite [5.0.0 PRD](../specs/2026-11-22-xpwebapi-5.0.0-prd.md)
and authorized this handoff and Git sync. The
[release-scope record](../../../BACKLOG.md#release-scope) tracks the published
`v4.0.0` baseline, the Python 3.13 support removal, the HTTPX2 transition,
and the pending 5.0.0 target. Package, runtime, lock, CI smoke, and changelog
versions agree. Version 5.0.0 is unpublished.

Source layout is first, followed by the typed flight API and FDR integration
in the order set by the PRD. The proposed
[capture settings ADR-0001, edition 1](../specs/ADR-0001-001-resolve-capture-settings-before-worker-launch.md)
awaits separate architectural approval. Review feedback asks for an explicit
field allowlist and launcher path preflight before writing the resolved
request. The ADR text remains the original proposal. NUL handling, the FDR
viewer, upstream intake, and Backplane activation remain deferred.

## Verification and open work

On Windows with uv-managed Python 3.12.16, the repository hygiene script
passed the offline lock check, 527 tests, 84% coverage, and all pre-commit
hooks. Ruff and strict MkDocs passed. A fresh offline build produced
`xpwebapi-5.0.0-py3-none-any.whl` and `xpwebapi-5.0.0.tar.gz`. Both passed
strict Twine and `tools/release.py check-dist`. The wheel passed the isolated
`tools/installed_smoke.py` check outside the checkout. Those verification
artifacts were temporary.

The migration plan now records the staged candidate tree and compares it with
the committed tree. Its archive comparison matched all 23 package files in
valid wheel and source-archive fixtures and rejected conflicting duplicate
member paths. The plan requires a fresh `origin/main` check before closing
issue #2. These checks exercised the plan and fixtures. The runtime package
still lives at `xpwebapi/`.

Run Task 0 from the committed checkpoint to establish the comparison artifacts
for actual migration verification. The plan then requires repository hygiene,
strict docs, artifact parity, and isolated installed-wheel smoke on the exact
migration candidate. Simulator acceptance for the later capabilities and
publication remain governed by the PRD and release workflow.
