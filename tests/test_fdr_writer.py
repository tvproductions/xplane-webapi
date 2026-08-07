"""Tests for deterministic and durable version 4 FDR writing."""

from __future__ import annotations

from datetime import date, time
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from xpwebapi.fdr import (
    FDRDataref,
    FDRHeader,
    FDRLegacyColumn,
    FDRMetadata,
    FDRReader,
    FDRRecording,
    FDRSample,
    FDRStreamWriter,
    FDRValidationError,
    FDRWriter,
)


class TrackingStream(StringIO):
    """Record writer lifecycle calls on a caller-owned text stream."""

    def __init__(self) -> None:
        super().__init__()
        self.flush_count = 0

    def flush(self) -> None:
        self.flush_count += 1
        super().flush()


class FaultingStream(StringIO):
    """Inject distinct writer operation and cleanup failures."""

    def __init__(
        self,
        *,
        flush_errors: tuple[BaseException, ...] = (),
        close_error: BaseException | None = None,
    ) -> None:
        super().__init__()
        self.flush_errors = list(flush_errors)
        self.close_error = close_error

    def flush(self) -> None:
        if self.flush_errors:
            raise self.flush_errors.pop(0)
        super().flush()

    def fileno(self) -> int:
        return 17

    def close(self) -> None:
        if self.close_error is not None:
            raise self.close_error
        super().close()


