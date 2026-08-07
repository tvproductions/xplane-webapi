"""Tests for live and synthetic FDR sample-source composition."""

from __future__ import annotations

import threading
import unittest
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from xpwebapi.capture_protocol import WebsocketCaptureConfig
from xpwebapi.fdr.models import FDRDataref, FDRHeader, FDRMetadata
from xpwebapi.fdr.recorder import FDRSampleSink, FDRSampleSource, FDRSourceSample, LiveFDRSampleSource
from xpwebapi.ws import CALLBACK_TYPE


MANDATORY_PATHS = (
    "sim/flightmodel/position/longitude",
    "sim/flightmodel/position/latitude",
    "sim/flightmodel/position/elevation",
    "sim/cockpit2/gauges/indicators/heading_electric_deg_mag_pilot",
    "sim/cockpit2/gauges/indicators/pitch_electric_deg_pilot",
    "sim/cockpit2/gauges/indicators/roll_electric_deg_pilot",
)
MANDATORY_IDS = (
    "longitude",
    "latitude",
    "altitude_msl_ft",
    "heading_magnetic_deg",
    "pitch_deg",
    "roll_deg",
)


@dataclass
class FakeClock:
    monotonic_now: float = 10.0
    utc_start: datetime = datetime(2026, 8, 7, 18, 30, tzinfo=UTC)

    def __post_init__(self) -> None:
        self.wait_calls: list[float] = []
        self.utc_calls = 0
        self.on_wait: Callable[[], None] | None = None

    def monotonic(self) -> float:
        return self.monotonic_now

    def utcnow(self) -> datetime:
        self.utc_calls += 1
        return self.utc_start + timedelta(seconds=self.monotonic_now - 10.0)

    def wait(self, stop_event: threading.Event, timeout: float) -> bool:
        self.wait_calls.append(timeout)
        if stop_event.is_set():
            return True
        self.monotonic_now += timeout
        if self.on_wait is not None:
            self.on_wait()
        return stop_event.is_set()


class FakeDataref:
    def __init__(self, path: str, value_type: str | None) -> None:
        self.name = path
        self.meta = None if value_type is None else SimpleNamespace(value_type=value_type, ident=1)


class FakeWebsocketClient:
    def __init__(
        self,
        *,
        metadata: Mapping[str, str | None],
        initial_values: Mapping[str, float],
        **kwargs: object,
    ) -> None:
        self.kwargs = kwargs
        self.metadata = metadata
        self.initial_values = initial_values
        self.callbacks: dict[CALLBACK_TYPE, list[Callable[..., None]]] = {}
        self.connected = False
        self.request_id = 17
        self.xp_version = "12.2.0"
        self.session = SimpleNamespace(close=lambda: self.events.append("session.close"))
        self.events: list[object] = []

    def set_callback(self, kind: CALLBACK_TYPE, callback: Callable[..., None]) -> None:
        self.callbacks.setdefault(kind, []).append(callback)

    def connect_websocket(self, timeout_resolver: Callable[[], tuple[float, float]] | None = None) -> None:
        if timeout_resolver is not None:
            self.events.append(("connect.timeouts", timeout_resolver()))
        self.connected = True

    def dataref(self, path: str, auto_save: bool = True) -> FakeDataref:
        self.events.append(("dataref", path, auto_save))
        return FakeDataref(path, self.metadata.get(path, "double"))

    def start(self, release: bool = False) -> None:
        self.events.append(("start", release))

    def monitor_datarefs(self, datarefs: Mapping[str, FakeDataref], reason: str | None = None) -> tuple[int, Mapping[str, FakeDataref]]:
        self.events.append(("monitor", tuple(datarefs), reason))
        for path, value in self.initial_values.items():
            self.emit(path, value)
        for callback in self.callbacks.get(CALLBACK_TYPE.ON_REQUEST_FEEDBACK, ()):
            callback(request_id=self.request_id, payload={"success": True})
        return self.request_id, datarefs

    def unmonitor_datarefs(self, datarefs: Mapping[str, FakeDataref], reason: str | None = None) -> tuple[bool, dict[str, FakeDataref]]:
        self.events.append(("unmonitor", tuple(datarefs), reason))
        return True, {}

    def stop(self, timeout_seconds: float | None = None) -> None:
        self.events.append(("stop", timeout_seconds))

    def disconnect_websocket(self, timeout_resolver: Callable[[], float] | None = None) -> None:
        timeout = timeout_resolver() if timeout_resolver is not None else None
        self.events.append(("disconnect", timeout))
        self.connected = False

    def abort_websocket(self) -> None:
        self.events.append("abort")
        self.connected = False

    def emit(self, path: str, value: float) -> None:
        for callback in self.callbacks.get(CALLBACK_TYPE.ON_DATAREF_UPDATE, ()):
            callback(dataref=path, value=value)


