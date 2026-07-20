"""Strict event, status, and version models for capture protocol version 1."""

from __future__ import annotations

import math
import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, TypeAlias, cast

from pydantic import Field, field_validator, model_validator

from xpwebapi.capture_protocol import CaptureCorrelation, CaptureTransportConfig, StrictModel


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


class CaptureEventKind(StrEnum):
    """All protocol-v1 JSONL event discriminators."""

    CAPTURE_STARTED = "capture_started"
    TRANSPORT_STATE = "transport_state"
    TRANSPORT_READY = "transport_ready"
    SUBSCRIPTION_RESULT = "subscription_result"
    AIRCRAFT_READY = "aircraft_ready"
    SAMPLE = "sample"
    GAP_STARTED = "gap_started"
    GAP_ENDED = "gap_ended"
    RETRY = "retry"
    CAPTURE_STOPPED = "capture_stopped"
    CAPTURE_FAILED = "capture_failed"
    CAPTURE_INTERRUPTED = "capture_interrupted"


class SampleStatus(StrEnum):
    """All protocol-v1 sample validity states."""

    SAMPLED = "sampled"
    MISSING = "missing"
    STALE = "stale"
    DISCONNECTED = "disconnected"
    UNSUPPORTED = "unsupported"
    INVALID = "invalid"


class CaptureStatusState(StrEnum):
    """All protocol-v1 lifecycle states."""

    STARTING = "starting"
    CONNECTING = "connecting"
    TRANSPORT_READY = "transport_ready"
    AWAITING_AIRCRAFT = "awaiting_aircraft"
    SUBSCRIBING = "subscribing"
    AWAITING_FIRST_VALUES = "awaiting_first_values"
    AIRCRAFT_READY = "aircraft_ready"
    CAPTURING = "capturing"
    RECONNECTING = "reconnecting"
    FINALIZING = "finalizing"
    COMPLETE = "complete"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


JsonScalar: TypeAlias = int | float | str


