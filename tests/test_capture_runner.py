"""Deterministic lifecycle tests for the read-only capture runner."""

from __future__ import annotations

import json
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, cast

from xpwebapi.capture_events import CaptureEventIdentity, SourceProvenance, TransportCapabilities
from xpwebapi.capture_output import AtomicStatusWriter, CaptureEventWriter
from xpwebapi.capture_protocol import CaptureRequest
from xpwebapi.capture_runner import CaptureOutcome, CaptureRunner
from xpwebapi.capture_transport import Observation, SubscriptionResult


class TimedValue:
    def __init__(self, value: object, observed_monotonic: float) -> None:
        self.value = value
        self.observed_monotonic = observed_monotonic


class FakeClock:
    def __init__(self, *, late_once: float = 0.0) -> None:
        self.now = 0.0
        self.base = datetime(2026, 7, 19, tzinfo=UTC)
        self.late_once = late_once
        self.waits: list[float] = []

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
        liveness_override: Literal["connected", "awaiting_first_identity_packet", "disconnected"] | None = None,
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
        self.liveness_override = liveness_override
        self._connected = False
        self.connected_checks = 0
        self.close_count = 0
        self.deadlines: list[float] = []
        self.identity_callbacks: list[tuple[Any, Any]] = []

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
        if purpose == "capture" and self.advance_on_capture:
            self.clock.now += self.advance_on_capture
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
        return SubscriptionResult(
            purpose=purpose,
            accepted_ref_ids=tuple(accepted),
            rejected=rejected,
            request_id=1,
        )

    def close(self, deadline: float) -> None:
        self.log.append("close")
        self.close_count += 1
        self.deadlines.append(deadline)
        self.clock.now += self.close_advance
        self._connected = False
        if self.close_error is not None:
            raise self.close_error


class RecordingStatusWriter:
    def __init__(self, path: Path, log: list[str]) -> None:
        self.writer = AtomicStatusWriter(path)
        self.documents: list[Any] = []
        self.log = log

    def write(self, document: Any) -> None:
        self.log.append(f"status:{document.state}")
        self.writer.write(document)
        self.documents.append(document)


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
    ) -> tuple[CaptureRunner, RecordingStatusWriter]:
        activity = log if log is not None else []
        writer = CaptureEventWriter(
            self.events,
            CaptureEventIdentity(capture_session_id=request.capture_session_id, sortie_id=request.sortie_id),
            clock,
        )
        status_writer = RecordingStatusWriter(self.status, activity)
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
                event_writer=writer,
                status_writer=cast(AtomicStatusWriter, status_writer),
                clock=clock,
                events_path=self.events,
            ),
            status_writer,
        )

    def rows(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in self.events.read_text(encoding="utf-8").splitlines()]

    def test_outcome_exit_codes_are_stable(self) -> None:
        def outcome(state: Literal["complete", "failed", "interrupted"]) -> CaptureOutcome:
            return CaptureOutcome(
                terminal_state=state,
                termination="x",
                reason=None,
                transport_ready=False,
                aircraft_ready=False,
                sample_count=0,
                gap_count=0,
                retry_count=0,
                clean_shutdown=False,
            )

        self.assertEqual(0, outcome("complete").exit_code)
        self.assertEqual(3, outcome("failed").exit_code)
        self.assertEqual(130, outcome("interrupted").exit_code)

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
        self.assertIn("reconnect_disconnect_timeout", duration_outcome.reason or "")

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


if __name__ == "__main__":
    unittest.main()
