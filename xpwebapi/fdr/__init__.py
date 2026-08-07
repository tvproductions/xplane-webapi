"""Validated immutable models for X-Plane Flight Data Recorder files."""

from .errors import FDRParseError, FDRValidationError
from .geojson import recording_to_geojson
from .models import FDRDataref, FDRHeader, FDRLegacyColumn, FDRMetadata, FDRNormalizationResult, FDRRecording, FDRSample
from .reader import FDRReader
from .writer import FDRStreamWriter, FDRWriter

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
    "FDRStreamWriter",
    "FDRValidationError",
    "FDRWriter",
    "recording_to_geojson",
]
