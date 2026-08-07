"""Deterministic and durable version 4 FDR serialization."""

from __future__ import annotations

import math
import os
from pathlib import Path
import re
import secrets
from typing import TextIO, cast

from .errors import FDRValidationError
from .models import FDRHeader, FDRNormalizationResult, FDRRecording, FDRSample


_METADATA_PATTERN = re.compile(r"^[A-Z0-9]{4}$")
_RESERVED_METADATA_KEYS = frozenset({"COMM", "DREF"})


def _single_line(value: str, name: str) -> str:
    if "\n" in value or "\r" in value:
        raise FDRValidationError(f"{name} must not contain a line separator")
    return value


def _render_number(value: int | float) -> str:
    if type(value) is int:
        return str(value)
    if type(value) is not float or not math.isfinite(value):
        raise FDRValidationError("FDR numbers must be finite int or float values")
    return repr(value)


def _render_header(header: FDRHeader) -> str:
    if not isinstance(header, FDRHeader):
        raise FDRValidationError("header must be an FDRHeader")
    if header.source_version != 4:
        raise FDRValidationError("writer supports version 4 headers only")

    lines = ["A", "4"]
    lines.extend(f"COMM, {_single_line(comment, 'comment')}" for comment in header.comments)
    for item in header.metadata:
        if _METADATA_PATTERN.fullmatch(item.key) is None or item.key in _RESERVED_METADATA_KEYS:
            raise FDRValidationError("metadata key must be four-character uppercase text")
        lines.append(f"{item.key}, {_single_line(item.value, 'metadata value')}")
    for dataref in header.datarefs:
        path = _single_line(dataref.path, "DataRef path")
        if any(character.isspace() for character in path) or "//" in path:
            raise FDRValidationError("DataRef path must not contain whitespace or '//'")
        declaration = f"DREF, {path} {_render_number(dataref.scale)}"
        if dataref.comment is not None:
            declaration += f" // {_single_line(dataref.comment, 'DataRef comment')}" if dataref.comment else " //"
        lines.append(declaration)
    return "\n".join(lines) + "\n"


def _render_sample(sample: FDRSample, dataref_count: int) -> str:
    if not isinstance(sample, FDRSample):
        raise FDRValidationError("sample must be an FDRSample")
    if len(sample.additional_values) != dataref_count:
        raise FDRValidationError("sample additional values do not match declared DataRefs")
    if sample.legacy_values:
        raise FDRValidationError("version 4 samples must not contain legacy values")
    fields = (
        sample.time_utc.isoformat(),
        _render_number(sample.longitude),
        _render_number(sample.latitude),
        _render_number(sample.altitude_msl_ft),
        _render_number(sample.heading_magnetic_deg),
        _render_number(sample.pitch_deg),
        _render_number(sample.roll_deg),
        *(_render_number(value) for value in sample.additional_values),
    )
    return ", ".join(fields) + "\n"


def _create_partial(destination: Path) -> tuple[Path, TextIO]:
    for _attempt in range(100):
        token = secrets.token_hex(8)
        partial_path = destination.with_name(f".{destination.name}.{token}.partial")
        try:
            stream = partial_path.open("x", encoding="utf-8", newline="\n")
        except FileExistsError:
            continue
        return partial_path, stream
    raise FileExistsError(f"could not create a unique partial file beside {destination}")


class FDRStreamWriter:
    """Incrementally write validated samples and explicitly commit or abort."""

    def __init__(
        self,
        header: FDRHeader,
        stream: TextIO,
        *,
        destination: Path | None,
        partial_path: Path | None,
        overwrite: bool,
        header_text: str,
    ) -> None:
        self._header = header
        self._stream = stream
        self._destination = destination
        self._partial_path = partial_path
        self._overwrite = overwrite
        self._sample_count = 0
        self._state = "active"
        try:
            self._stream.write(header_text)
        except BaseException:
            self.abort()
            raise

    @property
    def partial_path(self) -> Path | None:
        """Return the diagnostic partial path for path-based output."""
        return self._partial_path

    @property
    def sample_count(self) -> int:
        """Return the number of successfully written samples."""
        return self._sample_count

    def write_sample(self, sample: FDRSample) -> None:
        """Append one sample matching the header's declared DataRef width."""
        self._require_active()
        try:
            line = _render_sample(sample, len(self._header.datarefs))
            self._stream.write(line)
        except BaseException:
            self.abort()
            raise
        self._sample_count += 1

    def commit(self) -> None:
        """Flush output and expose path output only after a valid sample."""
        self._require_active()
        if self._sample_count == 0:
            self.abort()
            raise FDRValidationError("cannot commit an FDR recording without samples")

        if self._destination is None:
            try:
                self._stream.flush()
            except BaseException:
                self.abort()
                raise
            self._state = "committed"
            return

        partial_path = cast(Path, self._partial_path)
        try:
            self._stream.flush()
            os.fsync(self._stream.fileno())
            self._stream.close()
            if self._overwrite:
                os.replace(partial_path, self._destination)
            else:
                os.link(partial_path, self._destination)
                try:
                    partial_path.unlink()
                except OSError:
                    pass
        except BaseException:
            self._state = "aborted"
            if not self._stream.closed:
                self._stream.close()
            raise
        self._state = "committed"

    def abort(self) -> None:
        """Stop writing while preserving a path partial for diagnosis."""
        if self._state != "active":
            return
        self._state = "aborted"
        if self._destination is None:
            self._stream.flush()
        else:
            self._stream.close()

    def _require_active(self) -> None:
        if self._state != "active":
            raise FDRValidationError(f"writer is already {self._state}")


class FDRWriter:
    """Write complete or incremental canonical version 4 recordings."""

    def open(
        self,
        header: FDRHeader,
        destination: str | os.PathLike[str] | TextIO,
        *,
        overwrite: bool = False,
    ) -> FDRStreamWriter:
        """Open a stream writer for a path or caller-owned text stream."""
        header_text = _render_header(header)
        if isinstance(destination, (str, os.PathLike)):
            path = Path(cast(str | os.PathLike[str], destination))
            if path.exists() and not overwrite:
                raise FileExistsError(f"destination already exists: {path}")
            partial_path, stream = _create_partial(path)
            return FDRStreamWriter(
                header,
                stream,
                destination=path,
                partial_path=partial_path,
                overwrite=overwrite,
                header_text=header_text,
            )
        stream = cast(TextIO, destination)
        return FDRStreamWriter(
            header,
            stream,
            destination=None,
            partial_path=None,
            overwrite=overwrite,
            header_text=header_text,
        )

    def write(
        self,
        recording: FDRRecording,
        destination: str | os.PathLike[str] | TextIO,
        *,
        overwrite: bool = False,
        allow_lossy_legacy: bool = False,
    ) -> FDRNormalizationResult:
        """Write a complete recording and report any omitted legacy fields."""
        if not isinstance(recording, FDRRecording):
            raise FDRValidationError("recording must be an FDRRecording")
        if recording.header.source_version == 3 and not allow_lossy_legacy:
            raise FDRValidationError("version 3 writing requires allow_lossy_legacy=True")
        result = recording.normalized_v4(allow_lossy_legacy=allow_lossy_legacy)
        stream_writer = self.open(result.recording.header, destination, overwrite=overwrite)
        try:
            for sample in result.recording.samples:
                stream_writer.write_sample(sample)
            stream_writer.commit()
        except BaseException:
            stream_writer.abort()
            raise
        return result
