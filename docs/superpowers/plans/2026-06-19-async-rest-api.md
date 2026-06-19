# Async REST API Implementation Plan

**Goal:** Add opt-in async REST support via `AsyncXPRestAPI` using `httpx.AsyncClient`, with async variants of `dataref_value`, `write_dataref`, and `execute_command`, while preserving the existing sync API.

**Design:** See `docs/superpowers/specs/2026-06-19-async-rest-api-design.md`.

**Constraints:**

- Keep `XPRestAPI` behavior unchanged.
- Keep `rest_api()` returning `XPRestAPI`.
- Add `async_rest_api()` for async callers.
- Use stdlib `unittest` only.
- Do not modify `examples/` in this tranche.
- No new runtime dependencies.

---

## Task 1: Add Async REST Module Skeleton

**Files:**
- Create: `xpwebapi/async_rest.py`
- Create: `tests/test_async_rest.py`

**Interfaces:**
- Produces `AsyncXPRestAPI`
- Consumes `Dataref`, `Command`, metadata classes, `CONNECTION_STATUS`, `REST_KW`, `V1_CAPABILITIES`, and `PROXY_TCP_PORT`

- [ ] **Step 1: Create initial async test skeleton**

Create `tests/test_async_rest.py` with `unittest.IsolatedAsyncioTestCase`, a `mock_response()` helper, and an `AsyncRestAPITestCase.make_api()` helper that replaces `api.session` with a mock object exposing async `get`, `post`, `patch`, and `aclose`.

- [ ] **Step 2: Add import test**

Add a test that imports `AsyncXPRestAPI` from `xpwebapi.async_rest`.

- [ ] **Step 3: Run targeted tests and confirm failure**

```powershell
uv run python -m unittest tests.test_async_rest -v
```

Expected: import fails until the module exists.

- [ ] **Step 4: Create `xpwebapi/async_rest.py`**

Create the module with:

```python
from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING

import httpx

from .api import CONNECTION_STATUS, DATAREF_DATATYPE, Cache, Command, CommandMeta, Dataref, DatarefMeta, DatarefValueType, webapi_logger
from .rest import REST_KW, PROXY_TCP_PORT, V1_CAPABILITIES

if TYPE_CHECKING:
    from .beacon import BeaconData
```

Implement `AsyncXPRestAPI.__init__()` with the same defaults as `XPRestAPI`, using `httpx.AsyncClient`.

Do not inherit from the sync `API` abstract base. Duplicate the minimal shared state needed for URL building, status tracking, and object factories:

```python
def set_network(self, host: str, port: int, api: str, api_version: str) -> bool: ...
def _url(self, protocol: str) -> str: ...

@property
def rest_url(self) -> str: ...

def dataref(self, path: str, auto_save: bool = False) -> Dataref: ...
def command(self, path: str) -> Command: ...
```

- [ ] **Step 5: Add lifecycle methods**

Implement:

```python
async def aclose(self) -> None: ...
async def __aenter__(self) -> AsyncXPRestAPI: ...
async def __aexit__(self, exc_type, exc, tb) -> None: ...
```

- [ ] **Step 6: Verify import**

```powershell
uv run python -m unittest tests.test_async_rest -v
```

Expected: import/lifecycle tests pass after implementation.

---

## Task 2: Async Connectivity

**Files:**
- Modify: `xpwebapi/async_rest.py`
- Modify: `tests/test_async_rest.py`

**Interfaces:**
- Produces `await api.rest_api_reachable()`

- [ ] **Step 1: Add connectivity tests**

Cover:

- 200 response returns `True`
- non-200 response returns `False`
- `httpx.ConnectError` returns `False`
- successful reconnect resets `_unreach_count`

- [ ] **Step 2: Implement `rest_api_reachable()`**

Use the same probe URL as sync REST:

```python
check_url = f"http://{self.host}:{self.port}/api/v1/datarefs/count"
response = await self.session.get(check_url)
```

Update status to `REST_API_REACHABLE` or `REST_API_NOT_REACHABLE` as appropriate.

- [ ] **Step 3: Add `connected` guard**

Because `connected` cannot be awaitable, implement a conservative property:

```python
@property
def connected(self) -> bool:
    return self.status == CONNECTION_STATUS.REST_API_REACHABLE
```

Async methods must use `await self.rest_api_reachable()` for live checks.

- [ ] **Step 4: Verify**

```powershell
uv run python -m unittest tests.test_async_rest -v
```

---

## Task 3: Async Metadata Fetching

**Files:**
- Modify: `xpwebapi/async_rest.py`
- Modify: `tests/test_async_rest.py`

**Interfaces:**
- Produces `await api.get_rest_meta(obj, force=False)`

- [ ] **Step 1: Add metadata tests**

Cover:

- cached metadata returns without HTTP
- dataref metadata fetch creates `DatarefMeta`, caches it on the object, and returns it
- command metadata fetch creates `CommandMeta`, caches it on the object, and returns it
- disconnected API returns `None`
- empty metadata response returns `None`

- [ ] **Step 2: Implement `_meta_for()` helper**

```python
async def _meta_for(self, obj: Dataref | Command) -> DatarefMeta | CommandMeta | None:
    if obj._cached_meta is not None:
        return obj._cached_meta
    return await self.get_rest_meta(obj)
```

- [ ] **Step 3: Implement `get_rest_meta()`**

