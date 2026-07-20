"""Contract tests for the capture worker's narrow transport adapters."""

from __future__ import annotations

import socket
import struct
import threading
import time
import unittest
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, PropertyMock, patch

from xpwebapi.capture_protocol import (
    AircraftIdentityRef,
    CaptureCorrelation,
    CaptureRef,
    CaptureRequest,
    CaptureRetryPolicy,
    CaptureSampleGroup,
    DatarefMatchIdentityReadiness,
    UdpCaptureConfig,
    WebsocketCaptureConfig,
)
from xpwebapi.capture_transport import Observation, create_capture_transport
from xpwebapi.exceptions import XPReadOnlyViolation
from xpwebapi.read_only import _ReadOnlyDatagramSocketProxy
from xpwebapi.udp import XPUDPAPI, XPlaneTimeout
from xpwebapi.ws import CALLBACK_TYPE, XPWebsocketAPI


@dataclass
class FakeClock:
    now: float = 0.0

    def monotonic(self) -> float:
        return self.now


class FakeDataref:
    def __init__(self, path: str, value_type: str = "float", *, auto_save: bool = False) -> None:
        self.name = path
        self.path = path.split("[", 1)[0]
        self.index = int(path.rsplit("[", 1)[1][:-1]) if "[" in path else None
        self.auto_save = auto_save
        self.meta = SimpleNamespace(value_type=value_type, ident=1)


