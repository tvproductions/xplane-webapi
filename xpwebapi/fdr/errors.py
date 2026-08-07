"""Public exceptions for Flight Data Recorder processing."""

from __future__ import annotations


class _FDRContextError(ValueError):
    """Base error that optionally locates a failure in an FDR source."""

    def __init__(self, message: str, *, source: str | None = None, line: int | None = None) -> None:
        self.message = message
        self.source = source
        self.line = line
        location = ":".join(str(part) for part in (source, line) if part is not None)
        super().__init__(f"{location}: {message}" if location else message)


class FDRParseError(_FDRContextError):
    """Raised when FDR source text cannot be parsed."""


class FDRValidationError(_FDRContextError):
    """Raised when parsed FDR data violates the recording model."""
