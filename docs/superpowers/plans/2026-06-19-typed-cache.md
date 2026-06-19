# Typed Metadata Cache Implementation Plan

**Goal:** Replace the generic union-returning `Cache` with `DatarefCache` and `CommandCache`, so dataref cache lookups return `DatarefMeta | None` and command cache lookups return `CommandMeta | None`.

**Design:** See `docs/superpowers/specs/2026-06-19-typed-cache-design.md`.

**Constraints:**

- Preserve existing sync REST, async REST, WebSocket, and UDP behavior.
- Keep tests on stdlib `unittest`.
- Do not change cache refresh policy.
- Do not modify `examples/`.
- Avoid broad annotation modernization outside touched cache surfaces.

---

## Task 1: Add Typed Cache Tests

**Files:**
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes `DatarefCache`, `CommandCache`, `DatarefMeta`, `CommandMeta`

- [ ] **Step 1: Update imports**

Replace `Cache` test imports with `DatarefCache` and `CommandCache`.

- [ ] **Step 2: Replace generic factory tests**

Remove tests that assert `Cache.meta()` returns either metadata type. Add:

```python
DatarefCache.meta(name="sim/test/value", value_type="int", is_writable=True, id=1)
CommandCache.meta(name="sim/test/command", description="Test command", id=2)
```

Assert exact result types and field values.

- [ ] **Step 3: Add typed lookup tests**

Build each cache with loaded `_by_name` / `_by_ids` dictionaries and assert:

- `DatarefCache.get()` returns `DatarefMeta | None`
- `DatarefCache.get_by_id()` returns `DatarefMeta | None`
- `CommandCache.get()` returns `CommandMeta | None`
- `CommandCache.get_by_id()` returns `CommandMeta | None`

- [ ] **Step 4: Add load endpoint tests**

Use a dummy connected API with a mocked session.

Assert:

- `DatarefCache.load()` calls `{rest_url}/datarefs`
- `CommandCache.load()` calls `{rest_url}/commands`
- Loaded metadata dictionaries contain typed metadata objects.

- [ ] **Step 5: Run targeted test and confirm failure**

```powershell
uv run python -m unittest tests.test_api -v
```

Expected: fails until typed cache classes exist.

---

## Task 2: Implement Typed Cache Classes

**Files:**
- Modify: `xpwebapi/api.py`

**Interfaces:**
- Produces `MetaCacheBase`, `DatarefCache`, `CommandCache`
- Keeps `Cache` import compatibility if practical

- [ ] **Step 1: Extract shared cache behavior**

Rename or replace `Cache` internals with a shared base:

```python
class MetaCacheBase(ABC):
    path: str
    meta_type: type[APIObjMeta]
```

Shared behavior includes:

- `__init__`
- `load`
- `count`
- `has_data`
- `save`
- `equiv`

- [ ] **Step 2: Make `load()` endpoint-owned**

Change:

```python
cache.load("/datarefs")
```

to:

```python
cache.load()
```

`MetaCacheBase.load()` uses `self.path`.

- [ ] **Step 3: Add concrete typed caches**

Implement:

```python
class DatarefCache(MetaCacheBase):
    path = "/datarefs"

    @classmethod
    def meta(cls, **kwargs) -> DatarefMeta:
        return DatarefMeta(**kwargs)
```

```python
class CommandCache(MetaCacheBase):
    path = "/commands"

    @classmethod
    def meta(cls, **kwargs) -> CommandMeta:
        return CommandMeta(**kwargs)
```

Override or annotate `get`, `get_by_name`, and `get_by_id` with precise return types in each concrete class.

- [ ] **Step 4: Preserve compatibility name**

Keep `Cache` available from `xpwebapi.api`.

Preferred:

```python
Cache = MetaCacheBase
```

If that is too awkward for tests or type checks, create a compatibility class with a clear deprecation-oriented docstring. Internal code must not instantiate it.

- [ ] **Step 5: Update API attributes**

Change `API.__init__` annotations:

```python
self.all_datarefs: DatarefCache | None = None
self.all_commands: CommandCache | None = None
```

- [ ] **Step 6: Verify targeted API tests**

```powershell
uv run python -m unittest tests.test_api -v
```

---

## Task 3: Update Sync REST Cache Usage

**Files:**
- Modify: `xpwebapi/rest.py`
- Modify: `tests/test_rest.py` if needed

**Interfaces:**
- Consumes `DatarefCache`, `CommandCache`

