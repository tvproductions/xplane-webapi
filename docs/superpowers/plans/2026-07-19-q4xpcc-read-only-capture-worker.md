# Q4XPCC Read-Only Capture Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a hardened, strictly read-only WebSocket/UDP capture worker for q4xpcc development evidence.

**Architecture:** Existing clients gain opt-in read-only guards plus guarded
raw-handle proxies while retaining their normal default behavior. A narrow
worker validates a versioned JSON request, owns bounded transport lifecycle and
fixed-cadence sampling, and emits strict raw JSONL plus atomic status for
q4xpcc to consume through a process/file boundary.

**Tech Stack:** Python 3.12, Pydantic 2, `httpx`, `websockets` 16, stdlib
`unittest`, `uv`, `ruff`, and `ty`.

## Global Constraints

- Source design: `docs/superpowers/specs/2026-07-19-q4xpcc-read-only-capture-worker-design.md`.
- Tests use stdlib `unittest`; pytest is prohibited.
- Default clients remain backward-compatible and write-capable.
- Capture mode cannot write DataRefs, create or execute commands, initialize a
  flight, reposition X-Plane, or dispatch an arbitrary method or packet.
- Every network attempt, feedback wait, first-value wait, retry, reconnect, and
  shutdown operation has a finite configured bound.
- WebSocket is primary. UDP is diagnostic/fallback and supports only
  float-valued `RREF` observations at integral rates.
- Output is UTF-8, LF-only JSON/JSONL with `allow_nan=False`.
- q4xpcc packages and models are not imported.
- Do not modify `examples/`; the repository hygiene skill prohibits it unless
  the user explicitly requests example changes.

## File Structure

- `xpwebapi/read_only.py`: guarded HTTP, async HTTP, WebSocket, and UDP raw
  handle proxies.
- `xpwebapi/capture_protocol.py`: strict request, transport, retry, and
  correlation models plus request hashing.
- `xpwebapi/capture_events.py`: strict event/status models and transition map.
- `xpwebapi/capture_output.py`: JSONL writer, atomic status writer, and source
  provenance.
- `xpwebapi/capture_transport.py`: narrow WebSocket and UDP adapters.
- `xpwebapi/capture_runner.py`: readiness, cadence, gaps, reconnect, and
  finalization state machine.
- `xpwebapi/capture_cli.py`: preflight, signals, path semantics, and exit codes.
- `schemas/capture-request-v1.schema.json`: checked strict request schema.
- `schemas/capture-event-v1.schema.json`: checked discriminated event schema.
- `schemas/capture-status-v1.schema.json`: checked conditional status schema.
- `schemas/capture-version-v1.schema.json`: checked provenance-probe schema.

---

### Task 1: Library-Level Read-Only Guard and Raw-Handle Proxies

**Files:**
- Create: `xpwebapi/read_only.py`
- Modify: `xpwebapi/exceptions.py`
- Modify: `xpwebapi/api.py`
- Modify: `xpwebapi/rest.py`
- Modify: `xpwebapi/async_rest.py`
- Modify: `xpwebapi/ws.py`
- Modify: `xpwebapi/udp.py`
- Modify: `xpwebapi/__init__.py`
- Test: `tests/test_api.py`
- Test: `tests/test_rest.py`
- Test: `tests/test_async_rest.py`
- Test: `tests/test_ws.py`
- Test: `tests/test_udp.py`
- Test: `tests/test_type_annotations.py`

**Interfaces:**
- `XPReadOnlyViolation(XPWebAPIError)`.
- `API.read_only: bool`.
- `API._require_write_access(operation: str) -> None`.
- `_ReadOnlyHttpClientProxy`, `_ReadOnlyAsyncHttpClientProxy`,
  `_ReadOnlyWebsocketProxy`, and `_ReadOnlyDatagramSocketProxy`.
- `XPUDPAPI.monitor_dataref(dataref: Dataref, frequency_hz: int = 1) -> bool | int`.
- `XPWebsocketAPI(host: str = "127.0.0.1", port: int = 8086,
  api: str = "api", api_version: str = "v2", use_rest: bool = False,
  retry_attempts: int = 1, retry_backoff: float = 0.0,
  retry_backoff_max: float = 5.0, http_timeout: float | None = None,
  open_timeout: float = 10.0, close_timeout: float = 10.0,
  read_only: bool = False)`.
- `XPWebsocketAPI.stop(timeout_seconds: float | None = None)` and
  `disconnect(timeout_seconds: float | None = None)` retain existing constant
  defaults when no timeout is supplied.
- `XPUDPAPI.stop(timeout_seconds: float | None = None)` retains its existing
  default when no timeout is supplied.
- Existing behavior remains unchanged when `read_only=False`.

- [ ] **Step 1: Write failing high-level and raw-handle tests**

Add tests using actual constructor shapes:

```python
def test_read_only_rest_rejects_write_and_raw_post_before_http(self):
    raw_session = MagicMock()
    with patch("xpwebapi.rest._make_http_client", return_value=raw_session):
        api = XPRestAPI(read_only=True)
    dataref = api.dataref("sim/test/value")
    dataref.value = 1.0

    with self.assertRaises(XPReadOnlyViolation):
        api.write_dataref(dataref)
    with self.assertRaises(XPReadOnlyViolation):
        api.session.post("http://127.0.0.1", json={"value": 1.0})

    raw_session.post.assert_not_called()


def test_read_only_api_rejects_command_and_auto_save(self):
    api = DummyAPI()
    api.read_only = True

    with self.assertRaises(XPReadOnlyViolation):
        api.command("sim/test/command")
    with self.assertRaises(XPReadOnlyViolation):
        api.dataref("sim/test/value", auto_save=True)


def test_read_only_websocket_raw_handle_rejects_action_message(self):
    raw_websocket = MagicMock()
    proxy = _ReadOnlyWebsocketProxy(raw_websocket)

    with self.assertRaises(XPReadOnlyViolation):
        proxy.send(json.dumps({"type": "dataref_set_values"}))

    raw_websocket.send.assert_not_called()


def test_read_only_udp_raw_handle_accepts_rref_and_rejects_cmnd(self):
    raw_socket = MagicMock()
    destination = ("127.0.0.1", 49000)
    proxy = _ReadOnlyDatagramSocketProxy(raw_socket, destination)
    rref = struct.pack("<5sii400s", b"RREF\x00", 1, 0, b"sim/test/value")

    proxy.sendto(rref, destination)
    with self.assertRaises(XPReadOnlyViolation):
        proxy.sendto(b"CMND\x00sim/test/command", destination)

    raw_socket.sendto.assert_called_once_with(rref, destination)
```

Also add async `post`, WebSocket high-level write/command, UDP `DREF`/`CMND`,
unknown proxy attribute, malformed `RREF`, non-integral frequency, and normal
client regression tests. Update the expected `API.__annotations__` set with
`read_only`.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```powershell
uv run python -m unittest tests.test_api tests.test_rest tests.test_async_rest tests.test_ws tests.test_udp tests.test_type_annotations -v
```

