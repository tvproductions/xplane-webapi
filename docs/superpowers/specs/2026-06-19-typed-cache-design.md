# Typed Metadata Cache Design

**Date**: 2026-06-19
**Scope**: P1 separate `DatarefCache` and `CommandCache`
**Approach**: Replace the generic metadata cache behavior with typed cache classes while preserving the public object model and existing sync/async REST behavior.

---

## Goals

- Split generic cache storage into `DatarefCache` and `CommandCache`.
- Remove the heuristic `Cache.meta()` factory that decides type based on `"is_writable" in kwargs`.
- Make dataref cache lookups return `DatarefMeta | None`.
- Make command cache lookups return `CommandMeta | None`.
- Remove avoidable `isinstance` checks from REST and async REST metadata lookup paths.
- Preserve existing public methods such as `get_dataref_meta_by_name()`, `get_command_meta_by_id()`, `Dataref.meta`, and `Command.meta`.
- Keep WebSocket code behavior unchanged while benefiting from more precise return types.

## Non-Goals

- No cache refresh policy changes.
- No async cache loading in this tranche.
- No `Protocol` conversion for `API`.
- No modern type annotation sweep outside touched cache surfaces.
- No dependency changes.

---

## Current State

`xpwebapi.api.Cache` currently stores either `DatarefMeta` or `CommandMeta`.

```python
@classmethod
def meta(cls, **kwargs) -> DatarefMeta | CommandMeta:
    return DatarefMeta(**kwargs) if "is_writable" in kwargs else CommandMeta(**kwargs)
```

That creates a union return at the cache layer. Callers then compensate with `isinstance()` checks:

```python
r = self.all_datarefs.get_by_name(path)
return r if isinstance(r, DatarefMeta) else None
```

The cache type is already known at the assignment site:

```python
self.all_datarefs = Cache(self)
self.all_datarefs.load("/datarefs")
self.all_commands = Cache(self)
self.all_commands.load("/commands")
```

So the union type is unnecessary and makes type checking less precise.

---

## Proposed API

Create a shared implementation base and two typed concrete caches in `xpwebapi/api.py`.

```python
class MetaCacheBase(ABC):
    path: str

    def __init__(self, api) -> None: ...
    def load(self) -> None: ...
    def save(self, filename: str) -> None: ...
    def equiv(self, ident: int) -> str | None: ...

    @property
    def count(self) -> int: ...

    @property
    def has_data(self) -> bool: ...
```

```python
class DatarefCache(MetaCacheBase):
    path = "/datarefs"

    @classmethod
    def meta(cls, **kwargs) -> DatarefMeta: ...
    def get(self, name: str) -> DatarefMeta | None: ...
    def get_by_name(self, name: str) -> DatarefMeta | None: ...
    def get_by_id(self, ident: int) -> DatarefMeta | None: ...
```

```python
class CommandCache(MetaCacheBase):
    path = "/commands"

    @classmethod
    def meta(cls, **kwargs) -> CommandMeta: ...
    def get(self, name: str) -> CommandMeta | None: ...
    def get_by_name(self, name: str) -> CommandMeta | None: ...
    def get_by_id(self, ident: int) -> CommandMeta | None: ...
```

`load()` no longer accepts a path argument. Each concrete cache owns its endpoint.

```python
self.all_datarefs = DatarefCache(self)
self.all_datarefs.load()

self.all_commands = CommandCache(self)
self.all_commands.load()
```

---

## Compatibility

The preferred implementation should keep a `Cache` compatibility alias for one release cycle:

```python
Cache = MetaCacheBase
```

But new code should not instantiate `Cache` directly.

Tests and internal call sites should move to `DatarefCache` and `CommandCache`.

If a compatibility alias creates type or runtime confusion, define a small compatibility subclass that raises a clear error when `load()` is used without a concrete metadata type. The primary goal is to remove internal generic use, not to expand the public cache API.

---

## Type Surface Changes

Update object attributes:

```python
self.all_datarefs: DatarefCache | None = None
self.all_commands: CommandCache | None = None
```

Apply in:

- `API.__init__`
- `XPRestAPI.__init__`
- `AsyncXPRestAPI.__init__`

Update imports in `rest.py` and `async_rest.py`:

```python
from .api import DatarefCache, CommandCache
```

---

## REST Metadata Construction

Replace generic metadata construction:

```python
m = Cache.meta(**m0)
```

with type-directed construction:

```python
if isinstance(obj, Dataref):
    m = DatarefCache.meta(**m0)
else:
    m = CommandCache.meta(**m0)
```

For dedicated methods:

```python
def dataref_meta(...) -> DatarefMeta | None:
    return DatarefCache.meta(**data[0])

def datarefs_meta(...) -> list[DatarefMeta]:
    return [DatarefCache.meta(**m) for m in data]

def commands_meta(...) -> list[CommandMeta]:
    return [CommandCache.meta(**m) for m in data]
```

This removes the union from construction paths where the expected type is known.

---

## Lookup Simplification

The typed caches let these methods avoid `isinstance()` guards:

```python
def get_dataref_meta_by_name(self, path: str) -> DatarefMeta | None:
    if self.all_datarefs is not None:
        return self.all_datarefs.get_by_name(path)
    return None
```

Equivalent changes apply to:

- `get_dataref_meta_by_id`
- `get_command_meta_by_name`
- `get_command_meta_by_id`

Both sync REST and async REST should be updated.

---

## Dataref and Command Objects

`Dataref.meta` and `Command.meta` can drop casts around cache reads because the caches are typed:

```python
return self.api.all_datarefs.get(self.path)
```

The fallback `self.api.get_rest_meta(self)` still returns a union because `API.get_rest_meta()` accepts both object types. It can keep the existing cast unless a later refactor adds object-specific abstract methods.

---

## Tests

Update `tests/test_api.py`:

- Replace `TestCache` union factory tests with:
  - `TestDatarefCache`
  - `TestCommandCache`
- Verify `DatarefCache.meta()` returns `DatarefMeta`.
- Verify `CommandCache.meta()` returns `CommandMeta`.
- Verify each cache loads the correct endpoint.
- Verify typed `get`, `get_by_name`, and `get_by_id` return the expected metadata type.
- Verify `equiv()` still works.
- Verify failed load leaves cache empty.

Update REST tests if needed:

- Ensure `get_dataref_meta_by_name()` and `get_command_meta_by_name()` return exact metadata instances from typed caches.
- Ensure `get_rest_meta()` still caches the constructed metadata on the object.

Update async REST tests if needed:

- Ensure async metadata construction uses typed cache factories.

Verification commands:

```powershell
uv run python -m unittest tests.test_api -v
uv run python -m unittest tests.test_rest tests.test_async_rest tests.test_ws -v
uv run python -m unittest discover -v
uv run ruff check xpwebapi tests
uv run ruff format --check xpwebapi tests
```

---

## Risks

- `Cache.load(path)` may be used by downstream consumers even if not documented. Keeping a compatibility `Cache` name reduces import breakage, but direct construction may still change behavior.
- `Dataref` and `Command` annotations currently point at `API`; async REST intentionally does not inherit from `API`, so touched annotations should remain pragmatic and avoid broad object-model refactors.
- WebSocket code relies on `all_datarefs.equiv()` and `all_commands.equiv()` for diagnostics. The shared cache base must preserve that behavior exactly.

