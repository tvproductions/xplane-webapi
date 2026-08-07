"""Validated immutable models for X-Plane Flight Data Recorder files."""

from .errors import FDRParseError, FDRValidationError
from .geojson import recording_to_geojson
from .models import FDRDataref, FDRHeader, FDRLegacyColumn, FDRMetadata, FDRNormalizationResult, FDRRecording, FDRSample
from .reader import FDRReader, FDRSampleStream
from .recorder import FDRRecorder, FDRRecordResult, FDRSampleSink, FDRSampleSource, FDRSourceSample, LiveFDRSampleSource
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
    "FDRRecorder",
    "FDRRecordResult",
    "FDRSample",
    "FDRSampleSink",
    "FDRSampleSource",
    "FDRSampleStream",
    "FDRSourceSample",
    "FDRStreamWriter",
    "FDRValidationError",
    "FDRWriter",
    "LiveFDRSampleSource",
    "recording_to_geojson",
]
