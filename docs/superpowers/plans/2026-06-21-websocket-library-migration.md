# WebSocket Library Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `simple-websocket` with `websockets.sync.client` while preserving the synchronous `XPWebsocketAPI` behavior.

**Architecture:** Keep `XPWebsocketAPI` thread-based and synchronous. Use `websockets.sync.client.connect` directly in `xpwebapi/ws.py`, translate idle receives from `TimeoutError` into the existing timeout logging path, and catch `websockets.exceptions.ConnectionClosed` for closed sockets.

**Tech Stack:** Python 3.12, stdlib `unittest`, stdlib `unittest.mock`, `websockets.sync.client`, `uv`, `ruff`, `ty`.

## Global Constraints

- Use stdlib `unittest` only.
- Preserve the public synchronous `XPWebsocketAPI` API.
- Do not add an async WebSocket client in this P2 item.
- Use `websockets>=16,<17`.
- Disable proxy discovery for X-Plane WebSocket connections with `proxy=None`.
- Use `uv run python -m unittest discover -v` as the test workflow.

---

## File Structure

- Modify `tests/test_ws.py`: update connection patch points and add listener behavior coverage for `recv()` timeout and closed connections.
- Modify `xpwebapi/ws.py`: replace `simple_websocket` imports and API calls with `websockets`.
- Modify `pyproject.toml`: replace the dependency.
- Modify `uv.lock`: refresh the lock through `uv lock`.
- Modify `BACKLOG.md`: mark the P2 WebSocket library evaluation item complete after validation.

### Task 1: Update WebSocket Unit Tests For The Target Library

**Files:**
- Modify: `tests/test_ws.py`

**Interfaces:**
- Consumes: existing `WebsocketAPITestCase.make_api() -> XPWebsocketAPI`
- Produces: tests that require `xpwebapi.ws.connect(url, proxy=None)`, `ws.recv(timeout=...)`, and `ConnectionClosed` handling.

- [ ] **Step 1: Update connection patches and expected connect arguments**

Replace the three `@patch("xpwebapi.ws.Client.connect")` decorators with:

```python
@patch("xpwebapi.ws.connect")
```

In `test_connect_websocket_success`, replace:

```python
mock_connect.assert_called_once_with("ws://127.0.0.1:8086/api/v2")
```

with:

```python
mock_connect.assert_called_once_with("ws://127.0.0.1:8086/api/v2", proxy=None)
```

- [ ] **Step 2: Add listener tests for `websockets` receive semantics**

Add this import near the other imports:

```python
from websockets.exceptions import ConnectionClosedError
```

Add this test class after `TestXPWebsocketAPIMessageHandling`:

```python
class TestXPWebsocketAPIListener(WebsocketAPITestCase):
    def test_ws_listener_treats_recv_timeout_as_idle_receive(self):
        api = self.make_api()
        api.RECEIVE_TIMEOUT = 0.01
        api.ws.recv.side_effect = [TimeoutError, '{"type": "result", "req_id": 1, "success": true}']
        api._requests[1] = MagicMock()

        states = [True, True, False]
        with patch.object(XPWebsocketAPI, "websocket_listener_running", new_callable=PropertyMock, side_effect=states):
            with patch.object(api, "_log_receive_timeout") as log_timeout:
                with patch.object(api, "_close_websocket_listener"):
                    api.ws_listener()

        api.ws.recv.assert_any_call(timeout=0.01)
        log_timeout.assert_called_once_with(0)
        self.assertEqual(api._stats["receive_raw"], 1)
        self.assertEqual(api._stats["receive"], 1)

    def test_ws_listener_handles_connection_closed(self):
        api = self.make_api()
        api.RECEIVE_TIMEOUT = 0.01
        api.ws.recv.side_effect = ConnectionClosedError(None, None)

        states = [True, False]
        with patch.object(XPWebsocketAPI, "websocket_listener_running", new_callable=PropertyMock, side_effect=states):
            with patch.object(api, "_handle_websocket_closed") as handle_closed:
                with patch.object(api, "_close_websocket_listener"):
                    api.ws_listener()

        handle_closed.assert_called_once_with()
```

- [ ] **Step 3: Run focused tests and verify they fail for the expected reasons**

Run:

```powershell
uv run python -m unittest tests.test_ws.TestXPWebsocketAPIConnect tests.test_ws.TestXPWebsocketAPIListener -v
```

Expected: failure before production changes because `xpwebapi.ws.connect` does not exist and `ws_listener()` still calls `receive()`.

- [ ] **Step 4: Commit the red tests**

```powershell
git add tests/test_ws.py
git commit -m "test: capture websockets client behavior"
```

### Task 2: Migrate `XPWebsocketAPI` To `websockets`

**Files:**
- Modify: `xpwebapi/ws.py`

**Interfaces:**
- Consumes: `connect(uri: str, *, proxy=None)` from `websockets.sync.client`
- Consumes: `ConnectionClosed` from `websockets.exceptions`
- Produces: existing `XPWebsocketAPI.connect_websocket()`, `send()`, and `ws_listener()` behavior backed by `websockets`.

