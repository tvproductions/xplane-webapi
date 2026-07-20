# Q4XPCC Read-Only Capture Worker Design

## Status

Approved cross-project design derived from:

`C:/Users/Jeff/source/repos/xp/q4xpcc/.worktrees/phase-24a-shakedown-setup/docs/superpowers/specs/2026-07-19-phase-24a-shakedown-regimen-capture-setup-design.md`

The user selected this fork as the disciplined owner of X-Plane network calls
used while developing and validating q4xpcc. The q4xpcc plugin remains the
product and system under test.

## Goal

Provide a production-quality, strictly read-only external capture worker that
accepts one versioned request, observes only configured X-Plane DataRefs through
the WebSocket or UDP APIs, and emits durable JSONL plus atomic status evidence
for q4xpcc to normalize and bundle.

## Ownership Boundary

`xplane-webapi` owns:

- Web API, WebSocket, beacon, and UDP network behavior;
- connection, subscription, bounded retry, and resubscription logic;
- transport-level sample timestamps, gaps, and diagnostics;
- structural enforcement that capture cannot write or execute commands;
- worker request parsing, raw JSONL evidence, status, and provenance.

q4xpcc owns:

- watchlists, campaigns, routes, and sortie identity;
- translation of a q4xpcc watchlist into the worker request defined here;
- worker process orchestration;
- normalized q4xpcc recorder events and reports;
- replay, runtime correlation, evidence integrity, and final bundles.

The repositories communicate only through process, JSON, JSONL, and file
boundaries. q4xpcc never imports `xpwebapi`. The worker does not parse q4xpcc
campaigns or emit q4xpcc-normalized recorder events.

## Read-Only Enforcement

Read-only capture is a library capability, not a caller convention. Existing
clients remain write-capable by default. Each client accepts
`read_only: bool = False`; the default preserves the existing public behavior.

When `read_only=True`:

- `API.dataref(path, auto_save=True)` raises `XPReadOnlyViolation`;
- `API.command(path)` raises `XPReadOnlyViolation`;
- REST and async REST writes and command execution raise before HTTP I/O;
- WebSocket write helpers and command helpers raise before WebSocket I/O;
- WebSocket `send()` accepts only `dataref_subscribe_values` and
  `dataref_unsubscribe_values` payload types;
- UDP high-level write and command helpers raise before UDP I/O;
- UDP sends accept only a 413-byte `RREF\0` subscription or unsubscribe packet;
- all violations raise `XPReadOnlyViolation` before data reaches a raw handle.

The existing public raw handles are also guarded in read-only mode. Merely
guarding high-level methods is insufficient because current clients expose
`session`, `ws`, and `socket`:

- `_ReadOnlyHttpClientProxy` exposes `get()` and `close()` only;
- `_ReadOnlyAsyncHttpClientProxy` exposes async `get()` and `aclose()` only;
- `_ReadOnlyWebsocketProxy` exposes `recv()`, `close()`, and a validating
  `send()` that applies the same two-message allow-list;
- `_ReadOnlyDatagramSocketProxy` exposes `recvfrom()`, `settimeout()`,
  `close()`, and a validating `sendto()` that accepts only valid `RREF` packets.

Forbidden or unknown proxy attributes raise `XPReadOnlyViolation`. Normal
clients retain their real handles and behavior. These proxies protect the
supported Python API surface; they are not a security sandbox against hostile
reflection into private implementation attributes.

The capture transport adapters expose only `open`, `subscribe`, `connected`,
and `close`. They do not return the underlying general-purpose API or raw
handle. The request schema has no access-mode field, arbitrary method name,
command path, write value, or packet payload. The worker factory always creates
clients with `read_only=True` and DataRefs with `auto_save=False`.

## Version 1 Request Contract

The request is strict JSON. Every model forbids unknown fields and is frozen.
The top-level shape is:

