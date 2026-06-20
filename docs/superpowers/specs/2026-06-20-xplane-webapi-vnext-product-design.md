# xplane-webapi vNext Product Design

**Date:** 2026-06-20
**Scope:** Whole-app vNext product spec for `xplane-webapi`
**Status:** Draft for review
**Approach:** Stabilize and evolve the existing SDK without breaking current public entry points.

---

## Product Direction

`xplane-webapi` vNext is a Python 3.12 SDK for building X-Plane automation, monitoring, training, analytics, and cockpit tooling without forcing users to care which simulator transport is underneath.

The library exposes a coherent object model around `Dataref`, `Command`, metadata, and connection clients while supporting the simulator transports users need:

- Synchronous REST for direct request/response operations.
- Async REST for event-loop based applications.
- WebSocket for event monitoring and subscription workflows.
- UDP for simulator-native packet monitoring and command/dataref operations.
- Beacon discovery for finding X-Plane and identifying local vs remote simulator instances.

The main product promise is:

> A user can discover X-Plane, read and write datarefs, execute commands, monitor simulator state, and cleanly manage connections with predictable errors, typed metadata, documented lifecycle rules, and tests that prove behavior without requiring a live simulator.

vNext preserves existing public entry points:

- `xpwebapi.rest_api()`
- `xpwebapi.async_rest_api()`
- `xpwebapi.ws_api()`
- `xpwebapi.udp_api()`
- `xpwebapi.beacon()`
- `Dataref`
- `Command`
- existing custom exceptions and legacy exception aliases

The roadmap tightens behavior and documentation behind those entry points instead of replacing the public API.

---

## Users

### Primary Users

- Python developers building X-Plane companion tools.
- Simulator cockpit, training, and monitoring tool authors.
- Data logging and analytics developers.
- Automation users who need to read datarefs, write datarefs, or execute commands without implementing X-Plane protocols directly.

### Secondary Users

- Contributors maintaining transport behavior, examples, and docs.
- Advanced users building high-frequency monitoring workflows.
- Users migrating from simple REST scripts to async or WebSocket applications.

---

## Product Pillars

### 1. Stable Core SDK

The shared SDK model remains centered on:

- `Dataref`
- `Command`
- `DatarefMeta`
- `CommandMeta`
- dataref value parsing and encoding
- command duration handling
- metadata caches
- shared result and value types

Public factories remain the preferred entry points. Internals can evolve, but callers should not need to rewrite basic code for vNext.

### 2. Transport Parity

Each transport has a distinct role:

- REST owns simple direct read/write/execute operations.
- Async REST mirrors REST semantics for event-loop applications.
- WebSocket owns event subscription and callback-oriented monitoring.
- UDP owns packet-level simulator monitoring and command/dataref operations.
- Beacon discovery provides simulator location and reachability context.

Transport parity does not mean every transport exposes every feature. It means shared workflows have consistent naming, return semantics, lifecycle expectations, and error behavior where the underlying protocol supports them.

### 3. Reliability And Observability

The SDK should fail predictably:

- Library-originated failures use the custom exception hierarchy.
- Legacy exception names remain importable and catchable.
- Exceptions carry useful context such as host, port, timeout, packet type, expected length, and actual length.
- Connection status remains visible through client state.
- Logging separates user-facing application logs from request/response traffic where practical.
- Structured logging becomes available as an opt-in P2 feature.

### 4. Developer Confidence

The test suite should support safe evolution of every public workflow without a live X-Plane dependency.

The approved workflow remains:

```powershell
uv run python -m unittest discover -v
uv run ruff check xpwebapi tests
uv run ruff format --check xpwebapi tests
```

Shared test helpers should reduce duplicated mock setup for:

- REST responses
- async REST responses
- WebSocket messages
- UDP packets and sockets
- beacon packets and sockets
- metadata fixtures

### 5. Documentation And Examples

Docs should explain which transport to use:

- REST: one-off reads, writes, and command execution.
- Async REST: applications already running an event loop.
- WebSocket: subscriptions, callbacks, and event monitoring.
- UDP: simulator-native packet flows and lightweight data monitoring.
- Beacon: discovery and UDP setup.