class FakeWebsocketClient:
    def __init__(self, *, feedback: str = "success", metadata: dict[str, str] | None = None, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.feedback = feedback
        self.metadata = metadata or {}
        self.callbacks: dict[CALLBACK_TYPE, list[Callable[..., None]]] = {}
        self.created: list[FakeDataref] = []
        self.connected = False
        self.events: list[object] = []
        self.subscribe_calls = 0
        self.xp_version = "12.2.0"
        self.request_id = 41
        self.session = SimpleNamespace(close=lambda: self.events.append("session.close"))

    def set_callback(self, kind: CALLBACK_TYPE, callback: Callable[..., None]) -> None:
        self.callbacks.setdefault(kind, []).append(callback)

    def connect_websocket(self, timeout_resolver: Callable[[], tuple[float, float]] | None = None) -> None:
        if timeout_resolver is not None:
            self.events.append(("connect.timeouts", timeout_resolver()))
        self.events.append("connect_websocket")
        self.connected = True

    def connect(self) -> None:
        raise AssertionError("capture adapter must not use connect()")

    def wait_connection(self) -> None:
        raise AssertionError("capture adapter must not use wait_connection()")

    def connection_monitor(self) -> None:
        raise AssertionError("capture adapter must not use connection_monitor()")

    def dataref(self, path: str, auto_save: bool = True) -> FakeDataref:
        result = FakeDataref(path, self.metadata.get(path, "float"), auto_save=auto_save)
        self.created.append(result)
        return result

    def start(self, release: bool = False) -> None:
        self.events.append(("start", release))

    def monitor_datarefs(self, datarefs: dict[str, FakeDataref], reason: str | None = None) -> tuple[int | bool, dict[str, FakeDataref]]:
        self.events.append(("monitor", tuple(datarefs), reason))
        self.subscribe_calls += 1
        if self.feedback == "invalid-request":
            return False, datarefs
        callbacks = self.callbacks.get(CALLBACK_TYPE.ON_REQUEST_FEEDBACK, [])
        if self.feedback == "early-other-then-success":
            for callback in callbacks:
                callback(request_id=999, payload={"success": True})
                callback(request_id=self.request_id, payload={"success": True})
        elif self.feedback == "early-observation-then-success":
            self.emit("sim/test/identity", b"FlyJSim Q4XP")
            for callback in callbacks:
                callback(request_id=self.request_id, payload={"success": True})
        elif self.feedback == "success":
            for callback in callbacks:
                callback(request_id=self.request_id, payload={"success": True})
        elif self.feedback == "failure":
            for callback in callbacks:
                callback(request_id=self.request_id, payload={"success": False, "error_message": "nope"})
        return self.request_id, datarefs

    def unmonitor_datarefs(self, datarefs: dict[str, FakeDataref], reason: str | None = None) -> tuple[bool, dict]:
        self.events.append(("unmonitor", tuple(datarefs), reason))
        return True, {}

    def stop(self, timeout_seconds: float | None = None) -> None:
        self.events.append(("stop", timeout_seconds))

    def disconnect_websocket(self, timeout_resolver: Callable[[], float] | None = None) -> None:
        timeout = timeout_resolver() if timeout_resolver is not None else None
        self.events.append(("websocket.close.timeout", timeout))
        self.events.append("disconnect_websocket")
        self.connected = False

    def abort_websocket(self) -> None:
        self.events.append("abort_websocket")
        self.connected = False

    def emit(self, path: str, value: object) -> None:
        for callback in self.callbacks.get(CALLBACK_TYPE.ON_DATAREF_UPDATE, []):
            callback(dataref=path, value=value)


class WebsocketFactory:
    def __init__(self, *, feedback: str = "success", metadata: dict[str, str] | None = None) -> None:
        self.feedback = feedback
        self.metadata = metadata
        self.calls: list[dict[str, object]] = []
        self.clients: list[FakeWebsocketClient] = []

    def __call__(self, **kwargs: object) -> FakeWebsocketClient:
        self.calls.append(kwargs)
        client = FakeWebsocketClient(feedback=self.feedback, metadata=self.metadata, **kwargs)
        self.clients.append(client)
        return client


class FakeBeacon:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.timeouts: list[float] = []
        self.data = None
        self.stopped = False

    def get_beacon(self, timeout: float) -> SimpleNamespace:
        self.timeouts.append(timeout)
        self.data = SimpleNamespace(host="192.0.2.10", port=49001, xplane_version=122015)
        return self.data

    def stop_monitor(self) -> None:
        self.stopped = True

    def add_callback(self, _callback: Callable[..., None]) -> None:
        return None


class BeaconFactory:
    def __init__(self) -> None:
        self.monitors: list[FakeBeacon] = []

    def __call__(self, **kwargs: object) -> FakeBeacon:
        monitor = FakeBeacon(**kwargs)
        self.monitors.append(monitor)
        return monitor


class FakeUdpSocket:
    def __init__(self) -> None:
        self.timeouts: list[float] = []
        self.closed = False

    def settimeout(self, value: float) -> None:
        self.timeouts.append(value)

    def close(self) -> None:
        self.closed = True


class FakeUdpClient:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.socket = FakeUdpSocket()
        self.callbacks: list[Callable[..., None]] = []
        self.created: list[FakeDataref] = []
        self.monitor_calls: list[tuple[str, int]] = []
        self.unmonitor_calls: list[tuple[str, ...]] = []
        self.stop_timeouts: list[float | None] = []
        self.started = False
        self.closed = False

    def add_callback(self, callback: Callable[..., None]) -> None:
        self.callbacks.append(callback)

    def dataref(self, path: str, auto_save: bool = True) -> FakeDataref:
        ref = FakeDataref(path, auto_save=auto_save)
        self.created.append(ref)
        return ref

    def monitor_dataref(self, dataref: FakeDataref, frequency_hz: int = 1) -> bool:
        self.monitor_calls.append((dataref.name, frequency_hz))
        return True

    def unmonitor_datarefs(self, datarefs: dict[str, FakeDataref], reason: str | None = None) -> tuple[bool, dict]:
        self.unmonitor_calls.append(tuple(datarefs))
        return True, {}

    def start(self, release: bool = False) -> None:
        self.started = True

    def stop(self, timeout_seconds: float | None = None) -> None:
        self.stop_timeouts.append(timeout_seconds)

    def close(self) -> None:
        self.closed = True

    def emit(self, path: str, value: object) -> None:
        for callback in self.callbacks:
            callback(dataref=path, value=value)


class UdpFactory:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.clients: list[FakeUdpClient] = []

    def __call__(self, **kwargs: object) -> FakeUdpClient:
        self.calls.append(kwargs)
        client = FakeUdpClient(**kwargs)
        self.clients.append(client)
        return client


def make_request(kind: str = "websocket") -> CaptureRequest:
    identity = AircraftIdentityRef(
        id="identity",
        path="sim/test/identity",
        declared_type="string" if kind == "websocket" else "float",
        encoding="utf-8" if kind == "websocket" else None,
        rate_hz=1.0,
        operator="contains" if kind == "websocket" else "equals",
        expected_value="Q4XP" if kind == "websocket" else 1.0,
    )
    transport = (
        WebsocketCaptureConfig(kind="websocket", host="127.0.0.1", port=8086)
        if kind == "websocket"
        else UdpCaptureConfig(kind="udp", beacon_timeout_seconds=5.0, socket_timeout_seconds=1.0, liveness_timeout_seconds=3.0)
    )
    return CaptureRequest(
        protocol_version=1,
        capture_session_id="capture-1",
        sortie_id="sortie-1",
        correlation=CaptureCorrelation(campaign_id="campaign", route_profile_id="route", scenario_id="scenario"),
        identity_readiness=DatarefMatchIdentityReadiness(kind="dataref_match", target_aircraft="FlyJSim Q4XP", refs=(identity,)),
        transport=transport,
        sample_groups=(CaptureSampleGroup(id="group", rate_hz=2.0),),
        refs=(
            CaptureRef(
                id="capture",
                path="sim/test/capture",
                declared_type="float",
                availability="required",
                sample_group_id="group",
            ),
        ),
        retry=CaptureRetryPolicy(subscription_timeout_seconds=2.0, stale_after_seconds=3.0, shutdown_timeout_seconds=4.0),
    )


class WebsocketCaptureTransportTests(unittest.TestCase):
    def test_open_is_read_only_bounded_and_does_not_create_datarefs(self) -> None:
        clock = FakeClock(5.0)
        factory = WebsocketFactory()
        adapter = create_capture_transport(make_request(), client_factory=factory, clock=clock.monotonic)

        capabilities = adapter.open(deadline=8.0)

        self.assertEqual([], factory.clients[0].created)
        self.assertTrue(factory.calls[0]["read_only"])
        for name in ("http_timeout", "open_timeout", "close_timeout"):
            timeout = cast(float, factory.calls[0][name])
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, 3.0)
        self.assertEqual("websocket", capabilities.transport)
        self.assertEqual("connected", adapter.liveness_state)

    def test_nonpositive_deadline_prevents_client_construction(self) -> None:
        factory = WebsocketFactory()
        adapter = create_capture_transport(make_request(), client_factory=factory, clock=FakeClock(5.0).monotonic)

        with self.assertRaises(TimeoutError):
            adapter.open(deadline=5.0)

        self.assertEqual([], factory.calls)

    def test_subscription_uses_auto_save_false_and_early_matching_feedback(self) -> None:
        factory = WebsocketFactory(feedback="early-other-then-success", metadata={"sim/test/identity": "data"})
        adapter = create_capture_transport(make_request(), client_factory=factory, clock=FakeClock().monotonic)
        adapter.open(deadline=10.0)
        observations: list[Observation] = []

        result = adapter.subscribe(make_request().identity_readiness.refs, "aircraft_identity", observations.append, deadline=10.0)

        self.assertEqual(("identity",), result.accepted_ref_ids)
        self.assertEqual(41, result.request_id)
        self.assertFalse(factory.clients[0].created[0].auto_save)
        self.assertLess(
            factory.clients[0].events.index(("start", True)), factory.clients[0].events.index(("monitor", ("sim/test/identity",), "aircraft_identity"))
        )

    def test_observation_before_success_feedback_is_published_only_after_acceptance(self) -> None:
        factory = WebsocketFactory(feedback="early-observation-then-success", metadata={"sim/test/identity": "data"})
        request = make_request()
        adapter = create_capture_transport(request, client_factory=factory, clock=FakeClock().monotonic)
        adapter.open(deadline=10.0)
        observations: list[Observation] = []

        result = adapter.subscribe(request.identity_readiness.refs, "aircraft_identity", observations.append, deadline=10.0)

        self.assertEqual(("identity",), result.accepted_ref_ids)
        self.assertEqual(1, len(observations))
        capture = adapter.subscribe(request.refs, "capture", lambda _: None, deadline=10.0)
        self.assertEqual(("capture",), capture.accepted_ref_ids)

    def test_blocking_websocket_subscribe_send_is_aborted_at_absolute_deadline(self) -> None:
        factory = WebsocketFactory(metadata={"sim/test/identity": "data"})
        request = make_request()
        adapter = create_capture_transport(request, client_factory=factory, clock=time.monotonic)
        adapter.open(deadline=time.monotonic() + 1.0)
        client = factory.clients[0]
        release = threading.Event()

        def blocking_monitor(datarefs: dict[str, FakeDataref], reason: str | None = None) -> tuple[int | bool, dict[str, FakeDataref]]:
            client.events.append(("monitor.blocking", tuple(datarefs), reason))
            release.wait(0.4)
            return client.request_id, datarefs

        def abort() -> None:
            client.events.append("abort_websocket")
            client.connected = False
            release.set()
            raise RuntimeError("abort cleanup failed")

        cast(Any, client).monitor_datarefs = blocking_monitor
        cast(Any, client).abort_websocket = abort
        started = time.monotonic()

        with self.assertRaises(TimeoutError):
            adapter.subscribe(request.identity_readiness.refs, "aircraft_identity", lambda _: None, deadline=started + 0.05)

        self.assertLess(time.monotonic() - started, 0.25)
        self.assertIn("abort_websocket", client.events)

    def test_blocking_websocket_rollback_unmonitor_is_aborted_at_deadline(self) -> None:
        factory = WebsocketFactory(feedback="failure", metadata={"sim/test/identity": "data"})
        request = make_request()
        adapter = create_capture_transport(request, client_factory=factory, clock=time.monotonic)
        adapter.open(deadline=time.monotonic() + 1.0)
        client = factory.clients[0]
        release = threading.Event()

        def blocking_unmonitor(datarefs: dict[str, FakeDataref], reason: str | None = None) -> tuple[bool, dict]:
            client.events.append(("unmonitor.blocking", tuple(datarefs), reason))
            release.wait(0.4)
            return True, {}

        def abort() -> None:
            client.events.append("abort_websocket")
            client.connected = False
            release.set()

        cast(Any, client).unmonitor_datarefs = blocking_unmonitor
        cast(Any, client).abort_websocket = abort
        started = time.monotonic()

        result = adapter.subscribe(request.identity_readiness.refs, "aircraft_identity", lambda _: None, deadline=started + 0.05)

        self.assertLess(time.monotonic() - started, 0.25)
        self.assertEqual({"identity": "subscription feedback failed"}, dict(result.rejected))
        self.assertIn("abort_websocket", client.events)

    def test_failed_and_timed_out_feedback_rejects_the_batch(self) -> None:
        for feedback in ("failure", "timeout", "invalid-request"):
            with self.subTest(feedback=feedback):
                clock = FakeClock()
                factory = WebsocketFactory(feedback=feedback, metadata={"sim/test/identity": "data"})
                adapter = create_capture_transport(make_request(), client_factory=factory, clock=clock.monotonic)
                adapter.open(deadline=10.0)
                observations: list[Observation] = []
                if feedback == "timeout":

                    def expire(timeout: float | None = None) -> bool:
                        clock.now += timeout or 0.0
                        return False

                    adapter._feedback_condition.wait = expire  # type: ignore[attr-defined]
                result = adapter.subscribe(
                    make_request().identity_readiness.refs,
                    "aircraft_identity",
                    observations.append,
                    deadline=10.0,
                )
                self.assertEqual((), result.accepted_ref_ids)
                expected_reason = {
                    "failure": "subscription feedback failed",
                    "timeout": "subscription feedback timeout",
                    "invalid-request": "subscription request failed",
                }[feedback]
                self.assertEqual(
                    {"identity": expected_reason},
                    dict(result.rejected),
                )
                factory.clients[0].emit("sim/test/identity", b"FlyJSim Q4XP")
                self.assertEqual([], observations)
                with self.assertRaises(RuntimeError):
                    adapter.subscribe(make_request().refs, "capture", lambda _: None, deadline=10.0)
                unmonitor_events = [event for event in factory.clients[0].events if isinstance(event, tuple) and event[0] == "unmonitor"]
                self.assertEqual(1, len(unmonitor_events))

    def test_capture_datarefs_are_deferred_until_fresh_identity_match(self) -> None:
        clock = FakeClock()
        factory = WebsocketFactory(metadata={"sim/test/identity": "data", "sim/test/capture": "float"})
        request = make_request()
        adapter = create_capture_transport(request, client_factory=factory, clock=clock.monotonic)
        adapter.open(deadline=10.0)
        adapter.subscribe(request.identity_readiness.refs, "aircraft_identity", lambda _: None, deadline=10.0)

        with self.assertRaises(RuntimeError):
            adapter.subscribe(request.refs, "capture", lambda _: None, deadline=10.0)
        self.assertEqual(["sim/test/identity"], [ref.name for ref in factory.clients[0].created])

        factory.clients[0].emit("sim/test/identity", b"FlyJSim Q4XP\x00")
        result = adapter.subscribe(request.refs, "capture", lambda _: None, deadline=10.0)
        self.assertEqual(("capture",), result.accepted_ref_ids)

        clock.now = 4.0
        fresh = create_capture_transport(request, client_factory=WebsocketFactory(metadata={"sim/test/identity": "data"}), clock=clock.monotonic)
        fresh.open(deadline=10.0)
        with self.assertRaises(RuntimeError):
            fresh.subscribe(request.refs, "capture", lambda _: None, deadline=10.0)

    def test_metadata_type_contract_rejects_incompatible_and_unindexed_arrays(self) -> None:
        request = make_request()
        for value_type in ("int", "float_array"):
            with self.subTest(value_type=value_type):
                factory = WebsocketFactory(metadata={"sim/test/identity": value_type})
                adapter = create_capture_transport(request, client_factory=factory, clock=FakeClock().monotonic)
                adapter.open(deadline=10.0)
                result = adapter.subscribe(request.identity_readiness.refs, "aircraft_identity", lambda _: None, deadline=10.0)
                self.assertEqual((), result.accepted_ref_ids)
                self.assertIn("identity", result.rejected)
                self.assertEqual(0, factory.clients[0].subscribe_calls)

    def test_observations_map_paths_to_ref_ids(self) -> None:
        factory = WebsocketFactory(metadata={"sim/test/identity": "data"})
        request = make_request()
        adapter = create_capture_transport(request, client_factory=factory, clock=FakeClock(2.5).monotonic)
        adapter.open(deadline=10.0)
        observed: list[Observation] = []
        adapter.subscribe(request.identity_readiness.refs, "aircraft_identity", observed.append, deadline=10.0)
        factory.clients[0].emit("sim/test/identity", b"Q4XP")
        self.assertEqual(Observation("identity", "sim/test/identity", b"Q4XP", 2.5), observed[0])

    def test_fresh_adapter_resubscribes_once(self) -> None:
        factory = WebsocketFactory(metadata={"sim/test/identity": "data"})
        request = make_request()
        for deadline in (10.0, 20.0):
            adapter = create_capture_transport(request, client_factory=factory, clock=FakeClock().monotonic)
            adapter.open(deadline=deadline)
            adapter.subscribe(request.identity_readiness.refs, "aircraft_identity", lambda _: None, deadline=deadline)
            adapter.close(deadline=deadline)
        self.assertEqual([True, True], [call["read_only"] for call in factory.calls])
        self.assertEqual([1, 1], [client.subscribe_calls for client in factory.clients])

    def test_actual_websocket_connect_receives_bounded_open_and_close_timeouts(self) -> None:
        request = make_request()
        clock = FakeClock(7.0)
        raw = SimpleNamespace(close=lambda: None, send=lambda _message: None, recv=lambda: "")

        def advance_during_rest_probe() -> bool:
            clock.now = 8.5
            return True

        with (
            patch("xpwebapi.ws.connect", return_value=raw) as connect,
            patch.object(XPWebsocketAPI, "rest_api_reachable", new_callable=PropertyMock, side_effect=advance_during_rest_probe),
            patch.object(XPWebsocketAPI, "reload_caches", return_value=None),
        ):
            adapter = create_capture_transport(request, clock=clock.monotonic)
            adapter.open(deadline=9.0)
            adapter.close(deadline=9.0)
        self.assertLessEqual(connect.call_args.kwargs["open_timeout"], 0.5)
        self.assertLessEqual(connect.call_args.kwargs["close_timeout"], 0.5)
        self.assertLessEqual(raw.close_timeout, 0.5)

    def test_actual_rest_and_cache_gets_reclamp_the_absolute_deadline(self) -> None:
        clock = FakeClock()
        raw_session = MagicMock()
        calls: list[tuple[float, float]] = []

        def get(_url: str, *, timeout: float) -> SimpleNamespace:
            calls.append((clock.now, timeout))
            clock.now += 0.25
            return SimpleNamespace(status_code=200, json=lambda: {"data": []})

        raw_session.get.side_effect = get
        raw_websocket = SimpleNamespace(close=lambda: None, send=lambda _message: None, recv=lambda: "")
        with (
            patch("xpwebapi.rest._make_http_client", return_value=raw_session),
            patch("xpwebapi.ws.connect", return_value=raw_websocket),
            patch("xpwebapi.ws.socket.gethostname", return_value="testhost"),
            patch("xpwebapi.ws.socket.gethostbyname", return_value="127.0.0.1"),
        ):
            adapter = create_capture_transport(make_request(), clock=clock.monotonic)
            adapter.open(deadline=5.0)
            adapter.close(deadline=5.0)

        self.assertGreaterEqual(len(calls), 2)
        for before, timeout in calls:
            self.assertGreater(timeout, 0.0)
            self.assertLessEqual(timeout, 5.0 - before)
        raw_session.close.assert_called_once_with()

    def test_shutdown_reclamps_listener_and_websocket_close_after_each_boundary(self) -> None:
        clock = FakeClock()
        factory = WebsocketFactory(metadata={"sim/test/identity": "data"})
        adapter = create_capture_transport(make_request(), client_factory=factory, clock=clock.monotonic)
        adapter.open(deadline=10.0)
        client = factory.clients[0]
        original_stop = client.stop

        def advancing_stop(timeout_seconds: float | None = None) -> None:
            original_stop(timeout_seconds)
            clock.now = 3.0

        cast(Any, client).stop = advancing_stop
        adapter.close(deadline=4.0)
        stop_event = next(event for event in client.events if isinstance(event, tuple) and event[0] == "stop")
        close_event = next(event for event in client.events if isinstance(event, tuple) and event[0] == "websocket.close.timeout")
        self.assertEqual(4.0, stop_event[1])
        self.assertLessEqual(cast(float, close_event[1]), 1.0)

    def test_blocking_websocket_shutdown_unmonitor_times_out_and_aborts(self) -> None:
        factory = WebsocketFactory(metadata={"sim/test/identity": "data"})
        request = make_request()
        adapter = create_capture_transport(request, client_factory=factory, clock=time.monotonic)
        adapter.open(deadline=time.monotonic() + 1.0)
        adapter.subscribe(request.identity_readiness.refs, "aircraft_identity", lambda _: None, deadline=time.monotonic() + 1.0)
        client = factory.clients[0]
        release = threading.Event()

        def blocking_unmonitor(datarefs: dict[str, FakeDataref], reason: str | None = None) -> tuple[bool, dict]:
            client.events.append(("unmonitor.blocking", tuple(datarefs), reason))
            release.wait(0.4)
            return True, {}

        def abort() -> None:
            client.events.append("abort_websocket")
            client.connected = False
            release.set()
            raise RuntimeError("abort cleanup failed")

        cast(Any, client).unmonitor_datarefs = blocking_unmonitor
        cast(Any, client).abort_websocket = abort
        started = time.monotonic()

        with self.assertRaises(TimeoutError):
            adapter.close(deadline=started + 0.05)

        self.assertLess(time.monotonic() - started, 0.25)
        self.assertEqual(1, client.events.count("abort_websocket"))
        self.assertEqual(1, sum(isinstance(event, tuple) and event[0] == "stop" for event in client.events))
        self.assertEqual(1, client.events.count("disconnect_websocket"))
        self.assertEqual(1, client.events.count("session.close"))
        self.assertFalse(adapter.connected)
        self.assertTrue(cast(Any, adapter)._closed)

    def test_websocket_close_preserves_first_exception_while_attempting_cleanup(self) -> None:
        factory = WebsocketFactory(metadata={"sim/test/identity": "data"})
        request = make_request()
        adapter = create_capture_transport(request, client_factory=factory, clock=time.monotonic)
        adapter.open(deadline=time.monotonic() + 1.0)
        adapter.subscribe(request.identity_readiness.refs, "aircraft_identity", lambda _: None, deadline=time.monotonic() + 1.0)
        client = factory.clients[0]

        def fail_unmonitor(_datarefs: dict[str, FakeDataref], reason: str | None = None) -> tuple[bool, dict]:
            client.events.append(("unmonitor.failed", reason))
            raise ValueError("first cleanup failure")

        def fail_stop(timeout_seconds: float | None = None) -> None:
            client.events.append(("stop.failed", timeout_seconds))
            raise RuntimeError("later cleanup failure")

        cast(Any, client).unmonitor_datarefs = fail_unmonitor
        cast(Any, client).stop = fail_stop

        with self.assertRaisesRegex(ValueError, "first cleanup failure"):
            adapter.close(deadline=time.monotonic() + 1.0)

        self.assertTrue(any(isinstance(event, tuple) and event[0] == "stop.failed" for event in client.events))
        self.assertIn("disconnect_websocket", client.events)


