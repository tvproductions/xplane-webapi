"""Bounded lifecycle, readiness, sampling, and cleanup for capture workers."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, cast

from xpwebapi.capture_events import (
    AircraftReadyInput,
    CaptureCounters,
    CaptureFailedInput,
    CaptureInterruptedInput,
    CaptureStartedInput,
    CaptureStoppedInput,
    CompleteStatus,
    FailedStatus,
    GapEndedInput,
    GapStartedInput,
    IdentityObservation,
    InterruptedStatus,
    NonterminalStatus,
    RetryInput,
    SampleInput,
    SourceProvenance,
    StatusDocument,
    SubscriptionResultInput,
    TransportCapabilities,
    TransportReadyInput,
    TransportStateInput,
)
from xpwebapi.capture_output import (
    AtomicStatusWriter,
    CaptureEventWriter,
    PreparedCaptureClose,
    PreparedStatus,
)
from xpwebapi.capture_protocol import AircraftIdentityRef, CaptureRef, CaptureRequest, CaptureSampleGroup
from xpwebapi.capture_transport import CaptureTransport, Observation, SubscriptionResult


TerminalState = Literal["complete", "failed", "interrupted"]
InterruptionName = Literal["SIGINT", "SIGTERM"]
AnySampleStatus = Literal["sampled", "missing", "stale", "disconnected", "unsupported", "invalid"]
AnyTermination = Literal["stop_file", "capture_limit", "requested", "groups_complete"]


class CaptureInterruption:
    """Thread-safe signal identity shared by CLI handlers and the runner."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._signal: InterruptionName | None = None

    def set(self, signal: InterruptionName) -> None:
        """Record the first process signal without permitting replacement."""

        with self._lock:
            if self._signal is None:
                self._signal = signal

    def get(self) -> InterruptionName | None:
        """Return the signal recorded by a process signal handler, if any."""

        with self._lock:
            return self._signal


@dataclass(frozen=True, slots=True)
class CaptureOutcome:
    """Terminal worker result with stable process exit semantics."""

    terminal_state: TerminalState
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
        """Map the terminal state to the worker process exit code."""

        if self.terminal_state == "interrupted":
            return 130
        if self.terminal_state == "complete" and self.clean_shutdown:
            return 0
        return 3


class CaptureClock(Protocol):
    """Time and bounded-wait surface used by the capture lifecycle."""

    def monotonic(self) -> float:
        """Return monotonic seconds for deadlines and source age."""

        return time.monotonic()

    def utcnow(self) -> datetime:
        """Return the current aware UTC wall-clock timestamp."""

        return datetime.now(UTC)

    def wait(self, event: threading.Event, timeout: float) -> bool:
        """Wait no longer than timeout and report whether event was set."""

        return event.wait(timeout)


@dataclass(slots=True)
class _GroupSchedule:
    group: CaptureSampleGroup
    refs: tuple[CaptureRef, ...]
    interval: float
    next_deadline: float


@dataclass(slots=True)
class _RunState:
    started_monotonic: float
    finished: bool = False
    terminal_state: TerminalState = "failed"
    termination: str = "runtime_failure"
    reason: str | None = None
    clean_shutdown: bool = False
    transport_ready_at_utc: str | None = None
    aircraft_ready_at_utc: str | None = None
    connection_generation: int = 0
    transport_connection_state: str = "not_connected"
    attempt_phase: str = "none"
    current_attempt: int = 0
    maximum_attempts: int = 0
    connected_attempt: int = 0
    matched_identity_ref_count: int = 0
    observed_required_ref_count: int = 0
    identity_accepted_ref_ids: set[str] = field(default_factory=set)
    identity_rejected_refs: dict[str, str] = field(default_factory=dict)
    capture_accepted_ref_ids: set[str] = field(default_factory=set)
    capture_rejected_refs: dict[str, str] = field(default_factory=dict)
    observations: dict[str, Observation] = field(default_factory=dict)
    sample_count: int = 0
    gap_count: int = 0
    retry_count: int = 0
    current_status: str | None = None
    aircraft_ready_monotonic: float | None = None
    schedules: list[_GroupSchedule] = field(default_factory=list)
    schedules_initialized: bool = False


class _CaptureFailure(RuntimeError):
    pass


class _RetryableDisconnect(_CaptureFailure):
    pass


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock.utcnow() must return an aware datetime")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _error_text(error: BaseException) -> str:
    detail = str(error).strip()
    return f"{type(error).__name__}: {detail}" if detail else type(error).__name__


def _identity_value(ref: AircraftIdentityRef, value: object) -> int | float | str | None:
    if ref.declared_type == "string":
        if isinstance(value, bytes):
            try:
                return value.decode(cast(str, ref.encoding)).replace("\x00", "")
            except (LookupError, UnicodeDecodeError):
                return None
        return value if type(value) is str else None
    if ref.declared_type == "int":
        return value if type(value) is int else None
    if type(value) not in {int, float} or not math.isfinite(cast(int | float, value)):
        return None
    return float(cast(int | float, value))


def _identity_matches(ref: AircraftIdentityRef, value: object) -> bool:
    normalized = _identity_value(ref, value)
    if normalized is None:
        return False
    if ref.operator == "contains":
        return cast(str, ref.expected_value) in cast(str, normalized)
    if ref.declared_type in {"float", "double"}:
        return normalized == float(cast(float, ref.expected_value))
    return normalized == ref.expected_value


