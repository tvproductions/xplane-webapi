# Backlog

## P0 — Critical

### Add test suite
- Add `pytest` as a dev dependency
- Create `tests/` directory with fixtures for mocking X-Plane REST/WebSocket responses
- Cover: `Dataref`, `Command`, `Cache`, `XPRestAPI`, `XPWebsocketAPI`, `XPUDPAPI`, `XPBeaconMonitor`
- Add `uv run pytest` to development workflow

### [x] Fix LSP violations in `dataref_value` / `execute_command` / `write_dataref`
- [x] `API.dataref_value` returns `DatarefReadResult` with scalar, array, bytes, and `None` support
- [x] Standardize write/execute return types with `APIResult` across the abstract base and overrides
- [x] Verify override compatibility with the type checker

### Custom exception hierarchy
- `XPWebAPIError(Exception)` as base
- `XPConnectionError`, `XPTimeoutError`, `XPVersionError`, `XPBeaconError`
- Replace bare `raise XPlaneNoBeacon()` / `raise XPlaneTimeout` with typed exceptions carrying context

## P1 — High

### Async support via `httpx.AsyncClient`
- Add `AsyncXPRestAPI` (or async mixin) using `httpx.AsyncClient`
- Async variants of `dataref_value`, `write_dataref`, `execute_command`
- Keep sync API as default; async is opt-in

### Separate `DatarefCache` and `CommandCache`
- Replace `Cache.meta()` union return (`DatarefMeta | CommandMeta`) with two typed classes
- Eliminates `isinstance` checks in `rest.py` and `ws.py`
- Fix `get_dataref_meta_*` / `get_command_meta_*` to return precise types from the cache layer

### Context manager support
- `with xpwebapi.ws_api() as api:` for automatic connect/disconnect
- `__enter__` / `__exit__` on `XPRestAPI`, `XPWebsocketAPI`, `XPUDPAPI`
- Ensure socket/thread cleanup on exit

## P2 — Medium

### Use `Protocol` instead of `ABC` for `API`
- Replace `class API(ABC)` with a `Protocol` for structural subtyping
- Removes need for abstract method stubs that return `False`

### Modernize type annotations
- Replace `List`, `Dict`, `Tuple` from `typing` with built-in `list`, `dict`, `tuple`
- Replace `Optional[X]` with `X | None`
- Use `Self` from `typing` where appropriate

### Structured logging
- Add JSON log formatter option
- Separate request/response traffic logging from application logging
- Configurable log levels per component via environment variables

### WebSocket library evaluation
- Evaluate `websockets` as replacement for `simple-websocket`
- Better async support, more active maintenance
- Benchmark and migrate if beneficial

## P3 — Low

### CI/CD pipeline
- GitHub Actions: lint (`ruff check`), format (`ruff format --check`), type check (`ty check`), test (`pytest`)
- Publish to PyPI on tagged release via `uv publish`
- Pre-commit hooks for local development

### Documentation improvements
- Type-annotate all examples
- Add usage patterns (connection lifecycle, monitoring datarefs, executing commands)
- Generate and publish API docs via `mkdocstrings`

### Batch dataref request optimization
- WebSocket API supports bulk subscribe/unsubscribe
- Add `monitor_datarefs()` batch helper with single round-trip
- Document performance characteristics

### Connection pooling
- Reuse `httpx.Client` across `XPRestAPI` instances when possible
- Pool configuration options (max connections, timeouts)
