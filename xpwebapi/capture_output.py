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

        if self._closed:
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

    def close(self, payload: TerminalCaptureInput) -> dict[str, object]:
        """Append one terminal row, flush/fsync, and expose the complete hash."""

        if self._closed:
            raise ValueError("capture event writer is closed")
        event_type = _TERMINAL_EVENT_TYPES.get(payload.event)
        if event_type is None:
            raise ValueError(f"event {payload.event!r} is not terminal")
        document = {
            **self._envelope(),
            **payload.model_dump(mode="python"),
            "preceding_sha256": self._digest.hexdigest(),
        }
        validated = event_type.model_validate(document).model_dump(mode="python")
        result = self._append(cast(dict[str, object], validated))
        self._closed = True
        self._events_sha256 = self._digest.hexdigest()
        self._events_size_bytes = self._size_bytes
        finalization_error: BaseException | None = None
        try:
            self._stream.flush()
            os.fsync(self._stream.fileno())
        except BaseException as exc:
            finalization_error = exc
        try:
            self._stream.close()
        except BaseException as exc:
            if finalization_error is None:
                finalization_error = exc
        if finalization_error is not None:
            raise finalization_error
        return result


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

    def write(self, document: StatusDocument) -> None:
        """Validate and atomically publish one canonical status document."""

        validated = _STATUS_ADAPTER.validate_python(document.model_dump(mode="python"))
        self._validate_transition(validated)
        payload = cast(dict[str, object], validated.model_dump(mode="python"))
        status_bytes = _json_bytes(payload)
        temporary = self._path.with_name(f".{self._path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(status_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        self._previous = validated


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
