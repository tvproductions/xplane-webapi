# P0 Unittest Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the remaining P0 coverage tranche from `BACKLOG.md` by adding shared `unittest` helpers and focused behavior coverage across core objects, caches, REST, async REST, WebSocket, UDP, and beacon workflows.

**Architecture:** This is the first executable slice of `docs/superpowers/specs/2026-06-20-xplane-webapi-vnext-product-design.md`. The change is test-first and keeps production code unchanged unless a new test exposes an actual behavioral defect; shared test setup moves to `tests/helpers.py` so transport tests stay readable.

**Tech Stack:** Python 3.12, stdlib `unittest`, stdlib `unittest.mock`, `httpx`, `simple-websocket`, `uv`, `ruff`.

## Global Constraints

- Python version is `>=3.12,<3.13`.
- Use stdlib `unittest`; do not add or invoke another Python test framework.
- Keep the test workflow as `uv run python -m unittest discover -v`.
- Keep `examples/` untouched.
- Preserve existing public entry points and legacy exception aliases.
- Do not require a live X-Plane instance for tests.
- Required final checks:
  - `uv run python -m unittest discover -v`
  - `uv run ruff check xpwebapi tests`
  - `uv run ruff format --check xpwebapi tests`

---

## Scope Check

The approved vNext product spec covers multiple roadmap bands. This plan implements only the current P0 item, `Expand unittest coverage`, because it is the next critical slice and creates the confidence needed for later P1-P3 plans.

Follow-on implementation plans should cover:

- P1 async REST parity gaps if any remain after this test pass.
- P1 context manager support gaps.
- P2 structured logging.
- P3 docs and CI.

---

## File Structure

- Create `tests/helpers.py`: shared mock response builders, metadata factories, dummy API, UDP packet helper, and beacon packet helper.
- Modify `tests/test_api.py`: consume helper fixtures and add `Dataref`, `Command`, and cache edge coverage.
- Modify `tests/test_rest.py`: consume helper fixtures and add capabilities, API version, cache lifecycle, metadata miss, selected array write, and missing value coverage.
- Modify `tests/test_async_rest.py`: consume helper fixtures and add a small parity check that uses the shared helpers.
- Modify `tests/test_ws.py`: add bulk monitor/unmonitor and callback registration coverage.
- Modify `tests/test_udp.py`: consume helper packet builder and add disconnected write/execute and monitor counter coverage.
- Modify `tests/test_beacon.py`: consume helper beacon builder and add monitor lifecycle/status counter coverage.
- Modify `BACKLOG.md`: mark P0 `Expand unittest coverage` complete only after all validation passes.

---

### Task 1: Create Shared Test Helpers

**Files:**
- Create: `tests/helpers.py`

**Interfaces:**
- Produces: `mock_response(status_code: int, payload: dict | None = None) -> MagicMock`
- Produces: `make_dataref_meta(...) -> DatarefMeta`
- Produces: `make_command_meta(...) -> CommandMeta`
- Produces: `DummyAPI(API)`
- Produces: `make_rref_packet(values: list[tuple[int, float]]) -> bytes`
- Produces: `make_beacon_packet(...) -> bytes`

- [ ] **Step 1: Create `tests/helpers.py` with shared fixtures**

