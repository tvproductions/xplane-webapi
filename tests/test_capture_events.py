import hashlib
import json
import math
import os
import subprocess
import unittest
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from io import BufferedWriter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from pydantic import TypeAdapter, ValidationError

from xpwebapi.capture_events import (
    AircraftReadyEvent,
    AircraftReadyInput,
    CaptureCounters,
    CaptureEvent,
    CaptureEventIdentity,
    CaptureEventKind,
    CaptureFailedEvent,
    CaptureFailedInput,
    CaptureInterruptedEvent,
    CaptureInterruptedInput,
    CaptureStartedEvent,
    CaptureStartedInput,
    CaptureStoppedEvent,
    CaptureStoppedInput,
    GapEndedEvent,
    GapEndedInput,
    GapStartedEvent,
    GapStartedInput,
    IdentityObservation,
    RetryEvent,
    RetryInput,
    SampleEvent,
    SampleInput,
    SampleStatus,
    SourceProvenance,
    SubscriptionResultEvent,
    SubscriptionResultInput,
    TransportCapabilities,
    TransportReadyEvent,
    TransportReadyInput,
    TransportStateEvent,
    TransportStateInput,
    VersionJsonDocument,
)
from xpwebapi.capture_output import CaptureEventWriter, resolve_source_provenance
from xpwebapi.capture_protocol import CaptureCorrelation, WebsocketCaptureConfig


REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeClock:
    def __init__(self) -> None:
        self._monotonic = 20.0
        self._utc = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)

    def monotonic(self) -> float:
        value = self._monotonic
        self._monotonic += 0.25
        return value

    def utcnow(self) -> datetime:
        value = self._utc
        self._utc += timedelta(milliseconds=250)
        return value


class ScriptedClock:
    def __init__(self, monotonic_values: list[float]) -> None:
        self._monotonic_values = iter(monotonic_values)
        self._utc = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)

    def monotonic(self) -> float:
        return next(self._monotonic_values)

    def utcnow(self) -> datetime:
        value = self._utc
        self._utc += timedelta(milliseconds=250)
        return value


class FaultingStream:
    def __init__(self, stream: BufferedWriter, fault: str) -> None:
        self._stream = stream
        self._fault = fault
        self._flush_count = 0

    def write(self, value: bytes) -> int:
        return self._stream.write(value)

    def flush(self) -> None:
        self._flush_count += 1
        if self._fault == "flush" and self._flush_count == 2:
            raise OSError("final flush fault")
        self._stream.flush()

    def fileno(self) -> int:
        return self._stream.fileno()

    def close(self) -> None:
        self._stream.close()
        if self._fault == "close":
            raise OSError("final close fault")


def provenance_payload() -> dict[str, Any]:
    return {
        "package_name": "xpwebapi",
        "package_version": "3.5.0",
        "python_version": "3.12.0",
        "git_state": "available",
        "git_root": "C:/src/xplane-webapi",
        "git_revision": "a" * 40,
        "git_origin": "https://example.invalid/xplane-webapi.git",
        "git_dirty": False,
        "read_only": True,
    }


def capabilities_payload() -> dict[str, Any]:
    return {
        "transport": "websocket",
        "endpoint": "ws://127.0.0.1:8086/api/v2",
        "xplane_version": "12.1.4",
        "value_types": ("int", "float", "double", "string"),
    }


def identity_observation_payload() -> dict[str, Any]:
    return {
        "ref_id": "q4xp_path",
        "path": "sim/aircraft/view/acf_relative_path",
        "operator": "contains",
        "expected_value": "Q4XP",
        "observed_value": "Aircraft/FlyJSim_Q4XP/Q4XP.acf",
        "source_observed_elapsed_seconds": 1.0,
        "source_age_seconds": 0.0,
    }


