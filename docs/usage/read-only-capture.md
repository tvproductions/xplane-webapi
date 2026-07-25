---
title: Read-only capture
---

# Read-only capture

`xpwebapi-capture` is a bounded external recorder for configured X-Plane 12
DataRefs. It writes raw protocol-v1 JSONL events and an atomic polling-status
document. It never writes a DataRef or executes a command.

WebSocket is the primary transport. UDP is a diagnostic fallback for cases
where WebSocket observation is unavailable or a transport comparison is part
of the test. UDP supports only float DataRefs at integral rates from 1 through
100 Hz.

## Ownership boundary

xplane-webapi owns network discovery, connections, subscriptions, retries,
read-only enforcement, raw events, status, and source provenance. q4xpcc owns
the watchlist, campaign, route, scenario, sortie, worker process, normalized
recorder events, replay, correlation, integrity checks, and final evidence
bundle. q4xpcc remains the XPPython3 plugin and the system under test; it does
not import `xpwebapi`.

## Command modes

Capture mode requires three paths and accepts one optional stop path:

```powershell
uv run xpwebapi-capture `
  --request artifacts\stationary\request.json `
  --events artifacts\stationary\capture.jsonl `
  --status artifacts\stationary\capture-status.json `
  --stop-file artifacts\stationary\capture.stop
```

`--request`, `--events`, and `--status` are required together. `--stop-file`
is optional. A stop path supplied in both the request and the CLI must resolve
to the same path.

Provenance-only mode is:

```powershell
uv run xpwebapi-capture --version-json
```

`--version-json` is mutually exclusive with all capture arguments. It emits
one compact, key-sorted protocol-v1 JSON object plus LF (`0x0A`), never CRLF. It makes no
network calls and performs no filesystem mutation. It may read local package,
Git, and filesystem provenance. The object is the machine-readable handshake
q4xpcc should inspect before launching capture:

```json
{"git_dirty":null,"git_origin":null,"git_revision":null,"git_root":null,"git_state":"unavailable","package_name":"xpwebapi","package_version":"3.5.0","python_version":"3.12.0","read_only":true,"supported_transports":["udp","websocket"],"worker":"xpwebapi-capture","worker_protocol_version":1}
```

## Complete protocol-v1 request

Unknown fields and duplicate JSON object keys are rejected. Numeric fields are
strict: booleans and stringified numbers are not accepted.

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

The 10-second subscription timeout bounds each adapter's metadata/send/feedback
work; it does not truncate the aircraft-loading window. Set
`aircraft_identity_timeout_seconds` to `null` when aircraft loading is a
human-controlled action that must wait until a matching aircraft appears or the
worker is explicitly stopped. UDP reports `awaiting_first_identity_packet`
throughout that unbounded wait. Finite values retain the bounded timeout
behavior.

To use UDP instead, replace `transport` with:

```json
{
  "kind": "udp",
  "beacon_timeout_seconds": 5.0,
  "socket_timeout_seconds": 1.0,
  "liveness_timeout_seconds": 3.0
}
```

## Two-stage readiness regimen

Start X-Plane 12 without loading Q4XP, launch the worker, and poll the status
file. The order is intentional:

1. Wait until `transport_ready_at_utc` is non-null. The network channel is
   usable, but no aircraft or capture-ref claim has been made.
2. Load FlyJSim Q4XP.
3. Wait until `aircraft_ready_at_utc` is non-null and `state` is `capturing`.
   The declared identity refs matched, capture subscriptions were accepted,
   and every required capture ref produced a fresh first value.
4. Fly the intended segment. Create the stop file to end the sortie capture.

Both readiness timestamps are latches: reconnecting never clears a readiness
milestone already reached. A new connection generation must nevertheless emit
fresh `transport_ready` and `aircraft_ready` events before capture resumes.

An already-set programmatic stop or a stop file observed before readiness is a
clean pre-readiness requested stop: the status passes through `finalizing` and
can finish `complete` without inventing either readiness timestamp.

## Stop, signals, and exit codes

The worker polls but never deletes the stop file. The file must not exist at
preflight. A programmatic stop is recorded as `requested`; a stop-file request
as `stop_file`; a time limit as `capture_limit`; and completion of every
bounded group as `groups_complete`.

- `0`: complete and clean shutdown.
- `2`: invalid arguments, request, path, alias, collision, or preflight.
- `3`: connection, subscription, capture, output, cleanup, or a complete but unclean shutdown.
- `130`: SIGINT or SIGTERM, preserving the first signal identity.

Shutdown has one runner deadline. Each transport divides its remaining time
into a per-stage shutdown budget for unsubscribe, listener stop, channel close,
and owner/session or beacon close. A timed-out stage does not prevent later
cleanup stages from being attempted.

## Output safety and terminal commits

The events and status paths must be new, distinct from each other, and distinct
from the request and stop paths after resolution, case normalization, and
symlink handling. Output reservation uses exclusive creation.

The reservation rule is deliberately conservative: there is no cross-path
rollback. If the status reservation loses a race after this invocation has
created the empty events reservation, the worker closes its descriptor,
preserves the events path, emits `output_reservation_partial`, and exits 2.
Runner construction or an unexpected runner escape after reservation preserves
both paths and exits 3 with the same diagnostic family. Never automatically
delete such residue; inspect path identity and contents first.

Terminal evidence uses a two-phase event/status commit. The terminal JSONL row
is prepared and durably committed first; terminal status is prepared from the
complete event hash and size, then published by atomic replacement. If the
event commit cannot be proven, status remains `finalizing`. If JSONL commits
but status replacement fails, JSONL is authoritative, the process returns 3,
and the last status may remain `finalizing`. That is the observable
complete-but-unclean status-residue case. If atomic status replacement itself
succeeds just as its deadline passes, the published terminal status remains
authoritative and the internal deadline diagnostic does not contradict it.

Writing the complete terminal row makes the JSONL logically closed and
immutable, but does not publish its committed identity. Only successful flush
and fsync make the hash and size authoritative. A flush/fsync failure preserves
the raw unproven bytes, leaves status `finalizing`, and exits failed/unclean;
physical close failure after successful fsync is post-commit.

## Read-only network boundary

For capture, WebSocket may send only `dataref_subscribe_values` and
`dataref_unsubscribe_values`. UDP may send only validated 413-byte `RREF\0`
subscribe/unsubscribe packets for configured DataRefs and the discovered
destination. REST is used only for read-only capability and DataRef metadata
lookups required by the WebSocket adapter.

The read-only clients reject DataRef writes, commands, command monitoring,
unknown WebSocket message types, malformed or foreign UDP packets, auto-save,
and forbidden raw-handle methods before network I/O. The request contract has
no field for a method, command, write value, or arbitrary packet.

## Stationary ground-readiness check

This check is opt-in and requires a real local X-Plane endpoint. Do not invent
evidence when the endpoint is unavailable.

```powershell
uv run xpwebapi-capture --request artifacts\stationary\request.json --events artifacts\stationary\capture.jsonl --status artifacts\stationary\capture-status.json --stop-file artifacts\stationary\capture.stop
```

Poll for transport readiness, load Q4XP, poll for aircraft readiness and
`capturing`, create the stop file, and verify exit 0 plus terminal status
`complete`. Inspect `capture_started.provenance`, terminal hashes, and captured
traffic. Traffic must contain only WebSocket subscribe/unsubscribe requests or
UDP `RREF` packets. Raw live capture is not committed unless q4xpcc explicitly
promotes it into its evidence workflow.