```python
import base64
import struct
from unittest.mock import MagicMock

from xpwebapi.api import API, APIResult, Command, CommandMeta, Dataref, DatarefMeta, DatarefReadResult


def mock_response(status_code: int, payload: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.reason_phrase = "OK" if status_code == 200 else "Error"
    response.text = ""
    response.json.return_value = payload or {}
    return response


def make_dataref_meta(name: str = "sim/test/value", value_type: str = "int", is_writable: bool = True, ident: int = 10) -> DatarefMeta:
    return DatarefMeta(name=name, value_type=value_type, is_writable=is_writable, id=ident)


def make_command_meta(name: str = "sim/test/command", description: str = "Test command", ident: int = 20) -> CommandMeta:
    return CommandMeta(name=name, description=description, id=ident)


def encoded_data(value: bytes = b"abc") -> str:
    return base64.b64encode(value).decode("ascii")


def make_rref_packet(values: list[tuple[int, float]]) -> bytes:
    packet = b"RREF,"
    for ident, value in values:
        packet += struct.pack("<if", ident, value)
    return packet


def make_beacon_packet(
    hostname: str = "testhost",
    port: int = 49000,
    xplane_version: int = 121400,
    role: int = 1,
    major: int = 1,
    minor: int = 2,
    app_id: int = 1,
) -> bytes:
    header = b"BECN\x00"
    data = struct.pack("<BBiiIH", major, minor, app_id, xplane_version, role, port)
    return header + data + hostname.encode("utf-8") + b"\x00\x00"


class DummyAPI(API):
    def __init__(self, value: DatarefReadResult = None):
        self.meta_by_path = {}
        self.value_to_return = value
        self.written = []
        self.executed = []
        self.monitored_datarefs = []
        self.command_events = []
        super().__init__(host="127.0.0.1", port=8086, api="/api", api_version="v1")

    @property
    def connected(self) -> bool:
        return True

    def get_rest_meta(self, obj: Dataref | Command, force: bool = False) -> DatarefMeta | CommandMeta | None:
        return self.meta_by_path.get(obj.path)

    def write_dataref(self, dataref: Dataref) -> APIResult:
        self.written.append(dataref)
        return True

    def dataref_value(self, dataref: Dataref, raw: bool = False, no_decode: bool = False) -> DatarefReadResult:
        return self.value_to_return

    def execute_command(self, command: Command, duration: float = 0.0) -> APIResult:
        self.executed.append((command, duration))
        return True

    def monitor_dataref(self, dataref: Dataref) -> bool:
        self.monitored_datarefs.append(("monitor", dataref))
        return True

    def unmonitor_dataref(self, dataref: Dataref) -> bool:
        self.monitored_datarefs.append(("unmonitor", dataref))
        return True

    def register_command_is_active_event(self, path: str, on: bool = True) -> bool:
        self.command_events.append((path, on))
        return True
```

- [ ] **Step 2: Run helper import smoke test**

Run: `uv run python -m unittest tests.helpers -v`

Expected: command imports the module and reports `Ran 0 tests`.

- [ ] **Step 3: Commit helper scaffold**

```powershell
git add tests/helpers.py
git commit -m "test: add shared unittest helpers"
```

---

### Task 2: Refactor Existing Tests To Use Helpers

**Files:**
- Modify: `tests/test_api.py`
- Modify: `tests/test_rest.py`
- Modify: `tests/test_async_rest.py`
- Modify: `tests/test_udp.py`
- Modify: `tests/test_beacon.py`

**Interfaces:**
- Consumes: `tests.helpers.mock_response`
- Consumes: `tests.helpers.DummyAPI`
- Consumes: `tests.helpers.make_rref_packet`
- Consumes: `tests.helpers.make_beacon_packet`
- Consumes: `tests.helpers.make_dataref_meta`
- Consumes: `tests.helpers.make_command_meta`
- Consumes: `tests.helpers.encoded_data`
- Produces: existing tests with duplicated helper code removed

- [ ] **Step 1: Update `tests/test_api.py` imports**

Replace the local `MagicMock` import and local helper definitions with:

```python
import base64
import unittest

from tests.helpers import DummyAPI, mock_response
from xpwebapi.api import (
    DATAREF_DATATYPE,
    Cache,
    CommandCache,
    Command,
    CommandMeta,
    DatarefCache,
    Dataref,
    DatarefMeta,
    ValueCache,
)
```

Delete the local `mock_response` function and `DummyAPI` class from `tests/test_api.py`.

- [ ] **Step 2: Update `tests/test_rest.py` imports**

Replace the local `mock_response` function with the shared helper:

```python
import base64
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

import httpx

from tests.helpers import mock_response
from xpwebapi.api import DATAREF_DATATYPE, Command, CommandMeta, Dataref, DatarefMeta
from xpwebapi.rest import XPRestAPI
```

- [ ] **Step 3: Update `tests/test_async_rest.py` imports**

Replace the local `mock_response` function with:

```python
from tests.helpers import mock_response
```

Keep `AsyncMock`, `MagicMock`, and existing async test classes unchanged.

- [ ] **Step 4: Update `tests/test_udp.py` imports**

Replace local `struct` usage and local `make_rref_packet` with:

```python
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from tests.helpers import make_rref_packet
from xpwebapi.api import Command, Dataref
from xpwebapi.exceptions import XPPacketError
from xpwebapi.udp import XPUDPAPI, XPlaneTimeout
```

- [ ] **Step 5: Update `tests/test_beacon.py` imports**

Replace local `struct` usage and local `make_beacon_packet` with:

```python
import socket
import unittest
from unittest.mock import MagicMock, patch

import xpwebapi
from tests.helpers import make_beacon_packet
from xpwebapi.beacon import BeaconData, XPBeaconMonitor, XPlaneNoBeacon, XPlaneVersionNotSupported
```

- [ ] **Step 6: Run the existing test suite**

Run: `uv run python -m unittest discover -v`

Expected: all existing tests pass with the same behavior as before the helper refactor.

- [ ] **Step 7: Commit helper refactor**

```powershell
git add tests/test_api.py tests/test_rest.py tests/test_async_rest.py tests/test_udp.py tests/test_beacon.py
git commit -m "test: reuse shared test helpers"
```

---

### Task 3: Expand Core Object And Cache Coverage

**Files:**
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: `DummyAPI`
- Consumes: `make_dataref_meta`
- Consumes: `make_command_meta`
- Produces: additional `Dataref`, `Command`, and cache edge-case tests

- [ ] **Step 1: Add imports from helpers**

Ensure `tests/test_api.py` imports:

```python
from tests.helpers import DummyAPI, encoded_data, make_command_meta, make_dataref_meta, mock_response
```

- [ ] **Step 2: Add `Dataref` indexed path and string tests**

Add these methods to `TestDataref`:

```python
def test_indexed_path_parses_base_path_and_index(self):
    api = DummyAPI()
    dataref = Dataref(path="sim/test/array[4]", api=api)

    self.assertEqual(dataref.name, "sim/test/array[4]")
    self.assertEqual(dataref.path, "sim/test/array")
    self.assertEqual(dataref.index, 4)


def test_string_representation_includes_index_and_value(self):
    api = DummyAPI()
    dataref = Dataref(path="sim/test/array[4]", api=api)
    dataref.value = 12.5

    self.assertEqual(str(dataref), "sim/test/array[4]=12.5")


def test_get_string_value_decodes_data_bytes_and_strips_nulls(self):
    api = DummyAPI(value=b"ABC\x00\x00")
    api.meta_by_path["sim/test/data"] = make_dataref_meta(name="sim/test/data", value_type=DATAREF_DATATYPE.DATA.value)
    dataref = Dataref(path="sim/test/data", api=api)

    self.assertEqual(dataref.get_string_value("ascii"), "ABC")


def test_set_string_value_encodes_data_value(self):
    api = DummyAPI()
    api.meta_by_path["sim/test/data"] = make_dataref_meta(name="sim/test/data", value_type=DATAREF_DATATYPE.DATA.value)
    dataref = Dataref(path="sim/test/data", api=api)

    dataref.set_string_value("ABC", "ascii")

    self.assertEqual(dataref.value, b"ABC")
    self.assertEqual(dataref.b64encoded, encoded_data(b"ABC"))
```

- [ ] **Step 3: Add invalid metadata and monitor counter tests**

Add these methods to `TestDataref`:

```python
def test_invalid_meta_properties_record_errors(self):
    api = DummyAPI()
    dataref = Dataref(path="sim/test/missing", api=api)

    self.assertFalse(dataref.valid)
    self.assertIsNone(dataref.ident)
    self.assertIsNone(dataref.value_type)
    self.assertFalse(dataref.is_writable)
    self.assertGreaterEqual(dataref._err, 3)


def test_monitor_counter_tracks_nested_monitoring(self):
    api = DummyAPI()
    dataref = Dataref(path="sim/test/value", api=api)

    dataref.inc_monitor()
    dataref.inc_monitor()

    self.assertTrue(dataref.is_monitored)
    self.assertEqual(dataref.monitored_count, 2)
    self.assertTrue(dataref.dec_monitor())
    self.assertFalse(dataref.dec_monitor())
    self.assertEqual(dataref.monitored_count, 0)
```

- [ ] **Step 4: Add `Command` metadata tests**

Add these methods to `TestCommand`:

```python
def test_command_metadata_properties_use_cached_meta(self):
    api = DummyAPI()
    api.meta_by_path["sim/test/command"] = make_command_meta(ident=44)
    command = Command(path="sim/test/command", api=api)

    self.assertTrue(command.valid)
    self.assertEqual(command.ident, 44)
    self.assertEqual(command.description, "Test command")


def test_command_invalid_metadata_records_errors(self):
    api = DummyAPI()
    command = Command(path="sim/test/missing", api=api)

    self.assertFalse(command.valid)
    self.assertIsNone(command.ident)
    self.assertIsNone(command.description)
    self.assertGreaterEqual(command._err, 2)
```

- [ ] **Step 5: Add cache save behavior test**

Add this import:

```python
from tempfile import TemporaryDirectory
```

Add this method to `TestDatarefCache`:

```python
def test_save_writes_loaded_metadata_json(self):
    api = DummyAPI()
    cache = DatarefCache(api)
    meta = make_dataref_meta(name="sim/test/value", ident=7)
    cache._raw = [{"name": meta.name, "value_type": meta.value_type, "is_writable": meta.is_writable, "id": meta.ident}]
    cache._by_name = {meta.name: meta}
    cache._by_ids = {meta.ident: meta}

    with TemporaryDirectory() as tmpdir:
        filename = f"{tmpdir}/datarefs.json"
        cache.save(filename)
        with open(filename, encoding="utf-8") as handle:
            content = handle.read()

    self.assertIn("sim/test/value", content)
    self.assertIn('"id": 7', content)
```

- [ ] **Step 6: Run targeted core tests**

Run: `uv run python -m unittest tests.test_api -v`

Expected: all `tests.test_api` tests pass.

- [ ] **Step 7: Commit core coverage**

```powershell
git add tests/test_api.py
git commit -m "test: expand core object coverage"
```

---

### Task 4: Expand REST And Async REST Coverage

**Files:**
- Modify: `xpwebapi/rest.py`
- Modify: `tests/test_rest.py`
- Modify: `tests/test_async_rest.py`

**Interfaces:**
- Consumes: `mock_response`
- Consumes: existing `RestAPITestCase.make_api`
- Consumes: existing `AsyncRestAPITestCase.make_api`
- Produces: additional REST lifecycle, capabilities, version, cache, and parity tests
- Produces: fixed `XPRestAPI.set_api_version(None)` latest-version selection

- [ ] **Step 1: Import REST constants and caches in `tests/test_rest.py`**

Update the imports:

```python
from xpwebapi.api import DATAREF_DATATYPE, Command, CommandMeta, Dataref, DatarefCache, DatarefMeta
from xpwebapi.rest import V1_CAPABILITIES, XPRestAPI
```

- [ ] **Step 2: Add capabilities and API version tests**

Add this class after `TestXPRestAPIConnected`:

```python
class TestXPRestAPICapabilities(RestAPITestCase):
    def test_capabilities_are_cached_after_successful_fetch(self):
        api = self.make_api()
        payload = {"api": {"versions": ["v1", "v2"]}, "x-plane": {"version": "12.2.1"}}
        api.session.get.return_value = mock_response(200, payload)

        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertEqual(api.capabilities, payload)
            self.assertEqual(api.capabilities, payload)

        api.session.get.assert_called_once()

    def test_capabilities_fall_back_to_v1_probe(self):
        api = self.make_api()
        api.session.get.side_effect = [mock_response(404), mock_response(200, {"data": 1})]

        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertEqual(api.capabilities, V1_CAPABILITIES)

    def test_set_api_version_selects_latest_available_when_unspecified(self):
        api = self.make_api()
        api._capabilities = {"api": {"versions": ["v1", "v3", "v2"]}, "x-plane": {"version": "12.2.1"}}

        api.set_api_version()

        self.assertEqual(api.version, "v3")
        self.assertEqual(api._api_version, "/v3")
```

- [ ] **Step 3: Run latest-version test to verify it exposes the current defect**

Run: `uv run python -m unittest tests.test_rest.TestXPRestAPICapabilities.test_set_api_version_selects_latest_available_when_unspecified -v`

Expected: FAIL because `set_api_version(None)` logs the selected version but does not assign it to `api_version`.

- [ ] **Step 4: Fix latest-version assignment in `xpwebapi/rest.py`**