def input_payloads() -> list[tuple[type[Any], dict[str, Any], str]]:
    correlation = CaptureCorrelation(
        campaign_id="q4xp_shakedown",
        route_profile_id="kaus-kgls",
        scenario_id="baseline",
    )
    transport = WebsocketCaptureConfig(kind="websocket", host="127.0.0.1", port=8086)
    provenance = SourceProvenance.model_validate(provenance_payload())
    capabilities = TransportCapabilities.model_validate(capabilities_payload())
    observation = IdentityObservation.model_validate(identity_observation_payload())
    return [
        (
            CaptureStartedInput,
            {
                "event": "capture_started",
                "request_sha256": "b" * 64,
                "correlation": correlation,
                "transport": transport,
                "provenance": provenance,
            },
            "capture_started",
        ),
        (
            TransportStateInput,
            {
                "event": "transport_state",
                "state": "connected",
                "attempt": 1,
                "reason": None,
                "capabilities": capabilities,
            },
            "transport_state",
        ),
        (
            TransportReadyInput,
            {
                "event": "transport_ready",
                "connection_generation": 1,
                "endpoint": "ws://127.0.0.1:8086/api/v2",
                "read_only": True,
                "package_version": "3.5.0",
                "git_revision": "a" * 40,
                "git_dirty": False,
                "capabilities": capabilities,
            },
            "transport_ready",
        ),
        (
            SubscriptionResultInput,
            {
                "event": "subscription_result",
                "purpose": "capture",
                "accepted_ref_ids": ("altitude",),
                "rejected": {"optional_ref": "unsupported"},
                "request_id": 7,
            },
            "subscription_result",
        ),
        (
            AircraftReadyInput,
            {
                "event": "aircraft_ready",
                "connection_generation": 1,
                "target_aircraft": "FlyJSim Q4XP",
                "identity_observations": (observation,),
                "required_ref_ids": ("altitude",),
                "optional_missing_ref_ids": (),
                "ready_elapsed_seconds": 1.5,
            },
            "aircraft_ready",
        ),
        (
            SampleInput,
            {
                "event": "sample",
                "sample_group_id": "one_hz",
                "ref_id": "altitude",
                "path": "sim/flightmodel/position/elevation",
                "declared_type": "double",
                "status": "sampled",
                "value": 1234.0,
                "source_observed_elapsed_seconds": 1.25,
                "source_age_seconds": 0.25,
            },
            "sample",
        ),
        (
            GapStartedInput,
            {
                "event": "gap_started",
                "reason": "scheduler_late",
                "affected_ref_ids": ("altitude",),
                "gap_start_elapsed_seconds": 3.0,
            },
            "gap_started",
        ),
        (
            GapEndedInput,
            {
                "event": "gap_ended",
                "reason": "scheduler_late",
                "affected_ref_ids": ("altitude",),
                "gap_start_elapsed_seconds": 3.0,
                "gap_duration_seconds": 2.0,
                "skipped_slot_count": 2,
            },
            "gap_ended",
        ),
        (
            RetryInput,
            {
                "event": "retry",
                "phase": "initial_connect",
                "attempt": 2,
                "maximum_attempts": 3,
                "delay_seconds": 0.5,
                "reason": "connection refused",
            },
            "retry",
        ),
        (
            CaptureStoppedInput,
            {
                "event": "capture_stopped",
                "termination": "requested",
                "sample_count": 10,
                "gap_count": 1,
                "retry_count": 0,
            },
            "capture_stopped",
        ),
        (
            CaptureFailedInput,
            {
                "event": "capture_failed",
                "reason": "subscription failed",
                "sample_count": 0,
                "gap_count": 0,
                "retry_count": 2,
            },
            "capture_failed",
        ),
        (
            CaptureInterruptedInput,
            {
                "event": "capture_interrupted",
                "signal": "SIGINT",
                "sample_count": 4,
                "gap_count": 0,
                "retry_count": 1,
            },
            "capture_interrupted",
        ),
    ]