Examples should map to real workflows such as simple REST reads, WebSocket monitoring, UDP monitoring, beacon discovery, flight data recording, and analytics.

---

## Architecture

### Package Surface

`xpwebapi.__init__` remains the public aggregation point for stable factories, classes, exceptions, and value types.

The public package should continue to export:

- domain objects: `Dataref`, `Command`
- metadata and value types
- client classes: `XPRestAPI`, `AsyncXPRestAPI`, `XPWebsocketAPI`, `XPUDPAPI`, `XPBeaconMonitor`
- callback enum: `CALLBACK_TYPE`
- exception hierarchy and legacy aliases
- factories: `rest_api`, `async_rest_api`, `ws_api`, `udp_api`, `beacon`

### Domain Objects

`Dataref` and `Command` are the cross-transport handles users work with.

`Dataref` owns:

- path and optional selected array index parsing
- local value staging
- dataref metadata lookup
- value parsing and base64/data encoding
- monitor counters
- convenience delegation to the active API

`Command` owns:

- path and duration
- metadata lookup
- command execution delegation
- command monitoring delegation where supported

### Transport Clients

Transport clients remain separate because they have different I/O models.

`XPRestAPI` owns:

- synchronous HTTP session lifecycle
- capabilities lookup
- metadata fetches
- direct dataref read/write
- command execution
- sync cache loading

`AsyncXPRestAPI` owns:

- async HTTP session lifecycle
- async capabilities lookup
- async metadata fetches
- async dataref read/write
- async command execution
- async context manager cleanup

`XPWebsocketAPI` owns:

- WebSocket connection lifecycle
- listener thread lifecycle
- callback dispatch
- event subscription payloads
- monitored dataref and command-active workflows
- REST fallback when configured

`XPUDPAPI` owns:

- UDP socket lifecycle
- dataref write and command packet generation
- monitored dataref requests
- RREF packet decoding
- timeout and malformed packet errors

`XPBeaconMonitor` owns:

- multicast beacon listening
- same-host detection
- retry behavior
- beacon callbacks
- monitor thread lifecycle

### Metadata Caches

`DatarefCache` and `CommandCache` are the typed cache model for vNext.

The product direction is to prefer typed caches everywhere internal code knows whether it is handling datarefs or commands. The older generic `Cache` behavior can remain for compatibility, but new code should not depend on heuristic metadata construction.

---

## Priority Roadmap

The existing P0-P3 backlog model remains the product planning framework.

### P0 Critical

P0 work is required to trust the SDK's behavior and safely evolve it.

Current P0:

- Expand `unittest` coverage.

Completed P0 foundations:

- Fixed LSP return contract issues for `dataref_value`, `execute_command`, and `write_dataref`.
- Added the custom exception hierarchy.

Product definition of done for the remaining P0:

- Shared `unittest` helpers exist for REST, async REST, WebSocket, UDP, beacon, and metadata fixtures.
- Core object coverage includes `Dataref`, `Command`, cache behavior, value parsing, encoding, metadata failures, and monitor counters.
- Transport coverage includes success, disconnected, malformed response/packet, timeout, and cleanup paths.
- Tests remain independent from a live X-Plane instance.
- The approved local quality workflow passes.

### P1 High

P1 work materially improves SDK usefulness without requiring a breaking redesign.

P1 roadmap:

- Async REST support via `httpx.AsyncClient`.
- Separate `DatarefCache` and `CommandCache`.
- Context manager support for lifecycle-owning clients.

Product definition of done:

- Async REST mirrors sync REST behavior where practical.
- Typed caches are used internally for dataref and command metadata.
- REST, async REST, WebSocket, UDP, and beacon clients have explicit cleanup behavior.
- Public examples show sync and async lifecycle patterns.

### P2 Medium

P2 work improves maintainability, typing, and diagnostics.

P2 roadmap:

- Use `Protocol` instead of `ABC` for the API contract if it reduces friction without destabilizing current clients.
- Modernize type annotations.
- Add structured logging.
- Evaluate `websockets` as a replacement for `simple-websocket`.

Product definition of done:

- Type contracts are clearer for contributors and downstream users.
- Logging can be consumed by applications without parsing free-form text.
- WebSocket dependency decisions are backed by compatibility and maintenance evidence.

### P3 Low

P3 work improves polish, adoption, automation, and performance.

P3 roadmap:

- CI/CD pipeline.
- Documentation improvements.
- Batch dataref request optimization.
- Connection pooling.

Product definition of done:

- CI runs lint, format check, type checking, and `unittest`.
- Docs explain transport choice and lifecycle patterns.
- Batch monitoring helpers reduce repeated round trips where protocols support it.
- Connection pooling improves repeated REST usage without changing default behavior unexpectedly.

---

## User Workflows

### Discover Simulator

Users should be able to create a beacon monitor, wait for X-Plane, inspect beacon data, and pass discovery results into UDP workflows.

Success means discovery errors are typed, retries are configurable, and examples show same-host vs remote behavior.

### Read Simulator State

Users should be able to read datarefs through REST or async REST for direct operations and through WebSocket or UDP for monitored values.

Success means scalar, array, bytes/data, and `None` results are documented and tested.

### Write Simulator State

Users should be able to stage a `Dataref` value and write it through the selected transport when supported.

Success means unwritable datarefs, missing metadata, missing staged values, selected array indices, and data/base64 values behave consistently and are tested.

### Execute Commands

Users should be able to create `Command` objects and execute them with explicit or default durations.

Success means duration precedence and transport-specific payloads are documented and tested.

### Monitor Events

Users should be able to subscribe to dataref updates and command-active events through WebSocket, and monitor dataref values through UDP.

Success means callback behavior, duplicate monitor counts, unmonitor behavior, and disconnected behavior are predictable and tested.

### Clean Up Reliably

Users should be able to close sessions, disconnect sockets, stop listener threads, and stop beacon monitors explicitly or with context managers where supported.

Success means cleanup is idempotent enough for normal application use and examples use the preferred lifecycle style.

---

## Non-Goals

vNext does not require:

- A full transport rewrite.
- Removal of existing factory functions.
- Removal of legacy exception names.
- A forced migration from sync REST to async REST.
- A live X-Plane dependency for tests.
- A new testing framework.
- A broad example rewrite outside docs-focused work.
- A breaking public API change unless a future major-version plan explicitly approves it.

---

## Success Criteria

vNext succeeds when:

- The public API is easy to explain from the docs alone.
- Each transport has clear lifecycle, error, and return behavior.
- The remaining P0 coverage work is complete.
- P1 features are implemented or have current accepted specs and plans.
- New contributors can run one local quality workflow and trust the result.
- Examples and docs make transport selection obvious.
- Existing public entry points continue to work.
- The priority backlog remains the source of truth for roadmap sequencing.

---

## Product Risks

### Transport Semantics Diverge

REST, async REST, WebSocket, and UDP cannot be perfectly identical. The product should document transport differences instead of hiding them behind weak abstractions.

### Compatibility Slows Cleanup

Legacy factories, aliases, and cache behavior are valuable for users but can preserve internal complexity. vNext should prefer compatibility with clear internal migration steps.

### Tests Become Over-Mocked

No live simulator dependency is correct for local validation, but tests must still assert real protocol payloads, packet shapes, URLs, and callback behavior. Shared helpers should reduce setup without hiding behavior under opaque fixtures.

### Scope Creep

The backlog includes quality, architecture, docs, and performance work. The P0-P3 model should keep sequencing explicit so vNext does not become a rewrite.

---

## Documentation Requirements

Docs should include:

- Transport selection guide.
- Connection lifecycle guide.
- Sync REST quickstart.
- Async REST quickstart.
- WebSocket monitoring guide.
- UDP and beacon guide.
- Error handling guide.
- Testing and contribution workflow.

Each guide should use the current public factories and should prefer short, working examples.

---

## Quality Workflow

The project quality workflow remains:

```powershell
uv run python -m unittest discover -v
uv run ruff check xpwebapi tests
uv run ruff format --check xpwebapi tests
```

Future CI should run the same checks before adding publishing or release automation.
