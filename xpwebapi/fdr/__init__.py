"""Validated immutable models for X-Plane Flight Data Recorder files."""

from .errors import FDRParseError, FDRValidationError
from .models import FDRDataref, FDRHeader, FDRLegacyColumn, FDRMetadata, FDRNormalizationResult, FDRRecording, FDRSample
from .reader import FDRReader

__all__ = [
    "FDRDataref",
    "FDRHeader",
    "FDRLegacyColumn",
    "FDRMetadata",
    "FDRNormalizationResult",
    "FDRParseError",
    "FDRRecording",
    "FDRReader",
    "FDRSample",
    "FDRValidationError",
]
