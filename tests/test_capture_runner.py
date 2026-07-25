"""Deterministic lifecycle tests for the read-only capture runner."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, cast
from unittest.mock import patch

from xpwebapi.capture_events import CaptureEventIdentity, SourceProvenance, TransportCapabilities
from xpwebapi.capture_output import AtomicStatusWriter, CaptureEventWriter
from xpwebapi.capture_protocol import CaptureRequest
from xpwebapi.capture_runner import CaptureInterruption, CaptureOutcome, CaptureRunner
from xpwebapi.capture_transport import Observation, SubscriptionResult


class TimedValue:
    def __init__(self, value: object, observed_monotonic: float) -> None:
        self.value = value
        self.observed_monotonic = observed_monotonic


class FakeClock:
    def __init__(self, *, late_once: float = 0.0, on_wait: Any | None = None) -> None:
        self.now = 0.0
        self.base = datetime(2026, 7, 19, tzinfo=UTC)
        self.late_once = late_once
        self.waits: list[float] = []
        self.on_wait = on_wait

    def monotonic(self) -> float:
        return self.now

    def utcnow(self) -> datetime:
        return self.base + timedelta(seconds=self.now)

    def wait(self, event: threading.Event, timeout: float) -> bool:
        self.waits.append(timeout)
        self.now += max(0.0, timeout)
        if self.late_once:
            self.now += self.late_once
            self.late_once = 0.0
        if self.on_wait is not None:
            self.on_wait(event)
        return event.is_set()


class FakeTransport:
    def __init__(
        self,
        clock: FakeClock,
        log: list[str],
        *,
        observations: dict[str, object] | None = None,
        rejected: dict[str, str] | None = None,
        open_error: BaseException | None = None,
        open_advance: float = 0.0,
        subscribe_error: BaseException | None = None,
        disconnect_after_checks: int | None = None,
        close_error: BaseException | None = None,
        close_advance: float = 0.0,
        advance_on_capture: float = 0.0,
        refresh_identity_on_capture: bool = True,
        liveness_override: Literal["connected", "awaiting_first_identity_packet", "disconnected"] | None = None,
        on_subscribe: Any | None = None,
        on_open: Any | None = None,
        disconnect_on_subscribe: Literal["aircraft_identity", "capture"] | None = None,
    ) -> None:
        self.clock = clock
        self.log = log
        self.observations = observations or {}
        self.rejected = rejected or {}
        self.open_error = open_error
        self.open_advance = open_advance
        self.subscribe_error = subscribe_error
        self.disconnect_after_checks = disconnect_after_checks
        self.close_error = close_error
        self.close_advance = close_advance
        self.advance_on_capture = advance_on_capture
        self.refresh_identity_on_capture = refresh_identity_on_capture
        self.liveness_override = liveness_override
        self.on_subscribe = on_subscribe
        self.on_open = on_open
        self.disconnect_on_subscribe = disconnect_on_subscribe
        self._connected = False
        self.connected_checks = 0
        self.close_count = 0
        self.deadlines: list[float] = []
        self.identity_wait_deadlines: list[float | None] = []
        self.identity_callbacks: list[tuple[Any, Any]] = []
        self.callbacks_by_id: dict[str, Any] = {}

    @property
    def liveness_state(self) -> Literal["connected", "awaiting_first_identity_packet", "disconnected"]:
        if self.liveness_override is not None:
            return self.liveness_override
        return "connected" if self.connected else "disconnected"

    @property
    def connected(self) -> bool:
        self.connected_checks += 1
        if self.disconnect_after_checks is not None and self.connected_checks > self.disconnect_after_checks:
            self._connected = False
        return self._connected

    def open(self, deadline: float) -> TransportCapabilities:
        self.log.append("open")
        self.deadlines.append(deadline)
        self.clock.now += self.open_advance
        if self.on_open is not None:
            self.on_open()
        if self.open_error is not None:
            raise self.open_error
        self._connected = True
        return TransportCapabilities(
            transport="websocket",
            endpoint="ws://127.0.0.1:8086/api/v2",
            xplane_version="12.1",
            value_types=("int", "float", "double", "string"),
        )

    def subscribe(
        self,
        refs: Any,
        purpose: Literal["aircraft_identity", "capture"],
        callback: Any,
        deadline: float,
    ) -> SubscriptionResult:
        self.log.append(f"subscribe:{purpose}")
        self.deadlines.append(deadline)
        if self.subscribe_error is not None:
            raise self.subscribe_error
        if self.on_subscribe is not None:
            self.on_subscribe(purpose)
        if purpose == "capture" and self.advance_on_capture:
            self.clock.now += self.advance_on_capture
            if self.refresh_identity_on_capture:
                for identity_ref, identity_callback in self.identity_callbacks:
                    identity_callback(
                        Observation(
                            ref_id=identity_ref.id,
                            path=identity_ref.path,
                            value=self.observations[identity_ref.id],
                            observed_monotonic=self.clock.monotonic(),
                        )
                    )
        accepted: list[str] = []
        rejected: dict[str, str] = {}
        for ref in refs:
            if ref.id in self.rejected:
                rejected[ref.id] = self.rejected[ref.id]
                continue
            accepted.append(ref.id)
            if ref.id in self.observations:
                configured = self.observations[ref.id]
                value = configured.value if isinstance(configured, TimedValue) else configured
                observed_monotonic = configured.observed_monotonic if isinstance(configured, TimedValue) else self.clock.monotonic()
                callback(
                    Observation(
                        ref_id=ref.id,
                        path=ref.path,
                        value=value,
                        observed_monotonic=observed_monotonic,
                    )
                )
                if purpose == "aircraft_identity":
                    self.identity_callbacks.append((ref, callback))
                self.callbacks_by_id[ref.id] = callback
        if purpose == self.disconnect_on_subscribe:
            self._connected = False
            self.liveness_override = "disconnected"
        return SubscriptionResult(
            purpose=purpose,
            accepted_ref_ids=tuple(accepted),
            rejected=rejected,
            request_id=1,
        )

    def emit(self, ref_id: str, path: str, value: object) -> None:
        self.callbacks_by_id[ref_id](
            Observation(
                ref_id=ref_id,
                path=path,
                value=value,
                observed_monotonic=self.clock.monotonic(),
            )
        )

    def arm_identity_wait(self, deadline: float | None) -> None:
        self.identity_wait_deadlines.append(deadline)

    def close(self, deadline: float) -> None:
        self.log.append("close")
        self.close_count += 1
        self.deadlines.append(deadline)
        self.clock.now += self.close_advance
        self._connected = False
        if self.close_error is not None:
            raise self.close_error


class RecordingStatusWriter:
    def __init__(self, path: Path, log: list[str], *, fail_terminal_commit: bool = False) -> None:
        self.writer = AtomicStatusWriter(path)
        self.documents: list[Any] = []
        self.log = log
        self.fail_terminal_commit = fail_terminal_commit

    def write(self, document: Any, deadline: float | None = None, clock: Any | None = None) -> None:
        self.log.append(f"status:{document.state}")
        kwargs = {} if clock is None else {"clock": clock}
        self.writer.write(document, deadline=deadline, **kwargs)
        self.documents.append(document)

    def prepare(self, document: Any, deadline: float | None, clock: Any) -> Any:
        return self.writer.prepare(document, deadline=deadline, clock=clock)

    def commit(self, prepared: Any, deadline: float | None, clock: Any) -> None:
        if self.fail_terminal_commit and prepared.document.state in {"complete", "failed", "interrupted"}:
            raise OSError("terminal status replace failed")
        self.writer.commit(prepared, deadline=deadline, clock=clock)
        self.log.append(f"status:{prepared.document.state}")
        self.documents.append(prepared.document)

    def abort(self, prepared: Any, deadline: float | None = None, clock: Any | None = None) -> None:
        kwargs = {} if clock is None else {"clock": clock}
        self.writer.abort(prepared, deadline=deadline, **kwargs)


class FinalizationFaultStream:
    def __init__(self, stream: Any, fault: Literal["flush", "fsync", "close"]) -> None:
        self._stream = stream
        self._fault = fault

    def write(self, value: bytes) -> int:
        return self._stream.write(value)

    def flush(self) -> None:
        if self._fault == "flush":
            raise OSError("terminal event flush failed")
        self._stream.flush()

    def fileno(self) -> int:
        return self._stream.fileno()

    def close(self) -> None:
        self._stream.close()
        if self._fault == "close":
            raise OSError("terminal event close failed")


class FaultingEventWriter:
    def __init__(self, writer: CaptureEventWriter, fault: Literal["before", "flush", "fsync", "close"]) -> None:
        self.writer = writer
        self.fault = fault

    def __getattr__(self, name: str) -> Any:
        return getattr(self.writer, name)

    def commit_close(self, prepared: Any, deadline: float | None) -> Any:
        if self.fault == "before":
            raise OSError("terminal event commit failed before append")
        writer_for_fault_injection = cast(Any, self.writer)
        writer_for_fault_injection._stream = FinalizationFaultStream(self.writer._stream, self.fault)
        if self.fault == "fsync":
            with patch("xpwebapi.capture_output.os.fsync", side_effect=OSError("terminal event fsync failed")):
                return self.writer.commit_close(prepared, deadline)
        return self.writer.commit_close(prepared, deadline)


def make_request(
    *,
    refs: tuple[dict[str, object], ...] | None = None,
    groups: tuple[dict[str, object], ...] | None = None,
    capture_limit: float | None = None,
    retry: dict[str, object] | None = None,
) -> CaptureRequest:
    if groups is None:
        groups = ({"id": "fast", "rate_hz": 10.0, "duration_seconds": 0.2},)
    if refs is None:
        refs = (
            {
                "id": "speed",
                "path": "sim/flightmodel/position/groundspeed",
                "declared_type": "float",
                "availability": "required",
                "sample_group_id": "fast",
                "encoding": None,
            },
        )
    retry_values: dict[str, object] = {
        "initial_attempts": 2,
        "reconnect_attempts": 2,
        "backoff_seconds": 0.01,
        "backoff_max_seconds": 0.02,
        "subscription_timeout_seconds": 0.2,
        "aircraft_identity_timeout_seconds": 0.2,
        "first_values_timeout_seconds": 0.2,
        "max_disconnect_seconds": 0.2,
        "stale_after_seconds": 2.0,
        "poll_interval_seconds": 0.01,
        "shutdown_timeout_seconds": 0.2,
    }
    retry_values.update(retry or {})
    return CaptureRequest.model_validate(
        {
            "protocol_version": 1,
            "capture_session_id": "capture-1",
            "sortie_id": "sortie-1",
            "correlation": {
                "campaign_id": "campaign",
                "route_profile_id": "route",
                "scenario_id": "scenario",
            },
            "identity_readiness": {
                "kind": "dataref_match",
                "target_aircraft": "FlyJSim Q4XP",
                "refs": (
                    {
                        "id": "aircraft",
                        "path": "sim/aircraft/view/acf_relative_path",
                        "declared_type": "string",
                        "encoding": "utf-8",
                        "rate_hz": 1.0,
                        "operator": "contains",
                        "expected_value": "Q4XP",
                    },
                ),
            },
            "transport": {
                "kind": "websocket",
                "host": "127.0.0.1",
                "port": 8086,
                "api_path": "/api",
                "api_version": "v2",
                "http_timeout_seconds": 0.2,
                "open_timeout_seconds": 0.2,
                "close_timeout_seconds": 0.2,
            },
            "sample_groups": groups,
            "refs": refs,
            "retry": retry_values,
            "capture_limit_seconds": capture_limit,
            "stop_file": None,
        }
    )


PROVENANCE = SourceProvenance(
    package_name="xpwebapi",
    package_version="1.0",
    python_version="3.12",
    git_state="unavailable",
    git_root=None,
    git_revision=None,
    git_origin=None,
    git_dirty=None,
    read_only=True,
)


class CaptureRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.events = self.root / "events.jsonl"
        self.status = self.root / "status.json"

    def build(
        self,
        request: CaptureRequest,
        transports: list[FakeTransport],
        clock: FakeClock,
        *,
        stop_file: Path | None = None,
        log: list[str] | None = None,
        interruption_signal: Literal["SIGINT", "SIGTERM"] = "SIGINT",
        fail_terminal_status_commit: bool = False,
        event_commit_fault: Literal["before", "flush", "fsync", "close"] | None = None,
    ) -> tuple[CaptureRunner, RecordingStatusWriter]:
        activity = log if log is not None else []
        writer = CaptureEventWriter(
            self.events,
            CaptureEventIdentity(capture_session_id=request.capture_session_id, sortie_id=request.sortie_id),
            clock,
        )
        event_writer: Any = FaultingEventWriter(writer, event_commit_fault) if event_commit_fault is not None else writer
        status_writer = RecordingStatusWriter(
            self.status,
            activity,
            fail_terminal_commit=fail_terminal_status_commit,
        )
        interruption = CaptureInterruption()
        interruption.set(interruption_signal)
        pending = list(transports)

        def factory() -> FakeTransport:
            activity.append("factory")
            if not pending:
                raise RuntimeError("unexpected transport factory call")
            return pending.pop(0)

        return (
            CaptureRunner(
                request=request,
                request_sha256="a" * 64,
                provenance=PROVENANCE,
                stop_file=stop_file,
                transport_factory=cast(Any, factory),
                event_writer=event_writer,
                status_writer=cast(AtomicStatusWriter, status_writer),
                clock=clock,
                events_path=self.events,
                interruption=interruption,
            ),
            status_writer,
        )

    def rows(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in self.events.read_text(encoding="utf-8").splitlines()]

    def test_outcome_exit_codes_are_stable(self) -> None:
        def outcome(state: Literal["complete", "failed", "interrupted"], *, clean: bool = False) -> CaptureOutcome:
            return CaptureOutcome(
                terminal_state=state,
                termination="x",
                reason=None,
                transport_ready=False,
                aircraft_ready=False,
                sample_count=0,
                gap_count=0,
                retry_count=0,
                clean_shutdown=clean,
            )

        self.assertEqual(3, outcome("complete").exit_code)
        self.assertEqual(3, outcome("failed").exit_code)
        self.assertEqual(130, outcome("interrupted").exit_code)

        self.assertEqual(0, outcome("complete", clean=True).exit_code)

    def test_status_and_evidence_open_before_transport_and_readiness_order(self) -> None:
        clock = FakeClock()
        log: list[str] = []
        transport = FakeTransport(clock, log, observations={"aircraft": "Aircraft/Q4XP.acf", "speed": 42.0})
        runner, statuses = self.build(make_request(), [transport], clock, log=log)
        outcome = runner.run(threading.Event(), threading.Event())

        self.assertEqual("complete", outcome.terminal_state)
        self.assertLess(log.index("status:starting"), log.index("factory"))
        self.assertLess(log.index("status:transport_ready"), log.index("subscribe:aircraft_identity"))
        self.assertLess(log.index("subscribe:aircraft_identity"), log.index("subscribe:capture"))
        states = [document.state for document in statuses.documents]
        self.assertIn("aircraft_ready", states)
        rows = self.rows()
        self.assertEqual("capture_started", rows[0]["event"])
        self.assertLess(
            next(index for index, row in enumerate(rows) if row["event"] == "transport_ready"),
            next(index for index, row in enumerate(rows) if row["event"] == "subscription_result"),
        )

    def test_identity_mismatch_fails_before_capture_subscription(self) -> None:
        clock = FakeClock()
        log: list[str] = []
        transport = FakeTransport(clock, log, observations={"aircraft": "Aircraft/C172.acf", "speed": 1.0})
        runner, _ = self.build(make_request(), [transport], clock, log=log)
        outcome = runner.run(threading.Event(), threading.Event())
        self.assertEqual("failed", outcome.terminal_state)
        self.assertEqual("aircraft_identity_timeout", outcome.reason)
        self.assertNotIn("subscribe:capture", log)

    def test_unbounded_identity_wait_can_exceed_former_five_minute_limit(self) -> None:
        log: list[str] = []
        clock = FakeClock()
        transport = FakeTransport(
            clock,
            log,
            observations={
                "aircraft": "Aircraft/Cessna_172SP.acf",
                "speed": 42.0,
            },
        )
        emitted_q4xp = False

        def load_q4xp(_event: threading.Event) -> None:
            nonlocal emitted_q4xp
            if not emitted_q4xp and clock.now > 301.0:
                emitted_q4xp = True
                transport.emit(
                    "aircraft",
                    "sim/aircraft/view/acf_relative_path",
                    "Aircraft/Q4XP.acf",
                )

        clock.on_wait = load_q4xp
        request = make_request(
            capture_limit=0.1,
            retry={
                "aircraft_identity_timeout_seconds": None,
                "poll_interval_seconds": 1.0,
            },
        )
        runner, _status = self.build(request, [transport], clock)

        outcome = runner.run(threading.Event(), threading.Event())

        self.assertEqual("complete", outcome.terminal_state)
        self.assertGreater(clock.now, 301.0)
        self.assertTrue(emitted_q4xp)
        self.assertIn("subscribe:capture", log)

    def test_required_rejection_fails_but_optional_rejection_completes(self) -> None:
        clock = FakeClock()
        log: list[str] = []
        required = FakeTransport(
            clock,
            log,
            observations={"aircraft": "Q4XP"},
            rejected={"speed": "unsupported"},
        )
        outcome = self.build(make_request(), [required], clock, log=log)[0].run(threading.Event(), threading.Event())
        self.assertEqual("failed", outcome.terminal_state)
        self.assertIn("required capture refs rejected", outcome.reason or "")

        self.events = self.root / "optional-events.jsonl"
        self.status = self.root / "optional-status.json"
        optional_ref: tuple[dict[str, object], ...] = (
            {
                "id": "optional",
                "path": "sim/optional",
                "declared_type": "float",
                "availability": "optional",
                "sample_group_id": "fast",
                "encoding": None,
            },
        )
        second = FakeTransport(clock, log, observations={"aircraft": "Q4XP"}, rejected={"optional": "unsupported"})
        optional_outcome = self.build(make_request(refs=optional_ref), [second], clock, log=log)[0].run(threading.Event(), threading.Event())
        self.assertEqual("groups_complete", optional_outcome.termination)

    def test_identity_only_probe_completes_without_hanging(self) -> None:
        clock = FakeClock()
        transport = FakeTransport(clock, [], observations={"aircraft": "Q4XP"})
        runner, _ = self.build(make_request(refs=(), groups=()), [transport], clock)
        outcome = runner.run(threading.Event(), threading.Event())
        self.assertEqual("complete", outcome.terminal_state)
        self.assertEqual("groups_complete", outcome.termination)
        self.assertTrue(outcome.aircraft_ready)

    def test_required_first_value_timeout_is_exact_and_preserves_latches(self) -> None:
        clock = FakeClock()
        transport = FakeTransport(clock, [], observations={"aircraft": "Q4XP"})
        runner, statuses = self.build(make_request(), [transport], clock)
        outcome = runner.run(threading.Event(), threading.Event())
        self.assertEqual("first_values_timeout", outcome.reason)
        self.assertAlmostEqual(0.2, clock.now, places=6)
        terminal = statuses.documents[-1]
        self.assertIsNotNone(terminal.transport_ready_at_utc)
        self.assertIsNone(terminal.aircraft_ready_at_utc)

    def test_required_first_value_must_be_fresh_for_the_current_subscription(self) -> None:
        clock = FakeClock()
        transport = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP", "speed": TimedValue(10.0, 0.0)},
            advance_on_capture=3.0,
        )
        runner, _ = self.build(make_request(), [transport], clock)
        outcome = runner.run(threading.Event(), threading.Event())
        self.assertEqual("failed", outcome.terminal_state)
        self.assertEqual("first_values_timeout", outcome.reason)
        self.assertFalse(outcome.aircraft_ready)

    def test_static_identity_observation_remains_valid_after_capture_subscription_delay(self) -> None:
        clock = FakeClock()
        request = make_request(retry={"stale_after_seconds": 2.0})
        transport = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP", "speed": 10.0},
            advance_on_capture=3.0,
            refresh_identity_on_capture=False,
        )

        outcome = self.build(request, [transport], clock)[0].run(threading.Event(), threading.Event())

        self.assertEqual("complete", outcome.terminal_state)
        self.assertTrue(outcome.aircraft_ready)

    def test_later_identity_mismatch_invalidates_a_stale_cached_match(self) -> None:
        transport_box: list[FakeTransport] = []

        def lose_identity(_event: threading.Event) -> None:
            transport_box[0].emit("aircraft", "sim/aircraft/view/acf_relative_path", "C172")

        clock = FakeClock(on_wait=lose_identity)
        request = make_request(retry={"stale_after_seconds": 2.0})
        transport = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP", "speed": 1.0},
            advance_on_capture=3.0,
            refresh_identity_on_capture=False,
        )
        transport_box.append(transport)

        outcome = self.build(request, [transport], clock)[0].run(threading.Event(), threading.Event())

        self.assertEqual("aircraft_identity_lost", outcome.reason)
        self.assertEqual(1, len([row for row in self.rows() if row["event"] == "sample"]))

    def test_disconnect_during_identity_wait_reconnects_instead_of_waiting_for_timeout(self) -> None:
        clock = FakeClock()
        first = FakeTransport(clock, [], disconnect_on_subscribe="aircraft_identity")
        second = FakeTransport(clock, [], observations={"aircraft": "Q4XP", "speed": 2.0})
        outcome = self.build(make_request(), [first, second], clock)[0].run(threading.Event(), threading.Event())
        self.assertEqual("complete", outcome.terminal_state)
        disconnected = [row for row in self.rows() if row["event"] == "transport_state" and row["state"] == "disconnected"]
        self.assertEqual(1, len(disconnected))

    def test_disconnect_during_first_value_wait_reconnects(self) -> None:
        clock = FakeClock()
        first = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP"},
            disconnect_on_subscribe="capture",
        )
        second = FakeTransport(clock, [], observations={"aircraft": "Q4XP", "speed": 2.0})
        outcome = self.build(make_request(), [first, second], clock)[0].run(threading.Event(), threading.Event())
        self.assertEqual("complete", outcome.terminal_state)
        self.assertEqual(1, len([row for row in self.rows() if row["event"] == "aircraft_ready"]))

    def test_reconnect_readiness_deadlines_are_clamped_to_disconnect_deadline(self) -> None:
        clock = FakeClock()
        first = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP", "speed": 1.0},
            disconnect_after_checks=3,
        )
        second = FakeTransport(clock, [], observations={})
        outcome = self.build(
            make_request(
                retry={
                    "max_disconnect_seconds": 0.05,
                    "aircraft_identity_timeout_seconds": 0.2,
                    "first_values_timeout_seconds": 0.2,
                }
            ),
            [first, second],
            clock,
        )[0].run(threading.Event(), threading.Event())
        self.assertEqual("aircraft_identity_timeout", outcome.reason)
        self.assertLessEqual(clock.now, 0.05)
        self.assertTrue(all(deadline <= 0.05 for deadline in second.deadlines))

    def test_identity_subscription_operations_are_bounded_separately_from_readiness(self) -> None:
        clock = FakeClock()
        request = make_request(
            retry={
                "subscription_timeout_seconds": 10.0,
                "aircraft_identity_timeout_seconds": 300.0,
                "max_disconnect_seconds": 30.0,
            }
        )
        first = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP", "speed": 1.0},
            disconnect_after_checks=3,
        )
        second = FakeTransport(clock, [], observations={"aircraft": "Q4XP", "speed": 2.0})

        outcome = self.build(request, [first, second], clock)[0].run(threading.Event(), threading.Event())

        self.assertEqual("complete", outcome.terminal_state)
        self.assertEqual(10.0, first.deadlines[1])
        self.assertEqual([300.0], first.identity_wait_deadlines)
        self.assertEqual(10.0, second.deadlines[1])
        self.assertEqual([30.0], second.identity_wait_deadlines)

    def test_first_sample_occurs_at_aircraft_ready_and_status_polling_does_not_touch_jsonl(self) -> None:
        clock = FakeClock()
        transport = FakeTransport(clock, [], observations={"aircraft": "Q4XP", "speed": 12.0})
        runner, statuses = self.build(make_request(), [transport], clock)
        runner.run(threading.Event(), threading.Event())
        rows = self.rows()
        ready = next(row for row in rows if row["event"] == "aircraft_ready")
        first_sample = next(row for row in rows if row["event"] == "sample")
        self.assertEqual(ready["elapsed_seconds"], first_sample["elapsed_seconds"])
        before = self.events.read_bytes()
        statuses.writer.write  # polling the status path is external and read-only
        self.status.read_bytes()
        self.assertEqual(before, self.events.read_bytes())

    def test_late_scheduler_records_gap_without_burst_catch_up(self) -> None:
        clock = FakeClock(late_once=2.2)
        request = make_request(
            groups=({"id": "fast", "rate_hz": 1.0, "duration_seconds": 4.0},),
            refs=(
                {
                    "id": "speed",
                    "path": "sim/speed",
                    "declared_type": "float",
                    "availability": "required",
                    "sample_group_id": "fast",
                    "encoding": None,
                },
            ),
            retry={"poll_interval_seconds": 1.0, "stale_after_seconds": 10.0},
        )
        transport = FakeTransport(clock, [], observations={"aircraft": "Q4XP", "speed": 2.0})
        outcome = self.build(request, [transport], clock)[0].run(threading.Event(), threading.Event())
        rows = self.rows()
        samples = [row for row in rows if row["event"] == "sample"]
        gaps = [row for row in rows if row["event"] == "gap_ended"]
        self.assertEqual(2, len(samples))
        self.assertEqual(2, gaps[0]["skipped_slot_count"])
        self.assertEqual("complete", outcome.terminal_state)

    def test_sample_statuses_cover_missing_unsupported_invalid_stale_and_sampled(self) -> None:
        refs: tuple[dict[str, object], ...] = (
            {"id": "good", "path": "sim/good", "declared_type": "float", "availability": "required", "sample_group_id": "fast", "encoding": None},
            {"id": "missing", "path": "sim/missing", "declared_type": "float", "availability": "optional", "sample_group_id": "fast", "encoding": None},
            {"id": "bad", "path": "sim/bad", "declared_type": "int", "availability": "optional", "sample_group_id": "fast", "encoding": None},
            {"id": "old", "path": "sim/old", "declared_type": "float", "availability": "optional", "sample_group_id": "fast", "encoding": None},
            {"id": "unsupported", "path": "sim/unsupported", "declared_type": "float", "availability": "optional", "sample_group_id": "fast", "encoding": None},
        )
        clock = FakeClock()
        transport = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP", "good": 1.5, "bad": "wrong", "old": TimedValue(3.0, 0.0)},
            rejected={"unsupported": "no metadata"},
            advance_on_capture=3.0,
        )
        self.build(make_request(refs=refs), [transport], clock)[0].run(threading.Event(), threading.Event())
        statuses = {row["status"] for row in self.rows() if row["event"] == "sample"}
        self.assertTrue(
            {"sampled", "missing", "unsupported", "invalid", "stale"}.issubset(statuses),
            statuses,
        )

    def test_reconnect_uses_fresh_transport_and_fresh_observations(self) -> None:
        clock = FakeClock()
        log: list[str] = []
        first = FakeTransport(
            clock,
            log,
            observations={"aircraft": "Q4XP", "speed": 1.0},
            disconnect_after_checks=3,
        )
        second = FakeTransport(clock, log, observations={"aircraft": "Q4XP", "speed": 2.0})
        outcome = self.build(make_request(), [first, second], clock, log=log)[0].run(threading.Event(), threading.Event())
        self.assertEqual("complete", outcome.terminal_state)
        self.assertEqual(2, log.count("factory"))
        self.assertEqual(1, first.close_count)
        ready_rows = [row for row in self.rows() if row["event"] == "aircraft_ready"]
        self.assertEqual([1, 2], [row["connection_generation"] for row in ready_rows])
        status_documents = json.loads(self.status.read_text(encoding="utf-8"))
        self.assertIsNotNone(status_documents["transport_ready_at_utc"])
        self.assertIsNotNone(status_documents["aircraft_ready_at_utc"])
        self.assertIn("disconnected", {row.get("status") for row in self.rows() if row["event"] == "sample"})
        sampled_values = [row["value"] for row in self.rows() if row["event"] == "sample" and row["status"] == "sampled"]
        self.assertIn(2.0, sampled_values)

    def test_late_callback_from_closed_generation_cannot_satisfy_reconnect_readiness(self) -> None:
        clock = FakeClock()
        first = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP", "speed": 1.0},
            disconnect_after_checks=3,
        )

        def emit_old_generation(purpose: str) -> None:
            if purpose == "capture":
                first.emit("speed", "sim/flightmodel/position/groundspeed", 99.0)

        second = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP"},
            on_subscribe=emit_old_generation,
        )
        outcome = self.build(make_request(), [first, second], clock)[0].run(threading.Event(), threading.Event())
        self.assertEqual("complete", outcome.terminal_state)
        self.assertEqual("groups_complete", outcome.termination)
        self.assertTrue(outcome.clean_shutdown)
        rows = self.rows()
        self.assertEqual(1, len([row for row in rows if row["event"] == "aircraft_ready"]))
        self.assertFalse(any(row.get("event") == "sample" and row.get("value") == 99.0 for row in rows))

    def test_initial_attempts_and_disconnect_duration_exhaust_independently(self) -> None:
        clock = FakeClock()
        failed = FakeTransport(clock, [], open_error=ConnectionError("no endpoint"))
        failed2 = FakeTransport(clock, [], open_error=ConnectionError("still no endpoint"))
        outcome = self.build(make_request(), [failed, failed2], clock)[0].run(threading.Event(), threading.Event())
        self.assertEqual("failed", outcome.terminal_state)
        self.assertEqual(2, outcome.retry_count)
        self.assertIn("initial_connect_exhausted", outcome.reason or "")

        self.events = self.root / "reconnect-events.jsonl"
        self.status = self.root / "reconnect-status.json"
        clock = FakeClock()
        first = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP", "speed": 1.0},
            disconnect_after_checks=3,
        )
        reconnect1 = FakeTransport(clock, [], open_error=ConnectionError("retry one"))
        reconnect2 = FakeTransport(clock, [], open_error=ConnectionError("retry two"))
        reconnect_outcome = self.build(make_request(), [first, reconnect1, reconnect2], clock)[0].run(threading.Event(), threading.Event())
        self.assertIn("reconnect_attempts_exhausted", reconnect_outcome.reason or "")

        self.events = self.root / "duration-events.jsonl"
        self.status = self.root / "duration-status.json"
        clock = FakeClock()
        first = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP", "speed": 1.0},
            disconnect_after_checks=3,
        )
        slow_failure = FakeTransport(
            clock,
            [],
            open_error=ConnectionError("slow failure"),
            open_advance=0.3,
        )
        duration_outcome = self.build(
            make_request(retry={"max_disconnect_seconds": 0.2}),
            [first, slow_failure],
            clock,
        )[0].run(threading.Event(), threading.Event())
        self.assertEqual("complete", duration_outcome.terminal_state)
        self.assertEqual("groups_complete", duration_outcome.termination)
        self.assertTrue(duration_outcome.clean_shutdown)
        self.assertEqual(0, duration_outcome.exit_code)

    def test_awaiting_first_udp_identity_packet_uses_identity_deadline_without_reconnect(self) -> None:
        clock = FakeClock()
        log: list[str] = []
        transport = FakeTransport(
            clock,
            log,
            observations={},
            liveness_override="awaiting_first_identity_packet",
        )
        outcome = self.build(make_request(), [transport], clock, log=log)[0].run(threading.Event(), threading.Event())
        self.assertEqual("aircraft_identity_timeout", outcome.reason)
        self.assertEqual(1, log.count("factory"))

    def test_stop_file_capture_limit_programmatic_stop_and_interruption(self) -> None:
        cases = ("stop_file", "capture_limit", "requested", "interrupted")
        for index, case in enumerate(cases):
            with self.subTest(case=case):
                self.events = self.root / f"events-{index}.jsonl"
                self.status = self.root / f"status-{index}.json"
                clock = FakeClock()
                stop_path = self.root / f"stop-{index}"
                request = make_request(
                    groups=({"id": "fast", "rate_hz": 10.0, "duration_seconds": None},), capture_limit=0.05 if case == "capture_limit" else None
                )
                transport = FakeTransport(clock, [], observations={"aircraft": "Q4XP", "speed": 1.0})
                runner, _ = self.build(request, [transport], clock, stop_file=stop_path if case == "stop_file" else None)
                stop = threading.Event()
                interrupted = threading.Event()
                if case == "stop_file":
                    stop_path.touch()
                elif case == "requested":
                    stop.set()
                elif case == "interrupted":
                    interrupted.set()
                outcome = runner.run(stop, interrupted)
                if case == "interrupted":
                    self.assertEqual(130, outcome.exit_code)
                else:
                    self.assertEqual(case, outcome.termination)
                    self.assertEqual(0, outcome.exit_code)

    def test_preexisting_requested_and_stop_file_terminate_before_transport_factory(self) -> None:
        for index, termination in enumerate(("requested", "stop_file")):
            with self.subTest(termination=termination):
                self.events = self.root / f"pre-ready-{index}.jsonl"
                self.status = self.root / f"pre-ready-{index}.json"
                clock = FakeClock()
                log: list[str] = []
                stop_file = self.root / f"pre-ready-{index}.stop"
                stop_event = threading.Event()
                if termination == "requested":
                    stop_event.set()
                else:
                    stop_file.touch()
                runner, _ = self.build(
                    make_request(),
                    [FakeTransport(clock, log)],
                    clock,
                    stop_file=stop_file if termination == "stop_file" else None,
                    log=log,
                )

                outcome = runner.run(stop_event, threading.Event())

                self.assertEqual("complete", outcome.terminal_state)
                self.assertEqual(termination, outcome.termination)
                self.assertTrue(outcome.clean_shutdown)
                self.assertNotIn("factory", log)
                self.assertEqual(["capture_started", "capture_stopped"], [row["event"] for row in self.rows()])
                self.assertEqual("complete", json.loads(self.status.read_text(encoding="utf-8"))["state"])

    def test_requested_stop_is_observed_in_retry_identity_and_first_value_waits(self) -> None:
        for index, phase in enumerate(("open", "retry", "identity", "first_values")):
            with self.subTest(phase=phase):
                self.events = self.root / f"wait-stop-{index}.jsonl"
                self.status = self.root / f"wait-stop-{index}.json"
                stop_event = threading.Event()
                clock = FakeClock(on_wait=lambda _event: stop_event.set())
                log: list[str] = []
                if phase == "open":
                    first = FakeTransport(clock, log, on_open=stop_event.set)
                elif phase == "retry":
                    first = FakeTransport(clock, log, open_error=ConnectionError("retry"))
                elif phase == "first_values":
                    first = FakeTransport(clock, log, observations={"aircraft": "Q4XP"})
                else:
                    first = FakeTransport(clock, log)
                transports = [first]
                if phase == "retry":
                    transports.append(FakeTransport(clock, log, observations={"aircraft": "Q4XP", "speed": 1.0}))
                runner, _ = self.build(make_request(), transports, clock, log=log)

                outcome = runner.run(stop_event, threading.Event())

                self.assertEqual("complete", outcome.terminal_state)
                self.assertEqual("requested", outcome.termination)
                self.assertTrue(outcome.clean_shutdown)
                self.assertEqual(1, log.count("factory"))
                self.assertEqual("capture_stopped", self.rows()[-1]["event"])

    def test_stop_file_created_during_first_value_wait_completes_cleanly(self) -> None:
        stop_file = self.root / "during-first-values.stop"
        clock = FakeClock(on_wait=lambda _event: stop_file.touch())
        transport = FakeTransport(clock, [], observations={"aircraft": "Q4XP"})
        runner, _ = self.build(make_request(), [transport], clock, stop_file=stop_file)

        outcome = runner.run(threading.Event(), threading.Event())

        self.assertEqual("complete", outcome.terminal_state)
        self.assertEqual("stop_file", outcome.termination)
        self.assertTrue(outcome.clean_shutdown)
        self.assertEqual("capture_stopped", self.rows()[-1]["event"])

    def test_reconnect_samples_only_due_disconnected_slots_without_burst(self) -> None:
        clock = FakeClock()
        request = make_request(
            groups=({"id": "fast", "rate_hz": 10.0, "duration_seconds": 0.5},),
            retry={
                "reconnect_attempts": 3,
                "backoff_seconds": 0.25,
                "backoff_max_seconds": 0.25,
                "max_disconnect_seconds": 0.5,
                "poll_interval_seconds": 0.01,
            },
        )
        first = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP", "speed": 1.0},
            disconnect_after_checks=4,
        )
        failed = FakeTransport(clock, [], open_error=ConnectionError("retry"))
        recovered = FakeTransport(clock, [], observations={"aircraft": "Q4XP", "speed": 2.0})

        outcome = self.build(request, [first, failed, recovered], clock)[0].run(threading.Event(), threading.Event())

        disconnected = [row for row in self.rows() if row["event"] == "sample" and row["status"] == "disconnected"]
        self.assertEqual(2, len(disconnected))
        self.assertEqual([0.1, 0.2], [round(cast(float, row["elapsed_seconds"]), 1) for row in disconnected])
        self.assertEqual(2, len({row["elapsed_seconds"] for row in disconnected}))
        self.assertEqual("complete", outcome.terminal_state)

    def test_bounded_groups_complete_during_reconnect_open_backoff_and_readiness(self) -> None:
        for index, phase in enumerate(("open", "backoff", "readiness")):
            with self.subTest(phase=phase):
                self.events = self.root / f"group-expiry-{index}.jsonl"
                self.status = self.root / f"group-expiry-{index}.json"
                clock = FakeClock()
                request = make_request(
                    groups=({"id": "fast", "rate_hz": 10.0, "duration_seconds": 0.15},),
                    retry={
                        "reconnect_attempts": 3,
                        "backoff_seconds": 0.25,
                        "backoff_max_seconds": 0.25,
                        "poll_interval_seconds": 0.1,
                        "first_values_timeout_seconds": 0.3,
                        "max_disconnect_seconds": 0.5,
                    },
                )
                first = FakeTransport(
                    clock,
                    [],
                    observations={"aircraft": "Q4XP", "speed": 1.0},
                    disconnect_after_checks=4,
                )
                if phase == "open":
                    reconnecting = [
                        FakeTransport(
                            clock,
                            [],
                            observations={"aircraft": "Q4XP", "speed": 2.0},
                            open_advance=0.1,
                        )
                    ]
                elif phase == "backoff":
                    reconnecting = [
                        FakeTransport(clock, [], open_error=ConnectionError("retry")),
                        FakeTransport(clock, [], observations={"aircraft": "Q4XP", "speed": 2.0}),
                    ]
                else:
                    reconnecting = [FakeTransport(clock, [], observations={"aircraft": "Q4XP"})]

                outcome = self.build(request, [first, *reconnecting], clock)[0].run(
                    threading.Event(),
                    threading.Event(),
                )

                self.assertEqual("complete", outcome.terminal_state)
                self.assertEqual("groups_complete", outcome.termination)
                self.assertTrue(outcome.clean_shutdown)
                self.assertGreaterEqual(clock.now, 0.15)
                self.assertLess(clock.now, 0.21)
                self.assertEqual("capture_stopped", self.rows()[-1]["event"])
                disconnected_elapsed = [
                    cast(float, row["elapsed_seconds"]) for row in self.rows() if row["event"] == "sample" and row["status"] == "disconnected"
                ]
                self.assertTrue(all(elapsed < 0.15 for elapsed in disconnected_elapsed))

    def test_reconnect_boundary_stop_precedes_disconnected_sample(self) -> None:
        clock = FakeClock()
        stop_event = threading.Event()
        request = make_request(groups=({"id": "fast", "rate_hz": 10.0, "duration_seconds": 0.5},))
        first = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP", "speed": 1.0},
            disconnect_after_checks=4,
        )
        recovered = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP", "speed": 2.0},
            open_advance=0.1,
            on_open=stop_event.set,
        )

        outcome = self.build(request, [first, recovered], clock)[0].run(stop_event, threading.Event())

        self.assertEqual("requested", outcome.termination)
        self.assertNotIn("disconnected", {row.get("status") for row in self.rows() if row["event"] == "sample"})

    def test_reconnect_subscription_boundary_sigterm_precedes_disconnected_sample(self) -> None:
        clock = FakeClock()
        interrupted = threading.Event()
        request = make_request(groups=({"id": "fast", "rate_hz": 10.0, "duration_seconds": 0.5},))
        first = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP", "speed": 1.0},
            disconnect_after_checks=4,
        )

        def interrupt_during_capture_subscription(purpose: str) -> None:
            if purpose == "capture":
                clock.now += 0.1
                interrupted.set()

        recovered = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP", "speed": 2.0},
            on_subscribe=interrupt_during_capture_subscription,
        )

        outcome = self.build(
            request,
            [first, recovered],
            clock,
            interruption_signal="SIGTERM",
        )[0].run(threading.Event(), interrupted)

        self.assertEqual("SIGTERM", outcome.termination)
        self.assertNotIn("disconnected", {row.get("status") for row in self.rows() if row["event"] == "sample"})

    def test_sigterm_is_preserved_in_event_status_and_outcome(self) -> None:
        clock = FakeClock()
        transport = FakeTransport(clock, [], observations={"aircraft": "Q4XP", "speed": 1.0})
        runner, _ = self.build(
            make_request(),
            [transport],
            clock,
            interruption_signal="SIGTERM",
        )
        interrupted = threading.Event()
        interrupted.set()
        outcome = runner.run(threading.Event(), interrupted)

        self.assertEqual(130, outcome.exit_code)
        self.assertEqual("SIGTERM", outcome.termination)
        self.assertEqual("SIGTERM", outcome.reason)
        self.assertEqual("SIGTERM", self.rows()[-1]["signal"])
        self.assertEqual("SIGTERM", json.loads(self.status.read_text(encoding="utf-8"))["reason"])

    def test_stop_and_identity_loss_are_checked_before_a_due_sample(self) -> None:
        stop = threading.Event()
        interrupted = threading.Event()
        clock = FakeClock(on_wait=lambda _event: stop.set())
        request = make_request(
            groups=({"id": "fast", "rate_hz": 10.0, "duration_seconds": None},),
            retry={"poll_interval_seconds": 0.1},
        )
        transport = FakeTransport(clock, [], observations={"aircraft": "Q4XP", "speed": 1.0})
        stopped = self.build(request, [transport], clock)[0].run(stop, interrupted)
        self.assertEqual("requested", stopped.termination)
        self.assertEqual(1, len([row for row in self.rows() if row["event"] == "sample"]))

        self.events = self.root / "identity-loss-events.jsonl"
        self.status = self.root / "identity-loss-status.json"
        transport_box: list[FakeTransport] = []

        def lose_identity(_event: threading.Event) -> None:
            transport_box[0].emit("aircraft", "sim/aircraft/view/acf_relative_path", "C172")

        clock = FakeClock(on_wait=lose_identity)
        transport = FakeTransport(clock, [], observations={"aircraft": "Q4XP", "speed": 1.0})
        transport_box.append(transport)
        lost = self.build(request, [transport], clock)[0].run(threading.Event(), threading.Event())
        self.assertEqual("aircraft_identity_lost", lost.reason)
        self.assertEqual(1, len([row for row in self.rows() if row["event"] == "sample"]))

    def test_per_generation_subscription_counters_and_rejections_reset(self) -> None:
        optional_refs: tuple[dict[str, object], ...] = (
            {
                "id": "speed",
                "path": "sim/flightmodel/position/groundspeed",
                "declared_type": "float",
                "availability": "required",
                "sample_group_id": "fast",
                "encoding": None,
            },
            {
                "id": "optional",
                "path": "sim/optional",
                "declared_type": "float",
                "availability": "optional",
                "sample_group_id": "fast",
                "encoding": None,
            },
        )
        clock = FakeClock()
        first = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP", "speed": 1.0},
            rejected={"optional": "unsupported"},
            disconnect_after_checks=3,
        )
        second = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP", "speed": 2.0, "optional": 3.0},
        )
        self.build(make_request(refs=optional_refs), [first, second], clock)[0].run(threading.Event(), threading.Event())
        terminal_status = json.loads(self.status.read_text(encoding="utf-8"))
        self.assertEqual(2, terminal_status["counters"]["accepted_ref_count"])
        self.assertEqual(0, terminal_status["counters"]["rejected_ref_count"])
        later_optional = [row for row in self.rows() if row["event"] == "sample" and row["ref_id"] == "optional"][-1]
        self.assertEqual("sampled", later_optional["status"])

    def test_writer_runtime_and_cleanup_failures_preserve_partial_evidence(self) -> None:
        clock = FakeClock()
        transport = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP", "speed": 1.0},
            close_error=RuntimeError("close broke"),
        )
        outcome = self.build(make_request(), [transport], clock)[0].run(threading.Event(), threading.Event())
        self.assertEqual("failed", outcome.terminal_state)
        self.assertIn("close broke", outcome.reason or "")
        self.assertTrue(self.events.exists())
        self.assertEqual(1, transport.close_count)

        self.events = self.root / "first-failure-events.jsonl"
        self.status = self.root / "first-failure-status.json"
        clock = FakeClock()
        first_failure = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP"},
            subscribe_error=RuntimeError("subscription broke first"),
            close_error=RuntimeError("cleanup broke later"),
        )
        preserved = self.build(make_request(), [first_failure], clock)[0].run(threading.Event(), threading.Event())
        self.assertIn("subscription broke first", preserved.reason or "")
        self.assertIn("cleanup broke later", preserved.reason or "")
        self.assertLess(
            (preserved.reason or "").index("subscription broke first"),
            (preserved.reason or "").index("cleanup broke later"),
        )

    def test_shutdown_timeout_converts_completion_to_failure(self) -> None:
        clock = FakeClock()
        transport = FakeTransport(
            clock,
            [],
            observations={"aircraft": "Q4XP", "speed": 1.0},
            close_advance=1.0,
        )
        outcome = self.build(make_request(), [transport], clock)[0].run(threading.Event(), threading.Event())
        self.assertEqual("failed", outcome.terminal_state)
        self.assertIn("shutdown timeout", outcome.reason or "")
        self.assertFalse(outcome.clean_shutdown)

    def test_terminal_status_replace_failure_preserves_committed_jsonl_authority(self) -> None:
        clock = FakeClock()
        transport = FakeTransport(clock, [], observations={"aircraft": "Q4XP", "speed": 1.0})
        outcome = self.build(
            make_request(),
            [transport],
            clock,
            fail_terminal_status_commit=True,
        )[0].run(threading.Event(), threading.Event())

        rows = self.rows()
        status = json.loads(self.status.read_text(encoding="utf-8"))
        self.assertEqual("capture_stopped", rows[-1]["event"])
        self.assertEqual("complete", outcome.terminal_state)
        self.assertEqual("groups_complete", outcome.termination)
        self.assertFalse(outcome.clean_shutdown)
        self.assertEqual(3, outcome.exit_code)
        self.assertIn("terminal status replace failed", outcome.reason or "")
        self.assertEqual("finalizing", status["state"])

    def test_terminal_status_identity_matches_committed_event_bytes(self) -> None:
        clock = FakeClock()
        transport = FakeTransport(clock, [], observations={"aircraft": "Q4XP", "speed": 1.0})
        outcome = self.build(make_request(), [transport], clock)[0].run(threading.Event(), threading.Event())
        status = json.loads(self.status.read_text(encoding="utf-8"))
        content = self.events.read_bytes()

        self.assertTrue(outcome.clean_shutdown)
        self.assertEqual(hashlib.sha256(content).hexdigest(), status["events_sha256"])
        self.assertEqual(len(content), status["events_size_bytes"])

    def test_late_terminal_status_replace_keeps_outcome_and_status_aligned(self) -> None:
        clock = FakeClock()
        transport = FakeTransport(clock, [], observations={"aircraft": "Q4XP", "speed": 1.0})
        runner, statuses = self.build(make_request(), [transport], clock)
        real_replace = os.replace

        def advance_after_terminal_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
            document = json.loads(Path(source).read_text(encoding="utf-8"))
            real_replace(source, destination)
            if document["state"] in {"complete", "failed", "interrupted"}:
                clock.now += 1.0

        with patch("xpwebapi.capture_output.os.replace", side_effect=advance_after_terminal_replace):
            outcome = runner.run(threading.Event(), threading.Event())

        status = json.loads(self.status.read_text(encoding="utf-8"))
        self.assertEqual("complete", outcome.terminal_state)
        self.assertTrue(outcome.clean_shutdown)
        self.assertEqual(0, outcome.exit_code)
        self.assertEqual("complete", status["state"])
        self.assertTrue(status["clean_shutdown"])
        self.assertEqual(0, status["exit_code"])
        self.assertTrue(statuses.writer.terminal_commit_deadline_exceeded)

    def test_terminal_event_faults_do_not_publish_a_disagreeing_terminal_status(self) -> None:
        for index, fault in enumerate(("before", "flush", "fsync", "close")):
            with self.subTest(fault=fault):
                self.events = self.root / f"terminal-{index}.jsonl"
                self.status = self.root / f"terminal-{index}.json"
                clock = FakeClock()
                transport = FakeTransport(clock, [], observations={"aircraft": "Q4XP", "speed": 1.0})
                outcome = self.build(
                    make_request(),
                    [transport],
                    clock,
                    event_commit_fault=cast(Any, fault),
                )[0].run(threading.Event(), threading.Event())

                status = json.loads(self.status.read_text(encoding="utf-8"))
                self.assertFalse(outcome.clean_shutdown)
                self.assertEqual(3, outcome.exit_code)
                self.assertEqual("finalizing", status["state"])
                if fault == "close":
                    self.assertEqual("capture_stopped", self.rows()[-1]["event"])
                    self.assertEqual("complete", outcome.terminal_state)
                elif fault in {"flush", "fsync"}:
                    self.assertEqual("capture_stopped", self.rows()[-1]["event"])
                    self.assertEqual("failed", outcome.terminal_state)
                else:
                    self.assertNotIn(self.rows()[-1]["event"], {"capture_stopped", "capture_failed", "capture_interrupted"})
                    self.assertEqual("failed", outcome.terminal_state)


if __name__ == "__main__":
    unittest.main()
