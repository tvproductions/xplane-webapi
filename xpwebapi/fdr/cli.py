"""Command-line entry point for the X-Plane FDR toolkit."""

from __future__ import annotations

import argparse
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
import json
import math
import os
from pathlib import Path
import secrets
import signal
import sys
import threading
import time
from types import FrameType
from typing import Any, BinaryIO, NoReturn, TextIO, cast

from xpwebapi.capture_protocol import WebsocketCaptureConfig
from xpwebapi.fdr import (
    FDRDataref,
    FDRHeader,
    FDRMetadata,
    FDRReader,
    FDRRecorder,
    FDRRecording,
    FDRStreamWriter,
    FDRWriter,
    LiveFDRSampleSource,
    recording_to_geojson,
)


_MANDATORY_FIELDS = (
    "time_utc",
    "longitude",
    "latitude",
    "altitude_msl_ft",
    "heading_magnetic_deg",
    "pitch_deg",
    "roll_deg",
)
_PARTIAL_ATTEMPTS = 100
_SIGNAL_POLL_SECONDS = 0.1
_SUBSCRIPTION_TIMEOUT_SECONDS = 5.0


class FDRCliArgumentError(ValueError):
    """A relationship between otherwise parsed arguments is invalid."""


def _date_argument(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}; expected YYYY-MM-DD") from exc


