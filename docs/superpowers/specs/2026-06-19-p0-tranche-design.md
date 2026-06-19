# P0 Tranche Design: Exceptions, LSP Fixes, Test Suite

**Date**: 2026-06-19
**Scope**: BACKLOG.md P0 items — Custom exception hierarchy, LSP violation fixes, unittest test suite
**Approach**: Minimal & focused (Approach A) — fix violations without redesigning return type contracts
**Implementation order**: Exceptions → LSP fixes → Tests

---

## 1. Custom Exception Hierarchy

### New file: `xpwebapi/exceptions.py`

```
XPWebAPIError(Exception)
├── XPConnectionError
│   └── XPBeaconError
├── XPTimeoutError
└── XPVersionError
```

All exceptions carry optional context via kwargs:

```python
class XPWebAPIError(Exception):
    def __init__(self, message: str = "", **context: Any):
        self.context = context
        super().__init__(message)

class XPConnectionError(XPWebAPIError):
    pass

class XPBeaconError(XPConnectionError):
    pass

class XPTimeoutError(XPWebAPIError):
    pass

class XPVersionError(XPWebAPIError):
    pass
```

### Backward compatibility

Existing exception classes become subclasses of the new hierarchy, preserving the old names for downstream consumers:

**`beacon.py`**:
```python
from .exceptions import XPBeaconError, XPVersionError

class XPlaneNoBeacon(XPBeaconError):
    pass

class XPlaneVersionNotSupported(XPVersionError):
    pass
```

**`udp.py`**:
```python
from .exceptions import XPTimeoutError

class XPlaneTimeout(XPTimeoutError):
    pass
```

### Call site updates

All `raise XPlaneNoBeacon()` and `raise XPlaneTimeout` sites updated to pass context:

- `beacon.py:320` — `raise XPlaneNoBeacon("no beacon received", timeout=timeout)`
- `beacon.py:314` — `raise XPlaneVersionNotSupported(f"version {beacon_major_version}.{beacon_minor_version}.{application_host_id}")`
- `udp.py:337` — `raise XPlaneTimeout("UDP read timeout")`

### Exports

`__init__.py` updated to export new exceptions alongside existing ones:

```python
from .exceptions import XPWebAPIError, XPConnectionError, XPBeaconError, XPTimeoutError, XPVersionError
```

Old names (`XPlaneNoBeacon`, `XPlaneVersionNotSupported`, `XPlaneTimeout`) remain exported.

---

## 2. LSP Violation Fixes

### File: `xpwebapi/api.py`

#### 2a. Remove `**kwargs` from `dataref_value` abstract signature

Current:
```python
@abstractmethod
def dataref_value(self, dataref: Dataref, raw: bool = False, **kwargs) -> DatarefValueType | bytes | None:
```

Change to explicit parameters matching what REST override actually uses:
```python
@abstractmethod
def dataref_value(self, dataref: Dataref, raw: bool = False, no_decode: bool = False) -> DatarefValueType | bytes | None:
```

The UDP override (`udp.py:188`) currently accepts `**kwargs` — update to match:
```python
def dataref_value(self, dataref: Dataref, raw: bool = False, no_decode: bool = False) -> DatarefValueType | bytes | None:
```

#### 2b. Standardize return types

| Method | Current abstract return | New abstract return | Rationale |
|---|---|---|---|
| `write_dataref` | `bool \| int` | `bool \| int` | No change needed. REST returns `bool`, WS returns `bool \| int`. Both satisfy contract. |
| `execute_command` | `bool \| int` | `bool \| int` | No change needed. Same as above. |
| `dataref_value` | `DatarefValueType \| bytes \| None` | `DatarefValueType \| bytes \| None` | No change needed. |

#### 2c. Remove `return False` stubs from abstract methods

Replace `return False` with `...` (Ellipsis) in abstract method bodies:

- `api.py:249` — `connected` property: `return False` → `...`
- `api.py:359` — `write_dataref`: `return False` → `...`
- `api.py:371` — `dataref_value`: `return False` → `...`
- `api.py:384` — `execute_command`: `return False` → `...`

Abstract methods should not have implementations. The `return False` stubs mislead type checkers and violate the Liskov Substitution Principle by implying a concrete return value.

#### 2d. No changes to overrides

`rest.py`, `ws.py`, and `udp.py` override signatures already satisfy the corrected abstract contracts. No changes needed beyond the `dataref_value` kwargs fix in `udp.py`.

---

## 3. Test Suite

### Framework

`unittest` (Python stdlib). No additional dev dependencies.

