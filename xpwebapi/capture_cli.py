"""Command-line entry point for strictly read-only X-Plane capture."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import BinaryIO, Literal, TextIO, cast

from xpwebapi.capture_events import CaptureEventIdentity, SourceProvenance, VersionJsonDocument
from xpwebapi.capture_output import AtomicStatusWriter, CaptureEventWriter, resolve_source_provenance
from xpwebapi.capture_protocol import LoadedCaptureRequest, load_capture_request, resolve_stop_file
from xpwebapi.capture_runner import CaptureClock, CaptureInterruption, CaptureOutcome, CaptureRunner
from xpwebapi.capture_transport import create_capture_transport


class CaptureCliError(ValueError):
    """Invalid command-line mode or capture preflight input."""


class CaptureCliRuntimeError(RuntimeError):
    """Runtime setup failed after evidence paths were reserved."""


class _SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def utcnow(self) -> datetime:
        return datetime.now(UTC)

    def wait(self, event: threading.Event, timeout: float) -> bool:
        return event.wait(timeout)


def build_parser() -> argparse.ArgumentParser:
    """Build the two-mode capture-worker argument parser."""

    parser = argparse.ArgumentParser(
        prog="xpwebapi-capture",
        description="Capture configured X-Plane DataRefs through strictly read-only transports.",
    )
    parser.add_argument("--version-json", action="store_true", help="emit machine-readable worker provenance and exit")
    parser.add_argument("--request", type=Path, help="versioned capture request JSON")
    parser.add_argument("--events", type=Path, help="new immutable capture event JSONL")
    parser.add_argument("--status", type=Path, help="new atomic capture status JSON")
    parser.add_argument("--stop-file", type=Path, help="optional stop-file path")
    return parser


def validate_cli_mode(namespace: argparse.Namespace) -> None:
    """Require version-only mode or one complete capture invocation."""

    capture_values = (namespace.request, namespace.events, namespace.status, namespace.stop_file)
    if namespace.version_json:
        if any(value is not None for value in capture_values):
            raise CaptureCliError("--version-json cannot be combined with capture arguments")
        return
    if namespace.request is None or namespace.events is None or namespace.status is None:
        raise CaptureCliError("capture mode requires --request, --events, and --status")


def _version_document(provenance: SourceProvenance) -> VersionJsonDocument:
    return VersionJsonDocument(
        **provenance.model_dump(mode="python"),
        supported_transports=("udp", "websocket"),
        worker="xpwebapi-capture",
        worker_protocol_version=1,
    )


def emit_version_json(document: VersionJsonDocument, stream: TextIO) -> None:
    """Write one canonical protocol-v1 version object and one LF."""

    rendered = json.dumps(
        document.model_dump(mode="json"),
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    payload = (rendered + "\n").encode("utf-8")
    binary_stream = getattr(stream, "buffer", None)
    if binary_stream is None:
        stream.write(payload.decode("utf-8"))
    else:
        cast(BinaryIO, binary_stream).write(payload)


def install_signal_handlers(
    stop_event: threading.Event,
    interrupted_event: threading.Event,
    interruption: CaptureInterruption | None = None,
) -> None:
    """Install handlers that request shutdown and retain the first signal name."""

    def handle_signal(signum: int, _frame: FrameType | None) -> None:
        if interruption is not None:
            name = signal.Signals(signum).name
            interruption.set(cast(Literal["SIGINT", "SIGTERM"], name))
        interrupted_event.set()
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)


def _path_identity(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def _require_output_parent(path: Path) -> None:
    if not path.parent.exists() or not path.parent.is_dir():
        raise CaptureCliError(f"output parent is not an existing directory: {path.parent}")


def preflight_paths(events: Path, status: Path, stop_file: Path | None) -> None:
    """Validate output/stop path separation without mutating the filesystem."""

    resolved_events = events.resolve()
    resolved_status = status.resolve()
    resolved_stop = stop_file.resolve() if stop_file is not None else None
    paths = {"events": resolved_events, "status": resolved_status}
    if resolved_stop is not None:
        paths["stop file"] = resolved_stop
    identities: dict[str, str] = {}
    for name, path in paths.items():
        identity = _path_identity(path)
        previous = identities.get(identity)
        if previous is not None:
            raise CaptureCliError(f"path alias between {previous} and {name}: {path}")
        identities[identity] = name
    _require_output_parent(resolved_events)
    _require_output_parent(resolved_status)
    for name, path in (("events", resolved_events), ("status", resolved_status), ("stop file", resolved_stop)):
        if path is not None and path.exists():
            raise CaptureCliError(f"{name} path already exists: {path}")


def _preflight_request_aliases(request: Path, events: Path, status: Path, stop_file: Path | None) -> None:
    paths = {"request": request, "events": events, "status": status}
    if stop_file is not None:
        paths["stop file"] = stop_file
    identities: dict[str, str] = {}
    for name, path in paths.items():
        identity = _path_identity(path)
        previous = identities.get(identity)
        if previous is not None:
            raise CaptureCliError(f"path alias between {previous} and {name}: {path}")
        identities[identity] = name


def _load_preflight(
    request_path: Path,
    events_path: Path,
    status_path: Path,
    cli_stop_file: Path | None,
) -> tuple[LoadedCaptureRequest, Path, Path, Path, Path | None]:
    try:
        request = request_path.resolve()
        events = events_path.resolve()
        status = status_path.resolve()
        loaded = load_capture_request(request)
        request_stop = Path(loaded.request.stop_file) if loaded.request.stop_file is not None else None
        stop_file = resolve_stop_file(request, request_stop, cli_stop_file)
        _preflight_request_aliases(request, events, status, stop_file)
        preflight_paths(events, status, stop_file)
    except FileExistsError as exc:
        path = exc.filename or str(exc)
        raise CaptureCliError(f"path already exists: {path}") from exc
    except (OSError, ValueError) as exc:
        raise CaptureCliError(str(exc)) from exc
    return loaded, request, events, status, stop_file


def _abandon_event_reservation(writer: CaptureEventWriter) -> str | None:
    try:
        writer.abandon(deadline=None)
    except BaseException as exc:
        detail = str(exc).strip() or type(exc).__name__
        return detail
    return None


def _reserve_writers(
    events_path: Path,
    status_path: Path,
    identity: CaptureEventIdentity,
    clock: CaptureClock,
) -> tuple[CaptureEventWriter, AtomicStatusWriter]:
    try:
        event_writer = CaptureEventWriter(events_path, identity, clock)
    except OSError as exc:
        raise CaptureCliError(f"events path already exists or cannot be created: {events_path}: {exc}") from exc
    try:
        with status_path.open("xb"):
            pass
    except OSError as exc:
        close_error = _abandon_event_reservation(event_writer)
        # The design says both "It creates neither output when preflight fails."
        # and "it never removes a pre-existing or non-empty file." There is no
        # portable atomic compare-and-unlink for an arbitrary path. On this rare
        # second-reservation race, preserving the first zero-byte reservation is
        # the only policy that cannot delete a competitor replacement.
        detail = f"output_reservation_partial: status reservation failed after the events reservation was created; preserved events path {events_path}: {exc}"
        if close_error is not None:
            detail = f"{detail}; event close failed: {close_error}"
        raise CaptureCliError(detail) from exc
    return event_writer, AtomicStatusWriter(status_path)


def run_capture(
    request_path: Path,
    events_path: Path,
    status_path: Path,
    cli_stop_file: Path | None,
    stop_event: threading.Event,
    interrupted_event: threading.Event,
    interruption: CaptureInterruption | None = None,
) -> CaptureOutcome:
    """Preflight, reserve evidence, and run one bounded capture lifecycle."""

    loaded, _request_path, events, status, stop_file = _load_preflight(
        request_path,
        events_path,
        status_path,
        cli_stop_file,
    )
    provenance = resolve_source_provenance()
    clock = _SystemClock()
    identity = CaptureEventIdentity(
        capture_session_id=loaded.request.capture_session_id,
        sortie_id=loaded.request.sortie_id,
    )
    event_writer, status_writer = _reserve_writers(events, status, identity, clock)
    signal_identity = interruption if interruption is not None else CaptureInterruption()
    try:
        runner = CaptureRunner(
            request=loaded.request,
            request_sha256=loaded.request_sha256,
            provenance=provenance,
            stop_file=stop_file,
            transport_factory=lambda: create_capture_transport(loaded.request),
            event_writer=event_writer,
            status_writer=status_writer,
            clock=clock,
            events_path=events,
            interruption=signal_identity,
        )
    except BaseException as exc:
        close_error = _abandon_event_reservation(event_writer)
        detail = f"output_reservation_partial: runner construction failed after events and status reservations were created; preserved both paths: {exc}"
        if close_error is not None:
            detail = f"{detail}; event close failed: {close_error}"
        raise CaptureCliRuntimeError(detail) from exc
    try:
        outcome = runner.run(stop_event, interrupted_event)
    except BaseException as exc:
        close_error = _abandon_event_reservation(event_writer)
        detail = f"output_reservation_partial: runner escaped without an outcome after evidence ownership began; preserved events and status paths: {exc}"
        if close_error is not None:
            detail = f"{detail}; event close failed: {close_error}"
        raise CaptureCliRuntimeError(detail) from exc
    close_error = _abandon_event_reservation(event_writer)
    if close_error is not None:
        raise CaptureCliRuntimeError(
            f"output_reservation_partial: runner returned but event stream close failed; preserved events and status paths: {close_error}"
        )
    return outcome


def _diagnostic(prefix: str, error: BaseException) -> None:
    detail = str(error).strip() or type(error).__name__
    print(f"xpwebapi-capture: {prefix}: {detail}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the capture worker and return its stable process exit code."""

    parser = build_parser()
    try:
        namespace = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    try:
        validate_cli_mode(namespace)
    except CaptureCliError as exc:
        parser.print_usage(sys.stderr)
        _diagnostic("invalid arguments", exc)
        return 2
    if namespace.version_json:
        emit_version_json(_version_document(resolve_source_provenance()), sys.stdout)
        return 0

    stop_event = threading.Event()
    interrupted_event = threading.Event()
    interruption = CaptureInterruption()
    install_signal_handlers(stop_event, interrupted_event, interruption)
    try:
        capture_outcome = run_capture(
            namespace.request,
            namespace.events,
            namespace.status,
            namespace.stop_file,
            stop_event,
            interrupted_event,
            interruption,
        )
    except CaptureCliError as exc:
        _diagnostic("capture preflight failed", exc)
        return 2
    except BaseException as exc:
        _diagnostic("capture runtime failed", exc)
        return 3
    return capture_outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