class UdpCaptureTransportTests(unittest.TestCase):
    def make_adapter(self, clock: FakeClock | None = None) -> tuple[object, UdpFactory, BeaconFactory, CaptureRequest]:
        udp_factory = UdpFactory()
        beacon_factory = BeaconFactory()
        request = make_request("udp")
        adapter = create_capture_transport(
            request,
            client_factory=udp_factory,
            beacon_factory=beacon_factory,
            clock=(clock or FakeClock()).monotonic,
        )
        return adapter, udp_factory, beacon_factory, request

    def test_open_retains_beacon_data_and_builds_guarded_udp_client(self) -> None:
        adapter, udp_factory, beacon_factory, _request = self.make_adapter()
        capabilities = adapter.open(deadline=4.0)
        monitor = beacon_factory.monitors[0]
        self.assertIs(udp_factory.calls[0]["beacon"], monitor)
        self.assertEqual("192.0.2.10", udp_factory.calls[0]["host"])
        self.assertEqual(49001, udp_factory.calls[0]["port"])
        self.assertTrue(udp_factory.calls[0]["read_only"])
        self.assertEqual([4.0], monitor.timeouts)
        self.assertEqual([1.0], udp_factory.clients[0].socket.timeouts)
        self.assertEqual("12.2.0-r1", capabilities.xplane_version)

    def test_beacon_deadline_is_clamped_and_nonpositive_prevents_call(self) -> None:
        clock = FakeClock(3.0)
        adapter, _udp_factory, beacon_factory, _request = self.make_adapter(clock)
        adapter.open(deadline=4.5)
        self.assertEqual([1.5], beacon_factory.monitors[0].timeouts)

        expired, _udp_factory, expired_beacons, _request = self.make_adapter(FakeClock(5.0))
        with self.assertRaises(TimeoutError):
            expired.open(deadline=5.0)
        self.assertEqual([], expired_beacons.monitors)

    def test_udp_subscription_uses_integral_rate_and_liveness_requires_packet(self) -> None:
        clock = FakeClock()
        adapter, udp_factory, _beacon_factory, request = self.make_adapter(clock)
        adapter.open(deadline=10.0)
        seen: list[Observation] = []
        result = adapter.subscribe(request.identity_readiness.refs, "aircraft_identity", seen.append, deadline=8.0)
        self.assertEqual(("identity",), result.accepted_ref_ids)
        self.assertEqual([("sim/test/identity", 1)], udp_factory.clients[0].monitor_calls)
        self.assertFalse(udp_factory.clients[0].created[0].auto_save)
        self.assertEqual("awaiting_first_identity_packet", adapter.liveness_state)

        udp_factory.clients[0].emit("sim/not/configured", 1.0)
        self.assertEqual("awaiting_first_identity_packet", adapter.liveness_state)
        udp_factory.clients[0].emit("sim/test/identity", 1.0)
        self.assertTrue(adapter.connected)
        self.assertEqual("connected", adapter.liveness_state)
        self.assertEqual("identity", seen[0].ref_id)

        clock.now = 3.1
        self.assertFalse(adapter.connected)
        self.assertEqual("disconnected", adapter.liveness_state)

    def test_udp_identity_wait_expires_at_identity_deadline(self) -> None:
        clock = FakeClock()
        adapter, _udp_factory, _beacon_factory, request = self.make_adapter(clock)
        adapter.open(deadline=10.0)
        adapter.subscribe(request.identity_readiness.refs, "aircraft_identity", lambda _: None, deadline=2.0)
        clock.now = 2.0
        self.assertEqual("disconnected", adapter.liveness_state)

    def test_udp_defers_capture_until_fresh_identity_and_closes_bounded(self) -> None:
        clock = FakeClock()
        adapter, udp_factory, beacon_factory, request = self.make_adapter(clock)
        adapter.open(deadline=10.0)
        adapter.subscribe(request.identity_readiness.refs, "aircraft_identity", lambda _: None, deadline=8.0)
        with self.assertRaises(RuntimeError):
            adapter.subscribe(request.refs, "capture", lambda _: None, deadline=8.0)
        udp_factory.clients[0].emit("sim/test/identity", 1.0)
        result = adapter.subscribe(request.refs, "capture", lambda _: None, deadline=8.0)
        self.assertEqual(("capture",), result.accepted_ref_ids)
        self.assertEqual(("sim/test/capture", 2), udp_factory.clients[0].monitor_calls[-1])

        clock.now = 5.0
        adapter.close(deadline=7.0)
        stop_timeout = udp_factory.clients[0].stop_timeouts[0]
        self.assertIsNotNone(stop_timeout)
        self.assertLessEqual(cast(float, stop_timeout), 2.0)
        self.assertTrue(udp_factory.clients[0].closed)
        self.assertTrue(beacon_factory.monitors[0].stopped)

    def test_blocking_udp_monitor_send_is_closed_at_absolute_deadline(self) -> None:
        raw = _BlockingPacketSocket()
        beacon_factory = BeaconFactory()
        request = make_request("udp")
        with patch("xpwebapi.udp.socket.socket", return_value=raw), patch.object(XPUDPAPI, "start", return_value=None):
            adapter = create_capture_transport(request, beacon_factory=beacon_factory, clock=time.monotonic)
            adapter.open(deadline=time.monotonic() + 1.0)
            raw.block = True
            started = time.monotonic()

            with self.assertRaises(TimeoutError):
                adapter.subscribe(request.identity_readiness.refs, "aircraft_identity", lambda _: None, deadline=started + 0.05)

        self.assertLess(time.monotonic() - started, 0.25)
        self.assertTrue(raw.closed)

    def test_blocking_udp_shutdown_unmonitor_is_closed_at_absolute_deadline(self) -> None:
        raw = _BlockingPacketSocket()
        beacon_factory = BeaconFactory()
        request = make_request("udp")
        with patch("xpwebapi.udp.socket.socket", return_value=raw):
            adapter = create_capture_transport(request, beacon_factory=beacon_factory, clock=time.monotonic)
            adapter.open(deadline=time.monotonic() + 1.0)
            adapter.subscribe(request.identity_readiness.refs, "aircraft_identity", lambda _: None, deadline=time.monotonic() + 1.0)
            client = cast(Any, adapter)._client
            self.assertTrue(raw.recv_started.wait(0.5))
            raw.stop_event = client.udp_lsnr_not_running
            abort_calls: list[None] = []
            stop_calls: list[float | None] = []
            close_calls: list[None] = []
            original_stop = client.stop
            original_close = client.close

            def abort() -> None:
                abort_calls.append(None)
                client.udp_lsnr_not_running.set()
                client.socket.close()

            def stop(timeout_seconds: float | None = None) -> None:
                stop_calls.append(timeout_seconds)
                original_stop(timeout_seconds=timeout_seconds)

            def close() -> None:
                close_calls.append(None)
                original_close()

            client.abort = abort
            client.stop = stop
            client.close = close
            raw.block = True
            started = time.monotonic()

            try:
                with self.assertRaises(TimeoutError):
                    adapter.close(deadline=started + 0.2)
                listener_stopped = client.udp_lsnr_not_running.is_set()
                listener_alive = client.udp_thread.is_alive()
                beacon_stopped = beacon_factory.monitors[0].stopped
                client_closed = client._closed
            finally:
                client.udp_lsnr_not_running.set()
                raw.close()
                client.udp_thread.join(0.5)

        self.assertLess(time.monotonic() - started, 0.4)
        self.assertEqual([None], abort_calls)
        self.assertEqual(1, len(stop_calls))
        self.assertEqual([None], close_calls)
        self.assertTrue(listener_stopped)
        self.assertFalse(listener_alive)
        self.assertTrue(beacon_stopped)
        self.assertTrue(client_closed)
        self.assertTrue(raw.stop_was_set_at_first_close)
        self.assertTrue(raw.closed)