class FDRWriterTests(unittest.TestCase):
    def header(self, **changes: object) -> FDRHeader:
        values: dict[str, object] = {
            "source_version": 4,
            "source_origin": "I",
            "comments": ("café first", "second, comment"),
            "metadata": (
                FDRMetadata("ZZZZ", "first"),
                FDRMetadata("DATE", "08/07/2026"),
                FDRMetadata("ZZZZ", "last"),
            ),
            "datarefs": (
                FDRDataref("sim/test/ratio", 0.5, "normalized ratio"),
                FDRDataref("sim/test/whole", 2, None),
            ),
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
            "altitude_msl_ft": 640,
            "heading_magnetic_deg": 270,
            "pitch_deg": 2,
            "roll_deg": -1,
            "additional_values": (0.30000000000000004, 2),
            "legacy_values": (),
        }
        values.update(changes)
        return FDRSample(**values)  # type: ignore[arg-type]

    def recording(self, **changes: object) -> FDRRecording:
        values: dict[str, object] = {"header": self.header(), "samples": (self.sample(),)}
        values.update(changes)
        return FDRRecording(**values)  # type: ignore[arg-type]

    def test_writes_exact_canonical_text_in_model_order(self) -> None:
        destination = StringIO()

        result = FDRWriter().write(self.recording(), destination)

        self.assertEqual((), result.omitted_legacy_field_ids)
        self.assertEqual(
            """A
4
COMM, café first
COMM, second, comment
ZZZZ, first
DATE, 08/07/2026
ZZZZ, last
DREF, sim/test/ratio 0.5 // normalized ratio
DREF, sim/test/whole 2
23:59:59.500000, -87.9048, 41.9742, 640, 270, 2, -1, 0.30000000000000004, 2
""",
            destination.getvalue(),
        )

    def test_path_output_is_utf8_lf_only_and_deterministic(self) -> None:
        recording = self.recording()
        with TemporaryDirectory() as temporary_directory:
            first = Path(temporary_directory, "first.fdr")
            second = Path(temporary_directory, "second.fdr")

            FDRWriter().write(recording, first)
            FDRWriter().write(recording, second)

            first_bytes = first.read_bytes()
            self.assertTrue(first_bytes.startswith(b"A\n4\n"))
            self.assertNotIn(b"\r", first_bytes)
            self.assertIn("café".encode(), first_bytes)
            self.assertEqual(first_bytes, second.read_bytes())

    def test_complete_and_incremental_writes_share_canonical_rendering(self) -> None:
        recording = self.recording(samples=(self.sample(), self.sample(time_utc=time(0, 0, 1))))
        complete = StringIO()
        incremental = StringIO()

        FDRWriter().write(recording, complete)
        stream_writer = FDRWriter().open(recording.header, incremental)
        self.assertIsInstance(stream_writer, FDRStreamWriter)
        for sample in recording.samples:
            stream_writer.write_sample(sample)
        stream_writer.commit()

        self.assertEqual(complete.getvalue(), incremental.getvalue())

    def test_caller_stream_is_flushed_but_never_closed_or_fsynced(self) -> None:
        destination = TrackingStream()

        with patch("xpwebapi.fdr.writer.os.fsync") as fsync:
            FDRWriter().write(self.recording(), destination)

        self.assertGreaterEqual(destination.flush_count, 1)
        self.assertFalse(destination.closed)
        fsync.assert_not_called()

    def test_round_trip_preserves_v4_recording_values_and_order(self) -> None:
        original = self.recording(samples=(self.sample(), self.sample(time_utc=time(0, 0, 1), longitude=-87.0)))
        destination = StringIO()

        FDRWriter().write(original, destination)
        destination.seek(0)
        parsed = FDRReader().read(destination)

        self.assertEqual("A", parsed.header.source_origin)
        self.assertEqual(original.header.comments, parsed.header.comments)
        self.assertEqual(original.header.metadata, parsed.header.metadata)
        self.assertEqual(original.header.datarefs, parsed.header.datarefs)
        self.assertEqual(original.samples, parsed.samples)

    def test_rejects_malformed_and_impossible_date_before_stream_mutation(self) -> None:
        for value in ("not-a-date", "02/30/2026"):
            with self.subTest(value=value):
                destination = StringIO("sentinel")
                recording = self.recording(header=self.header(metadata=(FDRMetadata("DATE", value),)))

                with self.assertRaises(FDRValidationError):
                    FDRWriter().write(recording, destination)

                self.assertEqual("sentinel", destination.getvalue())
                self.assertFalse(destination.closed)

    def test_invalid_date_creates_no_path_or_partial(self) -> None:
        recording = self.recording(header=self.header(metadata=(FDRMetadata("DATE", "2026-02-29"),)))
        with TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory, "flight.fdr")

            with self.assertRaises(FDRValidationError):
                FDRWriter().write(recording, destination)

            self.assertFalse(destination.exists())
            self.assertEqual((), tuple(destination.parent.glob(f".{destination.name}.*.partial")))

    def test_valid_canonical_date_writes_and_round_trips(self) -> None:
        recording = self.recording(header=self.header(metadata=(FDRMetadata("DATE", "2026-08-07"),)))
        destination = StringIO()

        FDRWriter().write(recording, destination)
        destination.seek(0)
        parsed = FDRReader().read(destination)

        self.assertEqual(date(2026, 8, 7), parsed.header.local_date)
        self.assertEqual("2026-08-07", parsed.header.metadata_value("DATE"))

    def test_streaming_writer_rejects_sample_width_and_preserves_partial(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory, "flight.fdr")
            writer = FDRWriter().open(self.header(), destination)
            invalid = self.sample(additional_values=(1,))

            with self.assertRaises(FDRValidationError):
                writer.write_sample(invalid)

            self.assertFalse(destination.exists())
            partials = tuple(destination.parent.glob(f".{destination.name}.*.partial"))
            self.assertEqual(1, len(partials))
            self.assertGreater(partials[0].stat().st_size, 0)

    def test_version_three_write_requires_explicit_lossy_opt_in(self) -> None:
        legacy_header = self.header(
            source_version=3,
            datarefs=(),
            legacy_columns=(FDRLegacyColumn("elapsed_seconds"), FDRLegacyColumn("engine_n1")),
        )
        legacy_sample = self.sample(additional_values=(), legacy_values=(0, 95))
        recording = self.recording(header=legacy_header, samples=(legacy_sample,))
        refused = StringIO()

        with self.assertRaises(FDRValidationError):
            FDRWriter().write(recording, refused)

        self.assertEqual("", refused.getvalue())
        destination = StringIO()
        result = FDRWriter().write(recording, destination, allow_lossy_legacy=True)
        self.assertEqual(("elapsed_seconds", "engine_n1"), result.omitted_legacy_field_ids)
        destination.seek(0)
        normalized = FDRReader().read(destination)
        self.assertEqual(4, normalized.header.source_version)
        self.assertEqual((), normalized.header.legacy_columns)
        self.assertEqual((), normalized.samples[0].legacy_values)

    def test_existing_destination_is_rejected_without_creating_partial(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory, "flight.fdr")
            destination.write_text("existing", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                FDRWriter().write(self.recording(), destination)

            self.assertEqual(b"existing", destination.read_bytes())
            self.assertEqual((), tuple(destination.parent.glob(f".{destination.name}.*.partial")))

    def test_overwrite_replaces_destination_only_at_commit(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory, "flight.fdr")
            destination.write_text("existing", encoding="utf-8")
            writer = FDRWriter().open(self.header(), destination, overwrite=True)
            writer.write_sample(self.sample())

            self.assertEqual("existing", destination.read_text(encoding="utf-8"))
            writer.commit()

            self.assertTrue(destination.read_bytes().startswith(b"A\n4\n"))
            self.assertEqual((), tuple(destination.parent.glob(f".{destination.name}.*.partial")))

    def test_path_has_no_final_name_until_durable_commit(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory, "flight.fdr")
            writer = FDRWriter().open(self.header(), destination)
            writer.write_sample(self.sample())

            self.assertFalse(destination.exists())
            self.assertEqual(1, len(tuple(destination.parent.glob(f".{destination.name}.*.partial"))))
            with patch("xpwebapi.fdr.writer.os.fsync") as fsync:
                writer.commit()

            self.assertTrue(destination.exists())
            fsync.assert_called_once()
            self.assertEqual((), tuple(destination.parent.glob(f".{destination.name}.*.partial")))

    def test_commit_without_samples_fails_and_preserves_nonempty_partial(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory, "flight.fdr")
            writer = FDRWriter().open(self.header(), destination)

            with self.assertRaises(FDRValidationError):
                writer.commit()

            self.assertFalse(destination.exists())
            partials = tuple(destination.parent.glob(f".{destination.name}.*.partial"))
            self.assertEqual(1, len(partials))
            self.assertGreater(partials[0].stat().st_size, 0)

    def test_abort_preserves_path_partial_and_never_closes_caller_stream(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory, "flight.fdr")
            path_writer = FDRWriter().open(self.header(), destination)
            path_writer.write_sample(self.sample())
            partial_path = path_writer.partial_path
            path_writer.abort()

            self.assertFalse(destination.exists())
            self.assertIsNotNone(partial_path)
            self.assertGreater(partial_path.stat().st_size, 0)  # type: ignore[union-attr]

        stream = TrackingStream()
        stream_writer = FDRWriter().open(self.header(), stream)
        stream_writer.abort()
        self.assertFalse(stream.closed)
        self.assertGreaterEqual(stream.flush_count, 1)

    def test_stream_writer_context_manager_requires_explicit_commit(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory, "flight.fdr")
            with FDRWriter().open(self.header(), destination) as writer:
                writer.write_sample(self.sample())
                partial_path = writer.partial_path

            self.assertFalse(destination.exists())
            self.assertIsNotNone(partial_path)
            self.assertTrue(partial_path.is_file())  # type: ignore[union-attr]

            with FDRWriter().open(self.header(), destination) as committed:
                committed.write_sample(self.sample())
                committed.commit()

            self.assertTrue(destination.exists())

    def test_context_body_and_caller_stream_abort_failures_are_both_preserved(self) -> None:
        stream = FaultingStream(flush_errors=(RuntimeError("abort flush broke"),))

        with self.assertRaises(BaseExceptionGroup) as caught:
            with FDRWriter().open(self.header(), stream):
                raise ValueError("body broke")

        self.assertEqual((ValueError, RuntimeError), tuple(type(item) for item in caught.exception.exceptions))
        self.assertEqual(("body broke", "abort flush broke"), tuple(str(item) for item in caught.exception.exceptions))

    def test_context_body_and_path_close_failures_are_both_preserved(self) -> None:
        stream = FaultingStream(close_error=RuntimeError("partial close broke"))
        writer = FDRStreamWriter(
            self.header(),
            stream,
            destination=Path("flight.fdr"),
            partial_path=Path(".flight.fdr.partial"),
            overwrite=False,
            header_text="A\n4\n",
        )

        with self.assertRaises(BaseExceptionGroup) as caught:
            with writer:
                raise ValueError("body broke")

        self.assertEqual(("body broke", "partial close broke"), tuple(str(item) for item in caught.exception.exceptions))
        stream.close_error = None
        stream.close()

    def test_context_preserves_body_exception_and_raises_cleanup_failure_alone(self) -> None:
        with self.assertRaisesRegex(ValueError, "body broke"):
            with FDRWriter().open(self.header(), StringIO()):
                raise ValueError("body broke")

        stream = FaultingStream(flush_errors=(RuntimeError("abort alone broke"),))
        with self.assertRaisesRegex(RuntimeError, "abort alone broke"):
            with FDRWriter().open(self.header(), stream):
                pass

    def test_commit_preserves_caller_flush_and_abort_flush_failures(self) -> None:
        stream = FaultingStream(
            flush_errors=(
                RuntimeError("commit flush broke"),
                RuntimeError("abort flush broke"),
            )
        )
        writer = FDRWriter().open(self.header(), stream)
        writer.write_sample(self.sample())

        with self.assertRaises(BaseExceptionGroup) as caught:
            writer.commit()

        self.assertEqual(("commit flush broke", "abort flush broke"), tuple(str(item) for item in caught.exception.exceptions))

    def test_commit_preserves_path_fsync_and_close_failures(self) -> None:
        stream = FaultingStream(close_error=RuntimeError("partial close broke"))
        writer = FDRStreamWriter(
            self.header(),
            stream,
            destination=Path("flight.fdr"),
            partial_path=Path(".flight.fdr.partial"),
            overwrite=False,
            header_text="A\n4\n",
        )
        writer.write_sample(self.sample())

        with patch("xpwebapi.fdr.writer.os.fsync", side_effect=OSError("fsync broke")):
            with self.assertRaises(BaseExceptionGroup) as caught:
                writer.commit()

        self.assertEqual(("fsync broke", "partial close broke"), tuple(str(item) for item in caught.exception.exceptions))
        stream.close_error = None
        stream.close()


if __name__ == "__main__":
    unittest.main()
