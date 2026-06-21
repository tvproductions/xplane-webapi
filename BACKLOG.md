# Backlog

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

### [ ] CI/CD pipeline
- [ ] GitHub Actions: lint (`ruff check`), format (`ruff format --check`), type check (`ty check`), test (`python -m unittest discover -v`)
- [ ] Publish to PyPI on tagged release via `uv publish`
- [ ] Pre-commit hooks for local development

### [ ] Documentation improvements
- [ ] Type-annotate all examples
- [ ] Add usage patterns (connection lifecycle, monitoring datarefs, executing commands)
- [ ] Generate and publish API docs via `mkdocstrings`

### [ ] Batch dataref request optimization
- [ ] WebSocket API supports bulk subscribe/unsubscribe
- [ ] Add `monitor_datarefs()` batch helper with single round-trip
- [ ] Document performance characteristics

### [ ] Connection pooling
- [ ] Reuse `httpx.Client` across `XPRestAPI` instances when possible
- [ ] Pool configuration options (max connections, timeouts)