- [ ] **Step 1: Update imports**

Replace `Cache` import with `DatarefCache` and `CommandCache`.

- [ ] **Step 2: Update `XPRestAPI.__init__` annotations**

```python
self.all_datarefs: DatarefCache | None = None
self.all_commands: CommandCache | None = None
```

- [ ] **Step 3: Update `reload_caches()`**

```python
self.all_datarefs = DatarefCache(self)
self.all_datarefs.load()

self.all_commands = CommandCache(self)
self.all_commands.load()
```

Only load commands when the current API version supports commands, preserving current behavior.

- [ ] **Step 4: Update metadata constructors**

In `get_rest_meta()`:

- use `DatarefCache.meta(**m0)` for `Dataref`
- use `CommandCache.meta(**m0)` for `Command`

In `dataref_meta()`, `datarefs_meta()`, and `commands_meta()`, replace `Cache.meta()` with the appropriate typed cache factory.

- [ ] **Step 5: Simplify typed cache accessors**

Remove redundant `isinstance` checks from:

- `get_dataref_meta_by_name`
- `get_dataref_meta_by_id`
- `get_command_meta_by_name`
- `get_command_meta_by_id`

- [ ] **Step 6: Run REST tests**

```powershell
uv run python -m unittest tests.test_rest -v
```

---

## Task 4: Update Async REST Cache Usage

**Files:**
- Modify: `xpwebapi/async_rest.py`
- Modify: `tests/test_async_rest.py` if needed

**Interfaces:**
- Consumes `DatarefCache`, `CommandCache`

- [ ] **Step 1: Update imports and annotations**

Replace `Cache` import with `DatarefCache` and `CommandCache`.

```python
self.all_datarefs: DatarefCache | None = None
self.all_commands: CommandCache | None = None
```

- [ ] **Step 2: Update `_fetch_rest_meta()`**

Use the expected object type to select the metadata constructor:

```python
if isinstance(obj, Dataref):
    meta = DatarefCache.meta(**metadata[0])
else:
    meta = CommandCache.meta(**metadata[0])
```

- [ ] **Step 3: Simplify typed cache accessors**

Remove redundant `isinstance` checks from the async REST `get_*_meta_*` methods.

- [ ] **Step 4: Run async REST tests**

```powershell
uv run python -m unittest tests.test_async_rest -v
```

---

## Task 5: Update Dataref and Command Cache Reads

**Files:**
- Modify: `xpwebapi/api.py`

- [ ] **Step 1: Simplify `Dataref.meta` cache branch**

When `self.api.use_cache` and `self.api.all_datarefs` is present, return the typed cache result directly when found.

- [ ] **Step 2: Simplify `Command.meta` cache branch**

When `self.api.use_cache` and `self.api.all_commands` is present, return the typed cache result directly when found.

- [ ] **Step 3: Keep fallback casts if needed**

The fallback `self.api.get_rest_meta(self)` can keep a cast because the abstract method still accepts both object types.

- [ ] **Step 4: Run API tests**

```powershell
uv run python -m unittest tests.test_api -v
```

---

## Task 6: WebSocket Regression Check

**Files:**
- Modify: `xpwebapi/ws.py` only if type or runtime issues appear

- [ ] **Step 1: Review WebSocket cache call sites**

Confirm typed return values still satisfy call sites using:

- `get_dataref_meta_by_name`
- `get_dataref_meta_by_id`
- `get_command_meta_by_name`
- `get_command_meta_by_id`
- `all_datarefs.equiv()`
- `all_commands.equiv()`

- [ ] **Step 2: Run WebSocket tests**

```powershell
uv run python -m unittest tests.test_ws -v
```

---

## Task 7: Full Verification

**Files:** None unless formatting changes are needed.

- [ ] **Step 1: Run cache/API tests**

```powershell
uv run python -m unittest tests.test_api -v
```

- [ ] **Step 2: Run affected integration surface tests**

```powershell
uv run python -m unittest tests.test_rest tests.test_async_rest tests.test_ws -v
```

- [ ] **Step 3: Run full suite**

```powershell
uv run python -m unittest discover -v
```

- [ ] **Step 4: Run lint**

```powershell
uv run ruff check xpwebapi tests
```

- [ ] **Step 5: Run format check**

```powershell
uv run ruff format --check xpwebapi tests
```

- [ ] **Step 6: Verify package import**

```powershell
uv run python -c "import xpwebapi; print(xpwebapi.version)"
```

Expected: `3.5.0`