```json
{
  "protocol_version": 1,
  "capture_session_id": "capture-20260719-001",
  "sortie_id": "sortie-20260719-001",
  "correlation": {
    "campaign_id": "q4xp_shakedown",
    "route_profile_id": "kaus-kgls",
    "scenario_id": "kaus_kgls_live"
  },
  "identity_readiness": {
    "kind": "dataref_match",
    "target_aircraft": "FlyJSim Q4XP",
    "refs": [
      {
        "id": "q4xp_relative_path",
        "path": "sim/aircraft/view/acf_relative_path",
        "declared_type": "string",
        "encoding": "utf-8",
        "rate_hz": 1.0,
        "operator": "contains",
        "expected_value": "Q4XP"
      }
    ]
  },
  "transport": {
    "kind": "websocket",
    "host": "127.0.0.1",
    "port": 8086,
    "api_path": "/api",
    "api_version": "v2",
    "http_timeout_seconds": 5.0,
    "open_timeout_seconds": 5.0,
    "close_timeout_seconds": 5.0
  },
  "sample_groups": [
    {
      "id": "baseline_state",
      "rate_hz": 1.0,
      "duration_seconds": null
    }
  ],
  "refs": [
    {
      "id": "sim_groundspeed",
      "path": "sim/flightmodel/position/groundspeed",
      "declared_type": "float",
      "availability": "required",
      "sample_group_id": "baseline_state",
      "encoding": null
    }
  ],
  "retry": {
    "initial_attempts": 3,
    "reconnect_attempts": 3,
    "backoff_seconds": 0.5,
    "backoff_max_seconds": 5.0,
    "subscription_timeout_seconds": 10.0,
    "aircraft_identity_timeout_seconds": 300.0,
    "first_values_timeout_seconds": 30.0,
    "max_disconnect_seconds": 30.0,
    "stale_after_seconds": 3.0,
    "poll_interval_seconds": 0.25,
    "shutdown_timeout_seconds": 10.0
  },
  "capture_limit_seconds": null,
  "stop_file": null
}
```

`transport` is discriminated by `kind`. `identity_readiness` is independently
discriminated by `kind`; protocol v1 has exactly the `dataref_match` variant
shown above. A UDP transport request uses:

```json
{
  "kind": "udp",
  "beacon_timeout_seconds": 5.0,
  "socket_timeout_seconds": 1.0,
  "liveness_timeout_seconds": 3.0
}
```

UDP endpoint identity comes from bounded beacon discovery. The first version
does not claim reliable direct-host UDP readiness because the existing
`XPUDPAPI.connected` path without a beacon performs its own multicast probe.

Validation rules are:

- protocol version is exactly `1`;
- all identifiers and paths are non-empty and already trimmed;
- sample-group ids, identity-ref ids, capture-ref ids, and all ref paths are
  unique across their respective and combined namespaces;
- each ref names an existing sample group;
- `rate_hz`, timeouts, backoffs, and provided durations are finite;
- rates and timeouts are positive; backoffs are non-negative;
- attempt counts are integers from 1 through 100;
- `backoff_seconds` does not exceed `backoff_max_seconds`;
- `duration_seconds` and `capture_limit_seconds`, when provided, are positive;
- declared types are `int`, `float`, `double`, or `string`;
- string refs provide an encoding; numeric refs do not;
- `identity_readiness.target_aircraft` is exactly `FlyJSim Q4XP` for this
  worker contract and contains at least one identity ref;
- identity operators are `equals` for every type or `contains` for strings;
- identity expected values exactly match the declared type, are finite when
  numeric, and string codecs must resolve through `codecs.lookup()`;
- UDP accepts only `float` refs and mathematically integral rates from 1
  through 100 Hz for identity and capture refs;
- ports are integers from 1 through 65535; booleans are never numbers;
- stringified numbers, fractional integer fields, unknown codecs, malformed or
  negative array indexes, and duplicate JSON object keys are rejected;
