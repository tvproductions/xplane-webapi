# xplane-webapi Source-Layout Migration Design

- **Status:** draft
- **Date:** 2026-08-09
- **Decision owner:** Jeff / tvproductions
- **Approval:** —

## Context

The upstream devleaks repository began with the `xpwebapi` import package at
the repository root. The tvproductions fork preserved that inherited structure,
and its later `uv_build` migration encoded it with `module-root = ""`.

The flat layout was therefore a compatibility choice for an existing tree, not
a deliberate standard for current tvproductions libraries. xplane-webapi is a
packaged library and command-line application; its importable source should be
isolated from repository-root files and exercised through the installed
project.

## Decision

Move the import package from `xpwebapi/` to `src/xpwebapi/` and configure
`uv_build` with `module-root = "src"`.

The distribution name, import name, version, public API, capture command,
runtime dependencies, schemas, and installed wheel paths remain unchanged.

## Scope

The migration will:

1. move the complete tracked `xpwebapi` tree to `src/xpwebapi` while preserving
   bytes and Git history;
2. set `[tool.uv.build-backend].module-root` to `"src"`;
3. retarget quality, type, documentation, source-inspection, and release tools
   that address the physical checkout package;
4. preserve installed imports and wheel members under `xpwebapi/`;
5. update source-distribution expectations to include `src/xpwebapi/`;
6. prove repository-root imports resolve through the installed project rather
   than a top-level package directory; and
7. preserve the fork's upstream attribution and public compatibility.

No protocol, HTTP, WebSocket, UDP, capture-worker, logging, schema, or release
behavior changes in this migration.

## Repository layout

The resulting source structure is:

```text
src/
└── xpwebapi/
    ├── __init__.py
    ├── schemas/
    └── ...
```

`tests/`, `tools/`, `docs/`, and `examples/` remain at the repository root. No
root-level compatibility package or forwarding module is retained.

## Import and artifact contract

Callers continue to import `xpwebapi`. The console entry point remains:

```toml
xpwebapi-capture = "xpwebapi.capture_cli:main"
```

Source-aware checks use `src/xpwebapi`. Wheel checks continue to expect
`xpwebapi/...` because wheel installation does not expose the source-layout
directory. Source-archive checks expect `<distribution-prefix>/src/xpwebapi/...`.

The release tool reads the authoritative version from
`src/xpwebapi/__init__.py`. Packaged schemas remain under
`xpwebapi/schemas/...` in the wheel and under `src/xpwebapi/schemas/...` in the
source archive.

## Tooling changes

`tools/quality.py` targets `src/xpwebapi` for Ruff, Bandit, documentation
coverage, complexity, cohesion, and maintainability checks. Type-analysis and
annotation tests enumerate the new physical source root without changing module
names.

Release validation keeps all existing metadata, license, archive-safety,
schema, dependency, and installed-smoke checks. Only checkout and
source-archive paths change. Documentation and examples continue to use dotted
imports and should require no semantic edits.

## Test-first migration sequence

Implementation begins with failing `unittest` contracts for the new physical
layout, build-backend root, quality-tool targets, source enumeration, version
source, and source-archive paths. The package tree then moves once, followed by
the minimal path/configuration updates required by those contracts.

Verification runs the complete repository quality gate, documentation build,
distribution build/check, and installed-wheel smoke tests. The migration must
also prove that running from the repository root cannot import a root-level
checkout package.

## Failure handling

The migration stops if:

- tracked package files exist at both old and new roots;
- any active tool still enumerates the old physical source root;
- tests succeed only through repository-root import shadowing;
- wheel members acquire an unintended `src/` prefix;
- source-archive validation omits the required `src/` prefix;
- installed smoke testing resolves into the checkout; or
- public behavior, dependency metadata, or packaged schemas change.

## Acceptance criteria

- The complete runtime package exists only under `src/xpwebapi` and `uv_build`
  uses `module-root = "src"`.
- Quality, type, source-inspection, documentation, and release tooling address
  the new physical source root without weakening existing checks.
- Repository-root and installed-wheel tests prove imports resolve through the
  installed project rather than a top-level checkout package.
- Wheel members, public imports, schemas, and command entry points remain
  unchanged while source-archive members use `src/xpwebapi`.
- Full quality, documentation, distribution, and installed-artifact checks pass
  before the migration is synchronized.

## Delivery boundary

This is an independent xplane-webapi maintenance increment. It receives its own
implementation plan, review, commit, and repository sync. It does not depend on
or modify xplane-fdau runtime code.