class FakeWebsocketFactory:
    def __init__(
        self,
        initial_values: Mapping[str, float],
        *,
        missing_metadata: tuple[str, ...] = (),
    ) -> None:
        self.initial_values = dict(initial_values)
        self.metadata = {path: None for path in missing_metadata}
        self.calls: list[dict[str, object]] = []
        self.clients: list[FakeWebsocketClient] = []

    def __call__(self, **kwargs: object) -> FakeWebsocketClient:
        self.calls.append(kwargs)
        client = FakeWebsocketClient(metadata=self.metadata, initial_values=self.initial_values, **kwargs)
        self.clients.append(client)
        return client


def make_header(*datarefs: FDRDataref) -> FDRHeader:
    return FDRHeader(
        source_version=4,
        source_origin="A",
        comments=("recorded live",),
        metadata=(FDRMetadata("DATE", "2026-08-07"),),
        datarefs=tuple(datarefs),
        legacy_columns=(),
        local_date=date(2026, 8, 7),
    )


def initial_values(**changes: float) -> dict[str, float]:
    values = {
        MANDATORY_PATHS[0]: -87.9048,
        MANDATORY_PATHS[1]: 41.9742,
        MANDATORY_PATHS[2]: 304.8,
        MANDATORY_PATHS[3]: 270.0,
        MANDATORY_PATHS[4]: 2.0,
        MANDATORY_PATHS[5]: -1.0,
        "sim/test/ratio": 0.25,
        "sim/test/rejected": 99.0,
    }
    values.update(changes)
    return values


class FDRSourceProtocolTests(unittest.TestCase):
    def test_source_sample_is_frozen_and_copies_its_values(self) -> None:
        timestamp = datetime(2026, 8, 7, 18, 30, tzinfo=UTC)
        values = {"longitude": -87.9}

        sample = FDRSourceSample(timestamp, values)
        values["longitude"] = 0.0

        self.assertEqual(-87.9, sample.values["longitude"])
        with self.assertRaises(TypeError):
            sample.values["longitude"] = 1.0  # ty: ignore[invalid-assignment]
        with self.assertRaises((AttributeError, TypeError)):
            sample.timestamp_utc = timestamp + timedelta(seconds=1)  # ty: ignore[invalid-assignment]

    def test_protocols_define_header_samples_close_and_write_sample(self) -> None:
        self.assertEqual({"header", "samples", "close"}, set(FDRSampleSource.__annotations__) | set(FDRSampleSource.__dict__) & {"header", "samples", "close"})
        self.assertIn("write_sample", FDRSampleSink.__dict__)