Run command: `uv run python -m unittest discover`

### Structure

```
tests/
├── __init__.py
├── test_exceptions.py   # Exception hierarchy, context, backward compat
├── test_api.py          # Dataref, Command, Cache, ValueCache, APIObjMeta
├── test_rest.py         # XPRestAPI (mocked httpx.Client)
├── test_ws.py           # XPWebsocketAPI (mocked simple-websocket Client)
├── test_beacon.py       # XPBeaconMonitor (mocked socket)
└── test_udp.py          # XPUDPAPI (mocked socket)
```

### Mocking strategy

- **REST tests**: `unittest.mock.patch` on `httpx.Client.get`/`post`/`patch` — return mock `Response` objects with controlled `status_code` and `.json()`
- **WebSocket tests**: `unittest.mock.patch` on `simple_websocket.Client.connect` — return mock `Client` with `.send()`/`.receive()`
- **Beacon/UDP tests**: `unittest.mock.patch` on `socket.socket` — mock `recvfrom()` with crafted beacon/RREF packets
- No network access, no X-Plane instance required

### Coverage targets

**`test_exceptions.py`**:
- `XPWebAPIError` carries context kwargs
- Inheritance chain: `XPBeaconError` is `XPConnectionError` is `XPWebAPIError`
- `XPTimeoutError` is `XPWebAPIError`
- `XPVersionError` is `XPWebAPIError`
- Backward compat: `XPlaneNoBeacon` is `XPBeaconError`, `XPlaneTimeout` is `XPTimeoutError`, `XPlaneVersionNotSupported` is `XPVersionError`

**`test_api.py`**:
- `DatarefMeta` — construction, `is_array`, `append_index`/`remove_index`, `save_indices`/`last_indices`
- `CommandMeta` — construction
- `Cache` — `meta()` factory returns `DatarefMeta` or `CommandMeta` based on `is_writable` key, `get_by_name`/`get_by_id`
- `ValueCache` — `get_rounding` (plain, array root, wildcard), `changed` (rounding applied, no change detected)
- `Dataref` — `parse_raw_value` (scalar int/float, array with indices, base64 data), `value` property, `write()` delegation, `monitor()`/`unmonitor()` delegation
- `Command` — `execute()` delegation, `monitor()`/`unmonitor()` delegation

**`test_rest.py`**:
- `XPRestAPI.connected` — mocked 200 → True, mocked ConnectError → False
- `XPRestAPI.dataref_value` — mocked 200 with JSON response, base64 decode path, error path
- `XPRestAPI.write_dataref` — mocked 200 → True, mocked 400 → False, not connected → False, not writable → False
- `XPRestAPI.execute_command` — mocked 200 → True, mocked error → False
- `XPRestAPI.reload_caches` — mocked datarefs/commands responses
- `XPRestAPI.get_rest_meta` — mocked filter response

**`test_ws.py`**:
- `XPWebsocketAPI.send` — request ID increment, payload construction
- `XPWebsocketAPI.connect_websocket` — mocked Client.connect success/failure
- `XPWebsocketAPI.disconnect_websocket` — graceful close, callbacks executed
- `XPWebsocketAPI.set_dataref_value` — payload construction with array index
- `XPWebsocketAPI.register_bulk_dataref_value_event` — subscribe/unsubscribe payload

**`test_beacon.py`**:
- `XPBeaconMonitor.get_beacon` — valid BECN packet decoded correctly, timeout raises `XPlaneNoBeacon`, bad header logged
- `XPBeaconMonitor.start_monitor`/`stop_monitor` — thread lifecycle
- `XPBeaconMonitor.same_host` — IP comparison logic
- `XPBeaconMonitor.callback` — multiple callbacks executed, exception in callback handled

**`test_udp.py`**:
- `XPUDPAPI.write_dataref` — correct struct packing, socket.sendto called
- `XPUDPAPI.read_monitored_dataref_values` — RREF packet decoded, timeout raises `XPlaneTimeout`
- `XPUDPAPI._request_dataref` — RREF request sent, subscribe/unsubscribe (freq=0)

### Dev workflow

No changes to `pyproject.toml` dependencies. Test command:

```
uv run python -m unittest discover
```

---

## Out of scope (deferred to P1+)

- `Cache.meta()` union return type (`DatarefMeta | CommandMeta`) — P1 "Separate DatarefCache and CommandCache"
- `Protocol` vs `ABC` for `API` — P2
- Modernized type annotations (`list` vs `List`) — P2
- Async support — P1
- Context manager support — P1
