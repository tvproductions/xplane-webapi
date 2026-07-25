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

    def arm_identity_wait(self, deadline: float | None) -> None:
        """Record the full identity-readiness window after bounded subscription."""

    def close(self, deadline: float) -> None:
        raise RuntimeError("CaptureTransport.close must be implemented")


def _remaining(deadline: float, clock: Clock) -> float:
    remaining = deadline - clock()
    if remaining <= 0:
        raise TimeoutError("capture transport deadline expired")
    return remaining


def _bounded_call[T](
    call: Callable[[], T],
    deadline: float,
    clock: Clock,
    *,
    timeout_message: str,
    interrupt: Callable[[], None] | None = None,
    initiate_on_expiry: bool = False,
) -> T:
    failure: list[BaseException] = []
    result: list[T] = []

    def interrupt_operation() -> None:
        if interrupt is None:
            return
        try:
            interrupt()
        except BaseException:
            return

    def invoke() -> None:
        try:
            result.append(call())
        except BaseException as exc:
            failure.append(exc)

    thread = threading.Thread(target=invoke, name="xpwebapi-capture-bounded-operation", daemon=True)
    try:
        _remaining(deadline, clock)
    except TimeoutError:
        if initiate_on_expiry:
            interrupt_operation()
            thread.start()
        raise TimeoutError(timeout_message) from None
    thread.start()
    try:
        remaining = _remaining(deadline, clock)
    except TimeoutError:
        interrupt_operation()
        raise TimeoutError(timeout_message) from None
    thread.join(remaining)
    if thread.is_alive():
        interrupt_operation()
        raise TimeoutError(timeout_message)
    if failure:
        raise failure[0]
    return result[0]


def _attempt_cleanup(first_failure: BaseException | None, call: Callable[[], None]) -> BaseException | None:
    try:
        call()
    except BaseException as exc:
        return first_failure if first_failure is not None else exc
    return first_failure


@dataclass(frozen=True, slots=True)
class _ShutdownDeadlines:
    unsubscribe: float
    listener_stop: float
    transport_close: float
    owner_close: float


def _shutdown_deadlines(deadline: float, clock: Clock) -> _ShutdownDeadlines:
    now = clock()
    remaining = max(0.0, deadline - now)
    return _ShutdownDeadlines(
        unsubscribe=now + remaining * 0.25,
        listener_stop=now + remaining * 0.50,
        transport_close=now + remaining * 0.75,
        owner_close=now + remaining,
    )