- models use Pydantic `strict=True`; no string, boolean, integer, float, path,
  enum, or collection coercion is accepted;
- action-capable or unknown fields are rejected by `extra="forbid"`.

The following declarations are the canonical protocol-v1 request schema. They
are normative: implementation and documentation must use these field names,
types, defaults, literals, nullability, and discriminators rather than infer a
similar shape. `StrictModel` means frozen, `extra="forbid"`, and `strict=True`.
Tuple fields serialize as JSON arrays.

```python
class CaptureCorrelation(StrictModel):
    campaign_id: str
    route_profile_id: str
    scenario_id: str

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
    DatarefMatchIdentityReadiness, Field(discriminator="kind")
]
CaptureTransportConfig = Annotated[
    WebsocketCaptureConfig | UdpCaptureConfig, Field(discriminator="kind")
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
```

`load_capture_request()` reads request bytes exactly once. The same byte string
is decoded with a duplicate-key-rejecting `object_pairs_hook`, validated, and
hashed. Parsing and provenance therefore cannot disagree about request bytes.

The optional request `stop_file` and CLI `--stop-file` may both be absent or
may resolve to the same path. If both are present and differ, preflight fails.
If the resolved stop file already exists before capture starts, preflight
fails. A relative request value resolves against the request file's parent; a
relative CLI value resolves against the process working directory. Request,
events, status, and stop paths are fully resolved and case-normalized; aliases
are rejected even when expressed through `..`, symlinks, junctions, or Windows
case variants. The worker never deletes the stop file. Events and the initial
status reservation use exclusive creation so a race cannot overwrite evidence.
Reservations are acquired in deterministic events-then-status order. There is
no cross-path rollback because portable path checks cannot prove that a path
still names the file this invocation created at unlink time. If status
reservation fails, preflight closes its events descriptor, preserves the
zero-byte events reservation, emits `output_reservation_partial`, and exits 2.
After writer ownership begins, both paths are preserved on failure with the
same diagnostic family and exit 3.

## Version 1 Event Contract

Every JSONL row contains these common fields:

- `protocol_version`: integer `1`;
- `event`: one allowed event-kind string;
- `sequence`: integer starting at `1` and increasing by one;
- `capture_session_id` and `sortie_id`;
- `timestamp_utc`: RFC 3339 UTC with a trailing `Z`;
- `elapsed_seconds`: finite monotonic seconds since evidence was opened.

Event-specific fields are:

- `capture_started`: `request_sha256`, `correlation`, complete `transport`, and
  `provenance`. Provenance contains `package_name`, `package_version`,
  `python_version`, `git_state`, `git_root`, `git_revision`, `git_origin`,
  `git_dirty`, and `read_only`;
- `transport_state`: `state` (`connected` or `disconnected`), `attempt`,
  nullable `reason`, and capabilities containing `transport`, `endpoint`,
  nullable `xplane_version`, and `value_types`;
- `transport_ready`: `connection_generation`, `endpoint`, `read_only` equal to
  true, `package_version`, nullable `git_revision`, nullable `git_dirty`, and
  transport capabilities;
- `subscription_result`: `accepted_ref_ids`, `rejected` mapping ref id to
  reason, nullable WebSocket `request_id`, and `purpose` equal to
  `aircraft_identity` or `capture`;
- `aircraft_ready`: `connection_generation`, `target_aircraft`,
  `identity_observations`, `required_ref_ids`, `optional_missing_ref_ids`, and
  `ready_elapsed_seconds`. Each identity observation contains `ref_id`, `path`,
  `operator`, `expected_value`, and `observed_value`;
- `sample`: `sample_group_id`, `ref_id`, `path`, `declared_type`, `status`,
  `value`, `source_observed_elapsed_seconds`, and `source_age_seconds`;
- `gap_started`: `reason`, `affected_ref_ids`, and `gap_start_elapsed_seconds`;
- `gap_ended`: `reason`, `affected_ref_ids`, `gap_start_elapsed_seconds`, and
  `gap_duration_seconds`, and `skipped_slot_count`;