class _BlockingPacketSocket:
    def __init__(self) -> None:
        self.block = False
        self.closed = False
        self.release = threading.Event()
        self.recv_started = threading.Event()
        self.close_calls = 0
        self.stop_event: threading.Event | None = None
        self.stop_was_set_at_first_close = False

    def settimeout(self, _value: float) -> None:
        return None

    def sendto(self, message: bytes, _address: tuple[str, int]) -> int:
        if self.block:
            self.release.wait(0.8)
        return len(message)

    def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
        self.recv_started.set()
        self.release.wait(0.8)
        raise OSError("socket closed")

    def close(self) -> None:
        self.close_calls += 1
        if self.close_calls == 1 and self.stop_event is not None:
            self.stop_was_set_at_first_close = self.stop_event.is_set()
        self.closed = True
        self.release.set()


class ReadOnlyUdpWireTests(unittest.TestCase):
    class RawSocket:
        def __init__(self) -> None:
            self.sent: list[tuple[bytes, tuple[str, int]]] = []

        def sendto(self, message: bytes, address: tuple[str, int]) -> int:
            self.sent.append((message, address))
            return len(message)

    def test_guard_accepts_only_canonical_rref_control_packets(self) -> None:
        raw = self.RawSocket()
        destination = ("127.0.0.1", 49000)
        proxy = _ReadOnlyDatagramSocketProxy(cast(socket.socket, cast(Any, raw)), destination)
        valid = struct.pack("<5sii400s", b"RREF\x00", 1, 0, b"sim/test/value")
        self.assertEqual(413, proxy.sendto(valid, destination))

        invalid = (
            (valid, ("127.0.0.2", 49000)),
            (valid[:-1], destination),
            (struct.pack("<5sii400s", b"DREF\x00", 1, 0, b"sim/test/value"), destination),
            (struct.pack("<5sii400s", b"RREF\x00", -1, 0, b"sim/test/value"), destination),
            (struct.pack("<5sii400s", b"RREF\x00", 101, 0, b"sim/test/value"), destination),
            (struct.pack("<5sii400s", b"RREF\x00", 1, -1, b"sim/test/value"), destination),
            (struct.pack("<5sii400s", b"RREF\x00", 1, 0, b""), destination),
            (struct.pack("<5sii400s", b"RREF\x00", 1, 0, b"x" * 400), destination),
            (struct.pack("<5sii400s", b"RREF\x00", 1, 0, b"\xff"), destination),
            (struct.pack("<5sii400s", b"RREF\x00", 1, 0, b"sim/x\x00bad"), destination),
        )
        for message, address in invalid:
            with self.subTest(message=message[:16], address=address), self.assertRaises(XPReadOnlyViolation):
                proxy.sendto(message, address)
        self.assertEqual(1, len(raw.sent))

    def test_actual_udp_decoder_only_valid_configured_index_establishes_liveness(self) -> None:
        clock = FakeClock()
        beacon_factory = BeaconFactory()
        request = make_request("udp")

        class PacketSocket:
            def __init__(self) -> None:
                self.packets: list[bytes | BaseException] = []

            def settimeout(self, _value: float) -> None:
                return None

            def sendto(self, message: bytes, _address: tuple[str, int]) -> int:
                return len(message)

            def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
                item = self.packets.pop(0)
                if isinstance(item, BaseException):
                    raise item
                return item, ("192.0.2.10", 49001)

            def close(self) -> None:
                return None

        raw = PacketSocket()
        with patch("xpwebapi.udp.socket.socket", return_value=raw), patch.object(XPUDPAPI, "start", return_value=None):
            adapter = create_capture_transport(request, beacon_factory=beacon_factory, clock=clock.monotonic)
            adapter.open(deadline=10.0)
            adapter.subscribe(request.identity_readiness.refs, "aircraft_identity", lambda _: None, deadline=8.0)
            client = cast(Any, adapter)._client

            raw.packets.append(b"NOPE," + struct.pack("<if", 0, 1.0))
            client.read_monitored_dataref_values()
            self.assertEqual("awaiting_first_identity_packet", adapter.liveness_state)

            raw.packets.append(b"RREF," + struct.pack("<if", 999, 1.0))
            client.read_monitored_dataref_values()
            self.assertEqual("awaiting_first_identity_packet", adapter.liveness_state)

            raw.packets.append(socket.timeout())
            with self.assertRaises(XPlaneTimeout):
                client.read_monitored_dataref_values()
            self.assertEqual("awaiting_first_identity_packet", adapter.liveness_state)

            raw.packets.append(b"RREF," + struct.pack("<if", 0, 1.0))
            client.read_monitored_dataref_values()
            self.assertEqual("connected", adapter.liveness_state)

    def test_adapters_expose_no_public_client_or_socket(self) -> None:
        ws = create_capture_transport(make_request(), client_factory=WebsocketFactory(), clock=FakeClock().monotonic)
        udp, _factory, _beacon, _request = UdpCaptureTransportTests().make_adapter()
        for adapter in (ws, udp):
            self.assertFalse(hasattr(adapter, "client"))
            self.assertFalse(hasattr(adapter, "socket"))


if __name__ == "__main__":
    unittest.main()