Expected: failures identify the missing exception, constructor keyword,
proxies, frequency parameter, and protocol annotation.

- [ ] **Step 3: Implement guarded proxies**

Implement `xpwebapi/read_only.py` with these exact supported operations:

```python
READ_ONLY_WS_TYPES = frozenset(
    {"dataref_subscribe_values", "dataref_unsubscribe_values"}
)


def _forbidden_attribute(name: str) -> Never:
    raise XPReadOnlyViolation(f"read-only handle forbids attribute {name}")


class _ReadOnlyHttpClientProxy:
    def __init__(self, client: httpx.Client) -> None:
        self.__client = client

    def get(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return self.__client.get(*args, **kwargs)

    def close(self) -> None:
        self.__client.close()

    def __getattr__(self, name: str) -> Never:
        return _forbidden_attribute(name)


class _ReadOnlyAsyncHttpClientProxy:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.__client = client

    async def get(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return await self.__client.get(*args, **kwargs)

    async def aclose(self) -> None:
        await self.__client.aclose()

    def __getattr__(self, name: str) -> Never:
        return _forbidden_attribute(name)


class _ReadOnlyWebsocketProxy:
    def __init__(self, websocket: ClientConnection) -> None:
        self.__websocket = websocket

    def recv(self, *args: Any, **kwargs: Any) -> str | bytes:
        return self.__websocket.recv(*args, **kwargs)

    def close(self) -> None:
        self.__websocket.close()

    def send(self, message: str | bytes) -> None:
        if not isinstance(message, str):
            raise XPReadOnlyViolation("read-only WebSocket requires JSON text")
        try:
            payload = json.loads(message)
        except json.JSONDecodeError as exc:
            raise XPReadOnlyViolation("read-only WebSocket requires valid JSON") from exc
        if not isinstance(payload, dict) or payload.get("type") not in READ_ONLY_WS_TYPES:
            raise XPReadOnlyViolation("read-only WebSocket forbids action payload")
        self.__websocket.send(message)

    def __getattr__(self, name: str) -> Never:
        return _forbidden_attribute(name)


class _ReadOnlyDatagramSocketProxy:
    def __init__(
        self, udp_socket: socket.socket, destination: tuple[str, int]
    ) -> None:
        self.__socket = udp_socket
        self.__destination = destination

    def settimeout(self, value: float) -> None:
        self.__socket.settimeout(value)

    def recvfrom(self, size: int) -> tuple[bytes, Any]:
        return self.__socket.recvfrom(size)

    def close(self) -> None:
        self.__socket.close()

    def sendto(self, message: bytes, address: tuple[str, int]) -> int:
        if len(message) != 413 or address != self.__destination:
            raise XPReadOnlyViolation("read-only UDP packet shape or destination invalid")
        header, frequency, index, path_field = struct.unpack("<5sii400s", message)
        nul = path_field.find(b"\x00")
        path = path_field[:nul] if nul >= 0 else b""
        padding = path_field[nul + 1 :] if nul >= 0 else path_field
        if (
            header != b"RREF\x00"
            or frequency < 0
            or frequency > 100
            or index < 0
            or not path
            or any(padding)
        ):
            raise XPReadOnlyViolation("read-only UDP permits only valid RREF packets")
        try:
            path.decode("ascii")
        except UnicodeDecodeError as exc:
            raise XPReadOnlyViolation("read-only UDP requires an ASCII RREF path") from exc
        return self.__socket.sendto(message, address)

    def __getattr__(self, name: str) -> Never:
        return _forbidden_attribute(name)
```

Import `Any` and `Never` from `typing`, `httpx`, `socket`, and
`ClientConnection`. Annotate `API.session`, `XPRestAPI.session`,
`AsyncXPRestAPI.session`, `XPWebsocketAPI.ws`, and `XPUDPAPI.socket` with their
normal handle or matching proxy union so `ty` sees every permitted method. Do
not expose proxy internals in `xpwebapi.__all__`.

- [ ] **Step 4: Propagate read-only state through actual clients**

Add `read_only` to `API.__annotations__` and `API.__init__`, and implement:

```python
def _require_write_access(self, operation: str) -> None:
    if self.read_only:
        raise XPReadOnlyViolation(f"read-only API forbids {operation}")
```

Call it before command construction, `auto_save=True`, every REST/async/WS/UDP
write, every command execution, and every command setter. Wrap created raw
handles only when read-only. In `XPWebsocketAPI.connect_websocket()`, pass both
`open_timeout=self.open_timeout` and `close_timeout=self.close_timeout` to the
actual `websockets.sync.client.connect` call. In UDP,
route existing sends through `_send_packet()` and validate
`frequency_hz` with `isinstance(frequency_hz, int)`, excluding `bool`, and
`frequency_hz > 0`. Add optional timeout arguments to WebSocket stop/disconnect
and UDP stop; defaults use the current class constants, while capture adapters
pass their remaining shutdown deadline. Pass `http_timeout` to
`XPRestAPI.__init__(timeout=http_timeout)`.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run the Step 2 command. Expected: all focused tests pass and normal clients
still emit their existing REST, WebSocket, `DREF`, and `CMND` operations.

- [ ] **Step 6: Commit**

```powershell
git add xpwebapi/read_only.py xpwebapi/exceptions.py xpwebapi/api.py xpwebapi/rest.py xpwebapi/async_rest.py xpwebapi/ws.py xpwebapi/udp.py xpwebapi/__init__.py tests/test_api.py tests/test_rest.py tests/test_async_rest.py tests/test_ws.py tests/test_udp.py tests/test_type_annotations.py
git commit -m "feat: enforce read-only API mode"
```

### Task 2: Strict Capture Request Protocol

**Files:**
- Create: `xpwebapi/capture_protocol.py`
- Create: `tests/test_capture_protocol.py`
- Create: `schemas/capture-request-v1.schema.json`

**Interfaces:**
- Models: `CaptureCorrelation`, `AircraftIdentityRef`,
  `DatarefMatchIdentityReadiness`, `IdentityReadiness`,
  `WebsocketCaptureConfig`, `UdpCaptureConfig`, `CaptureTransportConfig`,
  `CaptureSampleGroup`, `CaptureRef`, `CaptureRetryPolicy`, `CaptureRequest`,
  and `LoadedCaptureRequest`.
- Functions:
  - `load_capture_request(path: Path) -> LoadedCaptureRequest` reads once,
    rejects duplicate keys, parses, validates, and hashes those bytes.
  - `resolve_stop_file(request_path: Path, request_value: Path | None,
    cli_value: Path | None) -> Path | None`.

- [ ] **Step 1: Write failing strict-model tests**

Create a `valid_request_payload(transport="websocket")` helper matching the
complete JSON in the design. Test exact version, extra-field rejection,
duplicate group/ref/path rejection, unknown group, empty strings, NaN/infinity,
attempt bounds, backoff ordering, missing string encoding, numeric encoding,
UDP non-float refs, UDP fractional/zero/over-100 rates, exact-byte SHA-256, and
stop-file conflict/existing-file behavior. Also test duplicate JSON keys;
strict non-coercion of strings, booleans, integers, floats, enums, and
collections; ports 0/65536/bool; malformed and negative array indexes; unknown
codecs; identity value/operator/type compatibility; identity/capture path
collisions; transport and identity discriminator rejection; and canonical
checked-schema equality.

