"""Tests for incremental version 4 FDR parsing."""

from __future__ import annotations

from datetime import date, time
from io import StringIO, TextIOBase
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from xpwebapi.fdr import FDRParseError, FDRReader, FDRValidationError


V4_TEXT = """A
4 Version 4 recording
COMM, first comment, with comma
ACFT, Aircraft/Test.acf
ZZZZ, custom
DATE, 08/07/2026
ZZZZ, effective
DREF, sim/test/ratio 0.5 // normalized ratio
COMM, UTC time, longitude, latitude, altmsl(ft), heading, pitch, roll, sim/test/ratio
23:59:59.5, -87.9048, 41.9742, 640, 270, 2, -1, 0.75
00:00:01.5, -87.9047, 41.9743, 641, 271, 3, -2, 0.80
"""


class ShortReadStream(TextIOBase):
    """Caller-owned text source that permits only bounded ``read`` calls."""

    def __init__(self, text: str, chunk_size: int = 7) -> None:
        self._text = text
        self._chunk_size = chunk_size
        self.position = 0
        self.read_sizes: list[int] = []

    def readable(self) -> bool:
        return True

    def read(self, size: int | None = -1, /) -> str:
        if size is None or size < 0:
            raise AssertionError("reader attempted to materialize the whole source")
        self.read_sizes.append(size)
        size = min(size, self._chunk_size)
        result = self._text[self.position : self.position + size]
        self.position += len(result)
        return result