class LiveFDRSampleSourceTests(unittest.TestCase):
    def make_source(
        self,
        factory: FakeWebsocketFactory,
        clock: FakeClock | None = None,
        *,
        header: FDRHeader | None = None,
        sample_interval_seconds: float = 0.5,
        first_values_timeout_seconds: float = 2.0,
    ) -> LiveFDRSampleSource:
        active_clock = clock or FakeClock()
        return LiveFDRSampleSource(
            config=WebsocketCaptureConfig(kind="websocket", host="127.0.0.1", port=8086),
            header=header or make_header(FDRDataref("sim/test/ratio", 0.5, "ratio")),
            sample_interval_seconds=sample_interval_seconds,
            subscription_timeout_seconds=2.0,
            first_values_timeout_seconds=first_values_timeout_seconds,
            client_factory=factory,
            monotonic_clock=active_clock.monotonic,
            utc_clock=active_clock.utcnow,
            wait=active_clock.wait,
        )

    def test_subscribes_mandatory_paths_then_ordered_optionals_read_only(self) -> None:
        optionals = (
            FDRDataref("sim/test/ratio", 0.5, "ratio"),
            FDRDataref("sim/test/second", 2, None),
        )
        values = initial_values()
        values["sim/test/second"] = 2.0
        factory = FakeWebsocketFactory(values)

        source = self.make_source(factory, header=make_header(*optionals))

        monitor = next(event for event in factory.clients[0].events if isinstance(event, tuple) and event[0] == "monitor")
        self.assertEqual(MANDATORY_PATHS + tuple(item.path for item in optionals), monitor[1])
        self.assertEqual("capture", monitor[2])
        self.assertTrue(factory.calls[0]["read_only"])
        self.assertEqual(optionals, source.header.datarefs)
        self.assertFalse(hasattr(source, "client"))
        self.assertFalse(hasattr(source, "execute_command"))
        source.close()

    def test_rejects_optional_paths_that_collide_with_mandatory_output_ids(self) -> None:
        for mandatory_id in MANDATORY_IDS:
            with self.subTest(mandatory_id=mandatory_id):
                factory = FakeWebsocketFactory(initial_values())

                with self.assertRaisesRegex(ValueError, "mandatory output IDs"):
                    self.make_source(factory, header=make_header(FDRDataref(mandatory_id, 1, None)))

                self.assertEqual([], factory.calls)

    def test_missing_required_subscription_fails_before_sampling_and_closes(self) -> None:
        factory = FakeWebsocketFactory(initial_values(), missing_metadata=(MANDATORY_PATHS[2],))
        clock = FakeClock()

        with self.assertRaisesRegex(RuntimeError, "required FDR DataRefs"):
            self.make_source(factory, clock)

        self.assertEqual(0, clock.utc_calls)
        self.assertIn("session.close", factory.clients[0].events)

    def test_rejected_optional_is_removed_from_effective_header(self) -> None:
        accepted = FDRDataref("sim/test/ratio", 0.5, "ratio")
        rejected = FDRDataref("sim/test/rejected", 1, None)
        factory = FakeWebsocketFactory(initial_values(), missing_metadata=(rejected.path,))

        source = self.make_source(factory, header=make_header(accepted, rejected))

        self.assertEqual((accepted,), source.header.datarefs)
        source.close()

    def test_missing_initial_required_value_fails_before_timestamping_sample(self) -> None:
        values = initial_values()
        del values[MANDATORY_PATHS[4]]
        factory = FakeWebsocketFactory(values)
        clock = FakeClock()

        with self.assertRaisesRegex(RuntimeError, "initial values"):
            self.make_source(factory, clock)

        self.assertEqual(0, clock.utc_calls)
        self.assertAlmostEqual(2.0, sum(clock.wait_calls))
        self.assertAlmostEqual(12.0, clock.monotonic_now)
        self.assertIn("session.close", factory.clients[0].events)

    def test_delayed_initial_required_value_is_awaited_with_injected_wait(self) -> None:
        values = initial_values()
        delayed_path = MANDATORY_PATHS[4]
        delayed_value = values.pop(delayed_path)
        factory = FakeWebsocketFactory(values)
        clock = FakeClock()
        clock.on_wait = lambda: factory.clients[0].emit(delayed_path, delayed_value)
        source = self.make_source(factory, clock)

        sample = next(source.samples(threading.Event()))

        self.assertEqual([0.1], clock.wait_calls)
        self.assertEqual(datetime(2026, 8, 7, 18, 30, 0, 100000, tzinfo=UTC), sample.timestamp_utc)
        self.assertEqual(2.0, sample.values["pitch_deg"])
        source.close()

    def test_unobserved_accepted_optional_is_excluded_and_later_updates_are_ignored(self) -> None:
        values = initial_values()
        del values["sim/test/ratio"]
        factory = FakeWebsocketFactory(values)
        clock = FakeClock()
        source = self.make_source(factory, clock)

        first = next(source.samples(threading.Event()))
        factory.clients[0].emit("sim/test/ratio", 0.75)
        stop_event = threading.Event()
        samples = source.samples(stop_event)
        second = next(samples)

        self.assertEqual((), source.header.datarefs)
        self.assertNotIn("sim/test/ratio", first.values)
        self.assertNotIn("sim/test/ratio", second.values)
        source.close()

    def test_first_values_timeout_is_a_strict_positive_finite_float(self) -> None:
        for value in (0.0, -1.0, float("inf"), float("nan"), 1):
            with self.subTest(value=value):
                factory = FakeWebsocketFactory(initial_values())
                with self.assertRaisesRegex(ValueError, "first_values_timeout_seconds"):
                    self.make_source(factory, first_values_timeout_seconds=value)  # type: ignore[arg-type]
                self.assertEqual([], factory.calls)

    def test_normal_close_is_idempotent(self) -> None:
        factory = FakeWebsocketFactory(initial_values())
        source = self.make_source(factory)

        source.close()
        source.close()

        events = factory.clients[0].events
        self.assertEqual(1, sum(isinstance(event, tuple) and event[0] == "unmonitor" for event in events))
        self.assertEqual(1, sum(isinstance(event, tuple) and event[0] == "stop" for event in events))
        self.assertEqual(1, sum(isinstance(event, tuple) and event[0] == "disconnect" for event in events))
        self.assertEqual(1, events.count("session.close"))

    def test_samples_latest_values_at_injected_cadence_and_converts_metres_to_feet(self) -> None:
        factory = FakeWebsocketFactory(initial_values())
        clock = FakeClock()
        source = self.make_source(factory, clock, sample_interval_seconds=0.25)
        stop_event = threading.Event()
        samples = source.samples(stop_event)

        first = next(samples)
        clock.monotonic_now += 0.1

        def update_values() -> None:
            factory.clients[0].emit(MANDATORY_PATHS[0], -87.5)
            factory.clients[0].emit(MANDATORY_PATHS[2], 609.6)
            factory.clients[0].emit("sim/test/ratio", 0.75)

        clock.on_wait = update_values
        second = next(samples)
        stop_event.set()
        with self.assertRaises(StopIteration):
            next(samples)

        self.assertEqual(1, len(clock.wait_calls))
        self.assertAlmostEqual(0.15, clock.wait_calls[0])
        self.assertEqual(datetime(2026, 8, 7, 18, 30, tzinfo=UTC), first.timestamp_utc)
        self.assertEqual(datetime(2026, 8, 7, 18, 30, 0, 250000, tzinfo=UTC), second.timestamp_utc)
        self.assertEqual(1000.0, first.values["altitude_msl_ft"])
        self.assertEqual(2000.0, second.values["altitude_msl_ft"])
        self.assertEqual(-87.5, second.values["longitude"])
        self.assertEqual(0.75, second.values["sim/test/ratio"])
        self.assertEqual(
            ("longitude", "latitude", "altitude_msl_ft", "heading_magnetic_deg", "pitch_deg", "roll_deg", "sim/test/ratio"),
            tuple(second.values),
        )
        self.assertIs(UTC, second.timestamp_utc.tzinfo)
        source.close()

    def test_samples_preserve_original_phase_after_wait_oversleeps(self) -> None:
        factory = FakeWebsocketFactory(initial_values())
        clock = FakeClock()
        source = self.make_source(factory, clock, sample_interval_seconds=0.25)
        samples = source.samples(threading.Event())

        first = next(samples)

        def oversleep_once() -> None:
            clock.monotonic_now += 0.35
            clock.on_wait = None

        clock.on_wait = oversleep_once
        second = next(samples)
        third = next(samples)

        self.assertEqual(datetime(2026, 8, 7, 18, 30, tzinfo=UTC), first.timestamp_utc)
        self.assertEqual(datetime(2026, 8, 7, 18, 30, 0, 600000, tzinfo=UTC), second.timestamp_utc)
        self.assertEqual(datetime(2026, 8, 7, 18, 30, 0, 750000, tzinfo=UTC), third.timestamp_utc)
        self.assertEqual(2, len(clock.wait_calls))
        self.assertAlmostEqual(0.25, clock.wait_calls[0])
        self.assertAlmostEqual(0.15, clock.wait_calls[1])
        source.close()

    def test_samples_skip_slots_missed_during_snapshot_without_burst(self) -> None:
        factory = FakeWebsocketFactory(initial_values())
        clock = FakeClock()
        source = self.make_source(factory, clock, sample_interval_seconds=0.25)
        samples = source.samples(threading.Event())
        original_snapshot = source._snapshot
        snapshot_count = 0

        def slow_first_snapshot() -> Mapping[str, float]:
            nonlocal snapshot_count
            values = original_snapshot()
            snapshot_count += 1
            if snapshot_count == 1:
                clock.monotonic_now += 0.6
            return values

        with patch.object(source, "_snapshot", side_effect=slow_first_snapshot):
            first = next(samples)
            second = next(samples)

        self.assertEqual(datetime(2026, 8, 7, 18, 30, 0, 600000, tzinfo=UTC), first.timestamp_utc)
        self.assertEqual(datetime(2026, 8, 7, 18, 30, 0, 750000, tzinfo=UTC), second.timestamp_utc)
        self.assertEqual(1, len(clock.wait_calls))
        self.assertAlmostEqual(0.15, clock.wait_calls[0])
        source.close()

    def test_naive_injected_utc_clock_is_rejected(self) -> None:
        factory = FakeWebsocketFactory(initial_values())
        clock = FakeClock()
        source = LiveFDRSampleSource(
            config=WebsocketCaptureConfig(kind="websocket", host="127.0.0.1", port=8086),
            header=make_header(),
            sample_interval_seconds=1.0,
            subscription_timeout_seconds=2.0,
            client_factory=factory,
            monotonic_clock=clock.monotonic,
            utc_clock=lambda: datetime(2026, 8, 7, 18, 30),
            wait=clock.wait,
        )

        with self.assertRaisesRegex(ValueError, "aware UTC"):
            next(source.samples(threading.Event()))
        source.close()


if __name__ == "__main__":
    unittest.main()
