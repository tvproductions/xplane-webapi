# WebSocket Library Migration Design

## Context

The P2 backlog item calls for evaluating `websockets` as a replacement for `simple-websocket`, with migration if beneficial. The project currently depends on `simple-websocket~=1.1` and uses it only inside `xpwebapi/ws.py` through these operations:

- `Client.connect(url)` to open a synchronous WebSocket.
- `ws.send(str)` to send JSON payloads.
- `ws.receive(timeout=float)` to read messages with a timeout.
- `ws.close()` to close the connection.
- `ConnectionClosed` to detect a closed connection in the listener loop.

The public `XPWebsocketAPI` is synchronous and thread-based. This migration preserves that surface.

## Decision

Fully migrate the synchronous WebSocket implementation from `simple-websocket` to `websockets.sync.client`.

`websockets` is a better fit for the backlog goal because it provides both threading and asyncio APIs, is actively released, and exposes the same core operations needed by the existing client. `websockets 16.0` was released on January 10, 2026 and supports Python 3.10+, which is compatible with this project's Python 3.12 requirement. `simple-websocket 1.1.0` is the current locked dependency and was uploaded on October 10, 2024.

Primary references:

- https://websockets.readthedocs.io/en/stable/reference/sync/client.html
- https://websockets.readthedocs.io/en/stable/project/changelog.html
- https://pypi.org/project/websockets/
- https://pypi.org/project/simple-websocket/

## Scope

In scope:

- Replace `simple-websocket` dependency with `websockets`.
- Update `XPWebsocketAPI` to connect through `websockets.sync.client.connect`.
- Update receive handling from `receive(timeout=...) -> None on timeout` to `recv(timeout=...) -> TimeoutError on timeout`.
- Update closed-connection handling to catch `websockets.exceptions.ConnectionClosed`.
- Update unit tests to patch the new `xpwebapi.ws.connect` import and verify timeout behavior.
- Mark the backlog item complete after validation passes.

Out of scope:

- Adding an async WebSocket API.
- Reworking the thread model.
- Changing public method names or callback contracts.
- Adding batch dataref optimization.
- Adding CI/CD.

## API Mapping

| Current `simple-websocket` API | Target `websockets` API | Notes |
| --- | --- | --- |
| `Client.connect(url)` | `connect(url, proxy=None)` | Import `connect` from `websockets.sync.client`. Disable proxy use for localhost simulator connections. |
| `ws.send(json_string)` | `ws.send(json_string)` | Existing JSON serialization remains unchanged. |
| `ws.receive(timeout=seconds)` | `ws.recv(timeout=seconds)` | `websockets` raises `TimeoutError` when no message arrives before the timeout. |
| `ConnectionClosed` | `websockets.exceptions.ConnectionClosed` | Catching the base class preserves current close handling. |
| `ws.close()` | `ws.close()` | `websockets` close is idempotent. |

## Behavioral Requirements

- `XPWebsocketAPI.connect_websocket()` still opens a WebSocket only when `rest_api_reachable` is true.
- Successful connection still sets status to `WEBSOCKET_CONNNECTED`, reloads caches, logs the opened URL, and runs `ON_OPEN` callbacks.
- Failed connection attempts still follow the existing retry policy.
- `send()` still returns the request id on success and `False` on disconnected or empty payload.
- `ws_listener()` still treats receive timeouts as normal idle periods and continues listening.
- Closed connections still clear `self.ws`, mark the listener as stopped, set status to `WEBSOCKET_DISCONNNECTED`, and run `ON_CLOSE` callbacks.
- Public synchronous `XPWebsocketAPI` behavior remains backward compatible.

## Dependency Requirements

- `pyproject.toml` must remove `simple-websocket~=1.1`.
- `pyproject.toml` must add `websockets>=16,<17`.
- `uv.lock` must be refreshed so `simple-websocket` and transitive `wsproto` entries are removed if no longer needed, and `websockets` is locked.
- No new test framework may be introduced. Tests must use stdlib `unittest`.

## Testing

Use test-first changes for behavior affected by the library migration:

- Update connection tests to fail until `connect(url, proxy=None)` is used.
- Add or update listener timeout coverage so `TimeoutError` from `recv(timeout=...)` is treated like the previous `None` timeout path.
- Update close handling coverage to use `websockets.exceptions.ConnectionClosed`.

Final validation commands:

```powershell
uv run python -m unittest discover -v
uv run ruff check .
uv run ty check
```

If `ty` uses a different command in this repo at execution time, use the repo's current type-check command instead.

## Risks

- `websockets` enables proxy discovery by default. Passing `proxy=None` avoids surprising behavior for local simulator URLs.
- `websockets.recv(timeout=...)` raises `TimeoutError` instead of returning `None`. The listener must handle this explicitly to preserve idle receive behavior.
- `websockets` has built-in ping behavior. The migration keeps defaults unless tests or local behavior show a need to configure ping settings.
- The project cannot run live X-Plane integration in this environment, so validation is limited to unit tests, linting, and type checks.
