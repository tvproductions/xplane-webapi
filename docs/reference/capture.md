---
title: Capture protocol
---

# Capture protocol

Protocol version 1 is the file/process boundary between a consuming development
tool and the xpwebapi read-only capture worker. The installed JSON Schemas are
the machine-readable contract; the models below are canonical.

## Request fields

`CaptureRequest` contains exactly:

- `protocol_version`, fixed integer `1`;
- `capture_session_id` and `sortie_id`;
- `correlation` with `campaign_id`, `route_profile_id`, and `scenario_id`;
- `identity_readiness`, currently `kind="dataref_match"`, target aircraft
  `FlyJSim Q4XP`, and one or more identity refs;
- discriminated `transport`, WebSocket or UDP;
- `sample_groups` and capture `refs`;
- `retry` policy;
- nullable `capture_limit_seconds` and `stop_file`.

Each identity ref has `id`, `path`, `declared_type`, nullable `encoding`,
`rate_hz`, `operator`, and `expected_value`. Each sample group has `id`,
`rate_hz`, and nullable `duration_seconds`. Each capture ref has `id`, `path`,
`declared_type`, `availability`, `sample_group_id`, and nullable `encoding`.

The retry object has `initial_attempts`, `reconnect_attempts`,
`backoff_seconds`, `backoff_max_seconds`, `subscription_timeout_seconds`,
`aircraft_identity_timeout_seconds`, `first_values_timeout_seconds`,
`max_disconnect_seconds`, `stale_after_seconds`, `poll_interval_seconds`, and
`shutdown_timeout_seconds`.

Identity subscription metadata, send, and feedback operations are always
bounded by `subscription_timeout_seconds`. The separate
`aircraft_identity_timeout_seconds` may be a positive number or `null`; `null`
waits for matching aircraft identity until explicit stop, interruption,
transport failure, or an owning reconnect deadline. UDP reports
`awaiting_first_identity_packet` for the full finite or unbounded identity wait.

`load_capture_request()` reads bytes once. The exact same bytes are parsed and
hashed, producing the `request_sha256` passed explicitly into `CaptureRunner`.
`SourceProvenance` is also resolved by the CLI and passed explicitly; the
runner never fabricates either value or reads it from writer internals.

## Event JSONL

Every row contains `protocol_version`, `event`, `sequence`,
`capture_session_id`, `sortie_id`, `timestamp_utc`, and `elapsed_seconds`.
Sequence starts at 1 and strictly increases. Elapsed time is non-decreasing, so
multiple events may share a monotonic instant.

Event-specific fields are exact:

- `capture_started`: `request_sha256`, `correlation`, `transport`,
  `provenance`.
- `transport_state`: `state`, `attempt`, nullable `reason`, `capabilities`.
- `transport_ready`: `connection_generation`, `endpoint`, `read_only`,
  `package_version`, nullable `git_revision`, nullable `git_dirty`,
  `capabilities`.
- `subscription_result`: `purpose`, `accepted_ref_ids`, `rejected`, nullable
  `request_id`.
- `aircraft_ready`: `connection_generation`, `target_aircraft`,
  `identity_observations`, `required_ref_ids`, `optional_missing_ref_ids`,
  `ready_elapsed_seconds`.
- `sample`: `sample_group_id`, `ref_id`, `path`, `declared_type`, `status`,
  nullable `value`, nullable `source_observed_elapsed_seconds`, nullable
  `source_age_seconds`.
- `gap_started`: `reason`, `affected_ref_ids`,
  `gap_start_elapsed_seconds`.
- `gap_ended`: the gap-start fields plus `gap_duration_seconds` and
  `skipped_slot_count`.
- `retry`: `phase`, `attempt`, `maximum_attempts`, `delay_seconds`, `reason`.
- `capture_stopped`: `termination`, `sample_count`, `gap_count`,
  `retry_count`, `preceding_sha256`.
- `capture_failed`: `reason`, the three counters, `preceding_sha256`.
- `capture_interrupted`: `signal`, the three counters, `preceding_sha256`.