Representative tests:

```python
def test_udp_rejects_fractional_rate(self):
    payload = valid_request_payload(transport="udp")
    payload["sample_groups"][0]["rate_hz"] = 2.5

    with self.assertRaises(ValidationError):
        CaptureRequest.model_validate(payload)


def test_stop_file_cli_and_request_must_agree(self):
    with self.assertRaises(ValueError):
        resolve_stop_file(
            Path("request.json"), Path("request.stop"), Path("cli.stop")
        )
```

- [ ] **Step 2: Run and confirm RED**

Run:

```powershell
uv run python -m unittest tests.test_capture_protocol -v
```

Expected: import failure for `xpwebapi.capture_protocol`.

- [ ] **Step 3: Implement exact models and validators**

Use `ConfigDict(extra="forbid", frozen=True, strict=True)`. Define the discriminated
transport union with `Field(discriminator="kind")`. Use these exact fields:

```python
class CaptureCorrelation(StrictModel):
    campaign_id: str
    route_profile_id: str
    scenario_id: str


class WebsocketCaptureConfig(StrictModel):
    kind: Literal["websocket"]
    host: str
    port: int
    api_path: str = "/api"
    api_version: str = "v2"
    http_timeout_seconds: float = 5.0
    open_timeout_seconds: float = 5.0
    close_timeout_seconds: float = 5.0


class UdpCaptureConfig(StrictModel):
    kind: Literal["udp"]
    beacon_timeout_seconds: float = 5.0
    socket_timeout_seconds: float = 1.0
    liveness_timeout_seconds: float = 3.0


class AircraftIdentityRef(StrictModel):
    id: str
    path: str
    declared_type: Literal["int", "float", "double", "string"]
    encoding: str | None = None
    rate_hz: float = 1.0
    operator: Literal["equals", "contains"]
    expected_value: int | float | str


class DatarefMatchIdentityReadiness(StrictModel):
    kind: Literal["dataref_match"]
    target_aircraft: Literal["FlyJSim Q4XP"]
    refs: tuple[AircraftIdentityRef, ...]


class CaptureSampleGroup(StrictModel):
    id: str
    rate_hz: float
    duration_seconds: float | None = None


class CaptureRef(StrictModel):
    id: str
    path: str
    declared_type: Literal["int", "float", "double", "string"]
    availability: Literal["required", "optional"]
    sample_group_id: str
    encoding: str | None = None


class CaptureRetryPolicy(StrictModel):
    initial_attempts: int = 3
    reconnect_attempts: int = 3
    backoff_seconds: float = 0.5
    backoff_max_seconds: float = 5.0
    subscription_timeout_seconds: float = 10.0
    aircraft_identity_timeout_seconds: float = 300.0
    first_values_timeout_seconds: float = 30.0
    max_disconnect_seconds: float = 30.0
    stale_after_seconds: float = 3.0
    poll_interval_seconds: float = 0.25
    shutdown_timeout_seconds: float = 10.0


IdentityReadiness = Annotated[
    DatarefMatchIdentityReadiness,
    Field(discriminator="kind"),
]
CaptureTransportConfig = Annotated[
    WebsocketCaptureConfig | UdpCaptureConfig,
    Field(discriminator="kind"),
]


class CaptureRequest(StrictModel):
    protocol_version: Literal[1]
    capture_session_id: str
    sortie_id: str
    correlation: CaptureCorrelation
    identity_readiness: IdentityReadiness
    transport: CaptureTransportConfig
    sample_groups: tuple[CaptureSampleGroup, ...]
    refs: tuple[CaptureRef, ...]
    retry: CaptureRetryPolicy
    capture_limit_seconds: float | None = None
    stop_file: str | None = None


@dataclass(frozen=True, slots=True)
class LoadedCaptureRequest:
    request: CaptureRequest
    request_sha256: str
```

Implement field/model validators for every rule in the design. Decode with
`json.loads(text, object_pairs_hook=reject_duplicate_keys)` and feed the result
to strict models. Resolve relative stop paths against the request file's
parent. Hash the exact single byte buffer read from disk, not normalized JSON.
Write canonical `CaptureRequest.model_json_schema()` and test exact equality
with `schemas/capture-request-v1.schema.json`.

- [ ] **Step 4: Run and confirm GREEN**

Run the Step 2 command. Expected: all request and stop-file tests pass.

- [ ] **Step 5: Commit**

```powershell
git add xpwebapi/capture_protocol.py tests/test_capture_protocol.py schemas/capture-request-v1.schema.json
git commit -m "feat: define capture worker request protocol"
```

### Task 3: Strict Events, Atomic Status, and Provenance

**Files:**
- Create: `xpwebapi/capture_events.py`
- Create: `xpwebapi/capture_output.py`
- Create: `tests/test_capture_events.py`
- Create: `tests/test_capture_output.py`
- Create: `schemas/capture-event-v1.schema.json`
- Create: `schemas/capture-status-v1.schema.json`
- Create: `schemas/capture-version-v1.schema.json`

**Interfaces:**
- `CaptureEventKind`, `SampleStatus`, `CaptureStatusState` string enums.
- Strict payload models for all twelve event kinds from the design, plus
  `SourceProvenance`, `TransportCapabilities`, `CaptureCounters`,
  `VersionJsonDocument`, and discriminated nonterminal/terminal status models.
- `StatusDocument` union and `LEGAL_STATUS_TRANSITIONS`.
- `CaptureEventWriter.write(payload: CaptureEventPayload) -> dict[str, object]`.
- `CaptureEventWriter.close(payload: CaptureStoppedInput | CaptureFailedInput |
  CaptureInterruptedInput) -> dict[str, object]`.
- `AtomicStatusWriter.write(document: StatusDocument) -> None`.
- `resolve_source_provenance() -> SourceProvenance`.

- [ ] **Step 1: Write failing schema, transition, and durability tests**

Test every event, provenance, capability, counter, version, and status model
for required fields, strict non-coercion, and extra-field rejection. Test
sequences `1, 2`, LF endings, NaN rejection, exact preceding hash, full-file
hash after close, legal transitions, terminal immutability, same-directory
replacement, Git worktree discovery, dirty state, Git-unavailable state,
terminal-only hash/size/exit fields, non-negative integer counters, persistent
transport/aircraft readiness latches, and equality with all three checked
schemas from this task.

```python
def test_status_rejects_transition_from_complete_to_capturing(self):
    writer = AtomicStatusWriter(status_path)
    for state in (
        "starting",
        "connecting",
        "transport_ready",
        "awaiting_aircraft",
        "subscribing",
        "awaiting_first_values",
        "aircraft_ready",
        "capturing",
        "finalizing",
        "complete",
    ):
        writer.write(status_document(state))

    with self.assertRaises(ValueError):
        writer.write(status_document("capturing"))


def test_terminal_row_hashes_all_preceding_bytes(self):
    writer = CaptureEventWriter(events_path, identity, clock)
    first = writer.write(capture_started_input())
    first_bytes = (
        json.dumps(first, allow_nan=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    terminal = writer.close(capture_stopped_input())

    self.assertEqual(
        hashlib.sha256(first_bytes).hexdigest(), terminal["preceding_sha256"]
    )
```