def _normalized_sample(ref: CaptureRef, observation: Observation) -> int | float | str | None:
    value = observation.value
    if ref.declared_type == "int":
        return value if type(value) is int else None
    if ref.declared_type in {"float", "double"}:
        if type(value) not in {int, float} or not math.isfinite(cast(int | float, value)):
            return None
        return float(cast(int | float, value))
    if type(value) is str:
        return value
    if isinstance(value, bytes):
        try:
            return value.decode(cast(str, ref.encoding))
        except (LookupError, UnicodeDecodeError):
            return None
    return None


class CaptureRunner:
    """Own one complete capture lifecycle and its terminal evidence."""

    def __init__(
        self,
        *,
        request: CaptureRequest,
        request_sha256: str,
        provenance: SourceProvenance,
        stop_file: Path | None,
        transport_factory: Callable[[], CaptureTransport],
        event_writer: CaptureEventWriter,
        status_writer: AtomicStatusWriter,
        clock: CaptureClock,
        events_path: Path,
        interruption: CaptureInterruption,
    ) -> None:
        self._request = request
        self._request_sha256 = request_sha256
        self._provenance = provenance
        self._stop_file = stop_file
        self._transport_factory = transport_factory
        self._event_writer = event_writer
        self._status_writer = status_writer
        self._clock = clock
        self._events_path = events_path
        self._interruption = interruption
        self._state = _RunState(started_monotonic=clock.monotonic())
        self._transport: CaptureTransport | None = None
        self._capabilities: TransportCapabilities | None = None
        self._observation_lock = threading.Lock()
        self._adapter_token = 0

    def run(
        self,
        stop_event: threading.Event,
        interrupted_event: threading.Event,
    ) -> CaptureOutcome:
        """Run capture until a bounded terminal condition is reached."""

        return self._run_with_cleanup(stop_event, interrupted_event)

    def _elapsed(self) -> float:
        return float(max(0.0, self._clock.monotonic() - self._state.started_monotonic))

    def _counters(self) -> CaptureCounters:
        return CaptureCounters(
            sample_count=self._state.sample_count,
            gap_count=self._state.gap_count,
            retry_count=self._state.retry_count,
            accepted_ref_count=len(self._state.capture_accepted_ref_ids),
            rejected_ref_count=len(self._state.capture_rejected_refs),
        )

    def _status_common(self) -> dict[str, object]:
        return {
            "protocol_version": 1,
            "capture_session_id": self._request.capture_session_id,
            "sortie_id": self._request.sortie_id,
            "updated_at_utc": _timestamp(self._clock.utcnow()),
            "elapsed_seconds": self._elapsed(),
            "events_path": str(self._events_path),
            "request_sha256": self._request_sha256,
            "transport": self._request.transport.kind,
            "transport_connection_state": self._state.transport_connection_state,
            "connection_generation": self._state.connection_generation,
            "transport_ready_at_utc": self._state.transport_ready_at_utc,
            "aircraft_ready_at_utc": self._state.aircraft_ready_at_utc,
            "target_aircraft": self._request.identity_readiness.target_aircraft,
            "identity_ref_count": len(self._request.identity_readiness.refs),
            "matched_identity_ref_count": self._state.matched_identity_ref_count,
            "required_capture_ref_count": sum(ref.availability == "required" for ref in self._request.refs),
            "observed_required_ref_count": self._state.observed_required_ref_count,
            "counters": self._counters(),
            "attempt_phase": self._state.attempt_phase,
            "current_attempt": self._state.current_attempt,
            "maximum_attempts": self._state.maximum_attempts,
        }

    def _write_status(
        self,
        state: str,
        *,
        reason: str | None = None,
        deadline: float | None = None,
    ) -> None:
        document = NonterminalStatus.model_validate({**self._status_common(), "state": state, "reason": reason})
        self._status_writer.write(document, deadline=deadline, clock=self._clock.monotonic)
        self._state.current_status = state

    def _set_no_attempt(self) -> None:
        self._state.attempt_phase = "none"
        self._state.current_attempt = 0
        self._state.maximum_attempts = 0

    def _on_observation(self, adapter_token: int, observation: Observation) -> None:
        with self._observation_lock:
            if adapter_token == self._adapter_token:
                self._state.observations[observation.ref_id] = observation

    def _observations(self) -> dict[str, Observation]:
        with self._observation_lock:
            return dict(self._state.observations)

    def _clear_generation_state(self) -> None:
        with self._observation_lock:
            self._state.observations.clear()
        self._state.identity_accepted_ref_ids.clear()
        self._state.identity_rejected_refs.clear()
        self._state.capture_accepted_ref_ids.clear()
        self._state.capture_rejected_refs.clear()
        self._state.matched_identity_ref_count = 0
        self._state.observed_required_ref_count = 0

    def _write_started(self) -> None:
        self._event_writer.write(
            CaptureStartedInput(
                event="capture_started",
                request_sha256=self._request_sha256,
                correlation=self._request.correlation,
                transport=self._request.transport,
                provenance=self._provenance,
            )
        )

    def _write_transport_ready(self) -> None:
        capabilities = self._require_capabilities()
        self._event_writer.write(
            TransportReadyInput(
                event="transport_ready",
                connection_generation=self._state.connection_generation,
                endpoint=capabilities.endpoint,
                read_only=True,
                package_version=self._provenance.package_version,
                git_revision=self._provenance.git_revision,
                git_dirty=self._provenance.git_dirty,
                capabilities=capabilities,
            )
        )

    def _require_capabilities(self) -> TransportCapabilities:
        if self._capabilities is None:
            raise _CaptureFailure("transport capabilities are unavailable")
        return self._capabilities

    def _open_timeout(self) -> float:
        transport = self._request.transport
        return transport.open_timeout_seconds if transport.kind == "websocket" else transport.beacon_timeout_seconds

    def _close_transport(self, deadline: float) -> None:
        transport = self._transport
        self._transport = None
        self._adapter_token += 1
        if transport is not None:
            transport.close(deadline)

    def _create_transport(self) -> CaptureTransport:
        self._adapter_token += 1
        return self._transport_factory()

    def _emit_retry(self, phase: Literal["initial_connect", "reconnect"], attempt: int, maximum: int, reason: str) -> float:
        failure_index = attempt - 1
        delay = min(
            self._request.retry.backoff_seconds * 2**failure_index,
            self._request.retry.backoff_max_seconds,
        )
        self._state.retry_count += 1
        self._event_writer.write(
            RetryInput(
                event="retry",
                phase=phase,
                attempt=attempt,
                maximum_attempts=maximum,
                delay_seconds=float(delay),
                reason=reason,
            )
        )
        return delay

    def _initial_connect(self, stop_event: threading.Event, interrupted_event: threading.Event) -> None:
        maximum = self._request.retry.initial_attempts
        last_error = "initial connection failed"
        for attempt in range(1, maximum + 1):
            if self._observe_termination(stop_event, interrupted_event):
                return
            self._state.attempt_phase = "initial_connect"
            self._state.current_attempt = attempt
            self._state.maximum_attempts = maximum
            self._write_status("connecting")
            deadline = self._clock.monotonic() + self._open_timeout()
            try:
                self._transport = self._create_transport()
                self._capabilities = self._transport.open(deadline)
            except BaseException as exc:
                last_error = _error_text(exc)
                self._best_effort_attempt_close(deadline)
                if self._observe_termination(stop_event, interrupted_event):
                    return
                delay = self._emit_retry("initial_connect", attempt, maximum, last_error)
                if attempt < maximum:
                    if self._wait_for_termination(stop_event, interrupted_event, delay):
                        return
                continue
            if self._observe_termination(stop_event, interrupted_event):
                return
            self._connected_milestone(attempt)
            return
        raise _CaptureFailure(f"initial_connect_exhausted: {last_error}")

    def _best_effort_attempt_close(self, deadline: float) -> None:
        try:
            self._close_transport(deadline)
        except BaseException:
            return

    def _connected_milestone(self, attempt: int) -> None:
        capabilities = self._require_capabilities()
        self._state.connected_attempt = attempt
        self._state.connection_generation += 1
        self._state.transport_connection_state = "connected"
        self._event_writer.write(
            TransportStateInput(
                event="transport_state",
                state="connected",
                attempt=attempt,
                reason=None,
                capabilities=capabilities,
            )
        )
        self._write_transport_ready()
        if self._state.transport_ready_at_utc is None:
            self._state.transport_ready_at_utc = _timestamp(self._clock.utcnow())
        self._set_no_attempt()
        self._write_status("transport_ready")
        self._write_status("awaiting_aircraft")

    def _subscribe(
        self, refs: Sequence[AircraftIdentityRef | CaptureRef], purpose: Literal["aircraft_identity", "capture"], deadline: float
    ) -> SubscriptionResult:
        if self._transport is None:
            raise _CaptureFailure("capture transport is unavailable")
        adapter_token = self._adapter_token
        result = self._transport.subscribe(
            refs,
            purpose,
            lambda observation: self._on_observation(adapter_token, observation),
            deadline,
        )
        self._event_writer.write(
            SubscriptionResultInput(
                event="subscription_result",
                purpose=result.purpose,
                accepted_ref_ids=result.accepted_ref_ids,
                rejected=dict(result.rejected),
                request_id=result.request_id,
            )
        )
        if purpose == "aircraft_identity":
            self._state.identity_accepted_ref_ids.update(result.accepted_ref_ids)
            self._state.identity_rejected_refs.update(result.rejected)
        else:
            self._state.capture_accepted_ref_ids.update(result.accepted_ref_ids)
            self._state.capture_rejected_refs.update(result.rejected)
        return result

    def _identity_observations(self) -> tuple[IdentityObservation, ...] | None:
        observations = self._observations()
        result: list[IdentityObservation] = []
        now = self._clock.monotonic()
        for ref in self._request.identity_readiness.refs:
            observation = observations.get(ref.id)
            if observation is None or not _identity_matches(ref, observation.value):
                self._state.matched_identity_ref_count = len(result)
                return None
            age = now - observation.observed_monotonic
            if age > self._request.retry.stale_after_seconds:
                self._state.matched_identity_ref_count = len(result)
                return None
            normalized = _identity_value(ref, observation.value)
            if normalized is None:
                self._state.matched_identity_ref_count = len(result)
                return None
            result.append(
                IdentityObservation(
                    ref_id=ref.id,
                    path=ref.path,
                    operator=ref.operator,
                    expected_value=ref.expected_value,
                    observed_value=normalized,
                    source_observed_elapsed_seconds=float(observation.observed_monotonic - self._state.started_monotonic),
                    source_age_seconds=float(age),
                )
            )
        self._state.matched_identity_ref_count = len(result)
        return tuple(result)

    def _wait_until(
        self,
        deadline: float,
        predicate: Callable[[], bool],
        stop_event: threading.Event,
        interrupted_event: threading.Event,
        *,
        sample_disconnected: bool = False,
    ) -> bool:
        while True:
            if self._observe_termination(stop_event, interrupted_event):
                return False
            if self._transport is None or self._transport.liveness_state == "disconnected":
                raise _RetryableDisconnect("transport disconnected during readiness")
            if predicate():
                return True
            remaining = deadline - self._clock.monotonic()
            if remaining <= 0:
                return False
            wait_seconds = self._bounded_wait_seconds(deadline, include_group_end=sample_disconnected)
            self._clock.wait(stop_event, wait_seconds)
            if sample_disconnected and not self._sample_disconnected_if_active(stop_event, interrupted_event):
                return False

    def _bounded_deadline(self, duration: float, owning_deadline: float | None) -> float:
        deadline = self._clock.monotonic() + duration
        return deadline if owning_deadline is None else min(deadline, owning_deadline)

    def _establish_aircraft(
        self,
        stop_event: threading.Event,
        interrupted_event: threading.Event,
        owning_deadline: float | None = None,
        *,
        sample_disconnected: bool = False,
    ) -> None:
        identity_deadline = self._bounded_deadline(
            self._request.retry.aircraft_identity_timeout_seconds,
            owning_deadline,
        )
        identity_result = self._subscribe(
            self._request.identity_readiness.refs,
            "aircraft_identity",
            min(
                identity_deadline,
                self._bounded_deadline(self._request.retry.subscription_timeout_seconds, owning_deadline),
            ),
        )
        if sample_disconnected:
            if not self._sample_disconnected_if_active(stop_event, interrupted_event):
                return
        elif self._observe_termination(stop_event, interrupted_event):
            return
        if identity_result.rejected:
            raise _CaptureFailure("aircraft_identity_subscription_rejected")
        if self._transport is not None:
            self._state.transport_connection_state = self._transport.liveness_state
        if not self._wait_until(
            identity_deadline,
            lambda: self._identity_observations() is not None,
            stop_event,
            interrupted_event,
            sample_disconnected=sample_disconnected,
        ):
            if self._state.finished:
                return
            raise _CaptureFailure("aircraft_identity_timeout")

        self._write_status("subscribing")
        capture_subscription_started = self._clock.monotonic()
        capture_deadline = self._bounded_deadline(
            self._request.retry.subscription_timeout_seconds,
            owning_deadline,
        )
        result = self._subscribe(self._request.refs, "capture", capture_deadline)
        if sample_disconnected:
            if not self._sample_disconnected_if_active(stop_event, interrupted_event):
                return
        elif self._observe_termination(stop_event, interrupted_event):
            return
        required_ids = {ref.id for ref in self._request.refs if ref.availability == "required"}
        rejected_required = required_ids.intersection(result.rejected)
        if rejected_required:
            raise _CaptureFailure(f"required capture refs rejected: {sorted(rejected_required)!r}")

        self._write_status("awaiting_first_values")
        first_values_deadline = self._bounded_deadline(
            self._request.retry.first_values_timeout_seconds,
            owning_deadline,
        )

        def required_values_ready() -> bool:
            observations = self._observations()
            now = self._clock.monotonic()
            observed = {
                ref_id
                for ref_id in required_ids
                if ref_id in observations
                and observations[ref_id].observed_monotonic >= capture_subscription_started
                and now - observations[ref_id].observed_monotonic <= self._request.retry.stale_after_seconds
            }
            self._state.observed_required_ref_count = len(observed)
            return observed == required_ids

        if not self._wait_until(
            first_values_deadline,
            required_values_ready,
            stop_event,
            interrupted_event,
            sample_disconnected=sample_disconnected,
        ):
            if self._state.finished:
                return
            raise _CaptureFailure("first_values_timeout")
        self._aircraft_ready(result)

    def _aircraft_ready(self, capture_result: SubscriptionResult) -> None:
        now = self._clock.monotonic()
        identity = self._identity_observations()
        if identity is None:
            raise _CaptureFailure("aircraft_identity_lost")
        required_ids = tuple(ref.id for ref in self._request.refs if ref.availability == "required")
        observations = self._observations()
        optional_missing = tuple(
            ref.id for ref in self._request.refs if ref.availability == "optional" and (ref.id not in observations or ref.id in capture_result.rejected)
        )
        ready_elapsed = self._elapsed()
        self._event_writer.write(
            AircraftReadyInput(
                event="aircraft_ready",
                connection_generation=self._state.connection_generation,
                target_aircraft=self._request.identity_readiness.target_aircraft,
                identity_observations=identity,
                required_ref_ids=required_ids,
                optional_missing_ref_ids=optional_missing,
                ready_elapsed_seconds=ready_elapsed,
            )
        )
        if self._state.aircraft_ready_at_utc is None:
            self._state.aircraft_ready_at_utc = _timestamp(self._clock.utcnow())
            self._state.aircraft_ready_monotonic = now
            self._build_schedules(now)
        self._write_status("aircraft_ready")
        self._write_status("capturing")

    def _build_schedules(self, ready_monotonic: float) -> None:
        refs_by_group: dict[str, list[CaptureRef]] = {}
        for ref in self._request.refs:
            refs_by_group.setdefault(ref.sample_group_id, []).append(ref)
        schedules: list[_GroupSchedule] = []
        for group in self._request.sample_groups:
            refs = tuple(refs_by_group.get(group.id, ()))
            if not refs or not any(ref.id in self._state.capture_accepted_ref_ids for ref in refs):
                continue
            schedules.append(
                _GroupSchedule(
                    group=group,
                    refs=refs,
                    interval=1.0 / group.rate_hz,
                    next_deadline=ready_monotonic,
                )
            )
        self._state.schedules = schedules
        self._state.schedules_initialized = True

    def _sample_input(self, group_id: str, ref: CaptureRef, now: float, *, disconnected: bool = False) -> SampleInput:
        observation = self._observations().get(ref.id)
        source_elapsed: float | None = None
        source_age: float | None = None
        if observation is not None:
            source_elapsed = float(observation.observed_monotonic - self._state.started_monotonic)
            source_age = float(max(0.0, now - observation.observed_monotonic))
        status: AnySampleStatus
        value: int | float | str | None = None
        if ref.id in self._state.capture_rejected_refs:
            status = "unsupported"
        elif disconnected:
            status = "disconnected"
        elif observation is None:
            status = "missing"
        elif cast(float, source_age) > self._request.retry.stale_after_seconds:
            status = "stale"
        else:
            value = _normalized_sample(ref, observation)
            status = "sampled" if value is not None else "invalid"
        if status == "missing":
            source_elapsed = None
            source_age = None
        return SampleInput(
            event="sample",
            sample_group_id=group_id,
            ref_id=ref.id,
            path=ref.path,
            declared_type=ref.declared_type,
            status=status,
            value=value,
            source_observed_elapsed_seconds=source_elapsed,
            source_age_seconds=source_age,
        )

    def _write_sample_group(self, schedule: _GroupSchedule, now: float, *, disconnected: bool = False) -> None:
        for ref in schedule.refs:
            self._event_writer.write(self._sample_input(schedule.group.id, ref, now, disconnected=disconnected))
            self._state.sample_count += 1

    def _active_schedules(self, now: float) -> list[_GroupSchedule]:
        ready = self._state.aircraft_ready_monotonic
        if ready is None:
            return []
        return [schedule for schedule in self._state.schedules if schedule.group.duration_seconds is None or now - ready < schedule.group.duration_seconds]

    def _write_cadence_gap(self, schedule: _GroupSchedule, now: float, skipped: int) -> None:
        affected = tuple(ref.id for ref in schedule.refs)
        start = schedule.next_deadline
        reason = "scheduler_late"
        self._event_writer.write(
            GapStartedInput(
                event="gap_started",
                reason=reason,
                affected_ref_ids=affected,
                gap_start_elapsed_seconds=float(start - self._state.started_monotonic),
            )
        )
        self._event_writer.write(
            GapEndedInput(
                event="gap_ended",
                reason=reason,
                affected_ref_ids=affected,
                gap_start_elapsed_seconds=float(start - self._state.started_monotonic),
                gap_duration_seconds=float(max(0.0, now - start)),
                skipped_slot_count=skipped,
            )
        )
        self._state.gap_count += 1

    def _sample_due(self, now: float, *, disconnected: bool = False) -> None:
        for schedule in self._active_schedules(now):
            if now < schedule.next_deadline:
                continue
            if now >= schedule.next_deadline + schedule.interval:
                skipped = int((now - schedule.next_deadline) // schedule.interval)
                if skipped:
                    self._write_cadence_gap(schedule, now, skipped)
                    schedule.next_deadline += skipped * schedule.interval
            self._write_sample_group(schedule, now, disconnected=disconnected)
            schedule.next_deadline += schedule.interval

    def _sample_disconnected_if_active(
        self,
        stop_event: threading.Event,
        interrupted_event: threading.Event,
    ) -> bool:
        if self._observe_termination(
            stop_event,
            interrupted_event,
            allow_groups_complete=self._state.schedules_initialized,
        ):
            return False
        self._sample_due(self._clock.monotonic(), disconnected=True)
        return True

    def _identity_is_fresh(self) -> bool:
        return self._identity_observations() is not None

    def _termination(
        self,
        stop_event: threading.Event,
        interrupted_event: threading.Event,
        now: float,
        *,
        allow_groups_complete: bool,
    ) -> tuple[TerminalState, str] | None:
        if interrupted_event.is_set():
            return "interrupted", self._interruption_name()
        if self._stop_file is not None and self._stop_file.exists():
            return "complete", "stop_file"
        if stop_event.is_set():
            return "complete", "requested"
        ready = self._state.aircraft_ready_monotonic
        if ready is not None and self._request.capture_limit_seconds is not None:
            if now - ready >= self._request.capture_limit_seconds:
                return "complete", "capture_limit"
        if allow_groups_complete and ready is not None and not self._active_schedules(now):
            return "complete", "groups_complete"
        return None

    def _observe_termination(
        self,
        stop_event: threading.Event,
        interrupted_event: threading.Event,
        *,
        allow_groups_complete: bool = False,
    ) -> bool:
        terminal = self._termination(
            stop_event,
            interrupted_event,
            self._clock.monotonic(),
            allow_groups_complete=allow_groups_complete,
        )
        if terminal is None:
            return False
        self._state.terminal_state, self._state.termination = terminal
        self._state.reason = None if terminal[0] == "complete" else terminal[1]
        self._state.finished = True
        return True

    def _wait_for_termination(
        self,
        stop_event: threading.Event,
        interrupted_event: threading.Event,
        duration: float,
        *,
        sample_disconnected: bool = False,
    ) -> bool:
        deadline = self._clock.monotonic() + duration
        while True:
            if self._observe_termination(
                stop_event,
                interrupted_event,
                allow_groups_complete=sample_disconnected and self._state.schedules_initialized,
            ):
                return True
            remaining = deadline - self._clock.monotonic()
            if remaining <= 0:
                return False
            wait_seconds = self._bounded_wait_seconds(deadline, include_group_end=sample_disconnected)
            self._clock.wait(stop_event, wait_seconds)
            if sample_disconnected and not self._sample_disconnected_if_active(stop_event, interrupted_event):
                return True

    def _bounded_wait_seconds(self, deadline: float, *, include_group_end: bool) -> float:
        now = self._clock.monotonic()
        wait_deadline = min(deadline, now + self._request.retry.poll_interval_seconds)
        if include_group_end:
            group_end = self._earliest_future_group_end(now)
            if group_end is not None:
                wait_deadline = min(wait_deadline, group_end)
        return max(0.0, wait_deadline - now)

    def _earliest_future_group_end(self, now: float) -> float | None:
        ready = self._state.aircraft_ready_monotonic
        if not self._state.schedules_initialized or ready is None:
            return None
        group_ends = (
            ready + schedule.group.duration_seconds
            for schedule in self._state.schedules
            if schedule.group.duration_seconds is not None and ready + schedule.group.duration_seconds > now
        )
        return min(group_ends, default=None)

    def _next_wait(self, now: float) -> float:
        deadlines = [now + self._request.retry.poll_interval_seconds]
        ready = self._state.aircraft_ready_monotonic
        for schedule in self._active_schedules(now):
            deadlines.append(schedule.next_deadline)
            if schedule.group.duration_seconds is not None and ready is not None:
                deadlines.append(ready + schedule.group.duration_seconds)
        if ready is not None and self._request.capture_limit_seconds is not None:
            deadlines.append(ready + self._request.capture_limit_seconds)
        return max(0.0, min(deadlines) - now)

    def _capture_loop(self, stop_event: threading.Event, interrupted_event: threading.Event) -> None:
        while True:
            now = self._clock.monotonic()
            if self._observe_termination(stop_event, interrupted_event, allow_groups_complete=True):
                return
            if self._transport is None:
                self._reconnect(stop_event, interrupted_event)
                continue
            self._state.transport_connection_state = self._transport.liveness_state
            if self._state.transport_connection_state == "disconnected":
                self._reconnect(stop_event, interrupted_event)
                continue
            if not self._identity_is_fresh():
                raise _CaptureFailure("aircraft_identity_lost")
            self._sample_due(now)
            self._clock.wait(stop_event, self._next_wait(now))

    def _start_disconnect_gap(self, reason: str, now: float) -> None:
        affected = tuple(ref.id for ref in self._request.refs)
        self._event_writer.write(
            TransportStateInput(
                event="transport_state",
                state="disconnected",
                attempt=max(1, self._state.connected_attempt),
                reason=reason,
                capabilities=self._require_capabilities(),
            )
        )
        self._event_writer.write(
            GapStartedInput(
                event="gap_started",
                reason=reason,
                affected_ref_ids=affected,
                gap_start_elapsed_seconds=self._elapsed(),
            )
        )
        self._state.gap_count += 1

    def _end_disconnect_gap(self, reason: str, started: float) -> None:
        now = self._clock.monotonic()
        skipped = 0
        for schedule in self._active_schedules(now):
            if now >= schedule.next_deadline + schedule.interval:
                count = int((now - schedule.next_deadline) // schedule.interval)
                skipped = max(skipped, count)
                schedule.next_deadline += count * schedule.interval
        self._event_writer.write(
            GapEndedInput(
                event="gap_ended",
                reason=reason,
                affected_ref_ids=tuple(ref.id for ref in self._request.refs),
                gap_start_elapsed_seconds=float(started - self._state.started_monotonic),
                gap_duration_seconds=float(now - started),
                skipped_slot_count=skipped,
            )
        )

    def _reconnect(self, stop_event: threading.Event, interrupted_event: threading.Event) -> None:
        reason = "transport_disconnected"
        started = self._clock.monotonic()
        self._start_disconnect_gap(reason, started)
        self._state.transport_connection_state = "disconnected"
        self._state.attempt_phase = "reconnect"
        self._state.current_attempt = 1
        self._state.maximum_attempts = self._request.retry.reconnect_attempts
        self._write_status("reconnecting", reason=reason)
        disconnect_deadline = started + self._request.retry.max_disconnect_seconds
        self._best_effort_attempt_close(disconnect_deadline)
        if not self._sample_disconnected_if_active(stop_event, interrupted_event):
            return
        self._clear_generation_state()
        last_error = reason
        for attempt in range(1, self._request.retry.reconnect_attempts + 1):
            if self._observe_termination(
                stop_event,
                interrupted_event,
                allow_groups_complete=self._state.schedules_initialized,
            ):
                return
            if self._clock.monotonic() >= disconnect_deadline:
                raise _CaptureFailure(f"reconnect_disconnect_timeout: {last_error}")
            self._state.attempt_phase = "reconnect"
            self._state.current_attempt = attempt
            self._state.maximum_attempts = self._request.retry.reconnect_attempts
            if attempt > 1:
                self._write_status("reconnecting", reason=last_error)
            try:
                self._transport = self._create_transport()
                open_deadline = min(disconnect_deadline, self._clock.monotonic() + self._open_timeout())
                self._capabilities = self._transport.open(open_deadline)
                if not self._sample_disconnected_if_active(stop_event, interrupted_event):
                    return
                self._connected_milestone(attempt)
                self._establish_aircraft(
                    stop_event,
                    interrupted_event,
                    disconnect_deadline,
                    sample_disconnected=True,
                )
                if self._state.finished:
                    return
            except _CaptureFailure as exc:
                if str(exc) in {"aircraft_identity_timeout", "aircraft_identity_lost"}:
                    self._best_effort_attempt_close(disconnect_deadline)
                    self._clear_generation_state()
                    raise
                last_error = str(exc)
            except BaseException as exc:
                last_error = _error_text(exc)
            else:
                if not self._sample_disconnected_if_active(stop_event, interrupted_event):
                    return
                self._end_disconnect_gap(reason, started)
                return
            if not self._sample_disconnected_if_active(stop_event, interrupted_event):
                return
            self._best_effort_attempt_close(disconnect_deadline)
            self._clear_generation_state()
            delay = self._emit_retry("reconnect", attempt, self._request.retry.reconnect_attempts, last_error)
            remaining = disconnect_deadline - self._clock.monotonic()
            if attempt < self._request.retry.reconnect_attempts and remaining > 0:
                if self._wait_for_termination(
                    stop_event,
                    interrupted_event,
                    min(delay, remaining),
                    sample_disconnected=True,
                ):
                    return
        if self._clock.monotonic() >= disconnect_deadline:
            raise _CaptureFailure(f"reconnect_disconnect_timeout: {last_error}")
        raise _CaptureFailure(f"reconnect_attempts_exhausted: {last_error}")

    def _interrupt(self) -> None:
        signal = self._interruption_name()
        self._state.terminal_state = "interrupted"
        self._state.termination = signal
        self._state.reason = signal
        self._state.finished = True

    def _interruption_name(self) -> InterruptionName:
        signal = self._interruption.get()
        if signal is None:
            raise _CaptureFailure("interrupted event set without a recorded process signal")
        return signal

    def _execute(self, stop_event: threading.Event, interrupted_event: threading.Event) -> None:
        self._write_status("starting")
        self._write_started()
        if self._observe_termination(stop_event, interrupted_event):
            return
        self._initial_connect(stop_event, interrupted_event)
        if self._state.finished:
            return
        try:
            self._establish_aircraft(stop_event, interrupted_event)
        except _RetryableDisconnect:
            self._reconnect(stop_event, interrupted_event)
        if self._state.finished:
            return
        self._capture_loop(stop_event, interrupted_event)

    def _append_cleanup_error(self, failure: str, cleanup: str) -> str:
        return f"{failure}; cleanup: {cleanup}" if failure else cleanup

    def _terminal_input(self) -> CaptureStoppedInput | CaptureFailedInput | CaptureInterruptedInput:
        common = {
            "sample_count": self._state.sample_count,
            "gap_count": self._state.gap_count,
            "retry_count": self._state.retry_count,
        }
        if self._state.terminal_state == "complete":
            return CaptureStoppedInput(event="capture_stopped", termination=cast(AnyTermination, self._state.termination), **common)
        if self._state.terminal_state == "interrupted":
            return CaptureInterruptedInput(
                event="capture_interrupted",
                signal=cast(InterruptionName, self._state.termination),
                **common,
            )
        return CaptureFailedInput(event="capture_failed", reason=self._state.reason or self._state.termination, **common)

    def _terminal_status(self, events_sha256: str, events_size: int) -> StatusDocument:
        common = {
            **self._status_common(),
            "events_sha256": events_sha256,
            "events_size_bytes": events_size,
        }
        if self._state.terminal_state == "complete":
            document = CompleteStatus.model_validate(
                {
                    **common,
                    "state": "complete",
                    "reason": self._state.termination,
                    "exit_code": 0,
                    "clean_shutdown": True,
                }
            )
        elif self._state.terminal_state == "interrupted":
            document = InterruptedStatus.model_validate(
                {
                    **common,
                    "state": "interrupted",
                    "reason": self._state.termination,
                    "exit_code": 130,
                    "clean_shutdown": self._state.clean_shutdown,
                }
            )
        else:
            document = FailedStatus.model_validate(
                {
                    **common,
                    "state": "failed",
                    "reason": self._state.reason or self._state.termination,
                    "exit_code": 3,
                    "clean_shutdown": False,
                }
            )
        return document

    def _record_cleanup_failure(self, failure: str) -> None:
        if self._state.terminal_state == "failed":
            self._state.reason = self._append_cleanup_error(
                self._state.reason or self._state.termination,
                failure,
            )
        else:
            self._state.terminal_state = "failed"
            self._state.termination = "cleanup_failure"
            self._state.reason = failure
        self._state.clean_shutdown = False

    def _record_post_commit_failure(self, failure: str) -> None:
        self._state.reason = self._append_cleanup_error(self._state.reason or "", failure)
        self._state.clean_shutdown = False

    def _abort_terminal_pair(
        self,
        event_prepared: PreparedCaptureClose | None,
        status_prepared: PreparedStatus | None,
        deadline: float,
    ) -> None:
        if status_prepared is not None:
            try:
                self._status_writer.abort(
                    status_prepared,
                    deadline=deadline,
                    clock=self._clock.monotonic,
                )
            except BaseException:
                pass
        if event_prepared is not None:
            try:
                self._event_writer.abort_close(event_prepared)
            except BaseException:
                pass

    def _prepare_terminal_pair(
        self,
        deadline: float,
    ) -> tuple[PreparedCaptureClose, PreparedStatus] | None:
        for _attempt in range(2):
            event_prepared: PreparedCaptureClose | None = None
            status_prepared: PreparedStatus | None = None
            try:
                event_prepared = self._event_writer.prepare_close(self._terminal_input(), deadline)
                terminal_status = self._terminal_status(
                    event_prepared.events_sha256,
                    event_prepared.events_size_bytes,
                )
                status_prepared = self._status_writer.prepare(
                    terminal_status,
                    deadline=deadline,
                    clock=self._clock.monotonic,
                )
                return event_prepared, status_prepared
            except BaseException as exc:
                self._abort_terminal_pair(event_prepared, status_prepared, deadline)
                self._record_cleanup_failure(_error_text(exc))
        return None

    def _terminal_event_was_committed(self, prepared: PreparedCaptureClose) -> bool:
        try:
            return self._event_writer.events_sha256 == prepared.events_sha256 and self._event_writer.events_size_bytes == prepared.events_size_bytes
        except ValueError:
            return False

    def _abandon_event_stream(self, deadline: float) -> None:
        try:
            self._event_writer.abandon(deadline)
        except BaseException as exc:
            self._record_cleanup_failure(_error_text(exc))

    def _commit_terminal_pair(
        self,
        event_prepared: PreparedCaptureClose,
        status_prepared: PreparedStatus,
        deadline: float,
    ) -> None:
        try:
            self._event_writer.commit_close(event_prepared, deadline)
        except BaseException as exc:
            self._abort_terminal_pair(None, status_prepared, deadline)
            failure = _error_text(exc)
            if self._terminal_event_was_committed(event_prepared):
                self._record_post_commit_failure(failure)
            else:
                try:
                    self._event_writer.abort_close(event_prepared)
                except BaseException:
                    pass
                self._record_cleanup_failure(failure)
                self._abandon_event_stream(deadline)
            return
        try:
            self._status_writer.commit(
                status_prepared,
                deadline=deadline,
                clock=self._clock.monotonic,
            )
        except BaseException as exc:
            self._abort_terminal_pair(None, status_prepared, deadline)
            self._record_post_commit_failure(_error_text(exc))
            return
        self._state.current_status = status_prepared.document.state

    def _finalize(self) -> None:
        shutdown_deadline = self._clock.monotonic() + self._request.retry.shutdown_timeout_seconds
        cleanup_failure: str | None = None
        if self._state.current_status is not None and self._state.current_status != "finalizing":
            try:
                self._set_no_attempt()
                self._write_status("finalizing", deadline=shutdown_deadline)
            except BaseException as exc:
                cleanup_failure = _error_text(exc)
        try:
            self._close_transport(shutdown_deadline)
        except BaseException as exc:
            cleanup_failure = self._append_cleanup_error(cleanup_failure or "", _error_text(exc))
        if self._clock.monotonic() >= shutdown_deadline:
            cleanup_failure = self._append_cleanup_error(cleanup_failure or "", "shutdown timeout")
        if cleanup_failure is not None:
            self._record_cleanup_failure(cleanup_failure)
        else:
            self._state.clean_shutdown = self._state.terminal_state in {"complete", "interrupted"}
        prepared = self._prepare_terminal_pair(shutdown_deadline)
        if prepared is not None:
            self._commit_terminal_pair(*prepared, shutdown_deadline)
        else:
            self._abandon_event_stream(shutdown_deadline)

    def _run_with_cleanup(self, stop_event: threading.Event, interrupted_event: threading.Event) -> CaptureOutcome:
        try:
            self._execute(stop_event, interrupted_event)
        except BaseException as exc:
            self._state.terminal_state = "failed"
            self._state.termination = "runtime_failure"
            self._state.reason = str(exc) if isinstance(exc, _CaptureFailure) else _error_text(exc)
        finally:
            self._finalize()
        return CaptureOutcome(
            terminal_state=self._state.terminal_state,
            termination=self._state.termination,
            reason=self._state.reason,
            transport_ready=self._state.transport_ready_at_utc is not None,
            aircraft_ready=self._state.aircraft_ready_at_utc is not None,
            sample_count=self._state.sample_count,
            gap_count=self._state.gap_count,
            retry_count=self._state.retry_count,
            clean_shutdown=self._state.clean_shutdown,
        )
