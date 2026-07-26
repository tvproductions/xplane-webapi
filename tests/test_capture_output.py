import json
import os
import unittest
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from pydantic import TypeAdapter, ValidationError

from xpwebapi.capture_events import (
    CaptureStatusState,
    CompleteStatus,
    FailedStatus,
    InterruptedStatus,
    LEGAL_STATUS_TRANSITIONS,
    NonterminalStatus,
    StatusDocument,
)
from xpwebapi.capture_output import AtomicStatusWriter


SCHEMA_ROOT = files("xpwebapi.schemas")


class ManualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def counters_payload() -> dict[str, int]:
    return {
        "sample_count": 0,
        "gap_count": 0,
        "retry_count": 0,
        "accepted_ref_count": 0,
        "rejected_ref_count": 0,
    }


def status_payload(state: str, *, attempt: int | None = None) -> dict[str, Any]:
    phase = "none"
    maximum_attempts = 0
    current_attempt = 0
    reason = None
    if state == "connecting":
        phase = "initial_connect"
        maximum_attempts = 3
        current_attempt = 1 if attempt is None else attempt
    elif state == "reconnecting":
        phase = "reconnect"
        maximum_attempts = 3
        current_attempt = 1 if attempt is None else attempt
        reason = "connection lost"

    reached_transport = state not in {"starting", "connecting"}
    reached_aircraft = state in {"aircraft_ready", "capturing", "finalizing", "complete"}
    payload: dict[str, Any] = {
        "protocol_version": 1,
        "capture_session_id": "capture-1",
        "sortie_id": "sortie-1",
        "state": state,
        "updated_at_utc": "2026-07-19T12:00:00Z",
        "elapsed_seconds": 1.0,
        "events_path": "C:/evidence/capture.jsonl",
        "request_sha256": "b" * 64,
        "transport": "websocket",
        "transport_connection_state": "connected" if reached_transport else "not_connected",
        "connection_generation": 1 if reached_transport else 0,
        "transport_ready_at_utc": "2026-07-19T12:00:00Z" if reached_transport else None,
        "aircraft_ready_at_utc": "2026-07-19T12:01:00Z" if reached_aircraft else None,
        "target_aircraft": "FlyJSim Q4XP",
        "identity_ref_count": 1,
        "matched_identity_ref_count": 1 if reached_aircraft else 0,
        "required_capture_ref_count": 2,
        "observed_required_ref_count": 2 if reached_aircraft else 0,
        "counters": counters_payload(),
        "attempt_phase": phase,
        "current_attempt": current_attempt,
        "maximum_attempts": maximum_attempts,
        "reason": reason,
    }
    if state == "complete":
        payload.update(
            reason="requested",
            events_sha256="c" * 64,
            events_size_bytes=200,
            exit_code=0,
            clean_shutdown=True,
        )
    elif state == "failed":
        payload.update(
            reason="transport failure",
            events_sha256="c" * 64,
            events_size_bytes=200,
            exit_code=3,
            clean_shutdown=False,
        )
    elif state == "interrupted":
        payload.update(
            reason="SIGTERM",
            events_sha256="c" * 64,
            events_size_bytes=200,
            exit_code=130,
            clean_shutdown=True,
        )
    return payload


def status_document(state: str, *, attempt: int | None = None) -> StatusDocument:
    model: type[Any]
    if state == "complete":
        model = CompleteStatus
    elif state == "failed":
        model = FailedStatus
    elif state == "interrupted":
        model = InterruptedStatus
    else:
        model = NonterminalStatus
    return model.model_validate(status_payload(state, attempt=attempt))


