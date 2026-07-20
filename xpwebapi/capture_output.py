"""Durable JSONL events, atomic status output, and source provenance."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import platform
import secrets

# Only fixed Git metadata commands are executed, always without a shell.
import subprocess  # nosec B404
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from pydantic import TypeAdapter

from xpwebapi.capture_events import (
    LEGAL_STATUS_TRANSITIONS,
    AircraftReadyEvent,
    CaptureEventIdentity,
    CaptureEventPayload,
    CaptureFailedEvent,
    CaptureInterruptedEvent,
    CaptureStartedEvent,
    CaptureStoppedEvent,
    GapEndedEvent,
    GapStartedEvent,
    RetryEvent,
    SampleEvent,
    SourceProvenance,
    StatusDocument,
    SubscriptionResultEvent,
    TerminalCaptureInput,
    TransportReadyEvent,
    TransportStateEvent,
)


_STATUS_ADAPTER = TypeAdapter(StatusDocument)
_EVENT_TYPES = {
    "capture_started": CaptureStartedEvent,
    "transport_state": TransportStateEvent,
    "transport_ready": TransportReadyEvent,
    "subscription_result": SubscriptionResultEvent,
    "aircraft_ready": AircraftReadyEvent,
    "sample": SampleEvent,
    "gap_started": GapStartedEvent,
    "gap_ended": GapEndedEvent,
    "retry": RetryEvent,
}
_TERMINAL_EVENT_TYPES = {
    "capture_stopped": CaptureStoppedEvent,
    "capture_failed": CaptureFailedEvent,
    "capture_interrupted": CaptureInterruptedEvent,
}


class EventClock(Protocol):
    """Clock surface used to construct deterministic evidence envelopes."""

    def monotonic(self) -> float: ...

    def utcnow(self) -> datetime: ...


DeadlineClock = Callable[[], float]


def _require_deadline(deadline: float | None, clock: DeadlineClock) -> None:
    if deadline is not None and clock() >= deadline:
        raise TimeoutError("capture output deadline expired")


@dataclass(frozen=True, slots=True)
class PreparedCaptureClose:
    """Validated terminal row and its projected complete-file identity."""

    document: dict[str, object]
    row_bytes: bytes
    events_sha256: str
    events_size_bytes: int


@dataclass(frozen=True, slots=True)
class PreparedStatus:
    """Durable status temporary file awaiting its atomic replace."""

    document: StatusDocument
    temporary_path: Path


def _timestamp_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock.utcnow() must return an aware datetime")
    utc = value.astimezone(UTC)
    rendered = utc.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return rendered


def _json_bytes(document: dict[str, object]) -> bytes:
    text = json.dumps(document, allow_nan=False, sort_keys=True, separators=(",", ":"))
    return (text + "\n").encode("utf-8")


class CaptureEventWriter:
    """Append immutable, canonical event rows and seal them with a terminal row."""

    def __init__(self, path: Path, identity: CaptureEventIdentity, clock: EventClock) -> None:
        self._path = path
        self._identity = CaptureEventIdentity.model_validate(identity.model_dump(mode="python"))
        self._clock = clock
        self._opened_monotonic = clock.monotonic()
        self._last_elapsed_seconds = 0.0
        self._sequence = 0
        self._digest = hashlib.sha256()
        self._size_bytes = 0
        self._closed = False
        self._events_sha256: str | None = None
        self._events_size_bytes: int | None = None
        self._prepared_close: PreparedCaptureClose | None = None
        self._stream = path.open("xb")

    @property
    def events_sha256(self) -> str:
        """SHA-256 of the complete, terminally sealed JSONL file."""

        if self._events_sha256 is None:
            raise ValueError("events SHA-256 is unavailable before close")
        return self._events_sha256

    @property
    def events_size_bytes(self) -> int:
        """Byte size of the complete, terminally sealed JSONL file."""

        if self._events_size_bytes is None:
            raise ValueError("events size is unavailable before close")
        return self._events_size_bytes

    def _envelope(self) -> dict[str, object]:
        elapsed = self._clock.monotonic() - self._opened_monotonic
        if not math.isfinite(elapsed) or elapsed < self._last_elapsed_seconds:
            raise ValueError("event clock must be finite and monotonic")
        return {
            "protocol_version": 1,
            "sequence": self._sequence + 1,
            "capture_session_id": self._identity.capture_session_id,
            "sortie_id": self._identity.sortie_id,
            "timestamp_utc": _timestamp_utc(self._clock.utcnow()),
            "elapsed_seconds": float(elapsed),
        }

    def _append(self, document: dict[str, object]) -> dict[str, object]:
        row_bytes = _json_bytes(document)
        self._stream.write(row_bytes)
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._digest.update(row_bytes)
        self._size_bytes += len(row_bytes)
        self._sequence += 1
        self._last_elapsed_seconds = cast(float, document["elapsed_seconds"])
        return document

    def write(self, payload: CaptureEventPayload) -> dict[str, object]:
        """Validate and durably append one nonterminal event payload."""

        if self._closed or self._prepared_close is not None:
            raise ValueError("capture event writer is closed")
        event = payload.event
        event_type = _EVENT_TYPES.get(event)
        if event_type is None:
            raise ValueError(f"event {event!r} is terminal or unsupported by write()")
        document = {
            **self._envelope(),
            **payload.model_dump(mode="python"),
        }
        validated = event_type.model_validate(document).model_dump(mode="python")
        return self._append(cast(dict[str, object], validated))

    def prepare_close(
        self,
        payload: TerminalCaptureInput,
        deadline: float | None,
    ) -> PreparedCaptureClose:
        """Validate a terminal row and project the sealed identity without mutation."""

        if self._closed or self._prepared_close is not None:
            raise ValueError("capture event writer is closed")
        _require_deadline(deadline, self._clock.monotonic)
        event_type = _TERMINAL_EVENT_TYPES.get(payload.event)
        if event_type is None:
            raise ValueError(f"event {payload.event!r} is not terminal")
        document = {
            **self._envelope(),
            **payload.model_dump(mode="python"),
            "preceding_sha256": self._digest.hexdigest(),
        }
        validated = event_type.model_validate(document).model_dump(mode="python")
        terminal_document = cast(dict[str, object], validated)
        row_bytes = _json_bytes(terminal_document)
        projected_digest = self._digest.copy()
        projected_digest.update(row_bytes)
        prepared = PreparedCaptureClose(
            document=terminal_document,
            row_bytes=row_bytes,
            events_sha256=projected_digest.hexdigest(),
            events_size_bytes=self._size_bytes + len(row_bytes),
        )
        self._prepared_close = prepared
        return prepared

    def abort_close(self, prepared: PreparedCaptureClose) -> None:
        """Release a prepared terminal row without changing the event stream."""

        if prepared is not self._prepared_close:
            raise ValueError("prepared capture close does not belong to this writer")
        self._prepared_close = None

    def abandon(self, deadline: float | None) -> None:
        """Close an unsealed stream while retaining every already-written evidence byte."""

        expired = deadline is not None and self._clock.monotonic() >= deadline
        self._prepared_close = None
        self._closed = True
        self._stream.close()
        if expired or (deadline is not None and self._clock.monotonic() >= deadline):
            raise TimeoutError("capture output deadline expired")

    def commit_close(
        self,
        prepared: PreparedCaptureClose,
        deadline: float | None,
    ) -> dict[str, object]:
        """Durably append a prepared terminal row and close the event stream."""

        if prepared is not self._prepared_close or self._closed:
            raise ValueError("prepared capture close does not belong to this writer")
        _require_deadline(deadline, self._clock.monotonic)
        try:
            written = self._stream.write(prepared.row_bytes)
        except BaseException:
            self._prepared_close = None
            self._closed = True
            self._stream.close()
            raise
        if written != len(prepared.row_bytes):
            self._prepared_close = None
            self._closed = True
            self._stream.close()
            raise OSError(f"incomplete terminal event write: {written} of {len(prepared.row_bytes)} bytes")

        # A complete canonical terminal row is the immutable JSONL commit point.
        self._digest.update(prepared.row_bytes)
        self._size_bytes = prepared.events_size_bytes
        self._sequence += 1
        self._last_elapsed_seconds = cast(float, prepared.document["elapsed_seconds"])
        self._closed = True
        self._events_sha256 = prepared.events_sha256
        self._events_size_bytes = prepared.events_size_bytes
        self._prepared_close = None
        finalization_error: BaseException | None = None
        try:
            _require_deadline(deadline, self._clock.monotonic)
            self._stream.flush()
            _require_deadline(deadline, self._clock.monotonic)
            os.fsync(self._stream.fileno())
            _require_deadline(deadline, self._clock.monotonic)
            self._stream.flush()
            _require_deadline(deadline, self._clock.monotonic)
            os.fsync(self._stream.fileno())
            _require_deadline(deadline, self._clock.monotonic)
        except BaseException as exc:
            finalization_error = exc
        try:
            self._stream.close()
            _require_deadline(deadline, self._clock.monotonic)
        except BaseException as exc:
            if finalization_error is None:
                finalization_error = exc
        if finalization_error is not None:
            raise finalization_error
        return prepared.document

    def close(self, payload: TerminalCaptureInput) -> dict[str, object]:
        """Append one terminal row, flush/fsync, and expose the complete hash."""

        prepared = self.prepare_close(payload, deadline=None)
        return self.commit_close(prepared, deadline=None)


class AtomicStatusWriter:
    """Validate lifecycle transitions and atomically replace polling status."""

    _IMMUTABLE_FIELDS = (
        "protocol_version",
        "capture_session_id",
        "sortie_id",
        "events_path",
        "request_sha256",
        "transport",
        "target_aircraft",
        "identity_ref_count",
        "required_capture_ref_count",
    )

    def __init__(self, path: Path) -> None:
        self._path = path
        self._previous: StatusDocument | None = None
        self._prepared: PreparedStatus | None = None

    def _validate_transition(self, document: StatusDocument) -> None:
        previous = self._previous
        if previous is None:
            if document.state != "starting":
                raise ValueError("the first capture status must be starting")
            return
        if document.state not in LEGAL_STATUS_TRANSITIONS[previous.state]:
            raise ValueError(f"illegal capture status transition: {previous.state} -> {document.state}")
        for field_name in self._IMMUTABLE_FIELDS:
            if getattr(document, field_name) != getattr(previous, field_name):
                raise ValueError(f"status field {field_name} is immutable")
        for latch_name in ("transport_ready_at_utc", "aircraft_ready_at_utc"):
            prior_latch = getattr(previous, latch_name)
            current_latch = getattr(document, latch_name)
            if prior_latch is not None and current_latch != prior_latch:
                raise ValueError(f"status latch {latch_name} is write-once and persistent")
            expected_state = "transport_ready" if latch_name == "transport_ready_at_utc" else "aircraft_ready"
            if prior_latch is None and current_latch is not None and document.state != expected_state:
                raise ValueError(f"status latch {latch_name} can be set only in {expected_state}")
        if previous.state == document.state and document.state in {"connecting", "reconnecting"}:
            if document.current_attempt <= previous.current_attempt:
                raise ValueError("repeated connection status must strictly increment current_attempt")

    def prepare(
        self,
        document: StatusDocument,
        deadline: float | None,
        clock: DeadlineClock = time.monotonic,
    ) -> PreparedStatus:
        """Validate and durably stage one status without replacing the published file."""

        if self._prepared is not None:
            raise ValueError("a status document is already prepared")
        _require_deadline(deadline, clock)
        validated = _STATUS_ADAPTER.validate_python(document.model_dump(mode="python"))
        self._validate_transition(validated)
        payload = cast(dict[str, object], validated.model_dump(mode="python"))
        status_bytes = _json_bytes(payload)
        temporary = self._path.with_name(f".{self._path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
        try:
            _require_deadline(deadline, clock)
            with temporary.open("xb") as stream:
                _require_deadline(deadline, clock)
                written = stream.write(status_bytes)
                if written != len(status_bytes):
                    raise OSError(f"incomplete status write: {written} of {len(status_bytes)} bytes")
                _require_deadline(deadline, clock)
                stream.flush()
                _require_deadline(deadline, clock)
                os.fsync(stream.fileno())
                _require_deadline(deadline, clock)
            _require_deadline(deadline, clock)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        prepared = PreparedStatus(document=validated, temporary_path=temporary)
        self._prepared = prepared
        return prepared

    def commit(
        self,
        prepared: PreparedStatus,
        deadline: float | None,
        clock: DeadlineClock = time.monotonic,
    ) -> None:
        """Atomically publish a previously prepared status document."""

        if prepared is not self._prepared:
            raise ValueError("prepared status does not belong to this writer")
        try:
            _require_deadline(deadline, clock)
            os.replace(prepared.temporary_path, self._path)
            self._previous = prepared.document
            self._prepared = None
            _require_deadline(deadline, clock)
        except BaseException:
            prepared.temporary_path.unlink(missing_ok=True)
            self._prepared = None
            raise

    def abort(
        self,
        prepared: PreparedStatus,
        deadline: float | None = None,
        clock: DeadlineClock = time.monotonic,
    ) -> None:
        """Remove an unpublished prepared status document."""

        if prepared is not self._prepared:
            raise ValueError("prepared status does not belong to this writer")
        expired = deadline is not None and clock() >= deadline
        prepared.temporary_path.unlink(missing_ok=True)
        self._prepared = None
        if expired or (deadline is not None and clock() >= deadline):
            raise TimeoutError("capture output deadline expired")

    def write(
        self,
        document: StatusDocument,
        deadline: float | None = None,
        clock: DeadlineClock = time.monotonic,
    ) -> None:
        """Validate and atomically publish one canonical status document."""

        prepared = self.prepare(document, deadline=deadline, clock=clock)
        self.commit(prepared, deadline=deadline, clock=clock)


def _run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    # Callers supply the four fixed protocol argument vectors below.
    return subprocess.run(  # nosec B603
        args,
        timeout=2,
        check=False,
        capture_output=True,
        text=True,
    )


def _unavailable_provenance(package_version: str) -> SourceProvenance:
    return SourceProvenance(
        package_name="xpwebapi",
        package_version=package_version,
        python_version=platform.python_version(),
        git_state="unavailable",
        git_root=None,
        git_revision=None,
        git_origin=None,
        git_dirty=None,
        read_only=True,
    )


def resolve_source_provenance() -> SourceProvenance:
    """Resolve bounded package and Git provenance from this installed module."""

    try:
        package_version = importlib.metadata.version("xpwebapi")
    except importlib.metadata.PackageNotFoundError:
        package_version = "unknown"
    module_directory = Path(__file__).resolve().parent
    try:
        root_result = _run_git(["git", "-C", str(module_directory), "rev-parse", "--show-toplevel"])
        if root_result.returncode != 0 or not root_result.stdout.strip():
            return _unavailable_provenance(package_version)
        root = root_result.stdout.strip()
        revision_result = _run_git(["git", "-C", root, "rev-parse", "HEAD"])
        origin_result = _run_git(["git", "-C", root, "config", "--get", "remote.origin.url"])
        dirty_result = _run_git(["git", "-C", root, "status", "--porcelain"])
        if revision_result.returncode != 0 or not revision_result.stdout.strip() or dirty_result.returncode != 0:
            return _unavailable_provenance(package_version)
        origin = origin_result.stdout.strip() if origin_result.returncode == 0 and origin_result.stdout.strip() else None
        return SourceProvenance(
            package_name="xpwebapi",
            package_version=package_version,
            python_version=platform.python_version(),
            git_state="available",
            git_root=root,
            git_revision=revision_result.stdout.strip(),
            git_origin=origin,
            git_dirty=bool(dirty_result.stdout),
            read_only=True,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return _unavailable_provenance(package_version)