Mirror sync `XPRestAPI.get_rest_meta()` but await the HTTP call:

```python
response = await self.session.get(url, params=payload)
```

Use `Cache.meta(**m0)` and only cache metadata that matches the object type.

- [ ] **Step 4: Verify**

```powershell
uv run python -m unittest tests.test_async_rest -v
```

---

## Task 4: Async Dataref Read

**Files:**
- Modify: `xpwebapi/async_rest.py`
- Modify: `tests/test_async_rest.py`

**Interfaces:**
- Produces `await api.dataref_value(dataref, raw=False, no_decode=False)`

- [ ] **Step 1: Add dataref read tests**

Cover:

- scalar value response
- base64 data response decoded when `raw=False`
- encoded data returned when `raw=True`
- `None` when disconnected
- `None` when metadata cannot be resolved
- `None` on non-200 response

- [ ] **Step 2: Implement `dataref_value()`**

Use `_meta_for(dataref)` for the identifier and avoid sync `dataref.valid` / `dataref.ident`.

Build:

```python
url = f"{self.rest_url}/datarefs/{meta.ident}/value"
response = await self.session.get(url)
```

Decode base64 using the existing sync behavior.

- [ ] **Step 3: Verify**

```powershell
uv run python -m unittest tests.test_async_rest -v
```

---

## Task 5: Async Dataref Write

**Files:**
- Modify: `xpwebapi/async_rest.py`
- Modify: `tests/test_async_rest.py`

**Interfaces:**
- Produces `await api.write_dataref(dataref)`

- [ ] **Step 1: Add dataref write tests**

Cover:

- success response returns `True`
- disconnected returns `False`
- missing metadata returns `False`
- unwritable dataref returns `False`
- missing `_new_value` returns `False`
- bytes / data values are base64 encoded
- selected array element appends `?index={dataref.index}`
- non-200 response returns `False`

- [ ] **Step 2: Implement `write_dataref()`**

Use `_meta_for(dataref)` and metadata attributes directly:

```python
if not isinstance(meta, DatarefMeta):
    return False
if not meta.is_writable:
    return False
```

Build the same payload and URL as sync REST, then:

```python
response = await self.session.patch(url, json=payload)
```

- [ ] **Step 3: Verify**

```powershell
uv run python -m unittest tests.test_async_rest -v
```

---

## Task 6: Async Command Execution

**Files:**
- Modify: `xpwebapi/async_rest.py`
- Modify: `tests/test_async_rest.py`

**Interfaces:**
- Produces `await api.execute_command(command, duration=0.0)`

- [ ] **Step 1: Add command execution tests**

Cover:

- success response returns `True`
- disconnected returns `False`
- missing metadata returns `False`
- explicit duration is sent
- command default duration is used when explicit duration is `0.0`
- non-200 response returns `False`

- [ ] **Step 2: Implement `execute_command()`**

Use `_meta_for(command)` and metadata identifier directly:

```python
payload = {REST_KW.IDENT.value: meta.ident, REST_KW.DURATION.value: duration}
url = f"{self.rest_url}/command/{meta.ident}/activate"
response = await self.session.post(url, json=payload)
```

- [ ] **Step 3: Verify**

```powershell
uv run python -m unittest tests.test_async_rest -v
```

---

## Task 7: Package Exports and Factory

**Files:**
- Modify: `xpwebapi/__init__.py`
- Modify: `tests/test_async_rest.py`

**Interfaces:**
- Produces `xpwebapi.AsyncXPRestAPI`
- Produces `xpwebapi.async_rest_api()`

- [ ] **Step 1: Add export tests**

Cover:

- `from xpwebapi import AsyncXPRestAPI`
- `xpwebapi.async_rest_api()` returns an `AsyncXPRestAPI`
- existing `xpwebapi.rest_api()` still returns `XPRestAPI`

- [ ] **Step 2: Update `__init__.py`**

Add:

```python
from .async_rest import AsyncXPRestAPI
```

Add `"AsyncXPRestAPI"` and `"async_rest_api"` to `__all__`.

Add:

```python
def async_rest_api(**kwargs):
    return AsyncXPRestAPI(**kwargs)
```

- [ ] **Step 3: Verify**

```powershell
uv run python -m unittest tests.test_async_rest -v
```

---

## Task 8: Documentation

**Files:**
- Modify: `docs/usage/index.md` or `README.md`

- [ ] **Step 1: Add a short async usage example**

Document `async_rest_api()` as opt-in and keep the sync API as the default path.

- [ ] **Step 2: Include cleanup guidance**

Show `async with` as the preferred pattern. Mention `await api.aclose()` for manual lifecycle management.

- [ ] **Step 3: Verify docs formatting manually**

No generated docs build is required in this tranche unless the documentation structure demands it.

---

## Task 9: Full Verification

**Files:** None unless formatting changes are applied.

- [ ] **Step 1: Run async tests**

```powershell
uv run python -m unittest tests.test_async_rest -v
```

- [ ] **Step 2: Run full suite**

```powershell
uv run python -m unittest discover -v
```

- [ ] **Step 3: Run lint**

```powershell
uv run ruff check xpwebapi tests
```

- [ ] **Step 4: Run format check**

```powershell
uv run ruff format --check xpwebapi tests
```

- [ ] **Step 5: Verify package imports**

```powershell
uv run python -c "import xpwebapi; print(xpwebapi.version)"
```

Expected: `3.5.0`