class StatusModelTests(unittest.TestCase):
    def test_status_enum_and_legal_transitions_are_exact(self) -> None:
        self.assertEqual(
            [
                "starting",
                "connecting",
                "transport_ready",
                "awaiting_aircraft",
                "subscribing",
                "awaiting_first_values",
                "aircraft_ready",
                "capturing",
                "reconnecting",
                "finalizing",
                "complete",
                "failed",
                "interrupted",
            ],
            [member.value for member in CaptureStatusState],
        )
        self.assertEqual(
            {
                "starting": frozenset({"connecting", "finalizing", "failed", "interrupted"}),
                "connecting": frozenset({"connecting", "transport_ready", "finalizing", "failed", "interrupted"}),
                "transport_ready": frozenset({"awaiting_aircraft", "finalizing", "failed", "interrupted"}),
                "awaiting_aircraft": frozenset({"subscribing", "reconnecting", "finalizing", "failed", "interrupted"}),
                "subscribing": frozenset({"awaiting_first_values", "reconnecting", "finalizing", "failed", "interrupted"}),
                "awaiting_first_values": frozenset({"aircraft_ready", "reconnecting", "finalizing", "failed", "interrupted"}),
                "aircraft_ready": frozenset({"capturing", "finalizing", "failed", "interrupted"}),
                "capturing": frozenset({"reconnecting", "finalizing", "failed", "interrupted"}),
                "reconnecting": frozenset({"reconnecting", "transport_ready", "finalizing", "failed", "interrupted"}),
                "finalizing": frozenset({"complete", "failed", "interrupted"}),
                "complete": frozenset(),
                "failed": frozenset(),
                "interrupted": frozenset(),
            },
            LEGAL_STATUS_TRANSITIONS,
        )

    def test_status_models_require_fields_reject_coercion_and_forbid_extra(self) -> None:
        for state in ("starting", "complete", "failed", "interrupted"):
            payload = status_payload(state)
            model = type(status_document(state))
            with self.subTest(state=state):
                model.model_validate(payload)
                with self.assertRaises(ValidationError):
                    model.model_validate({**payload, "elapsed_seconds": 1})
                with self.assertRaises(ValidationError):
                    model.model_validate({**payload, "extra": True})
                missing = dict(payload)
                missing.pop("capture_session_id")
                with self.assertRaises(ValidationError):
                    model.model_validate(missing)

    def test_terminal_fields_are_required_only_on_terminal_models(self) -> None:
        terminal_fields = {"events_sha256", "events_size_bytes", "exit_code", "clean_shutdown"}
        nonterminal = status_payload("starting")
        NonterminalStatus.model_validate(nonterminal)
        for field in terminal_fields:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                NonterminalStatus.model_validate({**nonterminal, field: 0})
        complete = status_payload("complete")
        for field in terminal_fields:
            missing = dict(complete)
            missing.pop(field)
            with self.subTest(field=field), self.assertRaises(ValidationError):
                CompleteStatus.model_validate(missing)

    def test_counts_attempts_hashes_and_sizes_obey_bounds(self) -> None:
        payload = status_payload("connecting")
        for field in ("connection_generation", "identity_ref_count", "matched_identity_ref_count", "required_capture_ref_count", "observed_required_ref_count"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                NonterminalStatus.model_validate({**payload, field: -1})
        with self.assertRaises(ValidationError):
            NonterminalStatus.model_validate({**payload, "current_attempt": 4})
        with self.assertRaises(ValidationError):
            NonterminalStatus.model_validate({**payload, "matched_identity_ref_count": 2})
        with self.assertRaises(ValidationError):
            NonterminalStatus.model_validate({**payload, "observed_required_ref_count": 3})
        with self.assertRaises(ValidationError):
            CompleteStatus.model_validate({**status_payload("complete"), "events_size_bytes": -1})
        with self.assertRaises(ValidationError):
            CompleteStatus.model_validate({**status_payload("complete"), "events_sha256": "not-a-hash"})

    def test_attempt_phase_zero_contract_and_readiness_timestamp_contract(self) -> None:
        with self.assertRaises(ValidationError):
            NonterminalStatus.model_validate({**status_payload("starting"), "current_attempt": 1})
        with self.assertRaises(ValidationError):
            NonterminalStatus.model_validate({**status_payload("connecting"), "maximum_attempts": 0})
        with self.assertRaises(ValidationError):
            NonterminalStatus.model_validate({**status_payload("transport_ready"), "transport_ready_at_utc": None})
        with self.assertRaises(ValidationError):
            NonterminalStatus.model_validate({**status_payload("capturing"), "aircraft_ready_at_utc": None})

    def test_nonterminal_reason_is_null_except_while_reconnecting(self) -> None:
        healthy_states = (
            "starting",
            "connecting",
            "transport_ready",
            "awaiting_aircraft",
            "subscribing",
            "awaiting_first_values",
            "aircraft_ready",
            "capturing",
            "finalizing",
        )
        for state in healthy_states:
            with self.subTest(state=state), self.assertRaises(ValidationError):
                NonterminalStatus.model_validate({**status_payload(state), "reason": "unexpected"})
        with self.assertRaises(ValidationError):
            NonterminalStatus.model_validate({**status_payload("reconnecting"), "reason": None})

    def test_checked_status_schema_equals_generated_canonical_json(self) -> None:
        generated = TypeAdapter(StatusDocument).json_schema()
        checked = json.loads(SCHEMA_ROOT.joinpath("capture-status-v1.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(
            json.dumps(generated, allow_nan=False, sort_keys=True, separators=(",", ":")),
            json.dumps(checked, allow_nan=False, sort_keys=True, separators=(",", ":")),
        )


class AtomicStatusWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.status_path = Path(self.temporary_directory.name) / "capture-status.json"

    def test_requires_starting_as_first_state(self) -> None:
        writer = AtomicStatusWriter(self.status_path)
        with self.assertRaises(ValueError):
            writer.write(status_document("connecting"))
        self.assertFalse(self.status_path.exists())

    def test_accepts_complete_legal_path_and_rejects_terminal_mutation(self) -> None:
        writer = AtomicStatusWriter(self.status_path)
        states = (
            "starting",
            "connecting",
            "transport_ready",
            "awaiting_aircraft",
            "subscribing",
            "awaiting_first_values",
            "aircraft_ready",
            "capturing",
            "finalizing",
            "complete",
        )
        for state in states:
            writer.write(status_document(state))
        self.assertEqual("complete", json.loads(self.status_path.read_text(encoding="utf-8"))["state"])
        with self.assertRaises(ValueError):
            writer.write(status_document("capturing"))

    def test_rejects_illegal_transition_and_requires_attempt_increment(self) -> None:
        writer = AtomicStatusWriter(self.status_path)
        writer.write(status_document("starting"))
        writer.write(status_document("connecting", attempt=1))
        with self.assertRaises(ValueError):
            writer.write(status_document("connecting", attempt=1))
        writer.write(status_document("connecting", attempt=2))
        with self.assertRaises(ValueError):
            writer.write(status_document("capturing"))

    def test_readiness_latches_are_write_once_and_persistent(self) -> None:
        writer = AtomicStatusWriter(self.status_path)
        states = ("starting", "connecting", "transport_ready", "awaiting_aircraft", "subscribing", "awaiting_first_values", "aircraft_ready")
        for state in states:
            writer.write(status_document(state))
        changed = status_payload("capturing")
        changed["aircraft_ready_at_utc"] = "2026-07-19T12:02:00Z"
        with self.assertRaises(ValueError):
            writer.write(NonterminalStatus.model_validate(changed))
        missing = status_payload("capturing")
        missing["aircraft_ready_at_utc"] = None
        with self.assertRaises(ValidationError):
            NonterminalStatus.model_validate(missing)

    def test_aircraft_readiness_latch_persists_during_reconnect(self) -> None:
        writer = AtomicStatusWriter(self.status_path)
        for state in (
            "starting",
            "connecting",
            "transport_ready",
            "awaiting_aircraft",
            "subscribing",
            "awaiting_first_values",
            "aircraft_ready",
            "capturing",
        ):
            writer.write(status_document(state))
        reconnecting = status_payload("reconnecting")
        reconnecting["aircraft_ready_at_utc"] = "2026-07-19T12:01:00Z"
        writer.write(NonterminalStatus.model_validate(reconnecting))
        self.assertEqual(
            "2026-07-19T12:01:00Z",
            json.loads(self.status_path.read_text(encoding="utf-8"))["aircraft_ready_at_utc"],
        )

    def test_atomic_replace_uses_same_directory_unique_temp_and_cleans_it(self) -> None:
        writer = AtomicStatusWriter(self.status_path)
        replacements: list[tuple[Path, Path]] = []
        real_replace = os.replace

        def recording_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
            replacements.append((Path(source), Path(destination)))
            real_replace(source, destination)

        with patch("xpwebapi.capture_output.os.replace", side_effect=recording_replace):
            writer.write(status_document("starting"))
            writer.write(status_document("connecting"))
        self.assertEqual(2, len(replacements))
        self.assertEqual({self.status_path.parent}, {source.parent for source, _destination in replacements})
        self.assertEqual({self.status_path}, {destination for _source, destination in replacements})
        self.assertEqual(2, len({source.name for source, _destination in replacements}))
        self.assertEqual([self.status_path.name], [path.name for path in self.status_path.parent.iterdir()])
        self.assertTrue(self.status_path.read_bytes().endswith(b"\n"))

    def test_terminal_status_can_be_prepared_without_replacing_then_committed(self) -> None:
        writer = AtomicStatusWriter(self.status_path)
        for state in (
            "starting",
            "connecting",
            "transport_ready",
            "awaiting_aircraft",
            "subscribing",
            "awaiting_first_values",
            "aircraft_ready",
            "capturing",
            "finalizing",
        ):
            writer.write(status_document(state))
        before = self.status_path.read_bytes()

        prepared = writer.prepare(status_document("complete"), deadline=10.0, clock=lambda: 0.0)

        self.assertEqual(before, self.status_path.read_bytes())
        self.assertTrue(prepared.temporary_path.exists())
        writer.commit(prepared, deadline=10.0, clock=lambda: 0.0)
        self.assertEqual("complete", json.loads(self.status_path.read_text(encoding="utf-8"))["state"])
        self.assertFalse(prepared.temporary_path.exists())

    def test_status_prepare_and_commit_honor_deadline_and_abort_cleans_temp(self) -> None:
        writer = AtomicStatusWriter(self.status_path)
        writer.write(status_document("starting"))
        before = self.status_path.read_bytes()
        with self.assertRaises(TimeoutError):
            writer.prepare(status_document("connecting"), deadline=0.0, clock=lambda: 0.0)
        self.assertEqual(before, self.status_path.read_bytes())

        prepared = writer.prepare(status_document("connecting"), deadline=10.0, clock=lambda: 0.0)
        writer.abort(prepared)
        self.assertFalse(prepared.temporary_path.exists())
        self.assertEqual(before, self.status_path.read_bytes())

    def test_status_prepare_checks_deadline_after_fsync_and_cleans_temp(self) -> None:
        writer = AtomicStatusWriter(self.status_path)
        writer.write(status_document("starting"))
        clock = ManualClock()
        real_fsync = os.fsync

        def advancing_fsync(file_descriptor: int) -> None:
            real_fsync(file_descriptor)
            clock.now = 10.0

        with patch("xpwebapi.capture_output.os.fsync", side_effect=advancing_fsync), self.assertRaises(TimeoutError):
            writer.prepare(status_document("connecting"), deadline=10.0, clock=clock)
        self.assertEqual([self.status_path.name], [path.name for path in self.status_path.parent.iterdir()])

    def test_terminal_status_replace_is_commit_point_and_records_late_diagnostic(self) -> None:
        writer = AtomicStatusWriter(self.status_path)
        for state in (
            "starting",
            "connecting",
            "transport_ready",
            "awaiting_aircraft",
            "subscribing",
            "awaiting_first_values",
            "aircraft_ready",
            "capturing",
            "finalizing",
        ):
            writer.write(status_document(state))
        clock = ManualClock()
        prepared = writer.prepare(status_document("complete"), deadline=10.0, clock=clock)
        real_replace = os.replace

        def advancing_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
            real_replace(source, destination)
            clock.now = 10.0

        with patch("xpwebapi.capture_output.os.replace", side_effect=advancing_replace):
            writer.commit(prepared, deadline=10.0, clock=clock)
        self.assertEqual("complete", json.loads(self.status_path.read_text(encoding="utf-8"))["state"])
        self.assertTrue(writer.terminal_commit_deadline_exceeded)
        self.assertFalse(prepared.temporary_path.exists())

    def test_terminal_status_deadline_before_replace_does_not_publish(self) -> None:
        writer = AtomicStatusWriter(self.status_path)
        for state in (
            "starting",
            "connecting",
            "transport_ready",
            "awaiting_aircraft",
            "subscribing",
            "awaiting_first_values",
            "aircraft_ready",
            "capturing",
            "finalizing",
        ):
            writer.write(status_document(state))
        clock = ManualClock()
        prepared = writer.prepare(status_document("complete"), deadline=10.0, clock=clock)
        clock.now = 10.0

        with self.assertRaises(TimeoutError):
            writer.commit(prepared, deadline=10.0, clock=clock)

        self.assertEqual("finalizing", json.loads(self.status_path.read_text(encoding="utf-8"))["state"])
        self.assertFalse(writer.terminal_commit_deadline_exceeded)

    def test_expired_status_abort_still_removes_temporary_file(self) -> None:
        writer = AtomicStatusWriter(self.status_path)
        writer.write(status_document("starting"))
        clock = ManualClock()
        prepared = writer.prepare(status_document("connecting"), deadline=10.0, clock=clock)
        clock.now = 10.0

        with self.assertRaises(TimeoutError):
            writer.abort(prepared, deadline=10.0, clock=clock)

        self.assertFalse(prepared.temporary_path.exists())


if __name__ == "__main__":
    unittest.main()