Replace this block inside `XPRestAPI.set_api_version`:

```python
if api_version is None:
    if api_versions is None:
        logger.error("cannot determine api, api not set")
        return
    sorted_apis = natsorted(api_versions, reverse=True)
    api = sorted_apis[0]  # takes the latest one, hoping it is the latest in time...
    logger.info(f"selected api {api} ({sorted_apis})")
```

with:

```python
if api_version is None:
    if api_versions is None:
        logger.error("cannot determine api, api not set")
        return
    sorted_apis = natsorted(api_versions, reverse=True)
    api_version = sorted_apis[0]  # takes the latest one, hoping it is the latest in time...
    logger.info(f"selected api {api_version} ({sorted_apis})")
```

- [ ] **Step 5: Re-run latest-version test**

Run: `uv run python -m unittest tests.test_rest.TestXPRestAPICapabilities.test_set_api_version_selects_latest_available_when_unspecified -v`

Expected: PASS.

- [ ] **Step 6: Add REST metadata miss and selected array write tests**

Add to `TestXPRestAPIGetRestMeta`:

```python
def test_get_rest_meta_returns_none_for_empty_metadata(self):
    api = self.make_api()
    dataref = Dataref(path="sim/test/value", api=api)
    api.session.get.return_value = mock_response(200, {"data": []})

    with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
        self.assertIsNone(api.get_rest_meta(dataref))
```

Add to `TestXPRestAPIWriteDataref`:

```python
def test_write_dataref_rejects_missing_new_value(self):
    api = self.make_api()
    dataref = self.make_dataref(api)

    with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
        self.assertFalse(api.write_dataref(dataref))

    api.session.patch.assert_not_called()


def test_write_dataref_selected_array_element_adds_index_to_url(self):
    api = self.make_api()
    dataref = Dataref(path="sim/test/array[2]", api=api)
    dataref._cached_meta = DatarefMeta(name=dataref.path, value_type=DATAREF_DATATYPE.FLOATARRAY.value, is_writable=True, id=31)
    dataref.value = 8.5
    api.session.patch.return_value = mock_response(200, {"result": "ok"})

    with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
        self.assertTrue(api.write_dataref(dataref))

    url = api.session.patch.call_args.args[0]
    self.assertTrue(url.endswith("/datarefs/31/value?index=2"))
```

- [ ] **Step 7: Add cache lifecycle tests**

Add this class:

```python
class TestXPRestAPICaches(RestAPITestCase):
    def test_invalidate_caches_clears_loaded_caches(self):
        api = self.make_api()
        api.all_datarefs = DatarefCache(api)
        api.all_commands = MagicMock()

        api.invalidate_caches()

        self.assertIsNone(api.all_datarefs)
        self.assertIsNone(api.all_commands)

    def test_get_dataref_meta_by_id_returns_none_without_cache(self):
        api = self.make_api()

        self.assertIsNone(api.get_dataref_meta_by_id(99))
        self.assertIsNone(api.get_dataref_meta_by_name("sim/test/value"))
```

- [ ] **Step 8: Add async REST helper parity smoke test**

Add this method to `TestAsyncXPRestAPIDatarefValue`:

```python
async def test_shared_mock_response_supports_async_rest(self):
    api = self.make_api()
    dataref = self.make_dataref(api)
    api.session.get.side_effect = [mock_response(200, {"data": 1}), mock_response(200, {"data": 77})]

    self.assertEqual(await api.dataref_value(dataref), 77)
```

- [ ] **Step 9: Run targeted REST tests**

Run: `uv run python -m unittest tests.test_rest tests.test_async_rest -v`

Expected: all REST and async REST tests pass.

- [ ] **Step 10: Commit REST coverage and latest-version fix**

```powershell
git add xpwebapi/rest.py tests/test_rest.py tests/test_async_rest.py
git commit -m "fix: cover rest api version selection"
```

---

### Task 5: Expand WebSocket Coverage

**Files:**
- Modify: `tests/test_ws.py`

**Interfaces:**
- Consumes: existing `WebsocketAPITestCase.make_api`
- Produces: additional bulk monitor, duplicate monitor, unmonitor, and callback registration coverage

- [ ] **Step 1: Add bulk monitor tests**

Add this class after `TestXPWebsocketAPIMessageHandling`:

```python
class TestXPWebsocketAPIMonitoring(WebsocketAPITestCase):
    def test_monitor_datarefs_subscribes_only_unmonitored_datarefs(self):
        api = self.make_api()
        first = Dataref(path="sim/test/first", api=api)
        first._cached_meta = DatarefMeta(name=first.path, value_type="float", is_writable=True, id=101)
        second = Dataref(path="sim/test/second", api=api)
        second._cached_meta = DatarefMeta(name=second.path, value_type="float", is_writable=True, id=102)
        second.inc_monitor()
        api.register_bulk_dataref_value_event = MagicMock(return_value=7)

        with patch.object(XPWebsocketAPI, "connected", new_callable=PropertyMock, return_value=True):
            result, effectives = api.monitor_datarefs({first.path: first, second.path: second}, reason="test")

        self.assertEqual(result, 7)
        self.assertEqual(set(effectives), {first.name, second.name})
        api.register_bulk_dataref_value_event.assert_called_once()
        bulk = api.register_bulk_dataref_value_event.call_args.kwargs["datarefs"]
        self.assertEqual(list(bulk), [101])
        self.assertEqual(first.monitored_count, 1)
        self.assertEqual(second.monitored_count, 2)

    def test_unmonitor_datarefs_skips_datarefs_still_monitored_elsewhere(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)
        dataref._cached_meta = DatarefMeta(name=dataref.path, value_type="float", is_writable=True, id=103)
        dataref.inc_monitor()
        dataref.inc_monitor()
        api.register_bulk_dataref_value_event = MagicMock(return_value=9)

        with patch.object(XPWebsocketAPI, "connected", new_callable=PropertyMock, return_value=True):
            result, effectives = api.unmonitor_datarefs({dataref.path: dataref}, reason="test")

        self.assertEqual(result, 0)
        self.assertEqual(effectives, {dataref.name: dataref})
        api.register_bulk_dataref_value_event.assert_not_called()
        self.assertEqual(dataref.monitored_count, 1)

    def test_monitor_datarefs_returns_false_when_disconnected(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)

        with patch.object(XPWebsocketAPI, "connected", new_callable=PropertyMock, return_value=False):
            self.assertEqual(api.monitor_datarefs({dataref.path: dataref}), (False, {}))
```

- [ ] **Step 2: Add callback set behavior test**

Add this method to `TestXPWebsocketAPICallbacks`:

```python
def test_add_callback_deduplicates_same_callable(self):
    api = self.make_api()
    callback = MagicMock()

    api.add_callback(CALLBACK_TYPE.ON_OPEN, callback)
    api.add_callback(CALLBACK_TYPE.ON_OPEN, callback)
    api.execute_callbacks(CALLBACK_TYPE.ON_OPEN)

    callback.assert_called_once()
```

- [ ] **Step 3: Run targeted WebSocket tests**

Run: `uv run python -m unittest tests.test_ws -v`

Expected: all WebSocket tests pass.

- [ ] **Step 4: Commit WebSocket coverage**

```powershell
git add tests/test_ws.py
git commit -m "test: expand websocket coverage"
```

---

### Task 6: Expand UDP Coverage

**Files:**
- Modify: `xpwebapi/udp.py`
- Modify: `tests/test_udp.py`

**Interfaces:**
- Consumes: `make_rref_packet`
- Consumes: existing `UDPAPITestCase.make_api`
- Produces: additional disconnected, command, and monitor counter coverage
- Produces: UDP monitor/unmonitor counter parity with `Dataref.is_monitored`

- [ ] **Step 1: Add disconnected write and command tests**

Add to `TestXPUDPAPIWriteDataref`:

```python
def test_write_dataref_sends_packet_without_connection_probe(self):
    api = self.make_api()
    dataref = Dataref(path="sim/test/value", api=api)
    dataref.value = 1.25

    self.assertTrue(api.write_dataref(dataref))
    api.socket.sendto.assert_called_once()
```

Add to `TestXPUDPAPIExecuteCommand`:

```python
def test_execute_command_ignores_duration_for_udp_packet(self):
    api = self.make_api()
    command = Command(path="sim/test/command", api=api)

    self.assertTrue(api.execute_command(command, duration=2.0))

    message, _address = api.socket.sendto.call_args.args
    self.assertTrue(message.startswith(b"CMND\x00"))
    self.assertIn(b"sim/test/command", message)
```