class CaptureEventModelTests(unittest.TestCase):
    def test_string_enums_have_exact_protocol_values(self) -> None:
        self.assertEqual(
            [
                "capture_started",
                "transport_state",
                "transport_ready",
                "subscription_result",
                "aircraft_ready",
                "sample",
                "gap_started",
                "gap_ended",
                "retry",
                "capture_stopped",
                "capture_failed",
                "capture_interrupted",
            ],
            [member.value for member in CaptureEventKind],
        )
        self.assertEqual(
            ["sampled", "missing", "stale", "disconnected", "unsupported", "invalid"],
            [member.value for member in SampleStatus],
        )

    def test_all_twelve_input_models_are_strict_required_and_extra_forbidden(self) -> None:
        for model, payload, _event in input_payloads():
            with self.subTest(model=model.__name__):
                self.assertEqual(payload["event"], model.model_validate(payload).event)
                missing = dict(payload)
                missing.pop(next(key for key in payload if key != "event"))
                with self.assertRaises(ValidationError):
                    model.model_validate(missing)
                with self.assertRaises(ValidationError):
                    model.model_validate({**payload, "unexpected": True})

    def test_all_twelve_event_models_reject_coercion_and_extra_fields(self) -> None:
        event_models = (
            CaptureStartedEvent,
            TransportStateEvent,
            TransportReadyEvent,
            SubscriptionResultEvent,
            AircraftReadyEvent,
            SampleEvent,
            GapStartedEvent,
            GapEndedEvent,
            RetryEvent,
            CaptureStoppedEvent,
            CaptureFailedEvent,
            CaptureInterruptedEvent,
        )
        envelope = {
            "protocol_version": 1,
            "sequence": 1,
            "capture_session_id": "capture-1",
            "sortie_id": "sortie-1",
            "timestamp_utc": "2026-07-19T12:00:00Z",
            "elapsed_seconds": 0.0,
        }
        for event_model, (_input_model, payload, _event) in zip(event_models, input_payloads(), strict=True):
            event_payload = {**envelope, **payload}
            if event_payload["event"].startswith("capture_") and event_payload["event"] != "capture_started":
                event_payload["preceding_sha256"] = "c" * 64
            with self.subTest(model=event_model.__name__):
                event_model.model_validate(event_payload)
                with self.assertRaises(ValidationError):
                    event_model.model_validate({**event_payload, "sequence": "1"})
                with self.assertRaises(ValidationError):
                    event_model.model_validate({**event_payload, "extra": "rejected"})

    def test_provenance_enforces_available_and_unavailable_git_states(self) -> None:
        SourceProvenance.model_validate(provenance_payload())
        unavailable = {
            **provenance_payload(),
            "git_state": "unavailable",
            "git_root": None,
            "git_revision": None,
            "git_origin": None,
            "git_dirty": None,
        }
        SourceProvenance.model_validate(unavailable)
        for field in ("git_root", "git_revision", "git_dirty"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                SourceProvenance.model_validate({**provenance_payload(), field: None})
        with self.assertRaises(ValidationError):
            SourceProvenance.model_validate({**unavailable, "git_dirty": False})

    def test_capabilities_counters_and_version_are_strict(self) -> None:
        TransportCapabilities.model_validate(capabilities_payload())
        counters = {
            "sample_count": 0,
            "gap_count": 0,
            "retry_count": 0,
            "accepted_ref_count": 1,
            "rejected_ref_count": 0,
        }
        CaptureCounters.model_validate(counters)
        version = {
            **provenance_payload(),
            "supported_transports": ("udp", "websocket"),
            "worker": "xpwebapi-capture",
            "worker_protocol_version": 1,
        }
        VersionJsonDocument.model_validate(version)
        for field in counters:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                CaptureCounters.model_validate({**counters, field: -1})
            with self.subTest(field=f"{field}-coercion"), self.assertRaises(ValidationError):
                CaptureCounters.model_validate({**counters, field: 0.0})
        with self.assertRaises(ValidationError):
            VersionJsonDocument.model_validate({**version, "supported_transports": ("websocket", "udp")})
        with self.assertRaises(ValidationError):
            TransportCapabilities.model_validate({**capabilities_payload(), "extra": 1})

    def test_numeric_validators_reject_nonfinite_and_invalid_attempts(self) -> None:
        for value in (math.nan, math.inf, -math.inf, -0.1):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                SampleInput.model_validate({**input_payloads()[5][1], "source_age_seconds": value})
        with self.assertRaises(ValidationError):
            TransportStateInput.model_validate({**input_payloads()[1][1], "attempt": 0})
        with self.assertRaises(ValidationError):
            RetryInput.model_validate({**input_payloads()[8][1], "attempt": 4})
        with self.assertRaises(ValidationError):
            GapEndedInput.model_validate({**input_payloads()[7][1], "skipped_slot_count": -1})

    def test_event_timestamp_rejects_calendar_invalid_rfc3339_text(self) -> None:
        payload = {
            "protocol_version": 1,
            "sequence": 1,
            "capture_session_id": "capture-1",
            "sortie_id": "sortie-1",
            "timestamp_utc": "2026-99-99T25:61:61Z",
            "elapsed_seconds": 0.0,
            **input_payloads()[0][1],
        }
        with self.assertRaises(ValidationError):
            CaptureStartedEvent.model_validate(payload)

    def test_sample_value_and_source_time_contract(self) -> None:
        sampled = input_payloads()[5][1]
        invalid_values = (True, "1234", None, math.nan)
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                SampleInput.model_validate({**sampled, "value": value})
        for declared_type, value, expected in (("int", 2, 2), ("float", 2, 2.0), ("double", 2.5, 2.5), ("string", "Q4XP", "Q4XP")):
            model = SampleInput.model_validate({**sampled, "declared_type": declared_type, "value": value})
            self.assertEqual(expected, model.value)
            self.assertIs(type(expected), type(model.value))
        for status in ("missing", "stale", "disconnected", "unsupported", "invalid"):
            SampleInput.model_validate(
                {
                    **sampled,
                    "status": status,
                    "value": None,
                    "source_observed_elapsed_seconds": None,
                    "source_age_seconds": None,
                }
            )
            with self.assertRaises(ValidationError):
                SampleInput.model_validate({**sampled, "status": status})
        with self.assertRaises(ValidationError):
            SampleInput.model_validate({**sampled, "source_age_seconds": None})

    def test_missing_sample_requires_both_source_times_to_be_null(self) -> None:
        sampled = input_payloads()[5][1]
        with self.assertRaises(ValidationError):
            SampleInput.model_validate({**sampled, "status": "missing", "value": None})

    def test_identity_observation_rejects_mismatched_and_nonfinite_values(self) -> None:
        payload = identity_observation_payload()
        with self.assertRaises(ValidationError):
            IdentityObservation.model_validate({**payload, "operator": "contains", "observed_value": 4})
        with self.assertRaises(ValidationError):
            IdentityObservation.model_validate({**payload, "operator": "equals", "expected_value": 2.0, "observed_value": math.inf})

    def test_checked_event_and_version_schemas_equal_generated_canonical_json(self) -> None:
        pairs = (
            (TypeAdapter(CaptureEvent).json_schema(), REPO_ROOT / "schemas" / "capture-event-v1.schema.json"),
            (VersionJsonDocument.model_json_schema(), REPO_ROOT / "schemas" / "capture-version-v1.schema.json"),
        )
        for generated, path in pairs:
            with self.subTest(path=path.name):
                checked = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(
                    json.dumps(generated, allow_nan=False, sort_keys=True, separators=(",", ":")),
                    json.dumps(checked, allow_nan=False, sort_keys=True, separators=(",", ":")),
                )


class CaptureEventWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.events_path = Path(self.temporary_directory.name) / "capture.jsonl"
        self.identity = CaptureEventIdentity(capture_session_id="capture-1", sortie_id="sortie-1")
        self.clock = FakeClock()

    def test_sequence_lf_and_terminal_hash_cover_exact_preceding_bytes(self) -> None:
        writer = CaptureEventWriter(self.events_path, self.identity, self.clock)
        first = writer.write(CaptureStartedInput.model_validate(input_payloads()[0][1]))
        second = writer.write(TransportStateInput.model_validate(input_payloads()[1][1]))
        preceding_bytes = b"".join((json.dumps(row, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8") for row in (first, second))
        terminal = writer.close(CaptureStoppedInput.model_validate(input_payloads()[9][1]))

        self.assertEqual([1, 2, 3], [first["sequence"], second["sequence"], terminal["sequence"]])
        self.assertEqual(hashlib.sha256(preceding_bytes).hexdigest(), terminal["preceding_sha256"])
        file_bytes = self.events_path.read_bytes()
        self.assertNotIn(b"\r", file_bytes)
        self.assertTrue(file_bytes.endswith(b"\n"))
        self.assertEqual(hashlib.sha256(file_bytes).hexdigest(), writer.events_sha256)
        self.assertEqual(len(file_bytes), writer.events_size_bytes)

    def test_writer_rejects_nan_without_appending_and_cannot_write_after_close(self) -> None:
        writer = CaptureEventWriter(self.events_path, self.identity, self.clock)
        good = writer.write(CaptureStartedInput.model_validate(input_payloads()[0][1]))
        original = self.events_path.read_bytes()
        poisoned = SampleInput.model_construct(
            event="sample",
            sample_group_id="one_hz",
            ref_id="altitude",
            path="sim/flightmodel/position/elevation",
            declared_type="double",
            status="sampled",
            value=math.nan,
            source_observed_elapsed_seconds=1.25,
            source_age_seconds=0.25,
        )
        with self.assertRaises((ValueError, ValidationError)):
            writer.write(poisoned)
        self.assertEqual(original, self.events_path.read_bytes())
        writer.close(CaptureFailedInput.model_validate(input_payloads()[10][1]))
        with self.assertRaises(ValueError):
            writer.write(CaptureStartedInput.model_validate(input_payloads()[0][1]))
        with self.assertRaises(ValueError):
            writer.close(CaptureFailedInput.model_validate(input_payloads()[10][1]))
        self.assertEqual(1, good["sequence"])

    def test_writer_rejects_elapsed_clock_regression_between_events(self) -> None:
        clock = ScriptedClock([10.0, 12.0, 11.0])
        writer = CaptureEventWriter(self.events_path, self.identity, clock)
        self.addCleanup(writer._stream.close)
        writer.write(CaptureStartedInput.model_validate(input_payloads()[0][1]))
        original = self.events_path.read_bytes()

        with self.assertRaises(ValueError):
            writer.write(TransportStateInput.model_validate(input_payloads()[1][1]))

        self.assertEqual(original, self.events_path.read_bytes())

    def test_terminal_append_is_logically_immutable_after_finalization_faults(self) -> None:
        for fault in ("flush", "fsync", "close"):
            with self.subTest(fault=fault):
                events_path = self.events_path.with_name(f"{fault}.jsonl")
                writer = CaptureEventWriter(events_path, self.identity, FakeClock())
                real_stream = writer._stream
                self.addCleanup(real_stream.close)
                writer_for_fault_injection: Any = writer
                writer_for_fault_injection._stream = FaultingStream(real_stream, fault)
                fsync_calls = 0
                real_fsync = os.fsync

                def faulting_fsync(file_descriptor: int) -> None:
                    nonlocal fsync_calls
                    fsync_calls += 1
                    if fault == "fsync" and fsync_calls == 2:
                        raise OSError("final fsync fault")
                    real_fsync(file_descriptor)

                fsync_context = patch("xpwebapi.capture_output.os.fsync", side_effect=faulting_fsync) if fault == "fsync" else nullcontext()
                with fsync_context, self.assertRaises(OSError):
                    writer.close(CaptureStoppedInput.model_validate(input_payloads()[9][1]))
                terminal_bytes = events_path.read_bytes()

                self.assertEqual(hashlib.sha256(terminal_bytes).hexdigest(), writer.events_sha256)
                with self.assertRaisesRegex(ValueError, "capture event writer is closed"):
                    writer.write(CaptureStartedInput.model_validate(input_payloads()[0][1]))
                with self.assertRaisesRegex(ValueError, "capture event writer is closed"):
                    writer.close(CaptureStoppedInput.model_validate(input_payloads()[9][1]))
                self.assertEqual(terminal_bytes, events_path.read_bytes())
                self.assertEqual(1, len(terminal_bytes.splitlines()))
                if not real_stream.closed:
                    real_stream.close()

    def test_writer_uses_exclusive_creation(self) -> None:
        self.events_path.write_text("competing data\n", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            CaptureEventWriter(self.events_path, self.identity, self.clock)
        self.assertEqual("competing data\n", self.events_path.read_text(encoding="utf-8"))


class ProvenanceTests(unittest.TestCase):
    def completed(self, args: list[str], *, stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr="")

    def test_git_worktree_discovery_and_dirty_state(self) -> None:
        root = "C:/src/xplane-webapi/.worktrees/capture"
        outputs = (root + "\n", "a" * 40 + "\n", "https://example.invalid/repo.git\n", "?? evidence.jsonl\n")
        calls: list[list[str]] = []

        def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            self.assertEqual(2, kwargs["timeout"])
            self.assertFalse(kwargs["check"])
            self.assertTrue(kwargs["capture_output"])
            self.assertTrue(kwargs["text"])
            return self.completed(args, stdout=outputs[len(calls) - 1])

        with patch("xpwebapi.capture_output.subprocess.run", side_effect=fake_run):
            provenance = resolve_source_provenance()

        self.assertEqual("available", provenance.git_state)
        self.assertEqual(root, provenance.git_root)
        self.assertTrue(provenance.git_dirty)
        self.assertEqual(["git", "-C"], calls[0][:2])
        self.assertEqual("rev-parse", calls[0][3])
        self.assertEqual(root, calls[1][2])

    def test_git_unavailable_has_null_details(self) -> None:
        with patch("xpwebapi.capture_output.subprocess.run", side_effect=FileNotFoundError):
            provenance = resolve_source_provenance()
        self.assertEqual("unavailable", provenance.git_state)
        self.assertIsNone(provenance.git_root)
        self.assertIsNone(provenance.git_revision)
        self.assertIsNone(provenance.git_origin)
        self.assertIsNone(provenance.git_dirty)
        self.assertTrue(provenance.read_only)


if __name__ == "__main__":
    unittest.main()