- [ ] **Step 2: Run and confirm RED**

Run:

```powershell
uv run python -m unittest tests.test_capture_events tests.test_capture_output -v
```

Expected: imports fail.

- [ ] **Step 3: Implement exact event and status models**

Implement the canonical models below exactly; validators add the positivity,
finite-number, Git-state, sample-value, timestamp-latch, attempt, and count
conditions stated in the design. `EventEnvelope.event` is overridden by every
concrete literal and `CaptureEvent` is discriminated on that field.

```python
JsonScalar = int | float | str

class SourceProvenance(StrictModel):
    package_name: str
    package_version: str
    python_version: str
    git_state: Literal["available", "unavailable"]
    git_root: str | None
    git_revision: str | None
    git_origin: str | None
    git_dirty: bool | None
    read_only: Literal[True]

class TransportCapabilities(StrictModel):
    transport: Literal["websocket", "udp"]
    endpoint: str
    xplane_version: str | None
    value_types: tuple[Literal["int", "float", "double", "string"], ...]

class IdentityObservation(StrictModel):
    ref_id: str
    path: str
    operator: Literal["equals", "contains"]
    expected_value: JsonScalar
    observed_value: JsonScalar
    source_observed_elapsed_seconds: float
    source_age_seconds: float

class CaptureCounters(StrictModel):
    sample_count: int
    gap_count: int
    retry_count: int
    accepted_ref_count: int
    rejected_ref_count: int

class EventEnvelope(StrictModel):
    protocol_version: Literal[1]
    event: str
    sequence: int
    capture_session_id: str
    sortie_id: str
    timestamp_utc: str
    elapsed_seconds: float

class CaptureStartedEvent(EventEnvelope):
    event: Literal["capture_started"]
    request_sha256: str
    correlation: CaptureCorrelation
    transport: CaptureTransportConfig
    provenance: SourceProvenance

class TransportStateEvent(EventEnvelope):
    event: Literal["transport_state"]
    state: Literal["connected", "disconnected"]
    attempt: int
    reason: str | None
    capabilities: TransportCapabilities

class TransportReadyEvent(EventEnvelope):
    event: Literal["transport_ready"]
    connection_generation: int
    endpoint: str
    read_only: Literal[True]
    package_version: str
    git_revision: str | None
    git_dirty: bool | None
    capabilities: TransportCapabilities

class SubscriptionResultEvent(EventEnvelope):
    event: Literal["subscription_result"]
    purpose: Literal["aircraft_identity", "capture"]
    accepted_ref_ids: tuple[str, ...]
    rejected: dict[str, str]
    request_id: int | None

class AircraftReadyEvent(EventEnvelope):
    event: Literal["aircraft_ready"]
    connection_generation: int
    target_aircraft: Literal["FlyJSim Q4XP"]
    identity_observations: tuple[IdentityObservation, ...]
    required_ref_ids: tuple[str, ...]
    optional_missing_ref_ids: tuple[str, ...]
    ready_elapsed_seconds: float

class SampleEvent(EventEnvelope):
    event: Literal["sample"]
    sample_group_id: str
    ref_id: str
    path: str
    declared_type: Literal["int", "float", "double", "string"]
    status: Literal[
        "sampled", "missing", "stale", "disconnected", "unsupported", "invalid"
    ]
    value: JsonScalar | None
    source_observed_elapsed_seconds: float | None
    source_age_seconds: float | None

class GapStartedEvent(EventEnvelope):
    event: Literal["gap_started"]
    reason: str
    affected_ref_ids: tuple[str, ...]
    gap_start_elapsed_seconds: float

class GapEndedEvent(EventEnvelope):
    event: Literal["gap_ended"]
    reason: str
    affected_ref_ids: tuple[str, ...]
    gap_start_elapsed_seconds: float
    gap_duration_seconds: float
    skipped_slot_count: int

class RetryEvent(EventEnvelope):
    event: Literal["retry"]
    phase: Literal["initial_connect", "reconnect"]
    attempt: int
    maximum_attempts: int
    delay_seconds: float
    reason: str

class CaptureStoppedEvent(EventEnvelope):
    event: Literal["capture_stopped"]
    termination: Literal[
        "stop_file", "capture_limit", "requested", "groups_complete"
    ]
    sample_count: int
    gap_count: int
    retry_count: int
    preceding_sha256: str

class CaptureFailedEvent(EventEnvelope):
    event: Literal["capture_failed"]
    reason: str
    sample_count: int
    gap_count: int
    retry_count: int
    preceding_sha256: str

class CaptureInterruptedEvent(EventEnvelope):
    event: Literal["capture_interrupted"]
    signal: Literal["SIGINT", "SIGTERM"]
    sample_count: int
    gap_count: int
    retry_count: int
    preceding_sha256: str

CaptureEvent = Annotated[
    CaptureStartedEvent | TransportStateEvent | TransportReadyEvent
    | SubscriptionResultEvent | AircraftReadyEvent | SampleEvent
    | GapStartedEvent | GapEndedEvent | RetryEvent | CaptureStoppedEvent
    | CaptureFailedEvent | CaptureInterruptedEvent,
    Field(discriminator="event"),
]
```

Implement status/version fields exactly as follows. Terminal-only fields do not
exist on `NonterminalStatus`.

```python
NonterminalState = Literal[
    "starting", "connecting", "transport_ready", "awaiting_aircraft",
    "subscribing", "awaiting_first_values", "aircraft_ready", "capturing",
    "reconnecting", "finalizing",
]

class StatusBase(StrictModel):
    protocol_version: Literal[1]
    capture_session_id: str
    sortie_id: str
    state: str
    updated_at_utc: str
    elapsed_seconds: float
    events_path: str
    request_sha256: str
    transport: Literal["websocket", "udp"]
    transport_connection_state: Literal[
        "not_connected", "connected", "awaiting_first_identity_packet",
        "disconnected",
    ]
    connection_generation: int
    transport_ready_at_utc: str | None
    aircraft_ready_at_utc: str | None
    target_aircraft: Literal["FlyJSim Q4XP"]
    identity_ref_count: int
    matched_identity_ref_count: int
    required_capture_ref_count: int
    observed_required_ref_count: int
    counters: CaptureCounters
    attempt_phase: Literal["none", "initial_connect", "reconnect"]
    current_attempt: int
    maximum_attempts: int
    reason: str | None

class NonterminalStatus(StatusBase):
    state: NonterminalState

class CompleteStatus(StatusBase):
    state: Literal["complete"]
    reason: Literal["stop_file", "capture_limit", "requested", "groups_complete"]
    events_sha256: str
    events_size_bytes: int
    exit_code: Literal[0]
    clean_shutdown: Literal[True]

class FailedStatus(StatusBase):
    state: Literal["failed"]
    reason: str
    events_sha256: str
    events_size_bytes: int
    exit_code: Literal[3]
    clean_shutdown: Literal[False]

class InterruptedStatus(StatusBase):
    state: Literal["interrupted"]
    reason: Literal["SIGINT", "SIGTERM"]
    events_sha256: str
    events_size_bytes: int
    exit_code: Literal[130]
    clean_shutdown: bool

StatusDocument = Annotated[
    NonterminalStatus | CompleteStatus | FailedStatus | InterruptedStatus,
    Field(discriminator="state"),
]

class VersionJsonDocument(StrictModel):
    git_dirty: bool | None
    git_origin: str | None
    git_revision: str | None
    git_root: str | None
    git_state: Literal["available", "unavailable"]
    package_name: str
    package_version: str
    python_version: str
    read_only: Literal[True]
    supported_transports: tuple[Literal["udp"], Literal["websocket"]]
    worker: Literal["xpwebapi-capture"]
    worker_protocol_version: Literal[1]
```