def _nonempty(value: str, *, name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{name} must be nonempty and already trimmed")
    return value


def _sha256(value: str, *, name: str) -> str:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
    return value


def _timestamp(value: str, *, name: str) -> str:
    if _UTC_TIMESTAMP.fullmatch(value) is None:
        raise ValueError(f"{name} must be an RFC 3339 UTC timestamp ending in Z")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid RFC 3339 UTC timestamp") from exc
    return value


def _strict_integer(value: object, *, name: str, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer of at least {minimum}")
    return value


def _strict_float(value: object, *, name: str) -> float:
    if type(value) is not float or not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be a finite non-negative float")
    return value


def _json_scalar(value: object, *, name: str) -> JsonScalar:
    if type(value) not in {int, float, str}:
        raise ValueError(f"{name} must be a JSON integer, finite float, or string")
    if type(value) is float and not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return cast(JsonScalar, value)


def _validate_git_fields(
    *,
    git_state: str,
    git_root: str | None,
    git_revision: str | None,
    git_origin: str | None,
    git_dirty: bool | None,
) -> None:
    if git_state == "available":
        if git_root is None or git_revision is None or git_dirty is None:
            raise ValueError("available Git provenance requires root, revision, and dirty state")
        _nonempty(git_root, name="git_root")
        _nonempty(git_revision, name="git_revision")
        if git_origin is not None:
            _nonempty(git_origin, name="git_origin")
    elif any(value is not None for value in (git_root, git_revision, git_origin, git_dirty)):
        raise ValueError("unavailable Git provenance requires all Git details to be null")


class SourceProvenance(StrictModel):
    """Source package and checkout identity embedded in capture evidence."""

    package_name: str
    package_version: str
    python_version: str
    git_state: Literal["available", "unavailable"]
    git_root: str | None
    git_revision: str | None
    git_origin: str | None
    git_dirty: bool | None
    read_only: Literal[True]

    @field_validator("package_name", "package_version", "python_version")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _nonempty(value, name=info.field_name)

    @model_validator(mode="after")
    def _validate_git(self) -> "SourceProvenance":
        _validate_git_fields(
            git_state=self.git_state,
            git_root=self.git_root,
            git_revision=self.git_revision,
            git_origin=self.git_origin,
            git_dirty=self.git_dirty,
        )
        return self


class TransportCapabilities(StrictModel):
    """Read-only values supported by one transport endpoint."""

    transport: Literal["websocket", "udp"]
    endpoint: str
    xplane_version: str | None
    value_types: tuple[Literal["int", "float", "double", "string"], ...]

    @field_validator("endpoint")
    @classmethod
    def _validate_endpoint(cls, value: str) -> str:
        return _nonempty(value, name="endpoint")

    @field_validator("xplane_version")
    @classmethod
    def _validate_xplane_version(cls, value: str | None) -> str | None:
        return None if value is None else _nonempty(value, name="xplane_version")

    @model_validator(mode="after")
    def _validate_value_types(self) -> "TransportCapabilities":
        if not self.value_types:
            raise ValueError("value_types must not be empty")
        if len(self.value_types) != len(set(self.value_types)):
            raise ValueError("value_types must not contain duplicates")
        if self.transport == "udp" and self.value_types != ("float",):
            raise ValueError("UDP capabilities support exactly float values")
        return self


class IdentityObservation(StrictModel):
    """One observation used to establish Q4XP aircraft readiness."""

    ref_id: str
    path: str
    operator: Literal["equals", "contains"]
    expected_value: JsonScalar
    observed_value: JsonScalar
    source_observed_elapsed_seconds: float
    source_age_seconds: float

    @field_validator("ref_id", "path")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _nonempty(value, name=info.field_name)

    @field_validator("expected_value", "observed_value", mode="before")
    @classmethod
    def _validate_scalar(cls, value: object, info: Any) -> JsonScalar:
        return _json_scalar(value, name=info.field_name)

    @field_validator("source_observed_elapsed_seconds", "source_age_seconds", mode="before")
    @classmethod
    def _validate_elapsed(cls, value: object, info: Any) -> float:
        return _strict_float(value, name=info.field_name)

    @model_validator(mode="after")
    def _validate_operator(self) -> "IdentityObservation":
        if self.operator == "contains" and (type(self.expected_value) is not str or type(self.observed_value) is not str):
            raise ValueError("contains identity observations require string values")
        return self


class CaptureCounters(StrictModel):
    """Cumulative capture lifecycle counters."""

    sample_count: int
    gap_count: int
    retry_count: int
    accepted_ref_count: int
    rejected_ref_count: int

    @field_validator("sample_count", "gap_count", "retry_count", "accepted_ref_count", "rejected_ref_count", mode="before")
    @classmethod
    def _validate_count(cls, value: object, info: Any) -> int:
        return _strict_integer(value, name=info.field_name, minimum=0)


class CaptureEventIdentity(StrictModel):
    """Immutable identity copied into every event envelope."""

    capture_session_id: str
    sortie_id: str

    @field_validator("capture_session_id", "sortie_id")
    @classmethod
    def _validate_identifier(cls, value: str, info: Any) -> str:
        return _nonempty(value, name=info.field_name)


class EventEnvelope(StrictModel):
    """Fields common to every JSONL event row."""

    protocol_version: Literal[1]
    event: str
    sequence: int
    capture_session_id: str
    sortie_id: str
    timestamp_utc: str
    elapsed_seconds: float

    @field_validator("protocol_version", mode="before")
    @classmethod
    def _validate_protocol_version(cls, value: object) -> int:
        if type(value) is not int or value != 1:
            raise ValueError("protocol_version must be exactly integer 1")
        return value

    @field_validator("sequence", mode="before")
    @classmethod
    def _validate_sequence(cls, value: object) -> int:
        return _strict_integer(value, name="sequence", minimum=1)

    @field_validator("capture_session_id", "sortie_id")
    @classmethod
    def _validate_identifier(cls, value: str, info: Any) -> str:
        return _nonempty(value, name=info.field_name)

    @field_validator("timestamp_utc")
    @classmethod
    def _validate_timestamp(cls, value: str) -> str:
        return _timestamp(value, name="timestamp_utc")

    @field_validator("elapsed_seconds", mode="before")
    @classmethod
    def _validate_elapsed(cls, value: object) -> float:
        return _strict_float(value, name="elapsed_seconds")


class CaptureStartedInput(StrictModel):
    event: Literal["capture_started"]
    request_sha256: str
    correlation: CaptureCorrelation
    transport: CaptureTransportConfig
    provenance: SourceProvenance

    @field_validator("request_sha256")
    @classmethod
    def _validate_request_hash(cls, value: str) -> str:
        return _sha256(value, name="request_sha256")


class TransportStateInput(StrictModel):
    event: Literal["transport_state"]
    state: Literal["connected", "disconnected"]
    attempt: int
    reason: str | None
    capabilities: TransportCapabilities

    @field_validator("attempt", mode="before")
    @classmethod
    def _validate_attempt(cls, value: object) -> int:
        return _strict_integer(value, name="attempt", minimum=1)

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str | None) -> str | None:
        return None if value is None else _nonempty(value, name="reason")


class TransportReadyInput(StrictModel):
    event: Literal["transport_ready"]
    connection_generation: int
    endpoint: str
    read_only: Literal[True]
    package_version: str
    git_revision: str | None
    git_dirty: bool | None
    capabilities: TransportCapabilities

    @field_validator("connection_generation", mode="before")
    @classmethod
    def _validate_generation(cls, value: object) -> int:
        return _strict_integer(value, name="connection_generation", minimum=1)

    @field_validator("endpoint", "package_version")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _nonempty(value, name=info.field_name)


class SubscriptionResultInput(StrictModel):
    event: Literal["subscription_result"]
    purpose: Literal["aircraft_identity", "capture"]
    accepted_ref_ids: tuple[str, ...]
    rejected: dict[str, str]
    request_id: int | None

    @field_validator("request_id", mode="before")
    @classmethod
    def _validate_request_id(cls, value: object) -> int | None:
        if value is None:
            return None
        return _strict_integer(value, name="request_id", minimum=0)

    @model_validator(mode="after")
    def _validate_results(self) -> "SubscriptionResultInput":
        for ref_id in self.accepted_ref_ids:
            _nonempty(ref_id, name="accepted ref id")
        for ref_id, reason in self.rejected.items():
            _nonempty(ref_id, name="rejected ref id")
            _nonempty(reason, name="rejection reason")
        if len(self.accepted_ref_ids) != len(set(self.accepted_ref_ids)):
            raise ValueError("accepted_ref_ids must not contain duplicates")
        if set(self.accepted_ref_ids).intersection(self.rejected):
            raise ValueError("a ref id cannot be both accepted and rejected")
        return self


class AircraftReadyInput(StrictModel):
    event: Literal["aircraft_ready"]
    connection_generation: int
    target_aircraft: Literal["FlyJSim Q4XP"]
    identity_observations: tuple[IdentityObservation, ...]
    required_ref_ids: tuple[str, ...]
    optional_missing_ref_ids: tuple[str, ...]
    ready_elapsed_seconds: float

    @field_validator("connection_generation", mode="before")
    @classmethod
    def _validate_generation(cls, value: object) -> int:
        return _strict_integer(value, name="connection_generation", minimum=1)

    @field_validator("ready_elapsed_seconds", mode="before")
    @classmethod
    def _validate_ready_elapsed(cls, value: object) -> float:
        return _strict_float(value, name="ready_elapsed_seconds")

    @model_validator(mode="after")
    def _validate_refs(self) -> "AircraftReadyInput":
        if not self.identity_observations:
            raise ValueError("identity_observations must not be empty")
        for ref_id in (*self.required_ref_ids, *self.optional_missing_ref_ids):
            _nonempty(ref_id, name="capture ref id")
        if len(self.required_ref_ids) != len(set(self.required_ref_ids)):
            raise ValueError("required_ref_ids must not contain duplicates")
        if len(self.optional_missing_ref_ids) != len(set(self.optional_missing_ref_ids)):
            raise ValueError("optional_missing_ref_ids must not contain duplicates")
        if set(self.required_ref_ids).intersection(self.optional_missing_ref_ids):
            raise ValueError("required and optional-missing ref ids must be disjoint")
        return self


class SampleInput(StrictModel):
    event: Literal["sample"]
    sample_group_id: str
    ref_id: str
    path: str
    declared_type: Literal["int", "float", "double", "string"]
    status: Literal["sampled", "missing", "stale", "disconnected", "unsupported", "invalid"]
    value: JsonScalar | None
    source_observed_elapsed_seconds: float | None
    source_age_seconds: float | None

    @model_validator(mode="before")
    @classmethod
    def _normalize_sample_value(cls, value: Any) -> Any:
        if not isinstance(value, dict) or value.get("status") != "sampled":
            return value
        prepared = dict(value)
        declared_type = prepared.get("declared_type")
        sample_value = prepared.get("value")
        if declared_type == "int":
            if type(sample_value) is not int:
                raise ValueError("sampled int values must be exact integers")
        elif declared_type in {"float", "double"}:
            if not isinstance(sample_value, (int, float)) or isinstance(sample_value, bool) or not math.isfinite(sample_value):
                raise ValueError("sampled float values must be finite numbers")
            prepared["value"] = float(sample_value)
        elif declared_type == "string":
            if type(sample_value) is not str:
                raise ValueError("sampled string values must be strings")
        return prepared

    @field_validator("sample_group_id", "ref_id", "path")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _nonempty(value, name=info.field_name)

    @field_validator("value", mode="before")
    @classmethod
    def _validate_value(cls, value: object) -> JsonScalar | None:
        return None if value is None else _json_scalar(value, name="value")

    @field_validator("source_observed_elapsed_seconds", "source_age_seconds", mode="before")
    @classmethod
    def _validate_optional_elapsed(cls, value: object, info: Any) -> float | None:
        return None if value is None else _strict_float(value, name=info.field_name)

    @model_validator(mode="after")
    def _validate_sample_contract(self) -> "SampleInput":
        source_times = (self.source_observed_elapsed_seconds, self.source_age_seconds)
        if (source_times[0] is None) != (source_times[1] is None):
            raise ValueError("sample source times must both be null or both be present")
        if self.status == "sampled":
            if self.value is None or source_times[0] is None:
                raise ValueError("sampled values and source times must be present")
        elif self.value is not None:
            raise ValueError("non-sampled statuses require a null value")
        if self.status == "missing" and source_times != (None, None):
            raise ValueError("missing samples require null source times")
        return self


class GapStartedInput(StrictModel):
    event: Literal["gap_started"]
    reason: str
    affected_ref_ids: tuple[str, ...]
    gap_start_elapsed_seconds: float

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _nonempty(value, name="reason")

    @field_validator("gap_start_elapsed_seconds", mode="before")
    @classmethod
    def _validate_elapsed(cls, value: object) -> float:
        return _strict_float(value, name="gap_start_elapsed_seconds")

    @model_validator(mode="after")
    def _validate_ref_ids(self) -> "GapStartedInput":
        for ref_id in self.affected_ref_ids:
            _nonempty(ref_id, name="affected ref id")
        if len(self.affected_ref_ids) != len(set(self.affected_ref_ids)):
            raise ValueError("affected_ref_ids must not contain duplicates")
        return self


class GapEndedInput(GapStartedInput):
    event: Literal["gap_ended"]
    gap_duration_seconds: float
    skipped_slot_count: int

    @field_validator("gap_duration_seconds", mode="before")
    @classmethod
    def _validate_duration(cls, value: object) -> float:
        return _strict_float(value, name="gap_duration_seconds")

    @field_validator("skipped_slot_count", mode="before")
    @classmethod
    def _validate_skipped_count(cls, value: object) -> int:
        return _strict_integer(value, name="skipped_slot_count", minimum=0)


class RetryInput(StrictModel):
    event: Literal["retry"]
    phase: Literal["initial_connect", "reconnect"]
    attempt: int
    maximum_attempts: int
    delay_seconds: float
    reason: str

    @field_validator("attempt", "maximum_attempts", mode="before")
    @classmethod
    def _validate_attempt(cls, value: object, info: Any) -> int:
        return _strict_integer(value, name=info.field_name, minimum=1)

    @field_validator("delay_seconds", mode="before")
    @classmethod
    def _validate_delay(cls, value: object) -> float:
        return _strict_float(value, name="delay_seconds")

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _nonempty(value, name="reason")

    @model_validator(mode="after")
    def _validate_attempt_range(self) -> "RetryInput":
        if self.attempt > self.maximum_attempts:
            raise ValueError("attempt must not exceed maximum_attempts")
        return self


class _TerminalInput(StrictModel):
    sample_count: int
    gap_count: int
    retry_count: int

    @field_validator("sample_count", "gap_count", "retry_count", mode="before")
    @classmethod
    def _validate_count(cls, value: object, info: Any) -> int:
        return _strict_integer(value, name=info.field_name, minimum=0)


class CaptureStoppedInput(_TerminalInput):
    event: Literal["capture_stopped"]
    termination: Literal["stop_file", "capture_limit", "requested", "groups_complete"]


class CaptureFailedInput(_TerminalInput):
    event: Literal["capture_failed"]
    reason: str

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _nonempty(value, name="reason")


class CaptureInterruptedInput(_TerminalInput):
    event: Literal["capture_interrupted"]
    signal: Literal["SIGINT", "SIGTERM"]


class CaptureStartedEvent(EventEnvelope, CaptureStartedInput):
    event: Literal["capture_started"]


class TransportStateEvent(EventEnvelope, TransportStateInput):
    event: Literal["transport_state"]


class TransportReadyEvent(EventEnvelope, TransportReadyInput):
    event: Literal["transport_ready"]


class SubscriptionResultEvent(EventEnvelope, SubscriptionResultInput):
    event: Literal["subscription_result"]


class AircraftReadyEvent(EventEnvelope, AircraftReadyInput):
    event: Literal["aircraft_ready"]


class SampleEvent(EventEnvelope, SampleInput):
    event: Literal["sample"]


class GapStartedEvent(EventEnvelope, GapStartedInput):
    event: Literal["gap_started"]


class GapEndedEvent(EventEnvelope, GapEndedInput):
    event: Literal["gap_ended"]


class RetryEvent(EventEnvelope, RetryInput):
    event: Literal["retry"]


class CaptureStoppedEvent(EventEnvelope, CaptureStoppedInput):
    event: Literal["capture_stopped"]
    preceding_sha256: str

    @field_validator("preceding_sha256")
    @classmethod
    def _validate_preceding_hash(cls, value: str) -> str:
        return _sha256(value, name="preceding_sha256")


class CaptureFailedEvent(EventEnvelope, CaptureFailedInput):
    event: Literal["capture_failed"]
    preceding_sha256: str

    @field_validator("preceding_sha256")
    @classmethod
    def _validate_preceding_hash(cls, value: str) -> str:
        return _sha256(value, name="preceding_sha256")


class CaptureInterruptedEvent(EventEnvelope, CaptureInterruptedInput):
    event: Literal["capture_interrupted"]
    preceding_sha256: str

    @field_validator("preceding_sha256")
    @classmethod
    def _validate_preceding_hash(cls, value: str) -> str:
        return _sha256(value, name="preceding_sha256")


CaptureEventPayload = Annotated[
    CaptureStartedInput
    | TransportStateInput
    | TransportReadyInput
    | SubscriptionResultInput
    | AircraftReadyInput
    | SampleInput
    | GapStartedInput
    | GapEndedInput
    | RetryInput,
    Field(discriminator="event"),
]
TerminalCaptureInput = CaptureStoppedInput | CaptureFailedInput | CaptureInterruptedInput
CaptureEvent = Annotated[
    CaptureStartedEvent
    | TransportStateEvent
    | TransportReadyEvent
    | SubscriptionResultEvent
    | AircraftReadyEvent
    | SampleEvent
    | GapStartedEvent
    | GapEndedEvent
    | RetryEvent
    | CaptureStoppedEvent
    | CaptureFailedEvent
    | CaptureInterruptedEvent,
    Field(discriminator="event"),
]


NonterminalState = Literal[
    "starting",
    "connecting",
    "transport_ready",
    "awaiting_aircraft",
    "subscribing",
    "awaiting_first_values",
    "aircraft_ready",
    "capturing",
    "reconnecting",
    "finalizing",
]


class StatusBase(StrictModel):
    """Fields common to terminal and nonterminal polling documents."""

    protocol_version: Literal[1]
    capture_session_id: str
    sortie_id: str
    state: str
    updated_at_utc: str
    elapsed_seconds: float
    events_path: str
    request_sha256: str
    transport: Literal["websocket", "udp"]
    transport_connection_state: Literal["not_connected", "connected", "awaiting_first_identity_packet", "disconnected"]
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

    @field_validator("protocol_version", mode="before")
    @classmethod
    def _validate_protocol_version(cls, value: object) -> int:
        if type(value) is not int or value != 1:
            raise ValueError("protocol_version must be exactly integer 1")
        return value

    @field_validator("capture_session_id", "sortie_id", "events_path")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _nonempty(value, name=info.field_name)

    @field_validator("request_sha256")
    @classmethod
    def _validate_request_hash(cls, value: str) -> str:
        return _sha256(value, name="request_sha256")

    @field_validator("updated_at_utc")
    @classmethod
    def _validate_updated_at(cls, value: str) -> str:
        return _timestamp(value, name="updated_at_utc")

    @field_validator("transport_ready_at_utc", "aircraft_ready_at_utc")
    @classmethod
    def _validate_optional_timestamp(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _timestamp(value, name=info.field_name)

    @field_validator("elapsed_seconds", mode="before")
    @classmethod
    def _validate_elapsed(cls, value: object) -> float:
        return _strict_float(value, name="elapsed_seconds")

    @field_validator(
        "connection_generation",
        "identity_ref_count",
        "matched_identity_ref_count",
        "required_capture_ref_count",
        "observed_required_ref_count",
        "current_attempt",
        "maximum_attempts",
        mode="before",
    )
    @classmethod
    def _validate_count(cls, value: object, info: Any) -> int:
        return _strict_integer(value, name=info.field_name, minimum=0)

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str | None) -> str | None:
        return None if value is None else _nonempty(value, name="reason")

    @model_validator(mode="after")
    def _validate_status_relationships(self) -> "StatusBase":
        if self.matched_identity_ref_count > self.identity_ref_count:
            raise ValueError("matched_identity_ref_count must not exceed identity_ref_count")
        if self.observed_required_ref_count > self.required_capture_ref_count:
            raise ValueError("observed_required_ref_count must not exceed required_capture_ref_count")
        if self.attempt_phase == "none":
            if self.current_attempt != 0 or self.maximum_attempts != 0:
                raise ValueError("attempt counts must be zero when attempt_phase is none")
        elif self.current_attempt < 1 or self.maximum_attempts < 1 or self.current_attempt > self.maximum_attempts:
            raise ValueError("active attempts must be positive and current must not exceed maximum")
        return self


class NonterminalStatus(StatusBase):
    state: NonterminalState

    @model_validator(mode="after")
    def _validate_readiness(self) -> "NonterminalStatus":
        before_transport = {"starting", "connecting"}
        after_aircraft = {"aircraft_ready", "capturing", "finalizing"}
        if self.state in before_transport:
            if self.connection_generation != 0 or self.transport_ready_at_utc is not None:
                raise ValueError("transport readiness is unavailable before transport_ready")
        elif self.connection_generation < 1 or self.transport_ready_at_utc is None:
            raise ValueError("transport-ready states require a positive generation and readiness timestamp")
        if self.state in after_aircraft and self.aircraft_ready_at_utc is None:
            raise ValueError("aircraft-ready states require the aircraft readiness timestamp")
        if self.state in before_transport and self.aircraft_ready_at_utc is not None:
            raise ValueError("aircraft readiness timestamp is unavailable before aircraft_ready")
        if self.state == "reconnecting":
            if self.reason is None:
                raise ValueError("reconnecting status requires a reason")
        elif self.reason is not None:
            raise ValueError("healthy nonterminal status requires a null reason")
        return self


class _TerminalStatus(StatusBase):
    events_sha256: str
    events_size_bytes: int

    @field_validator("events_sha256")
    @classmethod
    def _validate_events_hash(cls, value: str) -> str:
        return _sha256(value, name="events_sha256")

    @field_validator("events_size_bytes", mode="before")
    @classmethod
    def _validate_events_size(cls, value: object) -> int:
        return _strict_integer(value, name="events_size_bytes", minimum=0)


class CompleteStatus(_TerminalStatus):
    state: Literal["complete"]
    reason: Literal["stop_file", "capture_limit", "requested", "groups_complete"]
    exit_code: Literal[0]
    clean_shutdown: Literal[True]

    @model_validator(mode="after")
    def _validate_readiness(self) -> "CompleteStatus":
        if self.transport_ready_at_utc is None or self.aircraft_ready_at_utc is None or self.connection_generation < 1:
            raise ValueError("complete status requires both readiness latches")
        return self


class FailedStatus(_TerminalStatus):
    state: Literal["failed"]
    reason: str
    exit_code: Literal[3]
    clean_shutdown: Literal[False]


class InterruptedStatus(_TerminalStatus):
    state: Literal["interrupted"]
    reason: Literal["SIGINT", "SIGTERM"]
    exit_code: Literal[130]
    clean_shutdown: bool


StatusDocument = Annotated[
    NonterminalStatus | CompleteStatus | FailedStatus | InterruptedStatus,
    Field(discriminator="state"),
]


class VersionJsonDocument(StrictModel):
    """Machine-readable worker version and source provenance."""

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

    @field_validator("package_name", "package_version", "python_version")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _nonempty(value, name=info.field_name)

    @model_validator(mode="after")
    def _validate_git(self) -> "VersionJsonDocument":
        _validate_git_fields(
            git_state=self.git_state,
            git_root=self.git_root,
            git_revision=self.git_revision,
            git_origin=self.git_origin,
            git_dirty=self.git_dirty,
        )
        return self


LEGAL_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "starting": frozenset({"connecting", "failed", "interrupted"}),
    "connecting": frozenset({"connecting", "transport_ready", "failed", "interrupted"}),
    "transport_ready": frozenset({"awaiting_aircraft", "failed", "interrupted"}),
    "awaiting_aircraft": frozenset({"subscribing", "reconnecting", "failed", "interrupted"}),
    "subscribing": frozenset({"awaiting_first_values", "reconnecting", "failed", "interrupted"}),
    "awaiting_first_values": frozenset({"aircraft_ready", "reconnecting", "failed", "interrupted"}),
    "aircraft_ready": frozenset({"capturing", "finalizing", "failed", "interrupted"}),
    "capturing": frozenset({"reconnecting", "finalizing", "failed", "interrupted"}),
    "reconnecting": frozenset({"reconnecting", "transport_ready", "failed", "interrupted"}),
    "finalizing": frozenset({"complete", "failed", "interrupted"}),
    "complete": frozenset(),
    "failed": frozenset(),
    "interrupted": frozenset(),
}