- [ ] **Step 2: Add monitor counter tests**

Add to `TestXPUDPAPIRequestDataref`:

```python
def test_monitor_dataref_increments_dataref_monitor_count(self):
    api = self.make_api()
    dataref = Dataref(path="sim/test/value", api=api)

    with patch.object(XPUDPAPI, "connected", new_callable=PropertyMock, return_value=True):
        self.assertTrue(api.monitor_dataref(dataref))

    self.assertEqual(dataref.monitored_count, 1)
    self.assertTrue(dataref.is_monitored)


def test_unmonitor_datarefs_decrements_dataref_monitor_count(self):
    api = self.make_api()
    dataref = Dataref(path="sim/test/value", api=api)

    with patch.object(XPUDPAPI, "connected", new_callable=PropertyMock, return_value=True):
        api.monitor_dataref(dataref)
        result, effectives = api.unmonitor_datarefs({dataref.path: dataref})

    self.assertTrue(result)
    self.assertEqual(effectives, {})
    self.assertEqual(dataref.monitored_count, 0)
```

- [ ] **Step 3: Run UDP monitor counter tests to verify they expose the current defect**

Run: `uv run python -m unittest tests.test_udp.TestXPUDPAPIRequestDataref.test_monitor_dataref_increments_dataref_monitor_count tests.test_udp.TestXPUDPAPIRequestDataref.test_unmonitor_datarefs_decrements_dataref_monitor_count -v`

Expected: FAIL because `XPUDPAPI.monitor_dataref()` and `XPUDPAPI.unmonitor_datarefs()` do not currently update the `Dataref` monitor counter.

- [ ] **Step 4: Fix UDP monitor counter updates**

In `xpwebapi/udp.py`, replace `monitor_dataref` with:

```python
def monitor_dataref(self, dataref: Dataref) -> bool | int:
    """Starts monitoring single dataref.

    [description]

    Args:
        dataref (Dataref): Dataref to monitor

    Returns:
        bool if fails
        request id if succeeded
    """
    ret = self._request_dataref(dataref=dataref.path, freq=1)
    if ret:
        dataref.inc_monitor()
    return ret
```

Replace `unmonitor_datarefs` with:

```python
def unmonitor_datarefs(self, datarefs: dict, reason: str | None = None) -> Tuple[int | bool, Dict]:
    """Stops monitoring supplied datarefs.

    [description]

    Args:
        datarefs (dict): {path: Dataref} dictionary of datarefs
        reason (str | None): Documentation only string to identify call to function.

    Returns:
        Tuple[int | bool, Dict]: [description]
    """
    ret = True
    for dataref in datarefs.values():
        if dataref.monitored_count > 1:
            dataref.dec_monitor()
            continue
        r = self._request_dataref(dataref=dataref.path, freq=0)
        if r and dataref.is_monitored:
            dataref.dec_monitor()
        if not r:
            ret = False
    return ret, {}
```

- [ ] **Step 5: Re-run UDP monitor counter tests**

Run: `uv run python -m unittest tests.test_udp.TestXPUDPAPIRequestDataref.test_monitor_dataref_increments_dataref_monitor_count tests.test_udp.TestXPUDPAPIRequestDataref.test_unmonitor_datarefs_decrements_dataref_monitor_count -v`

Expected: PASS.

- [ ] **Step 6: Run targeted UDP tests**

Run: `uv run python -m unittest tests.test_udp -v`

Expected: all UDP tests pass.

- [ ] **Step 7: Commit UDP coverage and counter fix**

```powershell
git add xpwebapi/udp.py tests/test_udp.py
git commit -m "fix: track udp monitor counters"
```

---

### Task 7: Expand Beacon Coverage

**Files:**
- Modify: `tests/test_beacon.py`

**Interfaces:**
- Consumes: `make_beacon_packet`
- Consumes: existing `BeaconMonitorTestCase.make_monitor`
- Produces: additional receiving beacon, status, callback, and monitor lifecycle tests

- [ ] **Step 1: Import status enum**

Update imports:

```python
from xpwebapi.beacon import BEACON_MONITOR_STATUS, BeaconData, XPBeaconMonitor, XPlaneNoBeacon, XPlaneVersionNotSupported
```

