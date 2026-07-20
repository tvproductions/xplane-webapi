"""Deadline-bounded, read-only transport adapters for capture workers."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

from .beacon import API_XPLANE_VERSION_NAMES, XPBeaconMonitor
from .capture_events import TransportCapabilities
from .capture_protocol import (
    AircraftIdentityRef,
    CaptureRef,
    CaptureRequest,
    UdpCaptureConfig,
    WebsocketCaptureConfig,
)
from .udp import XPUDPAPI
from .ws import CALLBACK_TYPE, XPWebsocketAPI


Purpose = Literal["aircraft_identity", "capture"]
LivenessState = Literal["connected", "awaiting_first_identity_packet", "disconnected"]
Clock = Callable[[], float]
ClientFactory = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class Observation:
    """One transport callback mapped back to its request ref id."""

    ref_id: str
    path: str
    value: object
    observed_monotonic: float


@dataclass(frozen=True, slots=True)
class SubscriptionResult:
    """Accepted and rejected refs from one purpose-specific subscription."""

    purpose: Purpose
    accepted_ref_ids: tuple[str, ...]
    rejected: Mapping[str, str]
    request_id: int | None


class CaptureTransport(Protocol):
    """Narrow network surface exposed to the capture runner."""

    @property
    def liveness_state(self) -> LivenessState:
        return "disconnected"

    @property
    def connected(self) -> bool:
        return False

    def open(self, deadline: float) -> TransportCapabilities:
        raise RuntimeError("CaptureTransport.open must be implemented")

    def subscribe(
        self,
        refs: Sequence[AircraftIdentityRef | CaptureRef],
        purpose: Purpose,
        callback: Callable[[Observation], None],
        deadline: float,
    ) -> SubscriptionResult:
        raise RuntimeError("CaptureTransport.subscribe must be implemented")

    def close(self, deadline: float) -> None:
        raise RuntimeError("CaptureTransport.close must be implemented")


def _remaining(deadline: float, clock: Clock) -> float:
    remaining = deadline - clock()
    if remaining <= 0:
        raise TimeoutError("capture transport deadline expired")
    return remaining


def _indexed(path: str) -> bool:
    return "[" in path


def _compatible(ref: AircraftIdentityRef | CaptureRef, value_type: str) -> bool:
    indexed = _indexed(ref.path)
    if value_type in {"int_array", "float_array"} and not indexed:
        return False
    if ref.declared_type == "int":
        return value_type == "int" or (indexed and value_type == "int_array")
    if ref.declared_type == "float":
        return value_type in {"float", "double"} or (indexed and value_type == "float_array")
    if ref.declared_type == "double":
        return value_type in {"double", "float"}
    return value_type == "data"


def _identity_matches(ref: AircraftIdentityRef, value: object) -> bool:
    observed = value
    if ref.declared_type == "string" and isinstance(value, bytes):
        try:
            observed = value.decode(cast(str, ref.encoding)).replace("\x00", "")
        except (LookupError, UnicodeDecodeError):
            return False
    if ref.operator == "contains":
        return isinstance(observed, str) and cast(str, ref.expected_value) in observed
    if ref.declared_type == "int":
        return type(observed) is int and observed == ref.expected_value
    if ref.declared_type in {"float", "double"}:
        if type(observed) not in {int, float}:
            return False
        return float(cast(int | float, observed)) == ref.expected_value
    return type(observed) is str and observed == ref.expected_value


class _TransportBase:
    def __init__(self, request: CaptureRequest, clock: Clock) -> None:
        self._request = request
        self._clock = clock
        self._identity_refs = {ref.path: ref for ref in request.identity_readiness.refs}
        self._identity_matches_at: dict[str, float] = {}
        self._callbacks: dict[str, Callable[[Observation], None]] = {}
        self._refs_by_path: dict[str, AircraftIdentityRef | CaptureRef] = {}
        self._datarefs: dict[str, Any] = {}
        self._closed = False

    def _capture_allowed(self) -> bool:
        now = self._clock()
        stale_after = self._request.retry.stale_after_seconds
        return all(now - self._identity_matches_at.get(path, float("-inf")) <= stale_after for path in self._identity_refs)

    def _require_capture_allowed(self, purpose: Purpose) -> None:
        if purpose == "capture" and not self._capture_allowed():
            raise RuntimeError("capture refs require fresh matching aircraft identity observations")

    def _record_observation(self, path: str, value: object) -> bool:
        ref = self._refs_by_path.get(path)
        callback = self._callbacks.get(path)
        if ref is None or callback is None:
            return False
        observed_at = self._clock()
        identity_ref = self._identity_refs.get(path)
        if identity_ref is not None:
            if _identity_matches(identity_ref, value):
                self._identity_matches_at[path] = observed_at
            else:
                self._identity_matches_at.pop(path, None)
        callback(Observation(ref_id=ref.id, path=path, value=value, observed_monotonic=observed_at))
        return True


class _WebsocketCaptureTransport(_TransportBase):
    def __init__(self, request: CaptureRequest, client_factory: ClientFactory, clock: Clock) -> None:
        super().__init__(request, clock)
        self._config = cast(WebsocketCaptureConfig, request.transport)
        self._client_factory = client_factory
        self._client: Any | None = None
        self._feedback: dict[int, Mapping[str, object]] = {}
        self._feedback_condition = threading.Condition()
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected and self._client is not None and bool(self._client.connected)

    @property
    def liveness_state(self) -> LivenessState:
        return "connected" if self.connected else "disconnected"

    def _on_feedback(self, request_id: int, payload: Mapping[str, object]) -> None:
        with self._feedback_condition:
            self._feedback[request_id] = payload
            self._feedback_condition.notify_all()

    def _on_close(self, **_kwargs: object) -> None:
        self._connected = False

    def _on_dataref(self, dataref: str, value: object) -> None:
        self._record_observation(dataref, value)

    def open(self, deadline: float) -> TransportCapabilities:
        remaining = _remaining(deadline, self._clock)
        self._client = self._client_factory(
            host=self._config.host,
            port=self._config.port,
            api=self._config.api_path,
            api_version=self._config.api_version,
            use_rest=False,
            retry_attempts=1,
            retry_backoff=0.0,
            retry_backoff_max=0.0,
            http_timeout=min(self._config.http_timeout_seconds, remaining),
            open_timeout=min(self._config.open_timeout_seconds, remaining),
            close_timeout=min(self._config.close_timeout_seconds, remaining),
            read_only=True,
        )
        self._client.set_callback(CALLBACK_TYPE.ON_DATAREF_UPDATE, self._on_dataref)
        self._client.set_callback(CALLBACK_TYPE.ON_REQUEST_FEEDBACK, self._on_feedback)
        self._client.set_callback(CALLBACK_TYPE.ON_CLOSE, self._on_close)
        remaining = _remaining(deadline, self._clock)
        self._client.open_timeout = min(self._config.open_timeout_seconds, remaining)
        self._client.close_timeout = min(self._config.close_timeout_seconds, remaining)
        self._client.connect_websocket()
        if not self._client.connected:
            raise ConnectionError("WebSocket capture endpoint did not connect")
        self._connected = True
        endpoint = f"ws://{self._config.host}:{self._config.port}{self._config.api_path}/{self._config.api_version}"
        return TransportCapabilities(
            transport="websocket",
            endpoint=endpoint,
            xplane_version=getattr(self._client, "xp_version", None),
            value_types=("int", "float", "double", "string"),
        )

    def _prepare_refs(
        self,
        refs: Sequence[AircraftIdentityRef | CaptureRef],
        callback: Callable[[Observation], None],
        deadline: float,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        if self._client is None:
            raise RuntimeError("capture transport is not open")
        accepted: dict[str, Any] = {}
        rejected: dict[str, str] = {}
        for ref in refs:
            _remaining(deadline, self._clock)
            dataref = self._client.dataref(ref.path, auto_save=False)
            meta = dataref.meta
            if meta is None:
                rejected[ref.id] = "dataref metadata unavailable"
                continue
            if not _compatible(ref, meta.value_type):
                rejected[ref.id] = f"incompatible dataref type {meta.value_type!r}"
                continue
            accepted[ref.path] = dataref
            self._refs_by_path[ref.path] = ref
            self._callbacks[ref.path] = callback
        return accepted, rejected

    def _feedback_for(self, request_id: int, deadline: float) -> Mapping[str, object] | None:
        feedback_deadline = min(deadline, self._clock() + self._request.retry.subscription_timeout_seconds)
        with self._feedback_condition:
            while request_id not in self._feedback:
                remaining = feedback_deadline - self._clock()
                if remaining <= 0:
                    return None
                self._feedback_condition.wait(timeout=remaining)
            return self._feedback.pop(request_id)

    def subscribe(
        self,
        refs: Sequence[AircraftIdentityRef | CaptureRef],
        purpose: Purpose,
        callback: Callable[[Observation], None],
        deadline: float,
    ) -> SubscriptionResult:
        _remaining(deadline, self._clock)
        self._require_capture_allowed(purpose)
        prepared, rejected = self._prepare_refs(refs, callback, deadline)
        if not prepared:
            return SubscriptionResult(purpose, (), rejected, None)
        if self._client is None:
            raise RuntimeError("capture transport is not open")
        _remaining(deadline, self._clock)
        self._client.start(release=True)
        _remaining(deadline, self._clock)
        request_id, _effective = self._client.monitor_datarefs(prepared, reason=purpose)
        if type(request_id) is not int:
            failed = {ref.id: "subscription request failed" for ref in refs if ref.id not in rejected}
            return SubscriptionResult(purpose, (), rejected | failed, None)
        feedback = self._feedback_for(request_id, deadline)
        if feedback is None:
            reason = "subscription feedback timeout"
        elif feedback.get("success") is not True:
            reason = "subscription feedback failed"
        else:
            reason = ""
        if reason:
            failed = {ref.id: reason for ref in refs if ref.id not in rejected}
            return SubscriptionResult(purpose, (), rejected | failed, request_id)
        accepted_ids = tuple(ref.id for ref in refs if ref.id not in rejected)
        self._datarefs.update(prepared)
        return SubscriptionResult(purpose, accepted_ids, rejected, request_id)

    def close(self, deadline: float) -> None:
        if self._closed:
            return
        if self._client is None:
            self._closed = True
            return
        if self._datarefs:
            _remaining(deadline, self._clock)
            self._client.unmonitor_datarefs(self._datarefs, reason="capture_close")
        remaining = _remaining(deadline, self._clock)
        self._client.stop(timeout_seconds=min(self._request.retry.shutdown_timeout_seconds, remaining))
        _remaining(deadline, self._clock)
        self._client.disconnect_websocket()
        _remaining(deadline, self._clock)
        close = getattr(self._client, "close", None)
        if close is not None:
            close()
        else:
            self._client.session.close()
        self._connected = False
        self._closed = True


class _UdpCaptureTransport(_TransportBase):
    def __init__(
        self,
        request: CaptureRequest,
        client_factory: ClientFactory,
        beacon_factory: ClientFactory,
        clock: Clock,
    ) -> None:
        super().__init__(request, clock)
        self._config = cast(UdpCaptureConfig, request.transport)
        self._client_factory = client_factory
        self._beacon_factory = beacon_factory
        self._client: Any | None = None
        self._monitor: Any | None = None
        self._beacon_data: Any | None = None
        self._identity_deadline: float | None = None
        self._last_valid_rref_monotonic: float | None = None
        self._configured_paths: set[str] = set()

    @property
    def liveness_state(self) -> LivenessState:
        now = self._clock()
        if self._last_valid_rref_monotonic is not None:
            return "connected" if now - self._last_valid_rref_monotonic <= self._config.liveness_timeout_seconds else "disconnected"
        if self._identity_deadline is not None and now <= self._identity_deadline:
            return "awaiting_first_identity_packet"
        return "disconnected"

    @property
    def connected(self) -> bool:
        return self.liveness_state == "connected"

    def _on_dataref(self, dataref: str, value: object) -> None:
        if dataref not in self._configured_paths:
            return
        if self._last_valid_rref_monotonic is not None or dataref in self._identity_refs:
            self._last_valid_rref_monotonic = self._clock()
        self._record_observation(dataref, value)

    def open(self, deadline: float) -> TransportCapabilities:
        remaining = _remaining(deadline, self._clock)
        self._monitor = self._beacon_factory(retry_attempts=1, retry_backoff=0.0, retry_backoff_max=0.0)
        remaining = _remaining(deadline, self._clock)
        self._beacon_data = self._monitor.get_beacon(timeout=min(self._config.beacon_timeout_seconds, remaining))
        if self._beacon_data is None:
            raise ConnectionError("UDP capture endpoint beacon was not found")
        self._client = self._client_factory(
            beacon=self._monitor,
            host=self._beacon_data.host,
            port=self._beacon_data.port,
            read_only=True,
        )
        remaining = _remaining(deadline, self._clock)
        self._client.socket.settimeout(min(self._config.socket_timeout_seconds, remaining))
        self._client.add_callback(self._on_dataref)
        version = API_XPLANE_VERSION_NAMES.get(self._beacon_data.xplane_version, str(self._beacon_data.xplane_version))
        return TransportCapabilities(
            transport="udp",
            endpoint=f"udp://{self._beacon_data.host}:{self._beacon_data.port}",
            xplane_version=version,
            value_types=("float",),
        )

    def _rate_for(self, ref: AircraftIdentityRef | CaptureRef) -> int:
        if isinstance(ref, AircraftIdentityRef):
            return int(ref.rate_hz)
        groups = {group.id: group for group in self._request.sample_groups}
        return int(groups[ref.sample_group_id].rate_hz)

    def subscribe(
        self,
        refs: Sequence[AircraftIdentityRef | CaptureRef],
        purpose: Purpose,
        callback: Callable[[Observation], None],
        deadline: float,
    ) -> SubscriptionResult:
        _remaining(deadline, self._clock)
        self._require_capture_allowed(purpose)
        if self._client is None:
            raise RuntimeError("capture transport is not open")
        accepted: list[str] = []
        rejected: dict[str, str] = {}
        for ref in refs:
            _remaining(deadline, self._clock)
            dataref = self._client.dataref(ref.path, auto_save=False)
            result = self._client.monitor_dataref(dataref, frequency_hz=self._rate_for(ref))
            if result is False:
                rejected[ref.id] = "UDP subscription failed"
                continue
            accepted.append(ref.id)
            self._datarefs[ref.path] = dataref
            self._refs_by_path[ref.path] = ref
            self._callbacks[ref.path] = callback
            self._configured_paths.add(ref.path)
        if purpose == "aircraft_identity" and accepted:
            self._identity_deadline = deadline
        if accepted:
            _remaining(deadline, self._clock)
            self._client.start(release=True)
        return SubscriptionResult(purpose, tuple(accepted), rejected, None)

    def close(self, deadline: float) -> None:
        if self._closed:
            return
        if self._client is not None:
            if self._datarefs:
                _remaining(deadline, self._clock)
                self._client.unmonitor_datarefs(self._datarefs, reason="capture_close")
            remaining = _remaining(deadline, self._clock)
            self._client.stop(timeout_seconds=min(self._request.retry.shutdown_timeout_seconds, remaining))
            _remaining(deadline, self._clock)
            self._client.close()
        if self._monitor is not None:
            _remaining(deadline, self._clock)
            self._monitor.stop_monitor()
        self._closed = True


def create_capture_transport(
    request: CaptureRequest,
    *,
    client_factory: ClientFactory | None = None,
    beacon_factory: ClientFactory | None = None,
    clock: Clock = time.monotonic,
) -> CaptureTransport:
    """Create a fresh transport and client owner for one connection generation."""

    if isinstance(request.transport, WebsocketCaptureConfig):
        return _WebsocketCaptureTransport(request, client_factory or XPWebsocketAPI, clock)
    return _UdpCaptureTransport(request, client_factory or XPUDPAPI, beacon_factory or XPBeaconMonitor, clock)