- `retry`: `phase` (`initial_connect` or `reconnect`), `attempt`,
  `maximum_attempts`, `delay_seconds`, and `reason`;
- `capture_stopped`: `termination` (`stop_file`, `capture_limit`, or
  `requested`, or `groups_complete`), `sample_count`, `gap_count`,
  `retry_count`, and
  `preceding_sha256`;
- `capture_failed`: `reason`, `sample_count`, `gap_count`, `retry_count`, and
  `preceding_sha256`;
- `capture_interrupted`: `signal`, `sample_count`, `gap_count`, `retry_count`,
  and `preceding_sha256`.

Sample status is one of `sampled`, `missing`, `stale`, `disconnected`,
`unsupported`, or `invalid`. `value` is JSON null unless status is `sampled`.
Bytes from WebSocket data refs declared as `string` are decoded with the
requested encoding and serialized as JSON text; decode failure is `invalid`.
JSON serialization uses `allow_nan=False`.

Value normalization is exact: `int` accepts an `int` but not `bool`; `float`
and `double` accept finite `int` or `float` values but not `bool` and serialize
as float; `string` accepts `str` or decodes `bytes` with the configured
encoding. Every other value/type combination is `invalid` with null value.

These are the canonical nested and event payload declarations. Every event
model also has exactly the `EventEnvelope` fields; `event` is the discriminator.

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
```

`CaptureEvent` is the discriminated union of those twelve concrete event
models. Sequence, attempt, generation, count, and skipped-slot fields are strict
integers; sequence and generation are positive, other counters are
non-negative, and attempts are within their declared maximum. Elapsed/age/
delay fields are finite and non-negative. For a `sampled` sample, `value`,
`source_observed_elapsed_seconds`, and `source_age_seconds` are non-null and the
value matches `declared_type`; for every other status, `value` is null. Before a
first observation the two source-time fields are null; otherwise both are
non-null. For available Git, root/revision/dirty are non-null; for unavailable
Git all four Git detail fields are null. `git_origin` alone may be null for an
available checkout with no configured origin.

The terminal row's `preceding_sha256` covers the exact bytes of all prior
JSONL rows and therefore avoids a self-hash. Terminal status separately records
the SHA-256 and size of the complete JSONL file after final flush and fsync.

## Atomic Status Contract

The status document is the mutable polling surface; JSONL remains append-only
and is never rewritten or truncated. The status document contains:

- `protocol_version`, `capture_session_id`, and `sortie_id`;
- `state`;
- `updated_at_utc` and `elapsed_seconds`;
- `events_path` and `request_sha256`;
- transport kind and current connection state;
- `connection_generation`, `transport_ready_at_utc`, and
  `aircraft_ready_at_utc`; readiness timestamps are persistent latches and do
  not become null when the current state advances;
- `target_aircraft`, identity-ref count, matched-identity-ref count, required
  capture-ref count, and observed-required-ref count;
- sample, gap, retry, accepted-ref, and rejected-ref counts;
- `attempt_phase` (`none`, `initial_connect`, or `reconnect`),
  `current_attempt`, and `maximum_attempts`;
- `reason` when state is terminal or degraded;
- complete-file SHA-256, size, exit code, and `clean_shutdown` when terminal.

The canonical status and version-output declarations are:

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

Every status count, generation, attempt, event-size, and nested counter field is
a strict non-negative integer; `connection_generation` is zero until the first
base endpoint opens and positive thereafter. `current_attempt` and
`maximum_attempts` are zero exactly when `attempt_phase="none"`, otherwise both
are positive and current does not exceed maximum. `reason` is null in healthy
nonterminal states and non-null while degraded/reconnecting. Terminal-only
fields are absent, not null, from `NonterminalStatus`.

`transport_ready_at_utc` is null before the first `transport_ready` state and
non-null thereafter. `aircraft_ready_at_utc` is null until the first
`aircraft_ready` state and non-null thereafter. A failure or interruption may
therefore carry either latch as null if that gate was never reached. Identity
and required-observation counts never exceed their corresponding totals. The
version document applies the same Git availability condition as provenance and
its transport tuple is exactly `["udp", "websocket"]` in that order.

Status writes use a same-directory uniquely named temporary file, flush,
fsync, and `os.replace`. The writer enforces these legal transitions:

```text
starting -> connecting | finalizing | failed | interrupted
connecting -> connecting | transport_ready | finalizing | failed | interrupted
transport_ready -> awaiting_aircraft | finalizing | failed | interrupted
awaiting_aircraft -> subscribing | reconnecting | finalizing | failed | interrupted
subscribing -> awaiting_first_values | reconnecting | finalizing | failed | interrupted
awaiting_first_values -> aircraft_ready | reconnecting | finalizing | failed | interrupted
aircraft_ready -> capturing | finalizing | failed | interrupted
capturing -> reconnecting | finalizing | failed | interrupted
reconnecting -> reconnecting | transport_ready | finalizing | failed | interrupted
finalizing -> complete | failed | interrupted
complete -> terminal
failed -> terminal
interrupted -> terminal
```

The first status must be `starting`. Repeated `connecting` and `reconnecting`
writes are legal only when `current_attempt` strictly increases and remains at
or below `maximum_attempts`. `terminal` means no subsequent status write is
accepted. A poller that misses the brief `transport_ready` or `aircraft_ready`
state still observes the corresponding persistent timestamp latch.

## Transport Lifecycle

Every adapter method accepts one absolute monotonic deadline. Immediately
before each blocking HTTP, WebSocket, beacon, socket, feedback, join, close, or
sleep call it computes `remaining = deadline - monotonic_now`; non-positive
remaining time fails without making the call, and positive time is clamped
into that operation. A multi-call method never reuses the original duration.

### WebSocket

The adapter does not call the existing unbounded `connect()` plus
`wait_connection()` pair. One `open(deadline)` attempt constructs
`XPWebsocketAPI` with
`read_only=True`, finite HTTP and WebSocket open timeouts, and one internal
attempt. The actual `XPWebsocketAPI` constructor receives both `open_timeout`
and `close_timeout`, and `connect_websocket()` passes both remaining-deadline-
clamped values to `websockets.sync.client.connect`; calls
`connect_websocket()`; registers dataref, request-feedback,
and close callbacks; starts the listener with `start(release=True)`; submits
one `monitor_datarefs()` batch; and waits only until the supplied deadline for
successful request feedback.

Request feedback is buffered in a dictionary keyed by request id before the
adapter calls `monitor_datarefs()`. The callback always stores feedback and
sets a condition. After `monitor_datarefs()` returns its request id, the adapter
checks the buffer before waiting. This handles a response that arrives before
the sending method returns without accepting feedback for another request.

When `subscribe()` is called, the adapter creates and resolves metadata only for
the refs in that call. It must not create, query, or validate any capture-ref
DataRef before every identity ref has matched. Type
compatibility is: declared `int` accepts X-Plane `int`, or `int_array` for an
indexed path; declared `float` accepts `float`, `double`, or `float_array` for
an indexed path; declared `double` accepts `double` or `float`; and declared
`string` accepts X-Plane `data`. Missing metadata, an unindexed array declared
as scalar, and incompatible types reject that ref before the batch request.

After the endpoint is open and source provenance confirms `read_only: true`,
the worker emits `transport_ready` and atomically latches
`transport_ready_at_utc`. This milestone occurs before identity or capture refs
are required, so q4xpcc may poll status and then direct the pilot to load Q4XP.

The adapter next subscribes only the declared identity refs and waits for every
allow-listed identity comparison to match with source age no greater than
`stale_after_seconds`. It then creates, resolves, and subscribes the configured
capture refs and waits for a first observation from every required accepted
ref. Only then does it emit `aircraft_ready`, latch `aircraft_ready_at_utc`, and
begin capture sampling.

A disconnect closes that client. The runner creates a new adapter and client,
opens it, emits a new generation's `transport_ready`, revalidates aircraft
identity, and resubscribes the complete configured set. It emits
`aircraft_ready` for the new generation before returning to capture. It never
relies on the existing connection monitor to restore subscriptions. After a
match, every identity ref remains under a freshness deadline of
`last_matching_observation + stale_after_seconds`. A mismatching observation or
expiration of any such deadline fails with `aircraft_identity_lost`; silence
cannot preserve identity indefinitely.

### UDP

Each `open(deadline)` attempt constructs and retains one `XPBeaconMonitor`, then
calls `monitor.get_beacon()` with the configured finite timeout and worker-owned
attempt count. The returned `BeaconData` is retained separately as `data`, and
the client construction is exactly
`XPUDPAPI(beacon=monitor, host=data.host, port=data.port, read_only=True)`.
Passing `BeaconData` itself as `beacon`, discarding the monitor, or omitting the
discovered host/port is incorrect. The adapter registers its observation callback,
calls `monitor_dataref(dataref, frequency_hz=int(group.rate_hz))` for each ref,
and starts the listener. A successful `RREF` request is accepted; actual first
values are still required for aircraft readiness. Frequency-zero `RREF`
messages during close are permitted read-control traffic.

A successful beacon establishes the base endpoint and permits
`transport_ready`; it does not establish DataRef liveness. After the identity
subscription is sent, UDP liveness state is
`awaiting_first_identity_packet`, not `disconnected`, until either a valid
configured identity-index packet arrives or the aircraft-identity deadline
expires. The runner must not start reconnect merely because no first identity
packet has arrived during this bounded loading window.

A one-shot beacon never establishes continuing UDP liveness. The UDP adapter
records `last_valid_rref_monotonic` only after `read_monitored_dataref_values()`
has decoded a valid `RREF,` response containing at least one configured index.
Before the first valid identity response its distinct state is
`awaiting_first_identity_packet`. Afterwards `connected` is true
only while `monotonic_now - last_valid_rref_monotonic <=
liveness_timeout_seconds`. Socket receive timeouts are diagnostics, wake the
runner, and cause bounded reconnect once liveness expires.

The guarded UDP proxy unpacks every outgoing 413-byte packet with
`struct.unpack("<5sii400s", message)`. It requires header `RREF\0`, frequency
from 0 through 100, non-negative index, a non-empty NUL-terminated ASCII path,
all-zero padding after the first NUL, and destination exactly equal to the
configured `(host, port)`. Any mismatch raises before `sendto()`.

### Subscription Result

`subscribe()` returns `SubscriptionResult` with an accepted ref-id tuple,
rejected reason mapping, and optional WebSocket request id. A required rejected
ref fails preflight. An optional rejected ref is reported and does not prevent
readiness.

## Capture Timing

Evidence opens and the monotonic origin is recorded before the first network
attempt. Sampling schedules begin when `aircraft_ready` is emitted. Each group
sets its first deadline to the aircraft-ready monotonic instant and its
interval to `1 / rate_hz`.

At a deadline the runner writes one sample per active ref from the latest
callback observation. It never performs synchronous per-sample network I/O.
After writing, the next deadline advances by one interval. If the loop is late
by one or more whole intervals, it emits one gap pair describing the skipped
slot count, advances past every missed deadline, and does not burst-catch up.

A value is `stale` when its source age exceeds `stale_after_seconds`. It is
`disconnected` while the transport is disconnected and `missing` before a
first value. A reconnect clears old latest observations so readiness after
reconnect requires fresh values. Bounded sample-group duration is measured
from aircraft readiness. `capture_limit_seconds`, when present, is measured
from aircraft readiness and requests clean finalization. When every sample
group has a finite duration and the last group expires, the worker finalizes
cleanly with `termination="groups_complete"`; it never waits indefinitely with
no active group.

The scheduler's next wait is the non-negative minimum of the next sample
deadline, each group-completion deadline, the capture-limit deadline, the
active reconnect/disconnect deadline, and `poll_interval_seconds`. The polling
quantum checks stop/interruption files and UDP liveness even when no sample is
due. Every wait is also clamped to the remaining owning deadline.

Initial connection uses `initial_attempts`. Reconnection uses
`reconnect_attempts` and may not continue beyond `max_disconnect_seconds`.
Backoff is `min(backoff_seconds * 2 ** failure_index,
backoff_max_seconds)`. Every failed attempt emits `retry`. Exhaustion produces
`capture_failed` and status `failed`.

Aircraft identity matching uses the separate
`aircraft_identity_timeout_seconds`. Required capture first observations use
`first_values_timeout_seconds`; neither timeout starts before
`transport_ready`. Status exposes the active attempt phase and attempt counts
during initial connection and reconnection. A fresh matching identity
observation resets that ref's freshness deadline. Identity mismatch or
staleness after initial readiness is terminal `aircraft_identity_lost`, while
failure to receive the first matching identity before its deadline is
`aircraft_identity_timeout`.

## Finalization

A stop file requests a clean `stop_file` completion. Reaching the capture limit
requests a clean `capture_limit` completion. A programmatic stop event requests
clean `requested` completion. SIGINT or SIGTERM records
`capture_interrupted`, status `interrupted`, and exit code 130.

`CaptureRunner` receives the exact `request_sha256` and resolved
`SourceProvenance` explicitly. It also receives a shared `CaptureInterruption`
that retains the first SIGINT/SIGTERM identity. A pre-readiness requested stop
is legal from every nonterminal state: the runner enters `finalizing` and may
complete without inventing transport or aircraft readiness latches.

All paths enter one `finally`-owned cleanup sequence: unsubscribe, stop the
listener, disconnect or close the client, flush and fsync JSONL, compute the
complete-file hash and size, and atomically write terminal status. Cleanup is
bounded by `shutdown_timeout_seconds`; a cleanup timeout changes an otherwise
clean result to failure. Partial JSONL remains in place after failure or
interruption.

The transport divides its remaining absolute deadline into
per-stage transport shutdown budgets for unsubscribe, listener stop, channel close, and owner
close. Terminal publication uses a two-phase event/status commit: prepare and
durably commit the terminal JSONL row first, then atomically replace terminal
status using the committed file hash and size. If the JSONL commit point is
reached but status replacement fails, JSONL is authoritative, the status may
remain `finalizing`, and the complete-but-unclean outcome exits 3. A successful
atomic status replacement is authoritative even if its post-operation deadline
diagnostic observes that the deadline was crossed.

## Provenance

`resolve_source_provenance()` starts from `Path(__file__).resolve()` rather
than the request path. It records package name/version and Python version, then
uses bounded `git -C <module-root>` commands to discover the worktree root,
HEAD, `remote.origin.url`, and porcelain dirty state. This works with a normal
checkout or a Git worktree whose `.git` is a file. Git-unavailable and
not-a-checkout conditions are explicit provenance states, not invented clean
values. q4xpcc decides whether unavailable or dirty provenance invalidates a
campaign artifact.

The CLI resolves provenance after path/request preflight but before creating
events or status. Evidence files inside the source checkout therefore cannot
make a previously clean source appear dirty in its own `capture_started` row.

## CLI

The installed entry point has a provenance-only mode:

```text
xpwebapi-capture --version-json
```

It performs no network call and no filesystem mutation. It may read installed
package metadata and Git/filesystem provenance. On success it writes
one compact, key-sorted JSON object plus LF to stdout, writes nothing to
stderr, and exits 0:

```json
{"git_dirty":false,"git_origin":"https://github.com/tvproductions/xplane-webapi.git","git_revision":"0000000000000000000000000000000000000000","git_root":"C:/src/xplane-webapi","git_state":"available","package_name":"xpwebapi","package_version":"3.5.0","python_version":"3.12.0","read_only":true,"supported_transports":["udp","websocket"],"worker":"xpwebapi-capture","worker_protocol_version":1}
```

When Git is unavailable, `git_state` is `unavailable` and `git_root`,
`git_revision`, `git_origin`, and `git_dirty` are JSON null. Package and Python
fields remain present. This object is validated by the committed version-JSON
schema before output.

`--version-json` is mutually exclusive with `--request`, `--events`,
`--status`, and `--stop-file`. Combining modes or omitting any of the three
required capture arguments is an argparse/preflight error on stderr with exit
2 and no filesystem mutation.

Capture mode is:

```text
xpwebapi-capture --request REQUEST --events EVENTS --status STATUS
                 [--stop-file STOP_FILE]