- [ ] **Step 2: Add receiving beacon warning behavior tests**

Add this class after `TestXPBeaconMonitorSameHost`:

```python
class TestXPBeaconMonitorStatus(BeaconMonitorTestCase):
    def test_receiving_beacon_returns_true_when_data_exists(self):
        monitor = self.make_monitor()
        monitor.data = BeaconData(host="127.0.0.1", port=49000, hostname="xp", xplane_version=121400, role=1)

        self.assertTrue(monitor.receiving_beacon)

    def test_receiving_beacon_increments_warning_counter_when_no_data(self):
        monitor = self.make_monitor()

        with patch("xpwebapi.beacon.logger.warning"):
            self.assertFalse(monitor.receiving_beacon)

        self.assertEqual(monitor._already_warned, 1)

    def test_stop_monitor_marks_status_not_running_when_already_stopped(self):
        monitor = self.make_monitor()

        with patch("xpwebapi.beacon.logger.warning"):
            monitor.stop_monitor()

        self.assertEqual(monitor.status, BEACON_MONITOR_STATUS.NOT_RUNNING)
```

- [ ] **Step 3: Add callback no-op test**

Add this method to `TestXPBeaconMonitorCallbacks`:

```python
def test_set_callback_ignores_none(self):
    monitor = self.make_monitor()

    monitor.set_callback(None)
    monitor.callback(connected=False, beacon_data=None, same_host=None)

    self.assertEqual(monitor._callback, set())
```

- [ ] **Step 4: Run targeted beacon tests**

Run: `uv run python -m unittest tests.test_beacon -v`

Expected: all beacon tests pass.

- [ ] **Step 5: Commit beacon coverage**

```powershell
git add tests/test_beacon.py
git commit -m "test: expand beacon coverage"
```

---

### Task 8: Validate P0 Coverage Tranche And Update Backlog

**Files:**
- Modify: `BACKLOG.md`

**Interfaces:**
- Consumes: all tests added in Tasks 1-7
- Produces: P0 `Expand unittest coverage` marked complete after validation

- [ ] **Step 1: Run full test suite**

Run: `uv run python -m unittest discover -v`

Expected: all tests pass.

- [ ] **Step 2: Run lint**

Run: `uv run ruff check xpwebapi tests`

Expected: `All checks passed!`

- [ ] **Step 3: Run format check**

Run: `uv run ruff format --check xpwebapi tests`

Expected: all files already formatted.

- [ ] **Step 4: Update `BACKLOG.md` P0 coverage checkboxes**

Change:

```markdown
### [ ] Expand unittest coverage
- [ ] Add shared `unittest` helpers for mocking X-Plane REST/WebSocket responses
- [ ] Fill remaining coverage gaps for `Dataref`, `Command`, `Cache`, `XPRestAPI`, `XPWebsocketAPI`, `XPUDPAPI`, `XPBeaconMonitor`
- [ ] Keep `uv run python -m unittest discover -v` as the test workflow
```

to:

```markdown
### [x] Expand unittest coverage
- [x] Add shared `unittest` helpers for mocking X-Plane REST/WebSocket responses
- [x] Fill remaining coverage gaps for `Dataref`, `Command`, `Cache`, `XPRestAPI`, `XPWebsocketAPI`, `XPUDPAPI`, `XPBeaconMonitor`
- [x] Keep `uv run python -m unittest discover -v` as the test workflow
```

- [ ] **Step 5: Commit backlog update**

```powershell
git add BACKLOG.md
git commit -m "docs: mark p0 coverage complete"
```

- [ ] **Step 6: Final verification**

Run:

```powershell
git status -sb
git log --oneline -5
```

Expected:

- No unstaged or staged changes from the P0 coverage tranche.
- Recent commits include the helper, coverage, and backlog commits.

---

## Self-Review Notes

- Spec coverage: this plan implements the remaining P0 product requirement from `2026-06-20-xplane-webapi-vnext-product-design.md`.
- Scope: P1-P3 work is intentionally not included because the approved spec spans multiple roadmap bands.
- Test framework: all commands and examples use stdlib `unittest`.
- Live simulator dependency: every test uses mocks or deterministic packet builders.
- Public API: no public entry points are removed or renamed.
