# Async REST API Design

**Date**: 2026-06-19
**Scope**: P1 async support for REST operations
**Approach**: Add an opt-in `AsyncXPRestAPI` backed by `httpx.AsyncClient`, preserving the existing synchronous API unchanged.

---

## Goals

- Add asynchronous REST support for callers already running an event loop.
- Keep `XPRestAPI`, `rest_api()`, WebSocket, and UDP behavior unchanged.
- Reuse existing `Dataref`, `Command`, metadata, cache, URL, and serialization logic where practical.
- Provide explicit async lifecycle management for the underlying HTTP client.
- Cover async behavior with stdlib `unittest` async tests and mocks.

## Non-Goals

- No async WebSocket implementation in this tranche.
- No conversion of `API` from `ABC` to `Protocol`.
- No redesign of cache classes.
- No dependency changes; `httpx` is already a runtime dependency.
- No breaking changes to method return semantics.

---

## Public API

### New Class

Add `AsyncXPRestAPI` in a new module:

```python
# xpwebapi/async_rest.py
class AsyncXPRestAPI:
    ...
```

The class mirrors the REST operations that can be performed asynchronously:

```python
async def aclose(self) -> None: ...

async def rest_api_reachable(self) -> bool: ...

async def get_rest_meta(self, obj: Dataref | Command, force: bool = False) -> DatarefMeta | CommandMeta | None: ...

async def dataref_value(self, dataref: Dataref, raw: bool = False, no_decode: bool = False) -> DatarefValueType | bytes | None: ...

async def write_dataref(self, dataref: Dataref) -> bool: ...

async def execute_command(self, command: Command, duration: float = 0.0) -> bool: ...
```

`AsyncXPRestAPI` intentionally uses async methods for operations that perform I/O. It does not inherit from the synchronous `API` abstract base because the sync contract exposes methods and properties that cannot be awaited. The async class duplicates the small amount of shared network state and exposes its own async contract.

The class still provides the same object factories:

```python
def dataref(self, path: str, auto_save: bool = False) -> Dataref: ...

def command(self, path: str) -> Command: ...
```

Callers should pass these objects back to async API methods instead of using sync convenience accessors like `dataref.value`, `dataref.write()`, or `command.execute()`.

### Factory and Exports

Update `xpwebapi/__init__.py`:

```python
from .async_rest import AsyncXPRestAPI

def async_rest_api(**kwargs):
    return AsyncXPRestAPI(**kwargs)
```

Add `"AsyncXPRestAPI"` and `"async_rest_api"` to `__all__`.

Existing code continues to use:

```python
api = xpwebapi.rest_api()
```

Async callers can use:

```python
api = xpwebapi.async_rest_api()
try:
    value = await api.dataref_value(api.dataref("sim/test/value"))
finally:
    await api.aclose()
```

---

## Lifecycle

`AsyncXPRestAPI` owns an `httpx.AsyncClient`:

```python
self.session = httpx.AsyncClient(headers={"Accept": "application/json", "Content-Type": "application/json"})
```

The initial lifecycle API is explicit:

```python
await api.aclose()
```

Optional async context manager support can be included because it is low risk and directly tied to client cleanup:

```python
async with xpwebapi.async_rest_api() as api:
    value = await api.dataref_value(api.dataref("sim/test/value"))
```

Implementation:

```python
async def __aenter__(self) -> AsyncXPRestAPI:
    return self

async def __aexit__(self, exc_type, exc, tb) -> None:
    await self.aclose()
```

Sync context manager support remains out of scope.

---

## Connectivity

The sync `XPRestAPI.connected` property cannot be awaited. For async code, expose:

```python
async def rest_api_reachable(self) -> bool:
    ...
```

Async operation methods call `await self.rest_api_reachable()` before issuing requests, matching the sync behavior without introducing an awaitable property.

The probe URL remains:

```python
http://{host}:{port}/api/v1/datarefs/count
```

Connection failures return `False` and set status to `REST_API_NOT_REACHABLE`, consistent with `XPRestAPI`.

---

## Metadata and Datarefs

`Dataref.meta`, `Command.meta`, `Dataref.valid`, `Dataref.value`, `Dataref.write()`, and `Command.execute()` are synchronous properties or methods today. They cannot transparently call async I/O and should not be used as the primary async calling style.

The async API therefore supports two safe paths:

1. Use cached metadata on `Dataref` / `Command` objects before async operations.
2. Call `await api.get_rest_meta(obj)` explicitly to populate `_cached_meta`.

Async methods should avoid using `dataref.valid`, `dataref.ident`, `dataref.is_writable`, and `command.valid` when those properties might perform sync I/O through `obj.meta`.

Instead, async methods use a helper:

```python
async def _meta_for(self, obj: Dataref | Command) -> DatarefMeta | CommandMeta | None:
    if obj._cached_meta is not None:
        return obj._cached_meta
    return await self.get_rest_meta(obj)
```

This keeps async operations non-blocking while preserving existing object models. The async implementation should also expose `use_cache`, `all_datarefs`, and `all_commands` attributes for compatibility with the existing objects, but async methods must not depend on sync metadata properties.

---

## Return Semantics

Match sync REST behavior:

| Method | Success | Not connected / invalid / error |
|---|---:|---:|
| `dataref_value` | `DatarefValueType | bytes` | `None` |
| `write_dataref` | `True` | `False` |
| `execute_command` | `True` | `False` |
| `get_rest_meta` | `DatarefMeta | CommandMeta` | `None` |
| `rest_api_reachable` | `True` | `False` |

Unlike WebSocket operations, async REST does not return request IDs, so `write_dataref` and `execute_command` return `bool`.

---

## Serialization Behavior

`AsyncXPRestAPI.dataref_value()` follows sync REST behavior:

- `raw=False` decodes base64 string data responses when possible.
- `raw=True` returns the encoded response value as provided by the API.
- Non-data scalar values are returned unchanged.
- Error responses return `None`.

`AsyncXPRestAPI.write_dataref()` follows sync REST behavior:

- Rejects missing metadata.
- Rejects unwritable datarefs.
- Rejects missing new values.
- Base64-encodes `data` / `bytes` values through existing `Dataref.b64encoded`.
- Adds `?index={index}` for selected array element writes.

`AsyncXPRestAPI.execute_command()` follows sync REST behavior:

- Uses `command.duration` when explicit `duration` is `0.0`.
- Sends command identifier and duration to `/command/{ident}/activate`.

---

## Testing

Add `tests/test_async_rest.py` using `unittest.IsolatedAsyncioTestCase`.

Mock `httpx.AsyncClient` behavior with `AsyncMock` and controlled response objects. Tests should not require network access or a running simulator.

Coverage:

- `rest_api_reachable()` returns `True` on 200.
- `rest_api_reachable()` returns `False` on non-200.
- `rest_api_reachable()` returns `False` on `httpx.ConnectError`.
- `get_rest_meta()` returns cached metadata without HTTP.
- `get_rest_meta()` fetches and caches `DatarefMeta`.
- `get_rest_meta()` fetches and caches `CommandMeta`.
- `dataref_value()` returns scalars.
- `dataref_value()` decodes base64 data values.
- `dataref_value(raw=True)` returns encoded data.
- `dataref_value()` returns `None` when disconnected or on error.
- `write_dataref()` returns `True` on 200.
- `write_dataref()` rejects unwritable datarefs.
- `write_dataref()` handles selected array element URLs.
- `execute_command()` returns `True` on 200.
- `execute_command()` applies command default duration.
- `aclose()` awaits `AsyncClient.aclose()`.
- `async with AsyncXPRestAPI(...)` closes the client on exit.

Verification commands:

```powershell
uv run python -m unittest tests.test_async_rest -v
uv run python -m unittest discover -v
uv run ruff check xpwebapi tests
uv run ruff format --check xpwebapi tests
```

---

## Documentation

Add a short async usage section to `docs/usage/index.md` or `README.md`:

```python
import asyncio
import xpwebapi

async def main():
    async with xpwebapi.async_rest_api() as api:
        dataref = api.dataref("sim/time/total_running_time_sec")
        value = await api.dataref_value(dataref)
        print(value)

asyncio.run(main())
```

Keep the sync examples as the default path.

---

## Risks

- Existing `Dataref` and `Command` convenience methods remain sync; async callers must call API methods directly with `await`.
- Async cache loading is not included in the minimum tranche, so metadata fetches are per-object unless cached on the object.
- The async class initially duplicates network setup helpers from `API`. A later refactor can extract a non-abstract shared base if duplication grows.
