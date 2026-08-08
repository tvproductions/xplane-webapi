# xplane-fdr Extraction Handoff

## Status

The FDR feature originally implemented on the `feature/fdr-toolkit` branch is
being extracted into its own reusable project before `xpwebapi` 4.1.0 is
released.

The user approved the architectural direction, project identity, and Python
compatibility boundary. A written core design has been placed in the new
repository and is awaiting the written-spec review gate required by the
Superpowers workflow. Do not begin implementation before that review.

## Repositories and Working Locations

- New repository: `https://github.com/tvproductions/xplane-fdr.git`
- Canonical local checkout:
  `C:\Users\Jeff\source\repos\xp\xplane-fdr`
- Existing FDR feature worktree:
  `C:\Users\Jeff\source\repos\xp\xplane-webapi\.worktrees\fdr-toolkit`
- Existing FDR feature branch: `feature/fdr-toolkit`
- Existing branch head when the extraction decision was made: `ca7d621`

The new project identity is:

- GitHub repository: `tvproductions/xplane-fdr`
- PyPI distribution: `xplane-fdr`
- Python import package: `xplane_fdr`
- Python compatibility: 3.12 and newer
- Runtime dependencies: none

Project description:

> A standard-library-only Python toolkit for reading, writing, recording,
> validating, and converting X-Plane Flight Data Recorder files, independent
> of how flight data is captured.

## Approved Architecture

`xplane-fdr` owns the capture-neutral X-Plane FDR domain:

- FDR v3 reading;
- FDR v4 reading and deterministic writing;
- immutable models and validation;
- push-first recording sessions;
- optional source and sink composition protocols;
- stock-X-Plane recording profiles;
- strict, adapter-neutral JSON recording configuration and JSON Schema;
- GeoJSON conversion;
- offline inspect, validate, and conversion commands.

It must remain standard-library-only, pure Python, and importable without
X-Plane, XPPython3, XPLM, networking, or another project.

`xpwebapi` becomes an adapter and consumer. It retains only:

- Web API DataRef resolution and subscriptions;
- translation of Web API observations into `xplane_fdr` samples;
- WebSocket connection and lifecycle behavior;
- the source-specific `xpwebapi-fdr record` command.

An XPPython3 consumer such as q4xpcc supplies an in-process XPLM adapter and
calls the same recording session from a flight-loop callback. No FDR
implementation is copied into the consumer.

The native X-Plane FDR v4 file is the persistence and interchange boundary.
The package is X-Plane-specific but neutral to how values are captured.

## Important API Refinement

The current `xpwebapi` implementation uses a pull-oriented source as its main
recording abstraction. The extracted core must instead make recording
push-first:

```python
with FDRRecordingSession.open(path, definition) as session:
    session.record(sample)
```

This works naturally from an XPPython3/XPLM flight-loop callback and from a
WebSocket sampling loop. A pull-style `record_from(source)` may remain as a
convenience implemented on top of the same session.

The core must not expose Web API observation identifiers, `CaptureRef`, XPLM
handles, threads, event loops, or connection settings in its recording model.

## Configuration Boundary

The existing profile/configuration specification places a Web API `connection`
block inside `FDRRecordConfig`. That must change during extraction.

The reusable `xplane-fdr` configuration owns only:

- schema version;
- profile selection;
- sampling policy;
- native FDR metadata;
- ordered custom DataRef declarations.

Connection parameters, output paths, overwrite permission, and adapter
lifecycle belong to the consuming application. `xpwebapi` may compose the
neutral configuration into an outer Web API-specific configuration.

## Existing Design and Implementation Inputs

Read these files from the `xpwebapi` FDR worktree before writing the
implementation plan:

- `docs/superpowers/specs/2026-08-07-fdr-toolkit-design.md`
- `docs/superpowers/specs/2026-08-08-fdr-recording-profiles-config-design.md`
- `xpwebapi/fdr/`
- `tests/test_fdr*.py`
- relevant FDR fixtures and release-artifact checks

The old specifications describe the detailed parsing, writing, GeoJSON,
profiles, failure, and verification behavior. Their assumption that the core
lives in `xpwebapi.fdr` is superseded by this extraction decision.

The new written core design is:

- `C:\Users\Jeff\source\repos\xp\xplane-fdr\docs\superpowers\specs\2026-08-08-xplane-fdr-core-design.md`

Both this feature worktree and the new repository were refreshed from the
tagged upstream Superpowers v6.2.0 release at commit
`3dcbd5c4b48e02263fbf4a3c01e3fe4f81d584d9`. The new repository has a fresh
generic installation; its project-specific operational skills must be designed
for `xplane-fdr` rather than copied verbatim from this repository.

## Required Workflow in the New Repository

The user wants the new project to follow the same Superpowers-driven workflow
and quality discipline as `xplane-webapi`.

On the next session in `xplane-fdr`:

1. Read this handoff and the complete new core design.
2. Present the written design for user review and incorporate requested
   changes.
3. After explicit approval, invoke the `writing-plans` workflow.
4. Include repository bootstrap in the implementation plan: `AGENTS.md`,
   applicable repository-local skills, `uv` packaging, lockfile, `unittest`,
   Ruff, typing, coverage, security, documentation, artifact verification, and
   trusted publishing.
5. Execute the plan in `xplane-fdr` before changing `xpwebapi` to consume it.
6. Publish and verify an initial `xplane-fdr` release.
7. Return to the `xpwebapi` feature worktree, replace duplicated core code with
   the released dependency, retain the Web API adapter, update documentation,
   and complete the planned `xpwebapi` minor release.

## Repository Rules

- Do not use pytest. Do not add, suggest, or assume it.
- Use `unittest` for automated Python tests.
- Preserve MIT attribution when moving or adapting existing code.
- Do not copy GPL implementation from `hotbso/xgs`.
- Keep the core free of all third-party runtime dependencies.
- Do not duplicate neutral FDR code between repositories.
- Do not advance the `xpwebapi` release until the reusable core is published
  and its installed artifacts have been verified.