- [ ] **Step 1: Replace imports**

Replace:

```python
from simple_websocket import Client, ConnectionClosed
```

with:

```python
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect
```

- [ ] **Step 2: Update the websocket attribute type**

Replace:

```python
self.ws: Client | None = None  # None = no connection
```

with:

```python
self.ws: ClientConnection | None = None  # None = no connection
```

- [ ] **Step 3: Update connection creation**

Replace:

```python
self.ws = Client.connect(url)
```

with:

```python
self.ws = connect(url, proxy=None)
```

- [ ] **Step 4: Update listener receive handling**

Replace this block:

```python
message = self.ws.receive(timeout=self.RECEIVE_TIMEOUT)
self.inc("receive_raw")
# probably we don't receive messages because X-Plane has nothing to send...
if message is None:
    self._log_receive_timeout(to_count)
    to_count = to_count + 1
    continue
```

with:

```python
try:
    message = self.ws.recv(timeout=self.RECEIVE_TIMEOUT)
except TimeoutError:
    self._log_receive_timeout(to_count)
    to_count = to_count + 1
    continue

self.inc("receive_raw")
```

- [ ] **Step 5: Run focused tests and verify they pass**

Run:

```powershell
uv run python -m unittest tests.test_ws.TestXPWebsocketAPIConnect tests.test_ws.TestXPWebsocketAPIListener -v
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit the migration**

```powershell
git add xpwebapi/ws.py tests/test_ws.py
git commit -m "feat: migrate websocket client to websockets"
```

### Task 3: Replace The Dependency And Refresh The Lock

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: project dependency metadata.
- Produces: project install using `websockets>=16,<17` and no direct `simple-websocket` dependency.

- [ ] **Step 1: Update dependency metadata**

In `pyproject.toml`, replace:

```toml
    "simple-websocket~=1.1",
```

with:

```toml
    "websockets>=16,<17",
```

- [ ] **Step 2: Refresh the lock file**

Run:

```powershell
uv lock
```

Expected: `uv.lock` contains a `websockets` package entry compatible with `>=16,<17`, and `xpwebapi` depends on `websockets` instead of `simple-websocket`.

- [ ] **Step 3: Verify dependency references**

Run:

```powershell
rg -n "simple-websocket|simple_websocket|websockets" pyproject.toml uv.lock xpwebapi tests
```

Expected: no `simple-websocket` or `simple_websocket` references in `pyproject.toml`, `uv.lock`, `xpwebapi`, or `tests`; `websockets` references remain.

- [ ] **Step 4: Run the full unit test suite**

Run:

```powershell
uv run python -m unittest discover -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit dependency changes**

```powershell
git add pyproject.toml uv.lock
git commit -m "build: replace simple-websocket dependency"
```

### Task 4: Validate, Update Backlog, And Finish

**Files:**
- Modify: `BACKLOG.md`

**Interfaces:**
- Consumes: completed migration from Tasks 1-3.
- Produces: completed P2 backlog item and validation evidence.

- [ ] **Step 1: Run lint**

Run:

```powershell
uv run ruff check .
```

Expected: no lint violations.

- [ ] **Step 2: Run type check**

Run:

```powershell
uv run ty check
```

Expected: no type-checking errors. If the command is not available, run the repository's current type-check command and record the exact result.

- [ ] **Step 3: Run final full unit tests**

Run:

```powershell
uv run python -m unittest discover -v
```

Expected: all tests pass.

- [ ] **Step 4: Mark the backlog item complete**

In `BACKLOG.md`, replace:

```markdown
### [ ] WebSocket library evaluation
- [ ] Evaluate `websockets` as replacement for `simple-websocket`
- [ ] Better async support, more active maintenance
- [ ] Benchmark and migrate if beneficial
```

with:

```markdown
### [x] WebSocket library evaluation
- [x] Evaluate `websockets` as replacement for `simple-websocket`
- [x] Better async support, more active maintenance
- [x] Benchmark and migrate if beneficial
```

- [ ] **Step 5: Re-run final validation after backlog update**

Run:

```powershell
uv run python -m unittest discover -v
uv run ruff check .
uv run ty check
```

Expected: all commands pass.

- [ ] **Step 6: Commit backlog update**

```powershell
git add BACKLOG.md
git commit -m "docs: complete websocket library backlog item"
```

- [ ] **Step 7: Inspect final status**

Run:

```powershell
git status --short
git log --oneline -5
```

Expected: working tree is clean and recent commits show the spec, tests, migration, dependency update, and backlog completion.

## Self-Review

- Spec coverage: covered dependency replacement, sync API preservation, proxy disabling, timeout translation, close handling, tests, validation, and backlog completion.
- Placeholder scan: no placeholders are intentionally left for implementers.
- Type consistency: production imports use `ClientConnection` and tests patch the module-local `connect` symbol used by `XPWebsocketAPI.connect_websocket()`.