Define
`LEGAL_STATUS_TRANSITIONS` exactly as:

```python
LEGAL_STATUS_TRANSITIONS = {
    "starting": frozenset({"connecting", "failed", "interrupted"}),
    "connecting": frozenset(
        {"connecting", "transport_ready", "failed", "interrupted"}
    ),
    "transport_ready": frozenset(
        {"awaiting_aircraft", "failed", "interrupted"}
    ),
    "awaiting_aircraft": frozenset(
        {"subscribing", "reconnecting", "failed", "interrupted"}
    ),
    "subscribing": frozenset(
        {"awaiting_first_values", "reconnecting", "failed", "interrupted"}
    ),
    "awaiting_first_values": frozenset(
        {"aircraft_ready", "reconnecting", "failed", "interrupted"}
    ),
    "aircraft_ready": frozenset(
        {"capturing", "finalizing", "failed", "interrupted"}
    ),
    "capturing": frozenset(
        {"reconnecting", "finalizing", "failed", "interrupted"}
    ),
    "reconnecting": frozenset(
        {"reconnecting", "transport_ready", "failed", "interrupted"}
    ),
    "finalizing": frozenset({"complete", "failed", "interrupted"}),
    "complete": frozenset(),
    "failed": frozenset(),
    "interrupted": frozenset(),
}
```

`StatusDocument` contains every field in the design and makes terminal hash,
size, exit code, and clean-shutdown fields mandatory only for terminal states.
The writer requires `starting` as its first state. A repeated connecting or
reconnecting state must strictly increment `current_attempt` within
`maximum_attempts`. Readiness timestamps are write-once latches carried into
every later status document. Generate canonical schemas from the literal
strict unions and compare them byte-for-byte after canonical JSON rendering.

- [ ] **Step 4: Implement writers and provenance**

Serialize compact sorted JSON with a single LF. Track the digest using the
exact bytes written before the terminal row. Use a unique temporary filename
containing PID and a random token, flush and fsync it, then call `os.replace`.
Resolve Git from `Path(__file__).resolve()` with `subprocess.run`, `timeout=2`,
`check=False`, and captured text for:

```text
git -C <module-directory> rev-parse --show-toplevel
git -C <root> rev-parse HEAD
git -C <root> config --get remote.origin.url
git -C <root> status --porcelain
```

Represent unavailable Git as `git_state="unavailable"`, null revision/origin,
and null dirty state.

- [ ] **Step 5: Run and confirm GREEN**

Run the Step 2 command. Expected: all schema, transition, durability, and
provenance tests pass.

- [ ] **Step 6: Commit**

```powershell
git add xpwebapi/capture_events.py xpwebapi/capture_output.py tests/test_capture_events.py tests/test_capture_output.py schemas/capture-event-v1.schema.json schemas/capture-status-v1.schema.json schemas/capture-version-v1.schema.json
git commit -m "feat: add durable capture evidence protocol"
```

### Task 4: Narrow Read-Only Transport Adapters

**Files:**
- Create: `xpwebapi/capture_transport.py`
- Create: `tests/test_capture_transport.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class Observation:
    ref_id: str
    path: str
    value: object
    observed_monotonic: float


@dataclass(frozen=True, slots=True)
class SubscriptionResult:
    purpose: Literal["aircraft_identity", "capture"]
    accepted_ref_ids: tuple[str, ...]
    rejected: Mapping[str, str]
    request_id: int | None


class CaptureTransport(Protocol):
    @property
    def liveness_state(self) -> Literal[
        "connected", "awaiting_first_identity_packet", "disconnected"
    ]:
        return "disconnected"

    @property
    def connected(self) -> bool:
        return False

    def open(self, deadline: float) -> TransportCapabilities:
        raise RuntimeError("CaptureTransport.open must be implemented")

    def subscribe(
        self,
        refs: Sequence[AircraftIdentityRef | CaptureRef],
        purpose: Literal["aircraft_identity", "capture"],
        callback: Callable[[Observation], None],
        deadline: float,
    ) -> SubscriptionResult:
        raise RuntimeError("CaptureTransport.subscribe must be implemented")

    def close(self, deadline: float) -> None:
        raise RuntimeError("CaptureTransport.close must be implemented")
```

The concrete adapters implement the protocol. The runner reconnects by closing
the old adapter and asking the factory for a new adapter; there is no
`reconnect()` method.

- [ ] **Step 1: Write failing adapter and subscription-feedback tests**

Use fake client factories that record constructor keywords and clients. Verify:

- every constructed client receives `read_only=True`;
- each DataRef receives `auto_save=False`;
- every blocking fake receives a timeout no greater than the remaining absolute
  deadline, with a non-positive remaining deadline preventing the call;
- the actual WebSocket `connect` fake receives both `open_timeout` and
  `close_timeout`, each no greater than the then-remaining deadline;
- WebSocket uses `connect_websocket()` and never calls `connect()`,
  `wait_connection()`, or the background connection monitor;
- the listener starts before waiting for feedback;
- successful `ON_REQUEST_FEEDBACK` accepts the batch;
- failed or timed-out feedback rejects refs;
- request feedback delivered before `monitor_datarefs()` returns is recovered
  from the request-id buffer, while feedback for another id is ignored;
- a new adapter/client subscribes once after reconnect;
- UDP retains the `XPBeaconMonitor` and returned `BeaconData`, passes the
  monitor plus `data.host` and `data.port` to `XPUDPAPI`, and bounds socket reads;
- UDP passes `int(rate_hz)` to `monitor_dataref`;
- after UDP identity subscription, liveness is
  `awaiting_first_identity_packet`, not `disconnected`, until the first valid
  configured identity-index packet or the identity deadline;
- after first UDP liveness, silence expires after `liveness_timeout_seconds`
  and reconnects despite a previously successful beacon;
- neither adapter creates or validates capture-ref DataRefs before fresh
  matching identity observations;
- guarded UDP rejects wrong destination/header/length, negative index,
  frequency outside 0..100, missing/invalid NUL path, non-ASCII path, and
  nonzero padding;
- adapters expose no property returning the underlying client or socket.

