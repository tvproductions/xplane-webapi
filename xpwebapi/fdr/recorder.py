"""Read-only live and synthetic sample-source composition for FDR recording."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol, cast

from ..capture_protocol import CaptureRef, WebsocketCaptureConfig
from ..capture_transport import CaptureTransport, Observation, create_observation_transport
from .errors import FDRValidationError
from .models import FDRHeader, FDRSample


MonotonicClock = Callable[[], float]
UTCClock = Callable[[], datetime]
Wait = Callable[[threading.Event, float], bool]
FDRRecordTermination = Literal["source_exhausted", "stop_requested", "duration_reached", "keyboard_interrupt"]

_METRES_PER_FOOT = 0.3048
_READINESS_POLL_SECONDS = 0.1
_SAMPLE_GROUP_ID = "fdr-live"

_MANDATORY_REFS = (
    CaptureRef(
        id="longitude",
        path="sim/flightmodel/position/longitude",
        declared_type="double",
        availability="required",
        sample_group_id=_SAMPLE_GROUP_ID,
    ),
    CaptureRef(
        id="latitude",
        path="sim/flightmodel/position/latitude",
        declared_type="double",
        availability="required",
        sample_group_id=_SAMPLE_GROUP_ID,
    ),
    CaptureRef(
        id="altitude_msl_ft",
        path="sim/flightmodel/position/elevation",
        declared_type="double",
        availability="required",
        sample_group_id=_SAMPLE_GROUP_ID,
    ),
    CaptureRef(
        id="heading_magnetic_deg",
        path="sim/cockpit2/gauges/indicators/heading_electric_deg_mag_pilot",
        declared_type="double",
        availability="required",
        sample_group_id=_SAMPLE_GROUP_ID,
    ),
    CaptureRef(
        id="pitch_deg",
        path="sim/cockpit2/gauges/indicators/pitch_electric_deg_pilot",
        declared_type="double",
        availability="required",
        sample_group_id=_SAMPLE_GROUP_ID,
    ),
    CaptureRef(
        id="roll_deg",
        path="sim/cockpit2/gauges/indicators/roll_electric_deg_pilot",
        declared_type="double",
        availability="required",
        sample_group_id=_SAMPLE_GROUP_ID,
    ),
)
_MANDATORY_IDS = tuple(ref.id for ref in _MANDATORY_REFS)
_MANDATORY_PATHS = frozenset(ref.path for ref in _MANDATORY_REFS)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _wait(stop_event: threading.Event, timeout: float) -> bool:
    return stop_event.wait(timeout)


def _positive_finite(value: float, name: str) -> float:
    if type(value) is not float or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite float")
    return value


@dataclass(frozen=True, slots=True)
class FDRSourceSample:
    """One immutable source snapshot stamped with an absolute UTC instant."""

    timestamp_utc: datetime
    values: Mapping[str, float]

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp_utc, datetime) or self.timestamp_utc.utcoffset() != timedelta(0):
            raise ValueError("timestamp_utc must be an aware UTC datetime")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


class FDRSampleSource(Protocol):
    """Source of immutable timestamped value snapshots."""

    @property
    def header(self) -> FDRHeader: ...

    def samples(self, stop_event: threading.Event) -> Iterator[FDRSourceSample]: ...

    def close(self) -> None: ...


class FDRSampleSink(Protocol):
    """Lifecycle-managed destination accepting validated FDR samples."""

    @property
    def destination_path(self) -> Path | None: ...

    @property
    def partial_path(self) -> Path | None: ...

    def write_sample(self, sample: FDRSample) -> None: ...

    def commit(self) -> None: ...

    def abort(self) -> None: ...


@dataclass(frozen=True, slots=True)
class FDRRecordResult:
    """Successful immutable recording-session outcome."""

    sample_count: int
    started_at_utc: datetime
    ended_at_utc: datetime
    duration: timedelta
    termination: FDRRecordTermination
    partial_path: Path | None
    final_path: Path | None


@dataclass(slots=True)
class _RecordingProgress:
    sample_count: int = 0
    first_sample_at: datetime | None = None
    last_sample_at: datetime | None = None
    termination: FDRRecordTermination = "source_exhausted"


class _RecordingStopEvent(threading.Event):
    """Event view that combines a caller request with a monotonic deadline."""

    def __init__(
        self,
        requested: threading.Event,
        *,
        monotonic_clock: MonotonicClock,
        deadline: float | None,
    ) -> None:
        super().__init__()
        self._requested = requested
        self._monotonic_clock = monotonic_clock
        self._deadline = deadline

    @property
    def duration_reached(self) -> bool:
        return self._deadline is not None and self._monotonic_clock() >= self._deadline

    def is_set(self) -> bool:
        return super().is_set() or self._requested.is_set() or self.duration_reached

    def wait(self, timeout: float | None = None) -> bool:
        if self.is_set():
            return True
        effective_timeout = timeout
        if self._deadline is not None:
            remaining = max(0.0, self._deadline - self._monotonic_clock())
            effective_timeout = remaining if timeout is None else min(timeout, remaining)
        self._requested.wait(effective_timeout)
        return self.is_set()


def _source_number(values: Mapping[str, object], key: str) -> int | float:
    try:
        value = values[key]
    except KeyError as exc:
        raise FDRValidationError(f"source sample is missing required value {key!r}") from exc
    if type(value) is int:
        return value
    if type(value) is not float or not math.isfinite(value):
        raise FDRValidationError(f"source value {key!r} must be a finite int or float")
    return value


def _sample_from_source(header: FDRHeader, source_sample: FDRSourceSample) -> FDRSample:
    values: Mapping[str, object] = source_sample.values
    return FDRSample(
        time_utc=source_sample.timestamp_utc.time(),
        longitude=_source_number(values, "longitude"),
        latitude=_source_number(values, "latitude"),
        altitude_msl_ft=_source_number(values, "altitude_msl_ft"),
        heading_magnetic_deg=_source_number(values, "heading_magnetic_deg"),
        pitch_deg=_source_number(values, "pitch_deg"),
        roll_deg=_source_number(values, "roll_deg"),
        additional_values=tuple(_source_number(values, dataref.path) for dataref in header.datarefs),
        legacy_values=(),
    )


class FDRRecorder:
    """Map source snapshots into a sink and commit only graceful sessions."""

    def __init__(
        self,
        *,
        source: FDRSampleSource,
        sink: FDRSampleSink,
        monotonic_clock: MonotonicClock = time.monotonic,
        cleanup_timeout_seconds: float = 5.0,
        cleanup_wait: Wait = _wait,
    ) -> None:
        if not isinstance(source.header, FDRHeader) or source.header.source_version != 4:
            raise ValueError("FDRRecorder requires a version 4 source header")
        self._source = source
        self._sink = sink
        self._monotonic_clock = monotonic_clock
        self._cleanup_timeout_seconds = _positive_finite(cleanup_timeout_seconds, "cleanup_timeout_seconds")
        self._cleanup_wait = cleanup_wait

    def _bounded_cleanup(self, action: Callable[[], None], label: str) -> None:
        completed = threading.Event()
        failures: list[BaseException] = []

        def run() -> None:
            try:
                action()
            except BaseException as exc:
                failures.append(exc)
            finally:
                completed.set()

        threading.Thread(target=run, name=f"xpwebapi-fdr-{label}", daemon=True).start()
        if not self._cleanup_wait(completed, self._cleanup_timeout_seconds):
            raise TimeoutError(f"{label} cleanup exceeded {self._cleanup_timeout_seconds:g} seconds")
        if failures:
            raise failures[0]

    @staticmethod
    def _raise_failures(failures: list[BaseException]) -> None:
        if len(failures) == 1:
            raise failures[0]
        raise BaseExceptionGroup("FDR recording or cleanup failed", failures)

    def _abort_with(self, failures: list[BaseException]) -> None:
        try:
            self._bounded_cleanup(self._sink.abort, "sink abort")
        except BaseException as exc:
            failures.append(exc)
        self._raise_failures(failures)

    def _map_source_sample(self, progress: _RecordingProgress, source_sample: FDRSourceSample) -> FDRSample:
        if progress.last_sample_at is not None and source_sample.timestamp_utc < progress.last_sample_at:
            raise FDRValidationError("source sample UTC timestamps must not move backwards")
        return _sample_from_source(self._source.header, source_sample)

    def _write_mapped_sample(self, progress: _RecordingProgress, source_sample: FDRSourceSample, sample: FDRSample) -> None:
        self._sink.write_sample(sample)
        progress.sample_count += 1
        progress.first_sample_at = progress.first_sample_at or source_sample.timestamp_utc
        progress.last_sample_at = source_sample.timestamp_utc

    @staticmethod
    def _mark_graceful_interrupt(progress: _RecordingProgress, interrupt: KeyboardInterrupt) -> None:
        if progress.sample_count == 0:
            raise interrupt.with_traceback(interrupt.__traceback__)
        progress.termination = "keyboard_interrupt"

    def _consume_samples(self, recording_stop: _RecordingStopEvent) -> _RecordingProgress:
        progress = _RecordingProgress()
        iterator = iter(self._source.samples(recording_stop))
        while True:
            try:
                if recording_stop.is_set():
                    break
            except KeyboardInterrupt as interrupt:
                self._mark_graceful_interrupt(progress, interrupt)
                break

            try:
                source_sample = next(iterator)
            except StopIteration:
                break
            except KeyboardInterrupt as interrupt:
                self._mark_graceful_interrupt(progress, interrupt)
                break

            try:
                if recording_stop.is_set():
                    break
                sample = self._map_source_sample(progress, source_sample)
            except KeyboardInterrupt as interrupt:
                self._mark_graceful_interrupt(progress, interrupt)
                break
            self._write_mapped_sample(progress, source_sample, sample)
        return progress

    @staticmethod
    def _resolve_termination(
        progress: _RecordingProgress,
        recording_stop: _RecordingStopEvent,
        stop_event: threading.Event,
    ) -> None:
        if progress.termination == "keyboard_interrupt":
            return
        if recording_stop.duration_reached:
            progress.termination = "duration_reached"
        elif stop_event.is_set() or recording_stop.is_set():
            progress.termination = "stop_requested"

    def _commit_result(self, progress: _RecordingProgress) -> FDRRecordResult:
        if progress.sample_count == 0 or progress.first_sample_at is None or progress.last_sample_at is None:
            self._abort_with([FDRValidationError("cannot complete an FDR recording without samples")])
        completed_first_sample_at = cast(datetime, progress.first_sample_at)
        completed_last_sample_at = cast(datetime, progress.last_sample_at)
        try:
            self._sink.commit()
        except BaseException as exc:
            self._abort_with([exc])
        return FDRRecordResult(
            sample_count=progress.sample_count,
            started_at_utc=completed_first_sample_at,
            ended_at_utc=completed_last_sample_at,
            duration=completed_last_sample_at - completed_first_sample_at,
            termination=progress.termination,
            partial_path=None,
            final_path=self._sink.destination_path,
        )

    def record(
        self,
        *,
        stop_event: threading.Event,
        maximum_duration: float | None = None,
    ) -> FDRRecordResult:
        """Record until exhaustion, request, deadline, or graceful interrupt."""

        if not isinstance(stop_event, threading.Event):
            raise TypeError("stop_event must be a threading.Event")
        if maximum_duration is not None:
            maximum_duration = _positive_finite(maximum_duration, "maximum_duration")
        started_monotonic = self._monotonic_clock()
        deadline = None if maximum_duration is None else started_monotonic + maximum_duration
        recording_stop = _RecordingStopEvent(stop_event, monotonic_clock=self._monotonic_clock, deadline=deadline)
        failures: list[BaseException] = []
        progress = _RecordingProgress()

        try:
            progress = self._consume_samples(recording_stop)
            try:
                self._resolve_termination(progress, recording_stop, stop_event)
            except KeyboardInterrupt as interrupt:
                self._mark_graceful_interrupt(progress, interrupt)
        except BaseException as exc:
            failures.append(exc)
        finally:
            try:
                self._bounded_cleanup(self._source.close, "source")
            except BaseException as exc:
                failures.append(exc)

        if failures:
            self._abort_with(failures)
        return self._commit_result(progress)


class LiveFDRSampleSource:
    """Fixed-cadence version 4 snapshots from a read-only WebSocket transport."""

    def __init__(
        self,
        *,
        config: WebsocketCaptureConfig,
        header: FDRHeader,
        sample_interval_seconds: float,
        subscription_timeout_seconds: float,
        first_values_timeout_seconds: float = 30.0,
        client_factory: Callable[..., Any] | None = None,
        monotonic_clock: MonotonicClock = time.monotonic,
        utc_clock: UTCClock = _utc_now,
        wait: Wait = _wait,
    ) -> None:
        if not isinstance(header, FDRHeader) or header.source_version != 4:
            raise ValueError("live FDR sources require a version 4 FDRHeader")
        self._sample_interval_seconds = _positive_finite(sample_interval_seconds, "sample_interval_seconds")
        self._subscription_timeout_seconds = _positive_finite(subscription_timeout_seconds, "subscription_timeout_seconds")
        self._first_values_timeout_seconds = _positive_finite(first_values_timeout_seconds, "first_values_timeout_seconds")
        if any(dataref.path in _MANDATORY_PATHS for dataref in header.datarefs):
            raise ValueError("optional FDR DataRefs must not duplicate mandatory navigation DataRefs")
        if any(dataref.path in _MANDATORY_IDS for dataref in header.datarefs):
            raise ValueError("optional FDR DataRef paths must not collide with mandatory output IDs")
        self._header = header
        self._config = config
        self._monotonic_clock = monotonic_clock
        self._utc_clock = utc_clock
        self._wait = wait
        self._values: dict[str, float] = {}
        self._values_lock = threading.Lock()
        self._initial_values_ready = threading.Event()
        self._expected_initial_ref_ids: tuple[str, ...] | None = None
        self._active_ref_ids: frozenset[str] | None = None
        self._closed = False
        self._transport: CaptureTransport = create_observation_transport(
            config,
            subscription_timeout_seconds=self._subscription_timeout_seconds,
            shutdown_timeout_seconds=config.close_timeout_seconds,
            client_factory=client_factory,
            clock=monotonic_clock,
        )
        self._open_and_subscribe()

    @property
    def header(self) -> FDRHeader:
        """Return the effective header containing only accepted optional DataRefs."""

        return self._header

    def _optional_refs(self) -> tuple[CaptureRef, ...]:
        return tuple(
            CaptureRef(
                id=dataref.path,
                path=dataref.path,
                declared_type="double",
                availability="optional",
                sample_group_id=_SAMPLE_GROUP_ID,
            )
            for dataref in self._header.datarefs
        )

    def _close_after_failure(self) -> None:
        try:
            self.close()
        except BaseException:
            return

    def _open_and_subscribe(self) -> None:
        try:
            self._transport.open(self._monotonic_clock() + max(self._config.http_timeout_seconds, self._config.open_timeout_seconds))
            optional_refs = self._optional_refs()
            result = self._transport.subscribe(
                (*_MANDATORY_REFS, *optional_refs),
                "capture",
                self._record_observation,
                self._monotonic_clock() + self._subscription_timeout_seconds,
            )
            rejected_required = tuple(ref.id for ref in _MANDATORY_REFS if ref.id not in result.accepted_ref_ids)
            if rejected_required:
                raise RuntimeError(f"required FDR DataRefs were rejected: {', '.join(rejected_required)}")
            accepted_ids = frozenset(result.accepted_ref_ids)
            accepted_datarefs = tuple(dataref for dataref in self._header.datarefs if dataref.path in accepted_ids)
            self._header = replace(self._header, datarefs=accepted_datarefs)
            expected_ids = (*_MANDATORY_IDS, *tuple(dataref.path for dataref in accepted_datarefs))
            with self._values_lock:
                self._expected_initial_ref_ids = expected_ids
                self._active_ref_ids = frozenset(expected_ids)
                if all(ref_id in self._values for ref_id in expected_ids):
                    self._initial_values_ready.set()
            self._await_initial_values()
        except BaseException:
            self._close_after_failure()
            raise

    def _await_initial_values(self) -> None:
        deadline = self._monotonic_clock() + self._first_values_timeout_seconds
        while not self._initial_values_ready.is_set():
            remaining = deadline - self._monotonic_clock()
            if remaining <= 0:
                with self._values_lock:
                    expected_ids = self._expected_initial_ref_ids or ()
                    missing = tuple(ref_id for ref_id in expected_ids if ref_id not in self._values)
                raise RuntimeError(f"accepted FDR initial values readiness deadline expired: {', '.join(missing)}")
            self._wait(self._initial_values_ready, min(_READINESS_POLL_SECONDS, remaining))

    def _record_observation(self, observation: Observation) -> None:
        value = observation.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return
        numeric = float(value)
        if observation.ref_id == "altitude_msl_ft":
            numeric /= _METRES_PER_FOOT
        with self._values_lock:
            if self._active_ref_ids is not None and observation.ref_id not in self._active_ref_ids:
                return
            self._values[observation.ref_id] = numeric
            if self._expected_initial_ref_ids is not None and all(ref_id in self._values for ref_id in self._expected_initial_ref_ids):
                self._initial_values_ready.set()

    def _snapshot(self) -> Mapping[str, float]:
        with self._values_lock:
            missing = tuple(ref_id for ref_id in _MANDATORY_IDS if ref_id not in self._values)
            if missing:
                raise RuntimeError(f"required FDR initial values are unavailable: {', '.join(missing)}")
            ordered_ids = (*_MANDATORY_IDS, *tuple(dataref.path for dataref in self._header.datarefs))
            return {ref_id: self._values[ref_id] for ref_id in ordered_ids if ref_id in self._values}

    def samples(self, stop_event: threading.Event) -> Iterator[FDRSourceSample]:
        """Yield latest-value snapshots at the injected fixed cadence."""

        next_sample_at = self._monotonic_clock()
        while not stop_event.is_set():
            remaining = next_sample_at - self._monotonic_clock()
            if remaining > 0 and self._wait(stop_event, remaining):
                break
            if stop_event.is_set():
                break
            values = self._snapshot()
            yield FDRSourceSample(timestamp_utc=self._utc_clock(), values=values)
            if stop_event.is_set():
                break
            next_sample_at += self._sample_interval_seconds
            current_time = self._monotonic_clock()
            while next_sample_at < current_time:
                next_sample_at += self._sample_interval_seconds

    def close(self) -> None:
        """Close the owned read-only observation transport once."""

        if self._closed:
            return
        self._closed = True
        self._transport.close(self._monotonic_clock() + self._config.close_timeout_seconds)
