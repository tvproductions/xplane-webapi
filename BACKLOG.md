# Backlog

GitHub Issues are the actionable backlog for this independently maintained
fork. This file is the concise priority index; detailed scope, decisions,
progress, and acceptance evidence belong in the linked issues and their
Superpowers specifications and plans. Changes from `devleaks/xplane-webapi`
are reviewed selectively and are not merged wholesale.

## Active roadmap

1. [Complete the `src/xpwebapi` source-layout migration](https://github.com/tvproductions/xplane-webapi/issues/2)
2. [Add typed X-Plane API v3 flight management](https://github.com/tvproductions/xplane-webapi/issues/3)
3. [Add configurable NUL-byte replacement for decoded DataRefs](https://github.com/tvproductions/xplane-webapi/issues/4)
4. [Integrate and verify the FDR toolkit](https://github.com/tvproductions/xplane-webapi/issues/5)
5. [Design an optional FDR flight and telemetry viewer](https://github.com/tvproductions/xplane-webapi/issues/6)
6. [Establish a recurring upstream-intake workflow](https://github.com/tvproductions/xplane-webapi/issues/7)

## Release scope

- The published baseline is `v4.0.0` (2026-07-26), commit
  `2518aed3b234bf3aca73323d452f33628258d65f`, with Python support `>=3.12,<3.14`.
- The [skills-first adoption record](docs/superpowers/skills-first-adoption.md)
  covers the completed adoption of native skills, frozen uv workflows, and
  the Python `>=3.12,<3.13` support policy. Dropping Python 3.13 is a
  breaking compatibility change despite an unchanged Python client API.
- Shipping that removal requires `5.0.0` and a new major PRD. The release
  scope and target remain unapproved. Package metadata, runtime version and
  lock metadata still agree on `4.0.0`, with the changes under Unreleased in
  the changelog. Before release, approve the PRD and finite scope, reconcile
  version mirrors and changelog, and pass the existing quality, packaging,
  installed-wheel and tag gates.
- Implementation of the active roadmap remains pending. Individual items enter
  a release through its approved scope. Backplane stays deferred under the
  adoption record.

## P0 — Critical

### [x] Expand unittest coverage
- [x] Add shared `unittest` helpers for mocking X-Plane REST/WebSocket responses
- [x] Fill remaining coverage gaps for `Dataref`, `Command`, `Cache`, `XPRestAPI`, `XPWebsocketAPI`, `XPUDPAPI`, `XPBeaconMonitor`
- [x] Keep `uv run python -m unittest discover -v` as the test workflow

### [x] Fix LSP violations in `dataref_value` / `execute_command` / `write_dataref`
- [x] `API.dataref_value` returns `DatarefReadResult` with scalar, array, bytes, and `None` support
- [x] Standardize write/execute return types with `APIResult` across the abstract base and overrides
- [x] Verify override compatibility with the type checker

### [x] Custom exception hierarchy
- [x] `XPWebAPIError(Exception)` as base
- [x] `XPConnectionError`, `XPTimeoutError`, `XPVersionError`, `XPBeaconError`
- [x] Replace bare `raise XPlaneNoBeacon()` / `raise XPlaneTimeout` with typed exceptions carrying context

## P1 — High

### [x] Async support via `httpx.AsyncClient`
- [x] Add `AsyncXPRestAPI` (or async mixin) using `httpx.AsyncClient`
- [x] Async variants of `dataref_value`, `write_dataref`, `execute_command`
- [x] Keep sync API as default; async is opt-in

### [x] Separate `DatarefCache` and `CommandCache`
- [x] Replace `Cache.meta()` union return (`DatarefMeta | CommandMeta`) with two typed classes
- [x] Eliminates `isinstance` checks in `rest.py` and `ws.py`
- [x] Fix `get_dataref_meta_*` / `get_command_meta_*` to return precise types from the cache layer

### [x] Context manager support
- [x] `with xpwebapi.ws_api() as api:` for automatic connect/disconnect
- [x] `__enter__` / `__exit__` on `XPRestAPI`, `XPWebsocketAPI`, `XPUDPAPI`
- [x] Ensure socket/thread cleanup on exit

## P2 — Medium

### [x] Use `Protocol` instead of `ABC` for `API`
- [x] Replace `class API(ABC)` with a `Protocol` for structural subtyping
- [x] Removes need for abstract method stubs that return `False`

### [x] Modernize type annotations
- [x] Replace `List`, `Dict`, `Tuple` from `typing` with built-in `list`, `dict`, `tuple`
- [x] Replace `Optional[X]` with `X | None`
- [x] Use `Self` from `typing` where appropriate

### [x] Structured logging
- [x] Add JSON log formatter option
- [x] Separate request/response traffic logging from application logging
- [x] Configurable log levels per component via JSON configuration

### [x] WebSocket library evaluation
- [x] Evaluate `websockets` as replacement for `simple-websocket`
- [x] Better async support, more active maintenance
- [x] Benchmark and migrate if beneficial

## P3 — Low

### [x] CI/CD pipeline
- [x] GitHub Actions: lint (`ruff check`), format (`ruff format --check`), type check (`ty check`), test (`python -m unittest discover -v`), and package build validation (`uv build`)
- [x] Publish version 4.0.0 to PyPI from the tagged release workflow
- [x] Pre-commit hooks for local development
- [x] Preserve MkDocs deployment on pushes to `main`

### [x] Documentation improvements
- [x] Type-annotate all examples
- [x] Add usage patterns (connection lifecycle, monitoring datarefs, executing commands)
- [x] Generate and publish API docs via `mkdocstrings`

### [x] Batch dataref request optimization
- [x] WebSocket API supports bulk subscribe/unsubscribe
- [x] Add `monitor_datarefs()` batch helper with single round-trip
- [x] Document performance characteristics

### [x] Connection pooling
- [x] Reuse `httpx.Client` across `XPRestAPI` instances when possible
- [x] Pool configuration options (max connections, timeouts)