```python
def test_fresh_websocket_adapter_resubscribes_once(self):
    first = create_capture_transport(request, client_factory=factory)
    first.open(deadline=10.0)
    first.subscribe(request.refs, "capture", callback, deadline=10.0)
    first.close(deadline=10.0)
    second = create_capture_transport(request, client_factory=factory)
    second.open(deadline=20.0)
    second.subscribe(request.refs, "capture", callback, deadline=20.0)

    self.assertEqual([True, True], factory.read_only_arguments)
    self.assertEqual([1, 1], [client.subscribe_calls for client in factory.clients])
```

- [ ] **Step 2: Run and confirm RED**

Run:

```powershell
uv run python -m unittest tests.test_capture_transport -v
```

Expected: import failure.

- [ ] **Step 3: Implement the WebSocket adapter**

For one open attempt, clamp each call to `deadline - clock.monotonic()`:

1. Construct `XPWebsocketAPI` with request host, port, API path/version,
   `read_only=True`, `retry_attempts=1`, finite REST timeout, and finite
   `open_timeout` and `close_timeout`; verify both reach the actual
   `websockets.sync.client.connect` call.
2. Register `ON_DATAREF_UPDATE`, `ON_REQUEST_FEEDBACK`, and `ON_CLOSE` callbacks.
3. Call `connect_websocket()` and fail if `connected` is false.
4. Return base endpoint capabilities without creating or resolving a DataRef.
5. In each `subscribe()` call, create only that call's DataRefs with
   `auto_save=False`, then resolve and validate their metadata. Identity is the
   first call; capture refs are deferred until identity readiness succeeds.
6. Call `start(release=True)` so feedback can be received.
7. Initialize the feedback dictionary and condition before the batch call.
8. Have the callback store every result by request id before notifying.
9. Call one `monitor_datarefs()` batch and retain its integer request id.
10. Check buffered feedback for that id before waiting; then wait only to the
    lesser of `subscription_timeout_seconds` and the remaining deadline.
11. Map callback paths to ref ids and emit `Observation` with injected
   monotonic time.
12. Close by batch-unsubscribing, stopping the listener, disconnecting the
   WebSocket, and closing the HTTP session within the shutdown deadline.

- [ ] **Step 4: Implement the UDP adapter**

Construct and retain `monitor = XPBeaconMonitor(...)`, then call
`data = monitor.get_beacon(timeout=min(beacon_timeout_seconds, remaining))`
with one attempt per worker attempt. Construct exactly
`XPUDPAPI(beacon=monitor, host=data.host, port=data.port, read_only=True)`, set
the guarded socket timeout, register the callback, submit
each ref with `monitor_dataref(dataref, frequency_hz=int(rate_hz))`, and start
the listener. Return accepted/rejected ref ids from those calls. Close with
frequency-zero unsubscribe, listener stop, socket close, and beacon cleanup.
Pass the remaining `shutdown_timeout_seconds` to the bounded stop method.
Track the last valid configured-index RREF callback using the injected
monotonic clock; do not delegate `connected` to the beacon-backed API property.
After identity subscription but before the first valid identity-index packet,
report `liveness_state="awaiting_first_identity_packet"`; wait on the identity
deadline rather than reconnecting. After first liveness, receive timeouts leave
the listener responsive, and liveness expiry makes the
adapter disconnected so the runner performs its bounded fresh-adapter retry.
The runner passes the owning aircraft-identity deadline into identity
`subscribe()`. Each adapter derives the shorter internal operation deadline for
metadata/send/feedback, while UDP retains the full owner for the awaiting-first-
identity-packet state.

In `_ReadOnlyDatagramSocketProxy.sendto`, unpack `<5sii400s` and validate every
header, frequency, index, ASCII/NUL/padding, and configured-destination rule
from the design before calling the raw socket.

- [ ] **Step 5: Run and confirm GREEN**

Run the Step 2 command. Expected: all adapter, feedback, timeout, wire-safety,
and fresh-client resubscription tests pass.

- [ ] **Step 6: Commit**

```powershell
git add xpwebapi/capture_transport.py tests/test_capture_transport.py
git commit -m "feat: add read-only capture transports"
```

### Task 5: Capture Lifecycle, Cadence, Gaps, and Cleanup

**Files:**
- Create: `xpwebapi/capture_runner.py`
- Create: `tests/test_capture_runner.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class CaptureOutcome:
    terminal_state: Literal["complete", "failed", "interrupted"]
    termination: str
    reason: str | None
    transport_ready: bool
    aircraft_ready: bool
    sample_count: int
    gap_count: int
    retry_count: int
    clean_shutdown: bool

    @property
    def exit_code(self) -> int:
        if self.terminal_state == "interrupted":
            return 130
        if self.terminal_state == "complete" and self.clean_shutdown:
            return 0
        return 3


class CaptureClock(Protocol):
    def monotonic(self) -> float:
        return time.monotonic()

    def utcnow(self) -> datetime:
        return datetime.now(UTC)

    def wait(self, event: threading.Event, timeout: float) -> bool:
        return event.wait(timeout)


class CaptureRunner:
    def run(
        self,
        stop_event: threading.Event,
        interrupted_event: threading.Event,
    ) -> CaptureOutcome:
        return self._run_with_cleanup(stop_event, interrupted_event)
```

Constructor dependencies are `CaptureRequest`, exact `request_sha256`, resolved
`SourceProvenance`, resolved stop file, `Callable[[], CaptureTransport]`,
`CaptureEventWriter`, `AtomicStatusWriter`, `CaptureClock`, a path to the events
file, and a shared `CaptureInterruption` that retains the first SIGINT/SIGTERM
identity.
`_run_with_cleanup(stop_event, interrupted_event) -> CaptureOutcome` is the
single private implementation entry used by `run()` and is completed in Steps
3 through 5.

- [ ] **Step 1: Write failing lifecycle tests with deterministic fakes**

Create `FakeClock` whose `wait()` advances monotonic time, and fake transports
that synchronously publish configured observations. Test:

- evidence/status open before the first transport factory call;
- `transport_ready` is emitted and its status latch is set before any aircraft
  identity or capture subscription is sent;
- declared Q4XP identity refs must match before capture subscriptions begin;
- required rejected ref fails before readiness;
- optional rejected/missing ref does not prevent readiness;
- first required capture values gate `aircraft_ready` and timeout exactly;
- readiness latches survive later reconnecting/capturing status updates;
- status polling never changes the immutable JSONL byte stream;
- first group sample occurs at `aircraft_ready`;
- one late loop emits one skipped-slot gap and no catch-up burst;
- stale, disconnected, missing, unsupported, invalid, and sampled statuses;
- reconnect uses a fresh transport, clears cached observations, and requires
  fresh identity and capture values;
- UDP silence after the last valid configured-index `RREF,` packet triggers a
  reconnect even if beacon traffic continues;
- reconnect attempts and disconnect duration exhaust independently;
- stop file and capture limit complete cleanly, and exhaustion of all bounded
  groups completes with `termination="groups_complete"`;
