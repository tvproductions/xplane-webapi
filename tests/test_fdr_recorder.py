"""Tests for live and synthetic FDR sample-source composition."""

from __future__ import annotations

import threading
import unittest
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import xpwebapi.fdr.recorder as fdr_recorder_module
from xpwebapi.capture_protocol import WebsocketCaptureConfig
from xpwebapi.fdr import FDRReader, FDRWriter
from xpwebapi.fdr.models import FDRDataref, FDRHeader, FDRMetadata, FDRSample
from xpwebapi.fdr.recorder import (
    FDRRecorder,
    FDRRecordResult,
    FDRSampleSink,
    FDRSampleSource,
    FDRSourceSample,
    LiveFDRSampleSource,
)
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


class SyntheticSource:
    def __init__(
        self,
        header: FDRHeader,
        items: Sequence[FDRSourceSample | BaseException],
        *,
        close_error: BaseException | None = None,
    ) -> None:
        self.header = header
        self.items = items
        self.close_error = close_error
        self.close_count = 0

    def samples(self, stop_event: threading.Event):  # type: ignore[no-untyped-def]
        for item in self.items:
            if isinstance(item, BaseException):
                raise item
            yield item

    def close(self) -> None:
        self.close_count += 1
        if self.close_error is not None:
            raise self.close_error


class TimedSyntheticSource(SyntheticSource):
    def __init__(self, header: FDRHeader, clock: RecorderClock, samples: tuple[FDRSourceSample, ...]) -> None:
        super().__init__(header, [])
        self.clock = clock
        self.timed_samples = samples

    def samples(self, stop_event: threading.Event):  # type: ignore[no-untyped-def]
        for index, sample in enumerate(self.timed_samples):
            if index:
                self.clock.now += 2.0
            yield sample


class BlockingCloseSyntheticSource(SyntheticSource):
    def __init__(self, header: FDRHeader, samples: list[FDRSourceSample], entered: threading.Event, release: threading.Event) -> None:
        super().__init__(header, samples)
        self.entered = entered
        self.release = release

    def close(self) -> None:
        self.close_count += 1
        self.entered.set()
        self.release.wait()


class SyntheticSink:
    def __init__(
        self,
        *,
        on_write: Callable[[FDRSample], None] | None = None,
        commit_error: BaseException | None = None,
        abort_error: BaseException | None = None,
    ) -> None:
        self.samples: list[FDRSample] = []
        self.on_write = on_write
        self.commit_error = commit_error
        self.abort_error = abort_error
        self.commit_count = 0
        self.abort_count = 0
        self.destination_path = Path("final.fdr")
        self.partial_path = Path(".final.fdr.partial")

    def write_sample(self, sample: FDRSample) -> None:
        self.samples.append(sample)
        if self.on_write is not None:
            self.on_write(sample)

    def commit(self) -> None:
        self.commit_count += 1
        if self.commit_error is not None:
            raise self.commit_error

    def abort(self) -> None:
        self.abort_count += 1
        if self.abort_error is not None:
            raise self.abort_error


class RecorderClock:
    def __init__(self) -> None:
        self.now = 10.0

    def monotonic(self) -> float:
        return self.now


class InterruptingClock:
    def __init__(self, raise_on_call: int) -> None:
        self.raise_on_call = raise_on_call
        self.calls = 0

    def monotonic(self) -> float:
        self.calls += 1
        if self.calls == self.raise_on_call:
            raise KeyboardInterrupt
        return 10.0