def _positive_float_argument(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid positive number: {value!r}") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError(f"invalid positive number: {value!r}")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """Build the FDR toolkit argument parser."""

    parser = argparse.ArgumentParser(prog="xpwebapi-fdr", description="Record, inspect, validate, and convert X-Plane FDR files.")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="strictly parse and validate an FDR file")
    validate.add_argument("input", type=Path)

    inspect = commands.add_parser("inspect", help="print a normalized FDR summary")
    inspect.add_argument("input", type=Path)
    inspect.add_argument("--json", action="store_true", help="emit one compact JSON object")
    inspect.add_argument("--first-utc-date", type=_date_argument, metavar="YYYY-MM-DD")

    geojson = commands.add_parser("to-geojson", help="convert an FDR file to GeoJSON")
    geojson.add_argument("input", type=Path)
    geojson.add_argument("output", type=Path)
    geojson.add_argument("--first-utc-date", type=_date_argument, metavar="YYYY-MM-DD")
    geojson.add_argument("--overwrite", action="store_true")

    record = commands.add_parser("record", help="record live X-Plane Web API values")
    record.add_argument("output", type=Path)
    record.add_argument("--host", default="127.0.0.1")
    record.add_argument("--port", type=int, default=8086)
    record.add_argument("--api-path", default="/api")
    record.add_argument("--api-version", default="v2")
    record.add_argument("--interval", type=_positive_float_argument, default=1.0, metavar="SECONDS")
    record.add_argument("--duration", type=_positive_float_argument, metavar="SECONDS")
    record.add_argument("--local-date", type=_date_argument, metavar="YYYY-MM-DD")
    record.add_argument("--dataref", action="append", default=[], metavar="PATH")
    record.add_argument("--scale", action="append", default=[], metavar="PATH=FLOAT")
    record.add_argument("--comment", action="append", default=[], metavar="PATH=TEXT")
    record.add_argument("--overwrite", action="store_true")
    return parser


def _assignment(value: str, option: str) -> tuple[str, str]:
    path, separator, assigned = value.partition("=")
    if not separator or not path:
        raise FDRCliArgumentError(f"{option} requires PATH=VALUE")
    return path, assigned


def _unique_assignments(values: Sequence[str], option: str) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for value in values:
        path, assigned = _assignment(value, option)
        if path in assignments:
            raise FDRCliArgumentError(f"{option} may be specified only once for {path}")
        assignments[path] = assigned
    return assignments


def _valid_dataref_path(path: str) -> bool:
    return bool(path) and "//" not in path and not any(character.isspace() for character in path)


def _record_datarefs(namespace: argparse.Namespace) -> tuple[FDRDataref, ...]:
    """Resolve ordered DataRefs and their path-keyed scale and comment options."""

    paths = cast(list[str], namespace.dataref)
    if len(set(paths)) != len(paths):
        raise FDRCliArgumentError("--dataref paths must be unique")
    if any(not _valid_dataref_path(path) for path in paths):
        raise FDRCliArgumentError("--dataref paths must be non-empty and contain no whitespace or '//'")
    scales = _unique_assignments(cast(list[str], namespace.scale), "--scale")
    comments = _unique_assignments(cast(list[str], namespace.comment), "--comment")
    undeclared = tuple(path for path in (*scales, *comments) if path not in paths)
    if undeclared:
        raise FDRCliArgumentError(f"--scale and --comment require a matching --dataref: {undeclared[0]}")

    parsed_scales: dict[str, float] = {}
    for path, text in scales.items():
        try:
            scale = float(text)
        except ValueError as exc:
            raise FDRCliArgumentError(f"--scale for {path} must be a finite float") from exc
        if not math.isfinite(scale):
            raise FDRCliArgumentError(f"--scale for {path} must be a finite float")
        parsed_scales[path] = scale
    if any("\n" in comment or "\r" in comment for comment in comments.values()):
        raise FDRCliArgumentError("--comment values must be single-line text")
    return tuple(FDRDataref(path, parsed_scales.get(path, 1.0), comments.get(path)) for path in paths)


def _validate_record_arguments(namespace: argparse.Namespace) -> None:
    if not 1 <= namespace.port <= 65535:
        raise FDRCliArgumentError("--port must be from 1 through 65535")
    for option in ("host", "api_path", "api_version"):
        if not cast(str, getattr(namespace, option)).strip():
            raise FDRCliArgumentError(f"--{option.replace('_', '-')} must be non-empty")
    _record_datarefs(namespace)


def _json_line(document: object) -> str:
    return json.dumps(document, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"


def _write_json_stdout(document: object, stream: TextIO) -> None:
    payload = _json_line(document).encode("utf-8")
    binary_stream = getattr(stream, "buffer", None)
    if binary_stream is None:
        stream.write(payload.decode("utf-8"))
    else:
        cast(BinaryIO, binary_stream).write(payload)


def _utc_datetime_text(value: datetime) -> str:
    return f"{value.isoformat().removesuffix('+00:00')}Z"


def _inspection(recording: FDRRecording, first_utc_date: date | None) -> dict[str, object]:
    """Build the normalized JSON-compatible summary for one recording."""

    metadata = [{"key": item.key, "value": item.value} for item in recording.header.metadata]
    effective_metadata: dict[str, str] = {}
    for item in recording.header.metadata:
        effective_metadata[item.key] = item.value
    datarefs = [{"path": item.path, "scale": item.scale, "comment": item.comment} for item in recording.header.datarefs]
    legacy_columns = [{"field_id": item.field_id, "comment": item.comment} for item in recording.header.legacy_columns]
    fields = (*_MANDATORY_FIELDS, *(item.path for item in recording.header.datarefs), *(item.field_id for item in recording.header.legacy_columns))

    start_utc: str | None = None
    end_utc: str | None = None
    if recording.samples:
        if first_utc_date is None:
            start_utc = recording.samples[0].time_utc.isoformat()
            end_utc = recording.samples[-1].time_utc.isoformat()
        else:
            resolved = recording.resolved_utc_datetimes(first_utc_date)
            start_utc = _utc_datetime_text(resolved[0])
            end_utc = _utc_datetime_text(resolved[-1])
    return {
        "comments": list(recording.header.comments),
        "datarefs": datarefs,
        "duration_seconds": recording.duration.total_seconds(),
        "effective_metadata": effective_metadata,
        "end_utc": end_utc,
        "fields": list(fields),
        "legacy_columns": legacy_columns,
        "local_date": recording.header.local_date.isoformat() if recording.header.local_date is not None else None,
        "metadata": metadata,
        "origin": recording.header.source_origin,
        "sample_count": len(recording.samples),
        "start_utc": start_utc,
        "version": recording.header.source_version,
    }


def _write_human_inspection(document: dict[str, object], stream: TextIO) -> None:
    stream.write(f"Version: {document['version']}\n")
    stream.write(f"Origin: {document['origin']}\n")
    stream.write(f"Local date: {document['local_date'] or '-'}\n")
    stream.write(f"Samples: {document['sample_count']}\n")
    stream.write(f"Start UTC: {document['start_utc'] or '-'}\n")
    stream.write(f"End UTC: {document['end_utc'] or '-'}\n")
    stream.write(f"Duration: {cast(float, document['duration_seconds']):.3f} seconds\n")
    stream.write(f"Fields: {', '.join(cast(list[str], document['fields']))}\n")
    stream.write("Metadata:\n")
    metadata = cast(list[dict[str, str]], document["metadata"])
    if not metadata:
        stream.write("  -\n")
    for item in metadata:
        stream.write(f"  {item['key']}: {item['value']}\n")


def _create_partial(destination: Path) -> tuple[Path, TextIO]:
    for _attempt in range(_PARTIAL_ATTEMPTS):
        partial = destination.with_name(f".{destination.name}.{secrets.token_hex(8)}.partial")
        try:
            return partial, partial.open("x", encoding="utf-8", newline="\n")
        except FileExistsError:
            continue
    raise FileExistsError(f"could not create a unique partial file beside {destination}")


def _write_atomic_json(document: object, destination: Path, *, overwrite: bool) -> None:
    """Durably commit canonical JSON from a unique sibling partial file."""

    if destination.exists() and not overwrite:
        raise FileExistsError(f"destination already exists: {destination}")
    payload = _json_line(document)
    partial, stream = _create_partial(destination)
    try:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
        stream.close()
        if overwrite:
            os.replace(partial, destination)
        else:
            os.link(partial, destination)
            try:
                partial.unlink()
            except OSError:
                pass
    except BaseException:
        if not stream.closed:
            stream.close()
        raise


def _run_validate(namespace: argparse.Namespace) -> int:
    FDRReader().read(namespace.input)
    return 0


def _run_inspect(namespace: argparse.Namespace) -> int:
    recording = FDRReader().read(namespace.input)
    document = _inspection(recording, namespace.first_utc_date)
    if namespace.json:
        _write_json_stdout(document, sys.stdout)
    else:
        _write_human_inspection(document, sys.stdout)
    return 0


def _run_to_geojson(namespace: argparse.Namespace) -> int:
    recording = FDRReader().read(namespace.input)
    document = recording_to_geojson(recording, first_utc_date=namespace.first_utc_date)
    _write_atomic_json(document, namespace.output, overwrite=namespace.overwrite)
    return 0


@contextmanager
def _record_signal_context(stop_event: threading.Event, interrupted_event: threading.Event) -> Iterator[None]:
    """Install temporary CLI-only stop handlers and restore prior handlers."""

    previous: list[tuple[int, Any]] = []

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        interrupted_event.set()
        stop_event.set()

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous.append((signum, signal.getsignal(signum)))
            signal.signal(signum, request_stop)
        yield
    finally:
        for signum, handler in reversed(previous):
            signal.signal(signum, handler)


def _record_header(namespace: argparse.Namespace) -> FDRHeader:
    local_date = namespace.local_date or date.today()
    return FDRHeader(
        source_version=4,
        source_origin="A",
        comments=(),
        metadata=(FDRMetadata("DATE", local_date.isoformat()),),
        datarefs=_record_datarefs(namespace),
        legacy_columns=(),
        local_date=local_date,
    )


def _preflight_record_output(destination: Path, overwrite: bool) -> None:
    if destination.exists() and not overwrite:
        raise FileExistsError(f"destination already exists: {destination}")
    if not destination.parent.is_dir():
        raise FileNotFoundError(f"output parent does not exist: {destination.parent}")


def _interruptible_wait(interrupted_event: threading.Event, target: threading.Event, timeout: float) -> bool:
    """Wait for a source event while retaining prompt CLI signal response."""

    deadline = time.monotonic() + timeout
    while not interrupted_event.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return target.is_set()
        if target.wait(min(_SIGNAL_POLL_SECONDS, remaining)):
            return True
    raise KeyboardInterrupt


def _cleanup_before_recording(source: LiveFDRSampleSource, sink: FDRStreamWriter | None, primary: BaseException) -> NoReturn:
    failures = [primary]
    if sink is not None:
        try:
            sink.abort()
        except BaseException as exc:
            failures.append(exc)
    try:
        source.close()
    except BaseException as exc:
        failures.append(exc)
    if len(failures) > 1:
        raise BaseExceptionGroup("FDR CLI setup and cleanup failed", failures) from None
    raise primary.with_traceback(primary.__traceback__)


def _run_record(namespace: argparse.Namespace) -> int:
    """Compose the public live source, writer, and recorder for one session."""

    destination = cast(Path, namespace.output)
    _preflight_record_output(destination, namespace.overwrite)
    stop_event = threading.Event()
    interrupted_event = threading.Event()
    with _record_signal_context(stop_event, interrupted_event):
        config = WebsocketCaptureConfig(
            kind="websocket",
            host=namespace.host,
            port=namespace.port,
            api_path=namespace.api_path,
            api_version=namespace.api_version,
        )
        source = LiveFDRSampleSource(
            config=config,
            header=_record_header(namespace),
            sample_interval_seconds=namespace.interval,
            subscription_timeout_seconds=_SUBSCRIPTION_TIMEOUT_SECONDS,
            wait=lambda target, timeout: _interruptible_wait(interrupted_event, target, timeout),
        )
        sink: FDRStreamWriter | None = None
        try:
            sink = FDRWriter().open(source.header, destination, overwrite=namespace.overwrite)
            recorder = FDRRecorder(source=source, sink=sink)
        except BaseException as exc:
            _cleanup_before_recording(source, sink, exc)
        result = recorder.record(stop_event=stop_event, maximum_duration=namespace.duration)

    interrupted = interrupted_event.is_set() or result.termination == "keyboard_interrupt"
    if interrupted:
        return 130
    if result.final_path is None:
        raise RuntimeError("recording completed without a final output path")
    print(f"Recorded {result.sample_count} samples to {result.final_path} ({result.duration.total_seconds():.3f} seconds).")
    return 0


def _diagnostic(command: str, error: BaseException) -> None:
    detail = str(error).strip() or type(error).__name__
    print(f"xpwebapi-fdr: {command} failed: {detail}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one FDR command and return its stable process exit code."""

    parser = build_parser()
    try:
        namespace = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    if namespace.command == "record":
        try:
            _validate_record_arguments(namespace)
        except FDRCliArgumentError as exc:
            parser.print_usage(sys.stderr)
            _diagnostic("invalid arguments", exc)
            return 2

    handlers = {
        "validate": _run_validate,
        "inspect": _run_inspect,
        "to-geojson": _run_to_geojson,
        "record": _run_record,
    }
    try:
        return handlers[namespace.command](namespace)
    except KeyboardInterrupt:
        return 130
    except BaseException as exc:
        _diagnostic(namespace.command, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