- programmatic stop completes with `termination="requested"`;
- interruption returns 130 semantics;
- subscription, runtime, writer, and cleanup failures preserve partial JSONL;
- cleanup executes once and a shutdown timeout converts completion to failure.

```python
def test_late_scheduler_records_gap_without_burst_catch_up(self):
    clock = FakeClock(monotonic_values=[0.0, 0.0, 3.2, 4.0])
    outcome = make_runner(clock=clock, rate_hz=1.0).run(
        stop_event=threading.Event(), interrupted_event=threading.Event()
    )
    samples = [row for row in read_events() if row["event"] == "sample"]
    gaps = [row for row in read_events() if row["event"] == "gap_ended"]

    self.assertEqual(2, len(samples))
    self.assertEqual(2, gaps[0]["skipped_slot_count"])
    self.assertEqual("complete", outcome.terminal_state)
```

- [ ] **Step 2: Run and confirm RED**

Run:

```powershell
uv run python -m unittest tests.test_capture_runner -v
```

Expected: import failure.

- [ ] **Step 3: Implement readiness and retry state machine**

Write `starting`, then `connecting`. Set `current_attempt=1`, increment it for
every repeated `connecting` or `reconnecting` attempt, and never exceed the
phase's declared maximum. For each initial attempt, create a new transport and
call `open(connection_deadline)`. Once the underlying channel is usable, emit
`transport_ready`, latch `transport_ready_at_utc`, and enter
`awaiting_aircraft` before sending any aircraft subscription. This is the point
at which q4xpcc may load Q4XP. Emit retry with delay
`min(backoff_seconds * 2 ** failure_index, backoff_max_seconds)`. Fail after
`initial_attempts`.

Subscribe only the declared `identity_readiness.refs` with
`purpose="aircraft_identity"`, using a deadline no later than
`aircraft_identity_timeout_seconds`. Require every identity observation to
match its operator and expected value. Then enter `subscribing`, subscribe the
capture refs with `purpose="capture"`, enter `awaiting_first_values`, and
require a fresh observation for every required accepted ref before the
first-values deadline. Emit `aircraft_ready`, latch `aircraft_ready_at_utc`,
then enter `capturing`. Never use a generic `ready` state or event.

On disconnect, emit `gap_started`, set `reconnecting`, close the old transport,
clear observations, and use new factory instances for at most
`reconnect_attempts` and `max_disconnect_seconds`. Resubscribe the complete set,
emit a new-generation `transport_ready`, revalidate the declared Q4XP identity,
require fresh capture values, emit a new-generation `aircraft_ready`, then emit
`gap_ended` and return to `capturing`. Identity mismatch or identity-readiness
timeout is a failure, not permission to capture another aircraft.

- [ ] **Step 4: Implement exact cadence algorithm**

At `aircraft_ready`, set each active group's next deadline to
`aircraft_ready_monotonic`. At each loop choose the earliest deadline. After one sample set
`next_deadline += interval`. When `now >= next_deadline + interval`, compute:

```python
skipped_slot_count = int((now - next_deadline) // interval)
next_deadline += skipped_slot_count * interval
```

Emit one gap pair with `skipped_slot_count`, then one current sample set; never
write one sample set per skipped deadline. Stop a bounded group when
`now - aircraft_ready_monotonic >= duration_seconds`. When every group is
bounded and finished, complete with `termination="groups_complete"`. Determine
status and value using the exact rules in the design. Each scheduler wait is
the non-negative minimum of the next sample deadline, group-end deadlines,
capture limit, reconnect/disconnect deadlines, stop-file/liveness poll quantum,
and any active operation deadline.

- [ ] **Step 5: Implement single-owner cleanup**

Use one `try`/`except`/`finally` boundary. In `finally`, move to `finalizing`
from every nonterminal state, including a pre-readiness requested stop. Close
the transport using per-stage transport shutdown budgets, then use a two-phase
event/status commit: prepare and commit the terminal JSONL row, hash the
complete bytes, prepare terminal status, and atomically publish it. Measure
cleanup against `shutdown_timeout_seconds`. Preserve the original failure
reason and append cleanup diagnostics; never replace a failure with success.
Pass the absolute shutdown deadline into every cleanup operation and clamp each
blocking call to the remaining time; do not grant a fresh timeout per call. A
committed terminal event with failed status publication is a
complete-but-unclean exit 3 and may leave `finalizing` status residue.
A complete terminal-row write is logical closure, not durable commitment: the
writer becomes immutable immediately, but exposes no committed hash or size
until flush and fsync succeed. Flush/fsync failure leaves raw unproven evidence,
failed/unclean outcome, and `finalizing` status; close failure after successful
fsync is post-commit. Retry and abandon must never append or alter the row.

- [ ] **Step 6: Run and confirm GREEN**

Run the Step 2 command. Expected: all lifecycle, timing, reconnect, terminal,
and cleanup tests pass.

- [ ] **Step 7: Commit**

```powershell
git add xpwebapi/capture_runner.py tests/test_capture_runner.py
git commit -m "feat: run bounded capture lifecycle"
```

### Task 6: CLI, Signals, Exit Codes, and Package Entry Point

**Files:**
- Create: `xpwebapi/capture_cli.py`
- Create: `tests/test_capture_cli.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- `build_parser() -> argparse.ArgumentParser`.
- `validate_cli_mode(namespace: argparse.Namespace) -> None`.
- `emit_version_json(document: VersionJsonDocument, stream: TextIO) -> None`.
- `install_signal_handlers(stop_event, interrupted_event,
  interruption: CaptureInterruption | None = None) -> None`.
- `preflight_paths(events: Path, status: Path, stop_file: Path | None) -> None`.
- `run_capture(request_path, events_path, status_path, cli_stop_file,
  stop_event, interrupted_event,
  interruption: CaptureInterruption | None = None) -> CaptureOutcome`.
- `main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Write failing CLI tests**

Test `--help`; exact compact sorted `--version-json` stdout with one trailing
newline, no stderr, no network access, and no files created; Git-unavailable
version output with null Git fields; rejection when `--version-json` is mixed
with any capture argument; missing capture arguments; valid completion `0`;
invalid JSON/path `2`; runtime failure `3`;
SIGINT/SIGTERM outcome `130`; existing events; existing status; pre-existing
stop file; matching and conflicting request/CLI stop files; no outputs after
preflight failure; stderr diagnostics; and partial output preservation after
runtime failure. Add path-safety tests for identical paths, relative/absolute
aliases, symlink aliases, case-folded aliases on case-insensitive filesystems,
and an output-created-between-preflight-and-open race. The race must fail
without truncating the competing file.

```python
def test_cli_refuses_existing_status_without_creating_events(self):
    status_path.write_text("existing\n", encoding="utf-8")
    result = main(
        [
            "--request",
            str(request_path),
            "--events",
            str(events_path),
            "--status",
            str(status_path),
        ]
    )

    self.assertEqual(2, result)
    self.assertFalse(events_path.exists())
```

- [ ] **Step 2: Run and confirm RED**

Run:

```powershell
uv run python -m unittest tests.test_capture_cli -v
```

Expected: import failure.