class FDRRecorderTests(unittest.TestCase):
    def source_sample(self, second: int = 0, **changes: Any) -> FDRSourceSample:
        values: dict[str, Any] = {
            "longitude": -87.9048,
            "latitude": 41.9742,
            "altitude_msl_ft": 1000.0,
            "heading_magnetic_deg": 270.0,
            "pitch_deg": 2.0,
            "roll_deg": -1.0,
            "sim/test/zulu": 3.0,
            "sim/test/alpha": 4.0,
        }
        values.update(changes)
        return FDRSourceSample(datetime(2026, 8, 7, 18, 30, second, tzinfo=UTC), values)

    def test_maps_source_samples_in_header_order_and_returns_immutable_result(self) -> None:
        header = make_header(FDRDataref("sim/test/alpha", 1.0), FDRDataref("sim/test/zulu", 1.0))
        source = SyntheticSource(header, [self.source_sample(), self.source_sample(1, longitude=-87.5)])
        sink = SyntheticSink()

        with patch("signal.signal") as signal_handler:
            result = FDRRecorder(source=source, sink=sink).record(stop_event=threading.Event())

        self.assertIsInstance(result, FDRRecordResult)
        self.assertEqual(2, result.sample_count)
        self.assertEqual(datetime(2026, 8, 7, 18, 30, tzinfo=UTC), result.started_at_utc)
        self.assertEqual(datetime(2026, 8, 7, 18, 30, 1, tzinfo=UTC), result.ended_at_utc)
        self.assertEqual(timedelta(seconds=1), result.duration)
        self.assertEqual("source_exhausted", result.termination)
        self.assertEqual(Path("final.fdr"), result.final_path)
        self.assertIsNone(result.partial_path)
        self.assertEqual((4.0, 3.0), sink.samples[0].additional_values)
        self.assertEqual(1, source.close_count)
        self.assertEqual(1, sink.commit_count)
        self.assertEqual(0, sink.abort_count)
        signal_handler.assert_not_called()
        with self.assertRaises((AttributeError, TypeError)):
            result.sample_count = 3  # ty: ignore[invalid-assignment]

    def test_live_elevation_is_converted_from_metres_exactly_once_end_to_end(self) -> None:
        factory = FakeWebsocketFactory(initial_values())
        stop_event = threading.Event()
        sink = SyntheticSink(on_write=lambda _sample: stop_event.set())
        source = LiveFDRSampleSource(
            config=WebsocketCaptureConfig(kind="websocket", host="127.0.0.1", port=8086),
            header=make_header(),
            sample_interval_seconds=0.5,
            subscription_timeout_seconds=2.0,
            client_factory=factory,
            monotonic_clock=FakeClock().monotonic,
            utc_clock=lambda: datetime(2026, 8, 7, 18, 30, tzinfo=UTC),
            wait=FakeClock().wait,
        )

        result = FDRRecorder(source=source, sink=sink).record(stop_event=stop_event)

        self.assertEqual(1, result.sample_count)
        self.assertEqual(1000.0, sink.samples[0].altitude_msl_ft)

    def test_duration_and_stop_event_are_distinct_graceful_terminations(self) -> None:
        clock = RecorderClock()
        duration_source = TimedSyntheticSource(make_header(), clock, (self.source_sample(), self.source_sample(2)))
        duration_sink = SyntheticSink()
        duration_result = FDRRecorder(source=duration_source, sink=duration_sink, monotonic_clock=clock.monotonic).record(
            stop_event=threading.Event(), maximum_duration=2.0
        )
        self.assertEqual("duration_reached", duration_result.termination)
        self.assertEqual(1, duration_result.sample_count)

        stop_event = threading.Event()
        stop_sink = SyntheticSink(on_write=lambda _sample: stop_event.set())
        stop_result = FDRRecorder(source=SyntheticSource(make_header(), [self.source_sample(), self.source_sample(1)]), sink=stop_sink).record(
            stop_event=stop_event
        )
        self.assertEqual("stop_requested", stop_result.termination)
        self.assertEqual(1, stop_result.sample_count)

    def test_keyboard_interrupt_after_a_sample_commits_gracefully(self) -> None:
        source = SyntheticSource(make_header(), [self.source_sample(), KeyboardInterrupt()])
        sink = SyntheticSink()

        result = FDRRecorder(source=source, sink=sink).record(stop_event=threading.Event())

        self.assertEqual("keyboard_interrupt", result.termination)
        self.assertEqual(1, result.sample_count)
        self.assertEqual(1, sink.commit_count)
        self.assertEqual(1, source.close_count)

    def test_keyboard_interrupt_from_deadline_check_after_a_sample_is_graceful(self) -> None:
        clock = InterruptingClock(4)
        source = SyntheticSource(make_header(), [self.source_sample(), self.source_sample(1)])
        sink = SyntheticSink()

        result = FDRRecorder(source=source, sink=sink, monotonic_clock=clock.monotonic).record(stop_event=threading.Event(), maximum_duration=30.0)

        self.assertEqual("keyboard_interrupt", result.termination)
        self.assertEqual(1, result.sample_count)
        self.assertEqual(1, sink.commit_count)
        self.assertEqual(0, sink.abort_count)

    def test_keyboard_interrupt_during_mapping_after_a_sample_is_graceful_before_sink_mutation(self) -> None:
        original_mapping = fdr_recorder_module._sample_from_source
        mapping_calls = 0

        def interrupt_second_mapping(header: FDRHeader, source_sample: FDRSourceSample) -> FDRSample:
            nonlocal mapping_calls
            mapping_calls += 1
            if mapping_calls == 2:
                raise KeyboardInterrupt
            return original_mapping(header, source_sample)

        source = SyntheticSource(make_header(), [self.source_sample(), self.source_sample(1)])
        sink = SyntheticSink()
        with patch("xpwebapi.fdr.recorder._sample_from_source", side_effect=interrupt_second_mapping):
            result = FDRRecorder(source=source, sink=sink).record(stop_event=threading.Event())

        self.assertEqual("keyboard_interrupt", result.termination)
        self.assertEqual(1, result.sample_count)
        self.assertEqual(1, len(sink.samples))
        self.assertEqual(1, sink.commit_count)
        self.assertEqual(0, sink.abort_count)

    def test_keyboard_interrupt_during_termination_resolution_after_a_sample_is_graceful(self) -> None:
        source = SyntheticSource(make_header(), [self.source_sample()])
        sink = SyntheticSink()

        with patch.object(FDRRecorder, "_resolve_termination", side_effect=KeyboardInterrupt):
            result = FDRRecorder(source=source, sink=sink).record(stop_event=threading.Event())

        self.assertEqual("keyboard_interrupt", result.termination)
        self.assertEqual(1, result.sample_count)
        self.assertEqual(1, sink.commit_count)
        self.assertEqual(0, sink.abort_count)

    def test_keyboard_interrupt_from_sink_write_is_unsafe_and_never_commits(self) -> None:
        source = SyntheticSource(make_header(), [self.source_sample()])

        def interrupt_write(_sample: FDRSample) -> None:
            raise KeyboardInterrupt

        sink = SyntheticSink(on_write=interrupt_write)

        with self.assertRaises(KeyboardInterrupt):
            FDRRecorder(source=source, sink=sink).record(stop_event=threading.Event())

        self.assertEqual(0, sink.commit_count)
        self.assertEqual(1, sink.abort_count)
        self.assertEqual(1, source.close_count)

    def test_empty_or_invalid_sessions_abort_and_never_commit(self) -> None:
        invalid_optional_values = dict(self.source_sample().values)
        invalid_optional_values["sim/test/alpha"] = float("inf")
        invalid_optional = FDRSourceSample(self.source_sample().timestamp_utc, invalid_optional_values)
        cases: tuple[tuple[list[FDRSourceSample | BaseException], str], ...] = (
            ([], "without samples"),
            ([self.source_sample(longitude=float("nan"))], "longitude"),
            ([self.source_sample(pitch_deg=True)], "pitch_deg"),
            ([invalid_optional], "sim/test/alpha"),
            ([FDRSourceSample(self.source_sample().timestamp_utc, {"longitude": -87.9})], "missing"),
        )
        for items, message in cases:
            with self.subTest(message=message):
                source = SyntheticSource(make_header(FDRDataref("sim/test/alpha", 1.0)), items)
                sink = SyntheticSink()
                with self.assertRaisesRegex((ValueError, RuntimeError), message):
                    FDRRecorder(source=source, sink=sink).record(stop_event=threading.Event())
                self.assertEqual(0, sink.commit_count)
                self.assertEqual(1, sink.abort_count)
                self.assertEqual(1, source.close_count)

    def test_path_success_commits_and_runtime_failure_preserves_only_partial(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            successful_path = Path(temporary_directory, "successful.fdr")
            successful_source = SyntheticSource(make_header(), [self.source_sample()])
            successful_sink = FDRWriter().open(successful_source.header, successful_path)

            result = FDRRecorder(source=successful_source, sink=successful_sink).record(stop_event=threading.Event())

            self.assertEqual(successful_path, result.final_path)
            self.assertIsNone(result.partial_path)
            self.assertEqual(1, len(FDRReader().read(successful_path).samples))

            failed_path = Path(temporary_directory, "failed.fdr")
            failed_source = SyntheticSource(make_header(), [self.source_sample(), RuntimeError("source broke")])
            failed_sink = FDRWriter().open(failed_source.header, failed_path)
            expected_partial = failed_sink.partial_path

            with self.assertRaisesRegex(RuntimeError, "source broke"):
                FDRRecorder(source=failed_source, sink=failed_sink).record(stop_event=threading.Event())

            self.assertFalse(failed_path.exists())
            self.assertIsNotNone(expected_partial)
            self.assertTrue(expected_partial.is_file())  # type: ignore[union-attr]
            self.assertGreater(expected_partial.stat().st_size, 0)  # type: ignore[union-attr]

    def test_cleanup_and_commit_failures_abort_without_masking_evidence(self) -> None:
        source = SyntheticSource(make_header(), [self.source_sample()], close_error=RuntimeError("source close broke"))
        sink = SyntheticSink(abort_error=RuntimeError("sink abort broke"))

        with self.assertRaises(BaseExceptionGroup) as caught:
            FDRRecorder(source=source, sink=sink).record(stop_event=threading.Event())

        rendered = str(caught.exception)
        self.assertIn("cleanup", rendered)
        self.assertEqual(0, sink.commit_count)
        self.assertEqual(1, sink.abort_count)

        commit_sink = SyntheticSink(commit_error=RuntimeError("commit broke"))
        with self.assertRaisesRegex(RuntimeError, "commit broke"):
            FDRRecorder(source=SyntheticSource(make_header(), [self.source_sample()]), sink=commit_sink).record(stop_event=threading.Event())
        self.assertEqual(1, commit_sink.abort_count)

    def test_source_cleanup_has_an_injected_deadline(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        source = BlockingCloseSyntheticSource(make_header(), [self.source_sample()], entered, release)
        observed_timeouts: list[float] = []

        def timeout_wait(done: threading.Event, timeout: float) -> bool:
            observed_timeouts.append(timeout)
            if len(observed_timeouts) > 1:
                return done.wait(timeout)
            self.assertTrue(entered.wait(1.0))
            release.set()
            return False

        sink = SyntheticSink()
        with self.assertRaisesRegex(TimeoutError, "source cleanup"):
            FDRRecorder(source=source, sink=sink, cleanup_timeout_seconds=0.25, cleanup_wait=timeout_wait).record(stop_event=threading.Event())

        self.assertEqual([0.25, 0.25], observed_timeouts)
        self.assertEqual(1, sink.abort_count)
        self.assertEqual(0, sink.commit_count)


if __name__ == "__main__":
    unittest.main()
