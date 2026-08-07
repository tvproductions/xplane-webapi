"""Tests for the public immutable FDR data model."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, time, timedelta
import math
import unittest

from xpwebapi.fdr import (
    FDRDataref,
    FDRHeader,
    FDRLegacyColumn,
    FDRMetadata,
    FDRNormalizationResult,
    FDRRecording,
    FDRSample,
    FDRValidationError,
)


class FDRModelTests(unittest.TestCase):
    def header(self, **changes: object) -> FDRHeader:
        values: dict[str, object] = {
            "source_version": 4,
            "source_origin": "A",
            "comments": ("synthetic recording",),
            "metadata": (FDRMetadata("DATE", "2026-08-07"),),
            "datarefs": (FDRDataref("sim/test/ratio", 0.5, "ratio"),),
            "legacy_columns": (),
            "local_date": date(2026, 8, 7),
        }
        values.update(changes)
        return FDRHeader(**values)  # type: ignore[arg-type]

    def sample(self, **changes: object) -> FDRSample:
        values: dict[str, object] = {
            "time_utc": time(23, 59, 59, 500000),
            "longitude": -87.9048,
            "latitude": 41.9742,
            "altitude_msl_ft": 640.0,
            "heading_magnetic_deg": 270.0,
            "pitch_deg": 2.0,
            "roll_deg": -1.0,
            "additional_values": (0.75,),
            "legacy_values": (),
        }
        values.update(changes)
        return FDRSample(**values)  # type: ignore[arg-type]

    def test_constructs_immutable_ordered_models(self) -> None:
        header = self.header(metadata=[FDRMetadata("DATE", "first"), FDRMetadata("DATE", "last")])
        sample = self.sample(additional_values=[0.75])

        self.assertEqual((FDRMetadata("DATE", "first"), FDRMetadata("DATE", "last")), header.metadata)
        self.assertEqual("last", header.metadata_value("DATE"))
        self.assertEqual((0.75,), sample.additional_values)
        self.assertEqual(0.5, header.datarefs[0].scale)
        self.assertEqual("ratio", header.datarefs[0].comment)
        with self.assertRaises(FrozenInstanceError):
            sample.longitude = 0.0  # type: ignore[misc]
        with self.assertRaises(TypeError):
            sample.extra = "not slotted"  # type: ignore[attr-defined]

    def test_duration_counts_midnight_rollover(self) -> None:
        recording = FDRRecording(
            self.header(),
            (
                self.sample(),
                self.sample(time_utc=time(0, 0, 1, 500000)),
            ),
        )

        self.assertEqual(timedelta(seconds=2), recording.duration)

    def test_resolves_datetimes_only_with_explicit_utc_date(self) -> None:
        recording = FDRRecording(
            self.header(),
            (
                self.sample(),
                self.sample(time_utc=time(0, 0, 1, 500000)),
            ),
        )

        self.assertEqual(
            (
                datetime(2026, 8, 7, 23, 59, 59, 500000, tzinfo=UTC),
                datetime(2026, 8, 8, 0, 0, 1, 500000, tzinfo=UTC),
            ),
            recording.resolved_utc_datetimes(date(2026, 8, 7)),
        )

    def test_rejects_invalid_coordinates(self) -> None:
        for name, value in (("longitude", -180.1), ("longitude", 180.1), ("latitude", -90.1), ("latitude", 90.1)):
            with self.subTest(name=name, value=value), self.assertRaises(FDRValidationError):
                self.sample(**{name: value})

    def test_rejects_booleans_and_nonfinite_numeric_values(self) -> None:
        for name in (
            "longitude",
            "latitude",
            "altitude_msl_ft",
            "heading_magnetic_deg",
            "pitch_deg",
            "roll_deg",
        ):
            for value in (True, math.nan, math.inf, -math.inf):
                with self.subTest(name=name, value=value), self.assertRaises(FDRValidationError):
                    self.sample(**{name: value})
        for value in (True, math.nan, math.inf, -math.inf):
            with self.subTest(dataref_scale=value), self.assertRaises(FDRValidationError):
                FDRDataref("sim/test/value", value)
            with self.subTest(additional_value=value), self.assertRaises(FDRValidationError):
                self.sample(additional_values=(value,))
            with self.subTest(legacy_value=value), self.assertRaises(FDRValidationError):
                self.sample(legacy_values=(value,))

    def test_rejects_duplicate_datarefs_and_legacy_column_ids(self) -> None:
        with self.assertRaises(FDRValidationError):
            self.header(datarefs=(FDRDataref("sim/test/value", 1.0), FDRDataref("sim/test/value", 2.0)))
        with self.assertRaises(FDRValidationError):
            self.header(
                source_version=3,
                datarefs=(),
                legacy_columns=(FDRLegacyColumn("elapsed_seconds"), FDRLegacyColumn("elapsed_seconds")),
            )

    def test_rejects_version_three_datarefs_and_version_four_legacy_columns(self) -> None:
        with self.assertRaises(FDRValidationError):
            self.header(source_version=3)
        with self.assertRaises(FDRValidationError):
            self.header(legacy_columns=(FDRLegacyColumn("elapsed_seconds"),))

    def test_normalization_result_requires_a_version_four_recording(self) -> None:
        version_three_header = self.header(source_version=3, datarefs=())
        version_three_recording = FDRRecording(version_three_header, (self.sample(additional_values=()),))

        with self.assertRaises(FDRValidationError):
            FDRNormalizationResult(version_three_recording, ())

    def test_rejects_sample_values_that_do_not_match_declared_widths(self) -> None:
        with self.assertRaises(FDRValidationError):
            FDRRecording(self.header(), (self.sample(additional_values=()),))
        legacy_header = self.header(
            source_version=3,
            datarefs=(),
            legacy_columns=(FDRLegacyColumn("elapsed_seconds"), FDRLegacyColumn("engine_n1")),
        )
        with self.assertRaises(FDRValidationError):
            FDRRecording(legacy_header, (self.sample(additional_values=(), legacy_values=(0.0,)),))

    def test_backward_time_is_a_single_midnight_rollover(self) -> None:
        recording = FDRRecording(
            self.header(),
            (self.sample(time_utc=time(12, 0)), self.sample(time_utc=time(11, 0))),
        )

        self.assertEqual(timedelta(hours=23), recording.duration)

    def test_normalization_requires_opt_in_before_omitting_legacy_values(self) -> None:
        legacy_header = self.header(
            source_version=3,
            datarefs=(),
            legacy_columns=(FDRLegacyColumn("elapsed_seconds"), FDRLegacyColumn("engine_n1")),
        )
        recording = FDRRecording(legacy_header, (self.sample(additional_values=(), legacy_values=(0.0, 95.0)),))

        with self.assertRaises(FDRValidationError):
            recording.normalized_v4()
        result = recording.normalized_v4(allow_lossy_legacy=True)
        self.assertIsInstance(result, FDRNormalizationResult)
        self.assertEqual(("elapsed_seconds", "engine_n1"), result.omitted_legacy_field_ids)
        self.assertEqual(4, result.recording.header.source_version)
        self.assertEqual((), result.recording.header.legacy_columns)
        self.assertEqual((), result.recording.samples[0].legacy_values)


if __name__ == "__main__":
    unittest.main()