```

Preflight validates the request and stop-file resolution and refuses to start
if either events or status already exists. It creates neither output when
ordinary preflight fails before reservation. It rejects resolved path aliases,
then reserves events and status with exclusive creation and applies the
no-cross-path-rollback rule above to a second-reservation race.
Argparse help may use stdout; run diagnostics
use stderr. Capture events exist only in immutable JSONL; readiness and current
progress are exposed through the atomically replaced status JSON.

Exit codes are:

- `0`: clean stop-file, capture-limit, or programmatic completion;
- `2`: invalid arguments, request, paths, or preflight;
- `3`: connection, subscription, capture, output, or cleanup failure;
- `130`: SIGINT or SIGTERM interruption after best-effort bounded cleanup.

## Backward Compatibility

- `read_only=False` remains the default everywhere.
- Existing constructors remain source compatible because new parameters are
  keyword parameters with defaults.
- Existing write, command, monitoring, context-manager, and callback behavior
  is unchanged for normal clients.
- `XPUDPAPI.monitor_dataref(dataref)` retains its one-hertz default.
- Read-only proxies are installed only for read-only clients.
- New `API.read_only` protocol annotation is reflected in the repository's
  annotation-contract test.

## Checked Contract Schemas

Pydantic models are literal and strict for the request, correlation, identity,
transport variants, refs, sample groups, retry policy, capabilities,
provenance, every event variant, version JSON, status, counters, and terminal
status conditions. Generated schemas are committed as:

- `schemas/capture-request-v1.schema.json`;
- `schemas/capture-event-v1.schema.json`;
- `schemas/capture-status-v1.schema.json`;
- `schemas/capture-version-v1.schema.json`.

A stdlib test compares canonical `model_json_schema()` output with each checked
file. Conditional status requirements use a discriminated union of nonterminal
and terminal models rather than optional fields accepted in every state.
Counters are non-negative strict integers. The event schema is a discriminated
union on `event`; transport is discriminated on `kind`; no generic arbitrary
payload model participates in protocol v1.

## Testing

All tests use stdlib `unittest`. Tests prove normal clients retain behavior;
every supported action path and raw-handle path is rejected before I/O in
read-only mode; adapters never return general clients; only permitted wire
messages leave capture mode; subscription feedback gates readiness; every wait
is bounded; reconnect creates a fresh client and resubscribes; cadence gaps are
recorded without catch-up; transport and aircraft readiness remain separate;
atomic status can be polled without modifying JSONL; UDP liveness expires after
valid-RREF silence; legal status transitions are enforced; checked schemas
match strict models; and terminal evidence is durable.

## Non-Goals

- No q4xpcc campaign or bundle logic.
- No plugin runtime integration.
- No flight initialization or repositioning.
- No DataRef writes or command execution in capture mode.
- No broad unconfigured DataRef sweep.
- No replacement for plugin-runtime evidence.
- No security guarantee against hostile Python code using reflection to reach
  private proxy internals.