`sample.status` is `sampled`, `missing`, `stale`, `disconnected`,
`unsupported`, or `invalid`. Only `sampled` has a non-null value. `missing`
has both source-time fields null; other statuses may retain both source times.
The terminal `preceding_sha256` covers every complete row before the terminal
row.

## Status JSON

Every status document contains:

- `protocol_version`, `capture_session_id`, `sortie_id`, `state`;
- `updated_at_utc`, `elapsed_seconds`, `events_path`, `request_sha256`;
- `transport`, `transport_connection_state`, `connection_generation`;
- nullable `transport_ready_at_utc` and `aircraft_ready_at_utc`;
- `target_aircraft`, `identity_ref_count`, `matched_identity_ref_count`;
- `required_capture_ref_count`, `observed_required_ref_count`;
- `counters` containing `sample_count`, `gap_count`, `retry_count`,
  `accepted_ref_count`, and `rejected_ref_count`;
- `attempt_phase`, `current_attempt`, `maximum_attempts`, nullable `reason`.

Nonterminal states are `starting`, `connecting`, `transport_ready`,
`awaiting_aircraft`, `subscribing`, `awaiting_first_values`, `aircraft_ready`,
`capturing`, `reconnecting`, and `finalizing`. Every nonterminal state can
enter `finalizing` for a pre-readiness requested stop or another clean stop.
Only `reconnecting` has a non-null nonterminal reason.

Terminal status adds `events_sha256` and `events_size_bytes`. `complete` has a
reason of `stop_file`, `capture_limit`, `requested`, or `groups_complete`,
`exit_code=0`, and `clean_shutdown=true`. `failed` has a diagnostic reason,
`exit_code=3`, and `clean_shutdown=false`. `interrupted` has reason `SIGINT` or
`SIGTERM`, `exit_code=130`, and a boolean `clean_shutdown`.

Terminal event/status publication is a two-phase event/status commit: durable
terminal JSONL is the first commit point, and atomic terminal status replace is
the second. A complete-but-unclean runner outcome has process exit 3. When the
terminal event committed but status did not, JSONL is authoritative and status
may remain `finalizing`; this is deliberate status residue, not permission to
rewrite the event stream.

A full terminal-row write closes the event stream logically and prevents any
further append, retry, or abandon mutation. The committed hash and size become
available only after flush and fsync succeed. Flush/fsync failure leaves raw
unproven evidence with `finalizing` status and a failed, unclean outcome; close
failure after successful fsync is post-commit.

## Signals and cleanup

`CaptureInterruption` retains the first `SIGINT` or `SIGTERM` identity across
the CLI signal handler and runner. Programmatic stop sets only the stop event
and is recorded as `requested`.

The runner passes one absolute cleanup deadline to the transport. WebSocket
and UDP adapters assign per-stage transport shutdown budgets to unsubscribe,
listener stop, channel close, and HTTP-session or beacon-owner close. All
stages are attempted while the first cleanup failure remains authoritative.

## Transport safety

The transport factory always constructs read-only clients. Capture adapters
expose only `open`, `subscribe`, `connected`, `liveness_state`, and `close`;
no general API or raw socket escapes.
WebSocket capture sends only subscribe/unsubscribe value messages. UDP sends
only validated `RREF\0` packets. Reservation collision handling uses exclusive
creation and no cross-path rollback so a path replacement race cannot cause
the worker to delete another process's file.

## Installed JSON Schemas

The four protocol-v1 schemas ship in the `xpwebapi.schemas` package:

- `capture-event-v1.schema.json`
- `capture-request-v1.schema.json`
- `capture-status-v1.schema.json`
- `capture-version-v1.schema.json`

```python
from importlib.resources import files

schema_text = (
    files("xpwebapi.schemas")
    .joinpath("capture-request-v1.schema.json")
    .read_text(encoding="utf-8")
)
```

## API declarations

::: xpwebapi.capture_protocol

::: xpwebapi.capture_events

::: xpwebapi.capture_transport
