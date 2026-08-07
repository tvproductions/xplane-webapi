"""Read-only live and synthetic sample-source composition for FDR recording."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any, Protocol

from ..capture_protocol import CaptureRef, WebsocketCaptureConfig
from ..capture_transport import CaptureTransport, Observation, create_observation_transport
from .models import FDRHeader, FDRSample


MonotonicClock = Callable[[], float]
UTCClock = Callable[[], datetime]
Wait = Callable[[threading.Event, float], bool]

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
    """Destination accepting validated FDR model samples."""

    def write_sample(self, sample: FDRSample) -> None: ...


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
        self._header = header
        self._config = config
        self._monotonic_clock = monotonic_clock
        self._utc_clock = utc_clock
        self._wait = wait
        self._values: dict[str, float] = {}
        self._values_lock = threading.Lock()
        self._required_values_ready = threading.Event()
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
            self._await_initial_values()
            self._freeze_effective_header()
        except BaseException:
            self._close_after_failure()
            raise

    def _await_initial_values(self) -> None:
        deadline = self._monotonic_clock() + self._first_values_timeout_seconds
        while not self._required_values_ready.is_set():
            remaining = deadline - self._monotonic_clock()
            if remaining <= 0:
                with self._values_lock:
                    missing = tuple(ref_id for ref_id in _MANDATORY_IDS if ref_id not in self._values)
                raise RuntimeError(f"required FDR initial values readiness deadline expired: {', '.join(missing)}")
            self._wait(self._required_values_ready, min(_READINESS_POLL_SECONDS, remaining))

    def _freeze_effective_header(self) -> None:
        with self._values_lock:
            observed_datarefs = tuple(dataref for dataref in self._header.datarefs if dataref.path in self._values)
            self._header = replace(self._header, datarefs=observed_datarefs)
            self._active_ref_ids = frozenset((*_MANDATORY_IDS, *tuple(dataref.path for dataref in observed_datarefs)))

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
            if all(ref_id in self._values for ref_id in _MANDATORY_IDS):
                self._required_values_ready.set()

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
            next_sample_at = self._monotonic_clock() + self._sample_interval_seconds
            yield FDRSourceSample(timestamp_utc=self._utc_clock(), values=values)

    def close(self) -> None:
        """Close the owned read-only observation transport once."""

        if self._closed:
            return
        self._closed = True
        self._transport.close(self._monotonic_clock() + self._config.close_timeout_seconds)