- [ ] **Step 3: Implement preflight and signal semantics**

Parse capture options as optional at argparse level, then enforce exactly one
of two modes: `--version-json` alone, or all required capture arguments.
Handle `--version-json` before request loading, writer construction, transport
creation, or any filesystem mutation. Emit the exact protocol-v1
`VersionJsonDocument` as compact, key-sorted JSON followed by one newline;
unavailable Git metadata remains JSON null.

For capture mode, load and validate the request, resolve the stop-file rule,
and resolve all paths before creating evidence. Reject events/status aliases
and aliases with the request or stop file, including symlink and platform case
aliases. Reject any existing output or stop file. Resolve source provenance
before creating either output, then create events and status with exclusive
creation so a race cannot overwrite data. Signal
handlers set both `interrupted_event` and `stop_event`.
Programmatic callers set only `stop_event`. Catch request/path errors before
writer construction and return 2. Convert `CaptureOutcome.exit_code` directly;
unexpected runtime exceptions return 3 after runner-owned finalization.
Pass the loaded `request_sha256`, resolved `SourceProvenance`, and shared
`CaptureInterruption` into `CaptureRunner`. Output reservations use no
cross-path rollback: if the status reservation loses a race after events is
created, close the owned descriptor, preserve the zero-byte events residue,
emit `output_reservation_partial`, and return 2. Failures after both paths are
reserved preserve both paths and return 3 with the same diagnostic family.

#### Implemented interface clarifications

The final implementation makes these plan corrections normative:

- `CaptureRunner` receives `request_sha256`, `SourceProvenance`, and
  `CaptureInterruption` explicitly;
- every nonterminal state can enter `finalizing` for a pre-readiness requested
  stop;
- terminal evidence uses a two-phase event/status commit, and a
  complete-but-unclean outcome returns exit 3 with possible `finalizing`
  status residue;
- terminal-row write makes JSONL immutable, while successful flush and fsync
  are required before its committed identity is published;
- adapters use per-stage transport shutdown budgets inside the runner's one
  absolute cleanup deadline;
- multi-output reservation uses no cross-path rollback because portable
  check-then-unlink cannot safely exclude a competitor replacement.

Add:

```toml
[project.scripts]
xpwebapi-capture = "xpwebapi.capture_cli:main"
```

Run `uv lock` after editing `pyproject.toml`; keep `pyproject.toml` and
`uv.lock` in this task and commit.

- [ ] **Step 4: Run and confirm GREEN**

Run:

```powershell
uv run python -m unittest tests.test_capture_cli -v
uv run xpwebapi-capture --help
uv run xpwebapi-capture --version-json
uv lock --check
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit**

```powershell
git add xpwebapi/capture_cli.py tests/test_capture_cli.py pyproject.toml uv.lock
git commit -m "feat: add read-only capture worker CLI"
```

### Task 7: Documentation and Complete Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/usage/index.md`
- Modify: `docs/reference/index.md`
- Modify: `mkdocs.yml`
- Modify: `CHANGELOG.md`
- Modify: `docs/superpowers/specs/2026-07-19-q4xpcc-read-only-capture-worker-design.md`
- Modify: `docs/superpowers/plans/2026-07-19-q4xpcc-read-only-capture-worker.md`
- Modify: `tests/test_capture_cli.py`
- Create: `docs/usage/read-only-capture.md`
- Create: `docs/reference/capture.md`
- Test: `tests/test_documentation.py`

**Interfaces:**
- Documents the version-1 request, events, status, CLI, safety boundary, and
  q4xpcc ownership boundary.

- [ ] **Step 1: Add failing documentation contract tests**

Assert that:

- the usage page contains `xpwebapi-capture` and all four options;
- the usage page documents `--version-json` and its mutual exclusion from
  capture arguments;
- the reference page contains `::: xpwebapi.capture_protocol`,
  `::: xpwebapi.capture_events`, and `::: xpwebapi.capture_transport`;
- `mkdocs.yml` publishes both new pages;
- `docs/reference/index.md` links the capture protocol reference;
- README identifies WebSocket as primary and UDP as diagnostic/fallback;
- changelog contains an `Unreleased` read-only capture entry.

- [ ] **Step 2: Run and confirm RED**

Run:

```powershell
uv run python -m unittest tests.test_documentation -v
```

Expected: missing page, navigation, and content failures.

- [ ] **Step 3: Write operational and reference documentation**

Document a complete request, exact event/status fields, and the two-stage
readiness order: poll `transport_ready_at_utc`, load Q4XP, then poll
`aircraft_ready_at_utc`/`capturing`. Document `--version-json` as the exact
machine-readable provenance handshake and state that it makes no network calls
and performs no filesystem mutation, while it may read local package, Git, and
filesystem provenance. Also document
stop-file behavior, exit codes, provenance, permitted subscription and `RREF`
traffic, prohibited actions, stationary ground-readiness command, and the fact
that q4xpcc remains the plugin and evidence owner. Use an `Unreleased`
changelog section; do not imply a package release or version bump.

- [ ] **Step 4: Run focused and complete verification**

Run:

```powershell
uv run python -m unittest tests.test_api tests.test_rest tests.test_async_rest tests.test_ws tests.test_udp tests.test_type_annotations tests.test_capture_protocol tests.test_capture_events tests.test_capture_output tests.test_capture_transport tests.test_capture_runner tests.test_capture_cli tests.test_documentation -v
uv run xpwebapi-capture --help
uv run xpwebapi-capture --version-json
uv lock --check
uv build
uv run python .codex/skills/hygiene/scripts/hygiene.py
git diff --check
git status --short --branch
```

Expected: every command exits 0; no pytest invocation; hygiene reports its full
test count; the worktree contains only intentional source, tests, metadata,
lock, and documentation changes.

- [ ] **Step 5: Perform opt-in stationary live readiness**

With X-Plane 12 running before Q4XP is loaded, run:

```powershell
uv run xpwebapi-capture --request artifacts\stationary\request.json --events artifacts\stationary\capture.jsonl --status artifacts\stationary\capture-status.json --stop-file artifacts\stationary\capture.stop
```

Poll status until `transport_ready_at_utc` is non-null, load Q4XP, then poll
until `aircraft_ready_at_utc` is non-null and state reaches `capturing`. Create
the stop file, verify exit 0 and
status `complete`, inspect captured provenance, and use traffic/socket evidence
to confirm only WebSocket subscribe/unsubscribe messages or UDP `RREF` packets
left the worker. Record this as opt-in evidence; do not commit raw live capture
unless the q4xpcc evidence-promotion workflow explicitly selects it.

- [ ] **Step 6: Commit**

```powershell
git add README.md CHANGELOG.md docs/usage/index.md docs/usage/read-only-capture.md docs/reference/index.md docs/reference/capture.md docs/superpowers/specs/2026-07-19-q4xpcc-read-only-capture-worker-design.md docs/superpowers/plans/2026-07-19-q4xpcc-read-only-capture-worker.md mkdocs.yml tests/test_documentation.py tests/test_capture_cli.py
git commit -m "docs: document read-only capture worker"
```