class FDRReaderTests(unittest.TestCase):
    def test_reads_v4_from_string_stream_and_preserves_ordered_header(self) -> None:
        source = StringIO(V4_TEXT)

        with FDRReader().open(source) as stream:
            self.assertEqual(4, stream.header.source_version)
            self.assertEqual("A", stream.header.source_origin)
            self.assertEqual(
                ("first comment, with comma", "UTC time, longitude, latitude, altmsl(ft), heading, pitch, roll, sim/test/ratio"), stream.header.comments
            )
            self.assertEqual(("ACFT", "ZZZZ", "DATE", "ZZZZ"), tuple(item.key for item in stream.header.metadata))
            self.assertEqual("effective", stream.header.metadata_value("ZZZZ"))
            self.assertEqual(date(2026, 8, 7), stream.header.local_date)
            self.assertEqual("sim/test/ratio", stream.header.datarefs[0].path)
            self.assertEqual(0.5, stream.header.datarefs[0].scale)
            self.assertEqual("normalized ratio", stream.header.datarefs[0].comment)
            samples = tuple(stream)

        self.assertEqual(2, len(samples))
        self.assertEqual(time(23, 59, 59, 500000), samples[0].time_utc)
        self.assertEqual(
            (-87.9048, 41.9742, 640.0, 270.0, 2.0, -1.0),
            (samples[0].longitude, samples[0].latitude, samples[0].altitude_msl_ft, samples[0].heading_magnetic_deg, samples[0].pitch_deg, samples[0].roll_deg),
        )
        self.assertEqual((0.75,), samples[0].additional_values)
        self.assertFalse(source.closed)

    def test_full_read_composes_stream_into_recording(self) -> None:
        recording = FDRReader().read(StringIO(V4_TEXT))

        self.assertEqual(4, recording.header.source_version)
        self.assertEqual(2, len(recording.samples))
        self.assertEqual((), recording.samples[0].legacy_values)

    def test_reads_path_and_closes_owned_stream(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory, "recording.fdr")
            path.write_text(V4_TEXT, encoding="utf-8", newline="")

            with FDRReader().open(path) as stream:
                self.assertEqual(2, sum(1 for _ in stream))

            path.unlink()
            self.assertFalse(path.exists())

    def test_accepts_origin_markers_version_suffixes_and_whitespace(self) -> None:
        for origin in ("A", "I"):
            for version_line in ("4", "  4 explanatory suffix  "):
                text = f"  {origin}  \n{version_line}\n 12:00:00 , 1 , 2 , 3 , 4 , 5 , 6 \n"
                with self.subTest(origin=origin, version_line=version_line):
                    recording = FDRReader().read(StringIO(text))
                    self.assertEqual(origin, recording.header.source_origin)
                    self.assertEqual(4, recording.header.source_version)
                    self.assertEqual(1, len(recording.samples))

    def test_accepts_cr_lf_and_crlf_from_caller_streams(self) -> None:
        lines = ("A", "4 Version", "COMM, mixed", "12:00:00,1,2,3,4,5,6", "")
        for separator in ("\r", "\n", "\r\n"):
            with self.subTest(separator=repr(separator)):
                source = StringIO(separator.join(lines))
                recording = FDRReader().read(source)
                self.assertEqual(("mixed",), recording.header.comments)
                self.assertEqual(1, len(recording.samples))
                self.assertFalse(source.closed)

    def test_streams_without_materializing_all_samples(self) -> None:
        rows = "".join(f"12:00:{second % 60:02d},1,2,3,4,5,6\n" for second in range(10_000))
        source = ShortReadStream(f"A\n4\n{rows}")

        with FDRReader().open(source) as stream:
            first = next(stream)
            self.assertEqual(time(12), first.time_utc)
            self.assertLess(source.position, len(source._text))

        self.assertTrue(source.read_sizes)
        self.assertFalse(source.closed)

    def test_accepts_dref_without_comment_and_preserves_empty_comment(self) -> None:
        text = """A
4
DREF, sim/test/one 2
DREF, sim/test/two -0.25 //
12:00:00,1,2,3,4,5,6,7,8
"""

        header = FDRReader().read(StringIO(text)).header

        self.assertIsNone(header.datarefs[0].comment)
        self.assertEqual("", header.datarefs[1].comment)

    def test_date_is_local_only_and_duplicate_date_uses_last_value(self) -> None:
        text = "A\n4\nDATE, 01/02/2025\nDATE, 2026-08-07\n12:00:00,1,2,3,4,5,6\n"

        recording = FDRReader().read(StringIO(text))

        self.assertEqual(date(2026, 8, 7), recording.header.local_date)
        self.assertFalse(hasattr(recording.samples[0], "datetime_utc"))

    def test_preserves_plain_integer_lexemes_without_float_rounding(self) -> None:
        huge = 10**400 + 1
        text = f"A\n4\nDREF, sim/test/huge {huge}\n12:00:00,-87,41,{huge},{huge},{huge},{huge},{huge}\n"

        recording = FDRReader().read(StringIO(text))
        sample = recording.samples[0]

        self.assertEqual(huge, recording.header.datarefs[0].scale)
        self.assertEqual((huge, huge, huge, huge), (sample.altitude_msl_ft, sample.heading_magnetic_deg, sample.pitch_deg, sample.roll_deg))
        self.assertEqual((huge,), sample.additional_values)
        self.assertTrue(all(type(value) is int for value in (sample.longitude, sample.latitude, *sample.additional_values)))

    def test_rejects_unsupported_origin_and_version_with_source_lines(self) -> None:
        cases = (("X\n4\n", 1, "origin"), ("A\n3 Version\n", 2, "version 4"), ("A\nVersion 4\n", 2, "version"))
        for text, line, phrase in cases:
            with self.subTest(text=text), self.assertRaises(FDRParseError) as caught:
                FDRReader().read(StringIO(text))
            self.assertEqual(line, caught.exception.line)
            self.assertIn(phrase, caught.exception.message)
            self.assertTrue(str(caught.exception).startswith(f"<stream>:{line}:"))

    def test_rejects_non_ascii_or_python_specific_lexemes(self) -> None:
        cases = (
            ("A\n٤ Version\n", 2, "version"),
            ("A\n4\n12:00:00,1_0,2,3,4,5,6\n", 3, "number"),
            ("A\n4\nDATE, 1/02/2025\n", 3, "DATE"),
        )
        for text, line, phrase in cases:
            with self.subTest(text=text):
                with self.assertRaises(FDRParseError) as caught:
                    FDRReader().read(StringIO(text))
                self.assertEqual(line, caught.exception.line)
                self.assertIn(phrase, caught.exception.message)

    def test_rejects_malformed_header_records(self) -> None:
        cases = (
            ("A\n4\nBAD, value\n", 3, "four-character"),
            ("A\n4\nABCDE, value\n", 3, "four-character"),
            ("A\n4\nDREF, sim/test/value\n", 3, "DataRef"),
            ("A\n4\nDREF, sim/test/value nope\n", 3, "scale"),
            ("A\n4\nCOMM\n", 3, "comma"),
        )
        for text, line, phrase in cases:
            with self.subTest(text=text), self.assertRaises(FDRParseError) as caught:
                FDRReader().read(StringIO(text))
            self.assertEqual(line, caught.exception.line)
            self.assertIn(phrase, caught.exception.message)

    def test_rejects_duplicate_dataref_path_as_validation_error(self) -> None:
        text = "A\n4\nDREF, sim/test/value 1\nDREF, sim/test/value 2\n12:00:00,1,2,3,4,5,6,7,8\n"

        with self.assertRaises(FDRValidationError) as caught:
            FDRReader().read(StringIO(text))

        self.assertEqual(4, caught.exception.line)
        self.assertIn("unique", caught.exception.message)

    def test_rejects_wrong_sample_width(self) -> None:
        for row in ("12:00:00,1,2,3,4,5,6", "12:00:00,1,2,3,4,5,6,7,8"):
            text = f"A\n4\nDREF, sim/test/value 1\n{row}\n"
            with self.subTest(row=row), self.assertRaises(FDRParseError) as caught:
                FDRReader().read(StringIO(text))
            self.assertEqual(4, caught.exception.line)
            self.assertIn("8 columns", caught.exception.message)

    def test_rejects_malformed_timestamp_and_numbers(self) -> None:
        cases = (
            ("25:00:00,1,2,3,4,5,6", "timestamp"),
            ("12:00:00.1234567,1,2,3,4,5,6", "timestamp"),
            ("12:00:00,1,2,nope,4,5,6", "number"),
            ("12:00:00,1,2,3,4,5,True", "number"),
        )
        for row, phrase in cases:
            with self.subTest(row=row), self.assertRaises(FDRParseError) as caught:
                FDRReader().read(StringIO(f"A\n4\n{row}\n"))
            self.assertEqual(3, caught.exception.line)
            self.assertIn(phrase, caught.exception.message)

    def test_preserves_valid_timestamp_microseconds(self) -> None:
        recording = FDRReader().read(StringIO("A\n4\n12:00:00.123456,1,2,3,4,5,6\n"))

        self.assertEqual(time(12, 0, 0, 123456), recording.samples[0].time_utc)

    def test_model_failures_retain_source_line_context(self) -> None:
        cases = (
            ("A\n4\nDREF, sim/test/value nan\n", 3, "finite"),
            ("A\n4\n12:00:00,181,2,3,4,5,6\n", 3, "longitude"),
            ("A\n4\n12:00:00,1,nan,3,4,5,6\n", 3, "finite"),
        )
        for text, line, phrase in cases:
            with self.subTest(text=text), self.assertRaises(FDRValidationError) as caught:
                FDRReader().read(StringIO(text))
            self.assertEqual(line, caught.exception.line)
            self.assertIn(phrase, caught.exception.message)

    def test_rejects_header_declaration_after_samples_begin(self) -> None:
        text = "A\n4\n12:00:00,1,2,3,4,5,6\nCOMM, too late\n"

        with self.assertRaises(FDRParseError) as caught:
            FDRReader().read(StringIO(text))

        self.assertEqual(4, caught.exception.line)
        self.assertIn("after samples", caught.exception.message)


if __name__ == "__main__":
    unittest.main()