class _DeadlineHttpSession:
    def __init__(self, session: Any, max_timeout: float, deadline: float, clock: Clock) -> None:
        self._session = session
        self._max_timeout = max_timeout
        self._deadline = deadline
        self._clock = clock

    def set_deadline(self, deadline: float) -> None:
        self._deadline = deadline

    def get(self, *args: Any, **kwargs: Any) -> Any:
        remaining = _remaining(self._deadline, self._clock)
        kwargs["timeout"] = min(self._max_timeout, remaining)
        return self._session.get(*args, **kwargs)

    def close(self) -> None:
        self._session.close()


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
        self._matching_identity_paths: set[str] = set()
        self._callbacks: dict[str, Callable[[Observation], None]] = {}
        self._refs_by_path: dict[str, AircraftIdentityRef | CaptureRef] = {}
        self._datarefs: dict[str, Any] = {}
        self._closed = False

    def _capture_allowed(self) -> bool:
        return all(path in self._matching_identity_paths for path in self._identity_refs)

    def _require_capture_allowed(self, purpose: Purpose) -> None:
        if purpose == "capture" and not self._capture_allowed():
            raise RuntimeError("capture refs require matching aircraft identity observations")

    def _subscription_deadline(self, owning_deadline: float) -> float:
        now = self._clock()
        if owning_deadline - now <= 0:
            raise TimeoutError("capture transport deadline expired")
        return min(owning_deadline, now + self._request.retry.subscription_timeout_seconds)

    def _record_observation(self, path: str, value: object, observed_at: float | None = None) -> bool:
        ref = self._refs_by_path.get(path)
        callback = self._callbacks.get(path)
        if ref is None or callback is None:
            return False
        if observed_at is None:
            observed_at = self._clock()
        identity_ref = self._identity_refs.get(path)
        if identity_ref is not None:
            if _identity_matches(identity_ref, value):
                self._matching_identity_paths.add(path)
            else:
                self._matching_identity_paths.discard(path)
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
        self._pending_lock = threading.Lock()
        self._pending_refs: dict[str, tuple[AircraftIdentityRef | CaptureRef, Callable[[Observation], None], Any]] = {}
        self._pending_observations: list[tuple[str, object, float]] = []
        self._cleanup_datarefs: dict[str, Any] = {}
        self._http_session: _DeadlineHttpSession | None = None
        self._abort_lock = threading.Lock()
        self._abort_started = False
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
        with self._pending_lock:
            if dataref in self._pending_refs:
                self._pending_observations.append((dataref, value, self._clock()))
                return
        self._record_observation(dataref, value)

    def _resolve_connect_timeouts(self, deadline: float) -> tuple[float, float]:
        remaining = _remaining(deadline, self._clock)
        return (
            min(self._config.open_timeout_seconds, remaining),
            min(self._config.close_timeout_seconds, remaining),
        )

    def _set_http_deadline(self, deadline: float) -> None:
        if self._http_session is not None:
            self._http_session.set_deadline(deadline)

    def _abort_websocket(self) -> None:
        with self._abort_lock:
            if self._abort_started:
                return
            self._abort_started = True
        if self._client is not None:
            self._client.abort_websocket()

    def _bounded_websocket_call[T](
        self,
        call: Callable[[], T],
        deadline: float,
        operation: str,
        *,
        initiate_on_expiry: bool = False,
    ) -> T:
        return _bounded_call(
            call,
            deadline,
            self._clock,
            timeout_message=f"WebSocket {operation} deadline expired",
            interrupt=self._abort_websocket,
            initiate_on_expiry=initiate_on_expiry,
        )

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
        if hasattr(self._client, "session"):
            self._http_session = _DeadlineHttpSession(
                self._client.session,
                self._config.http_timeout_seconds,
                deadline,
                self._clock,
            )
            self._client.session = self._http_session
        self._client.set_callback(CALLBACK_TYPE.ON_DATAREF_UPDATE, self._on_dataref)
        self._client.set_callback(CALLBACK_TYPE.ON_REQUEST_FEEDBACK, self._on_feedback)
        self._client.set_callback(CALLBACK_TYPE.ON_CLOSE, self._on_close)
        self._client.connect_websocket(timeout_resolver=lambda: self._resolve_connect_timeouts(deadline))
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
        self._set_http_deadline(deadline)
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
        return accepted, rejected

    def _stage_refs(
        self,
        refs: Sequence[AircraftIdentityRef | CaptureRef],
        prepared: Mapping[str, Any],
        callback: Callable[[Observation], None],
    ) -> None:
        refs_by_path = {ref.path: ref for ref in refs}
        with self._pending_lock:
            self._pending_refs = {path: (refs_by_path[path], callback, dataref) for path, dataref in prepared.items()}
            self._pending_observations = []

    def _activate_staged_refs(self) -> None:
        with self._pending_lock:
            for path, (ref, callback, dataref) in self._pending_refs.items():
                self._refs_by_path[path] = ref
                self._callbacks[path] = callback
                self._datarefs[path] = dataref
            observations = tuple(self._pending_observations)
            self._pending_refs = {}
            self._pending_observations = []
        for path, value, observed_at in observations:
            self._record_observation(path, value, observed_at)

    def _discard_staged_refs(self, prepared: Mapping[str, Any], deadline: float) -> None:
        with self._pending_lock:
            self._pending_refs = {}
            self._pending_observations = []
        if self._client is None:
            return
        try:
            self._bounded_websocket_call(
                lambda: self._client.unmonitor_datarefs(prepared, reason="subscription_rollback"),
                deadline,
                "subscription rollback",
            )
        except BaseException:
            self._cleanup_datarefs.update(prepared)

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
        operation_deadline = self._subscription_deadline(deadline)
        self._require_capture_allowed(purpose)
        prepared, rejected = self._prepare_refs(refs, callback, operation_deadline)
        if not prepared:
            return SubscriptionResult(purpose, (), rejected, None)
        if self._client is None:
            raise RuntimeError("capture transport is not open")
        self._stage_refs(refs, prepared, callback)
        self._set_http_deadline(operation_deadline)
        try:
            _remaining(operation_deadline, self._clock)
            self._client.start(release=True)
            request_id, _effective = self._bounded_websocket_call(
                lambda: self._client.monitor_datarefs(prepared, reason=purpose),
                operation_deadline,
                "subscription",
            )
        except BaseException:
            self._discard_staged_refs(prepared, operation_deadline)
            raise
        if type(request_id) is not int:
            self._discard_staged_refs(prepared, operation_deadline)
            failed = {ref.id: "subscription request failed" for ref in refs if ref.id not in rejected}
            return SubscriptionResult(purpose, (), rejected | failed, None)
        feedback = self._feedback_for(request_id, operation_deadline)
        if feedback is None:
            reason = "subscription feedback timeout"
        elif feedback.get("success") is not True:
            reason = "subscription feedback failed"
        else:
            reason = ""
        if reason:
            self._discard_staged_refs(prepared, operation_deadline)
            failed = {ref.id: reason for ref in refs if ref.id not in rejected}
            return SubscriptionResult(purpose, (), rejected | failed, request_id)
        accepted_ids = tuple(ref.id for ref in refs if ref.id not in rejected)
        self._activate_staged_refs()
        return SubscriptionResult(purpose, accepted_ids, rejected, request_id)

    def arm_identity_wait(self, deadline: float | None) -> None:
        del deadline

    def close(self, deadline: float) -> None:
        if self._closed:
            return
        if self._client is None:
            self._closed = True
            return
        phases = _shutdown_deadlines(deadline, self._clock)
        failure: BaseException | None = None
        cleanup_datarefs = self._datarefs | self._cleanup_datarefs
        if cleanup_datarefs:
            failure = _attempt_cleanup(
                failure,
                lambda: self._bounded_websocket_call(
                    lambda: self._client.unmonitor_datarefs(cleanup_datarefs, reason="capture_close"),
                    phases.unsubscribe,
                    "shutdown unsubscribe",
                    initiate_on_expiry=True,
                ),
            )
        failure = _attempt_cleanup(
            failure,
            lambda: self._bounded_websocket_call(
                lambda: self._client.stop(
                    timeout_seconds=min(
                        self._request.retry.shutdown_timeout_seconds,
                        max(0.0, phases.listener_stop - self._clock()),
                    )
                ),
                phases.listener_stop,
                "listener shutdown",
                initiate_on_expiry=True,
            ),
        )
        failure = _attempt_cleanup(
            failure,
            lambda: self._bounded_websocket_call(
                lambda: self._client.disconnect_websocket(
                    timeout_resolver=lambda: min(
                        self._config.close_timeout_seconds,
                        _remaining(phases.transport_close, self._clock),
                    )
                ),
                phases.transport_close,
                "close",
                initiate_on_expiry=True,
            ),
        )
        close = getattr(self._client, "close", None)
        if close is not None:
            close_call = close
        else:
            close_call = self._client.session.close
        failure = _attempt_cleanup(
            failure,
            lambda: self._bounded_websocket_call(
                close_call,
                phases.owner_close,
                "HTTP close",
                initiate_on_expiry=True,
            ),
        )
        self._connected = False
        self._closed = True
        if failure is not None:
            raise failure


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
        self._identity_wait_active = False
        self._last_valid_rref_monotonic: float | None = None
        self._configured_paths: set[str] = set()
        self._abort_lock = threading.Lock()
        self._abort_started = False

    @property
    def liveness_state(self) -> LivenessState:
        now = self._clock()
        if self._last_valid_rref_monotonic is not None:
            return "connected" if now - self._last_valid_rref_monotonic <= self._config.liveness_timeout_seconds else "disconnected"
        if self._identity_wait_active and (self._identity_deadline is None or now < self._identity_deadline):
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

    def _abort_udp(self) -> None:
        with self._abort_lock:
            if self._abort_started:
                return
            self._abort_started = True
        if self._client is not None:
            self._client.abort()

    def _bounded_udp_call[T](
        self,
        call: Callable[[], T],
        deadline: float,
        operation: str,
        *,
        initiate_on_expiry: bool = False,
    ) -> T:
        return _bounded_call(
            call,
            deadline,
            self._clock,
            timeout_message=f"UDP {operation} deadline expired",
            interrupt=self._abort_udp,
            initiate_on_expiry=initiate_on_expiry,
        )

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
        operation_deadline = self._subscription_deadline(deadline)
        self._require_capture_allowed(purpose)
        if self._client is None:
            raise RuntimeError("capture transport is not open")
        accepted: list[str] = []
        rejected: dict[str, str] = {}
        for ref in refs:
            _remaining(operation_deadline, self._clock)
            dataref = self._client.dataref(ref.path, auto_save=False)
            result = self._bounded_udp_call(
                lambda: self._client.monitor_dataref(dataref, frequency_hz=self._rate_for(ref)),
                operation_deadline,
                "subscription",
            )
            if result is False:
                rejected[ref.id] = "UDP subscription failed"
                continue
            accepted.append(ref.id)
            self._datarefs[ref.path] = dataref
            self._refs_by_path[ref.path] = ref
            self._callbacks[ref.path] = callback
            self._configured_paths.add(ref.path)
        if purpose == "aircraft_identity" and accepted:
            self._identity_wait_active = True
            self._identity_deadline = deadline
        if accepted:
            _remaining(operation_deadline, self._clock)
            self._client.start(release=True)
        return SubscriptionResult(purpose, tuple(accepted), rejected, None)

    def arm_identity_wait(self, deadline: float | None) -> None:
        self._identity_wait_active = True
        self._identity_deadline = deadline

    def close(self, deadline: float) -> None:
        if self._closed:
            return
        phases = _shutdown_deadlines(deadline, self._clock)
        failure: BaseException | None = None
        if self._client is not None:
            if self._datarefs:
                failure = _attempt_cleanup(
                    failure,
                    lambda: self._bounded_udp_call(
                        lambda: self._client.unmonitor_datarefs(self._datarefs, reason="capture_close"),
                        phases.unsubscribe,
                        "shutdown unsubscribe",
                        initiate_on_expiry=True,
                    ),
                )
            failure = _attempt_cleanup(
                failure,
                lambda: self._bounded_udp_call(
                    lambda: self._client.stop(
                        timeout_seconds=min(
                            self._request.retry.shutdown_timeout_seconds,
                            max(0.0, phases.listener_stop - self._clock()),
                        )
                    ),
                    phases.listener_stop,
                    "listener shutdown",
                    initiate_on_expiry=True,
                ),
            )
            failure = _attempt_cleanup(
                failure,
                lambda: self._bounded_udp_call(
                    self._client.close,
                    phases.transport_close,
                    "socket close",
                    initiate_on_expiry=True,
                ),
            )
        if self._monitor is not None:
            failure = _attempt_cleanup(
                failure,
                lambda: _bounded_call(
                    self._monitor.stop_monitor,
                    phases.owner_close,
                    self._clock,
                    timeout_message="UDP beacon monitor shutdown deadline expired",
                    initiate_on_expiry=True,
                ),
            )
        self._closed = True
        if failure is not None:
            raise failure


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
