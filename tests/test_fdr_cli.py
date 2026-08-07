"""Command-line contract tests for the FDR toolkit."""

from __future__ import annotations

import io
import json
import os
import signal
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal
from unittest.mock import Mock, patch

from xpwebapi.fdr import FDRDataref, FDRHeader, FDRMetadata, FDRRecordResult, FDRSourceSample
from xpwebapi.fdr.cli import _write_atomic_json, build_parser, main


VALID_FDR = """A
4
COMM, deterministic fixture
DATE, 08/07/2026
ACFT, Q4XP
DREF, sim/test/value 2.0 // Test value
23:59:59, -87.9048, 41.9742, 1000, 270, 2, -1, 3
00:00:01, -87.8, 42.0, 1100, 271, 1, 0, 4
"""


def make_header(*datarefs: FDRDataref, local_date: date = date(2026, 8, 7)) -> FDRHeader:
    """Return a small canonical version 4 header."""

    return FDRHeader(
        source_version=4,
        source_origin="A",
        comments=(),
        metadata=(FDRMetadata("DATE", local_date.isoformat()),),
        datarefs=datarefs,
        legacy_columns=(),
        local_date=local_date,
    )


def record_result(
    path: Path,
    *,
    termination: Literal["source_exhausted", "stop_requested", "duration_reached", "keyboard_interrupt"] = "duration_reached",
) -> FDRRecordResult:
    """Return a deterministic successful recording result."""

    started = datetime(2026, 8, 7, 18, 30, tzinfo=UTC)
    return FDRRecordResult(
        sample_count=2,
        started_at_utc=started,
        ended_at_utc=started + timedelta(seconds=1),
        duration=timedelta(seconds=1),
        termination=termination,
        partial_path=None,
        final_path=path,
    )


class FailingSource:
    """Synthetic public-protocol source that fails after one sample."""

    def __init__(self, header: FDRHeader) -> None:
        self.header = header
        self.close_count = 0

    def samples(self, _stop_event: threading.Event):  # type: ignore[no-untyped-def]
        yield FDRSourceSample(
            datetime(2026, 8, 7, 18, 30, tzinfo=UTC),
            {
                "longitude": -87.9048,
                "latitude": 41.9742,
                "altitude_msl_ft": 1000.0,
                "heading_magnetic_deg": 270.0,
                "pitch_deg": 2.0,
                "roll_deg": -1.0,
            },
        )
        raise RuntimeError("live source failed")

    def close(self) -> None:
        self.close_count += 1


class InterruptBeforeSampleSource:
    """Synthetic source that requests SIGINT before yielding its first sample."""

    def __init__(self, header: FDRHeader) -> None:
        self.header = header
        self.signal_handler: Any = None
        self.close_count = 0

    def samples(self, _stop_event: threading.Event):  # type: ignore[no-untyped-def]
        self.signal_handler(signal.SIGINT, None)
        yield from ()

    def close(self) -> None:
        self.close_count += 1


class FailingAtomicStream:
    """Real sibling stream with one injected operation or cleanup failure."""

    def __init__(self, path: Path, *, failure: str, close_failure: bool = False) -> None:
        self._stream = path.open("x", encoding="utf-8", newline="\n")
        self._failure = failure
        self._close_failure = close_failure

    @property
    def closed(self) -> bool:
        return self._stream.closed

    def write(self, text: str) -> int:
        if self._failure == "write":
            raise OSError("injected write failure")
        return self._stream.write(text)

    def flush(self) -> None:
        if self._failure == "flush":
            raise OSError("injected flush failure")
        self._stream.flush()

    def fileno(self) -> int:
        return self._stream.fileno()

    def close(self) -> None:
        self._stream.close()
        if self._close_failure:
            raise OSError("injected close cleanup failure")


class FDRCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.input = self.root / "flight.fdr"
        self.input.write_text(VALID_FDR, encoding="utf-8", newline="")

    def capture_main(self, arguments: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(arguments)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_help_lists_all_subcommands_on_stdout(self) -> None:
        result, stdout, stderr = self.capture_main(["--help"])

        self.assertEqual(0, result)
        self.assertIn("xpwebapi-fdr", stdout)
        for command in ("record", "inspect", "validate", "to-geojson"):
            self.assertIn(command, stdout)
        self.assertEqual("", stderr)

    def test_parser_accepts_every_documented_command_shape(self) -> None:
        parser = build_parser()
        commands = (
            ["validate", str(self.input)],
            ["inspect", str(self.input), "--json", "--first-utc-date", "2026-08-07"],
            ["to-geojson", str(self.input), str(self.root / "flight.geojson"), "--first-utc-date", "2026-08-07", "--overwrite"],
            [
                "record",
                str(self.root / "recorded.fdr"),
                "--host",
                "xplane.local",
                "--port",
                "8087",
                "--api-path",
                "/web-api",
                "--api-version",
                "v3",
                "--interval",
                "0.25",
                "--duration",
                "30",
                "--local-date",
                "2026-08-07",
                "--dataref",
                "sim/test/value",
                "--scale",
                "sim/test/value=2.5",
                "--comment",
                "sim/test/value=Test value=with equals",
                "--overwrite",
            ],
        )

        for arguments in commands:
            with self.subTest(command=arguments[0]):
                self.assertEqual(arguments[0], parser.parse_args(arguments).command)

    def test_validate_is_silent_on_success(self) -> None:
        result, stdout, stderr = self.capture_main(["validate", str(self.input)])

        self.assertEqual(0, result)
        self.assertEqual("", stdout)
        self.assertEqual("", stderr)

    def test_validate_reports_invalid_input_only_on_stderr(self) -> None:
        self.input.write_text("not an FDR\n", encoding="utf-8")

        result, stdout, stderr = self.capture_main(["validate", str(self.input)])

        self.assertEqual(1, result)
        self.assertEqual("", stdout)
        self.assertIn("xpwebapi-fdr: validate failed", stderr)
        self.assertIn(str(self.input), stderr)

    def test_inspect_json_is_compact_sorted_and_lf_terminated(self) -> None:
        result, stdout, stderr = self.capture_main(["inspect", str(self.input), "--json"])

        document = json.loads(stdout)
        self.assertEqual(0, result)
        self.assertEqual("", stderr)
        self.assertTrue(stdout.endswith("\n"))
        self.assertFalse(stdout.endswith("\n\n"))
        self.assertNotIn(": ", stdout)
        self.assertEqual(sorted(document), list(document))
        self.assertEqual(4, document["version"])
        self.assertEqual("A", document["origin"])
        self.assertEqual("2026-08-07", document["local_date"])
        self.assertEqual(2, document["sample_count"])
        self.assertEqual("23:59:59", document["start_utc"])
        self.assertEqual("00:00:01", document["end_utc"])
        self.assertEqual(2.0, document["duration_seconds"])
        self.assertEqual("Q4XP", document["effective_metadata"]["ACFT"])
        self.assertEqual("sim/test/value", document["datarefs"][0]["path"])
        self.assertEqual("sim/test/value", document["fields"][-1])

    def test_inspect_json_bypasses_windows_newline_translation(self) -> None:
        raw_stdout = io.BytesIO()
        translated_stdout = io.TextIOWrapper(raw_stdout, encoding="utf-8", newline="\r\n")
        stderr = io.StringIO()
        with redirect_stdout(translated_stdout), redirect_stderr(stderr):
            result = main(["inspect", str(self.input), "--json"])
            translated_stdout.flush()

        self.assertEqual(0, result)
        self.assertNotIn(b"\r", raw_stdout.getvalue())
        self.assertTrue(raw_stdout.getvalue().endswith(b"\n"))
        self.assertEqual("", stderr.getvalue())

    def test_inspect_resolves_explicit_utc_date_across_midnight(self) -> None:
        result, stdout, stderr = self.capture_main(["inspect", str(self.input), "--json", "--first-utc-date", "2026-08-07"])

        document = json.loads(stdout)
        self.assertEqual(0, result)
        self.assertEqual("2026-08-07T23:59:59Z", document["start_utc"])
        self.assertEqual("2026-08-08T00:00:01Z", document["end_utc"])
        self.assertEqual("", stderr)

    def test_inspect_human_output_contains_normalized_summary(self) -> None:
        result, stdout, stderr = self.capture_main(["inspect", str(self.input)])

        self.assertEqual(0, result)
        for text in ("Version: 4", "Samples: 2", "Start UTC: 23:59:59", "Duration: 2.000 seconds", "sim/test/value", "ACFT: Q4XP"):
            self.assertIn(text, stdout)
        self.assertEqual("", stderr)

    def test_invalid_first_utc_date_is_an_argument_error(self) -> None:
        result, stdout, stderr = self.capture_main(["inspect", str(self.input), "--first-utc-date", "2026-02-30"])

        self.assertEqual(2, result)
        self.assertEqual("", stdout)
        self.assertIn("invalid date", stderr)

    def test_to_geojson_writes_canonical_atomic_output_with_explicit_timestamps(self) -> None:
        output = self.root / "flight.geojson"

        result, stdout, stderr = self.capture_main(["to-geojson", str(self.input), str(output), "--first-utc-date", "2026-08-07"])

        payload = output.read_bytes()
        document = json.loads(payload)
        self.assertEqual(0, result)
        self.assertEqual("", stdout)
        self.assertEqual("", stderr)
        self.assertTrue(payload.endswith(b"\n"))
        self.assertNotIn(b"\r", payload)
        self.assertNotIn(b": ", payload)
        self.assertEqual("FeatureCollection", document["type"])
        self.assertEqual("2026-08-07T23:59:59Z", document["features"][0]["properties"]["timestamp_utc"])
        self.assertEqual([], [path.name for path in self.root.iterdir() if path.suffix == ".partial"])

    def test_to_geojson_commits_from_a_sibling_temporary(self) -> None:
        output = self.root / "flight.geojson"
        real_link = os.link
        observed: list[tuple[Path, Path]] = []

        def observe_link(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
            source_path = Path(source)
            destination_path = Path(destination)
            observed.append((source_path, destination_path))
            self.assertEqual(output.parent, source_path.parent)
            self.assertEqual(output, destination_path)
            self.assertTrue(source_path.name.startswith(f".{output.name}."))
            real_link(source_path, destination_path)

        with patch("xpwebapi.fdr.cli.os.link", side_effect=observe_link):
            result, stdout, stderr = self.capture_main(["to-geojson", str(self.input), str(output)])

        self.assertEqual(0, result)
        self.assertEqual(1, len(observed))
        self.assertEqual("", stdout)
        self.assertEqual("", stderr)

    def test_to_geojson_reports_partial_cleanup_failure_after_successful_link(self) -> None:
        output = self.root / "flight.geojson"

        with patch.object(Path, "unlink", side_effect=OSError("injected committed-partial cleanup failure")):
            result, stdout, stderr = self.capture_main(["to-geojson", str(self.input), str(output)])

        partials = list(self.root.glob(f".{output.name}.*.partial"))
        self.assertEqual(1, result)
        self.assertEqual("", stdout)
        self.assertIn("to-geojson failed", stderr)
        self.assertIn("injected committed-partial cleanup failure", stderr)
        self.assertTrue(output.exists())
        self.assertEqual("FeatureCollection", json.loads(output.read_text(encoding="utf-8"))["type"])
        self.assertEqual(1, len(partials))
        self.assertEqual(output.read_bytes(), partials[0].read_bytes())
        partials[0].unlink()
        self.assertTrue(output.exists())

    def test_to_geojson_protects_existing_output_unless_overwrite_is_explicit(self) -> None:
        output = self.root / "flight.geojson"
        output.write_text("existing\n", encoding="utf-8")

        result, stdout, stderr = self.capture_main(["to-geojson", str(self.input), str(output)])

        self.assertEqual(1, result)
        self.assertEqual("", stdout)
        self.assertIn("already exists", stderr)
        self.assertEqual("existing\n", output.read_text(encoding="utf-8"))

        result, stdout, stderr = self.capture_main(["to-geojson", str(self.input), str(output), "--overwrite"])
        self.assertEqual(0, result)
        self.assertEqual("FeatureCollection", json.loads(output.read_text(encoding="utf-8"))["type"])
        self.assertEqual("", stdout)
        self.assertEqual("", stderr)

    def test_to_geojson_output_failure_is_diagnostic_only(self) -> None:
        output = self.root / "missing" / "flight.geojson"

        result, stdout, stderr = self.capture_main(["to-geojson", str(self.input), str(output)])

        self.assertEqual(1, result)
        self.assertEqual("", stdout)
        self.assertIn("to-geojson failed", stderr)
        self.assertFalse(output.exists())

    def test_atomic_geojson_removes_owned_partial_after_each_operation_failure(self) -> None:
        for stage in ("write", "flush", "fsync", "link", "replace"):
            with self.subTest(stage=stage):
                output = self.root / f"{stage}.geojson"
                partial = self.root / f".{output.name}.injected.partial"
                if stage == "replace":
                    output.write_text("existing\n", encoding="utf-8")

                def create_partial(_destination: Path) -> tuple[Path, FailingAtomicStream]:
                    failure = stage if stage in {"write", "flush"} else "none"
                    return partial, FailingAtomicStream(partial, failure=failure)

                def race_destination(_source: Path, destination: Path) -> None:
                    destination.write_text("raced\n", encoding="utf-8")
                    raise FileExistsError("injected link race")

                patches = [patch("xpwebapi.fdr.cli._create_partial", side_effect=create_partial)]
                if stage == "fsync":
                    patches.append(patch("xpwebapi.fdr.cli.os.fsync", side_effect=OSError("injected fsync failure")))
                elif stage == "link":
                    patches.append(patch("xpwebapi.fdr.cli.os.link", side_effect=race_destination))
                elif stage == "replace":
                    patches.append(patch("xpwebapi.fdr.cli.os.replace", side_effect=OSError("injected replace failure")))

                with patches[0]:
                    if len(patches) == 1:
                        with self.assertRaises(OSError):
                            _write_atomic_json({"type": "FeatureCollection"}, output, overwrite=False)
                    else:
                        with patches[1], self.assertRaises(OSError):
                            _write_atomic_json({"type": "FeatureCollection"}, output, overwrite=stage == "replace")

                self.assertFalse(partial.exists())
                if stage == "link":
                    self.assertEqual("raced\n", output.read_text(encoding="utf-8"))
                elif stage == "replace":
                    self.assertEqual("existing\n", output.read_text(encoding="utf-8"))
                else:
                    self.assertFalse(output.exists())

    def test_atomic_geojson_groups_primary_and_close_cleanup_failures_after_unlink(self) -> None:
        output = self.root / "close-failure.geojson"
        partial = self.root / ".close-failure.geojson.injected.partial"

        def create_partial(_destination: Path) -> tuple[Path, FailingAtomicStream]:
            return partial, FailingAtomicStream(partial, failure="write", close_failure=True)

        with patch("xpwebapi.fdr.cli._create_partial", side_effect=create_partial), self.assertRaises(BaseExceptionGroup) as caught:
            _write_atomic_json({"type": "FeatureCollection"}, output, overwrite=False)

        self.assertEqual(["injected write failure", "injected close cleanup failure"], [str(error) for error in caught.exception.exceptions])
        self.assertFalse(partial.exists())
        self.assertFalse(output.exists())

    def test_atomic_geojson_groups_primary_and_unlink_cleanup_failures(self) -> None:
        output = self.root / "unlink-failure.geojson"
        partial = self.root / ".unlink-failure.geojson.injected.partial"

        def create_partial(_destination: Path) -> tuple[Path, FailingAtomicStream]:
            return partial, FailingAtomicStream(partial, failure="none")

        with (
            patch("xpwebapi.fdr.cli._create_partial", side_effect=create_partial),
            patch("xpwebapi.fdr.cli.os.link", side_effect=OSError("injected link failure")),
            patch.object(Path, "unlink", side_effect=OSError("injected unlink cleanup failure")),
            self.assertRaises(BaseExceptionGroup) as caught,
        ):
            _write_atomic_json({"type": "FeatureCollection"}, output, overwrite=False)

        self.assertEqual(["injected link failure", "injected unlink cleanup failure"], [str(error) for error in caught.exception.exceptions])
        self.assertTrue(partial.exists())
        partial.unlink()
        self.assertFalse(output.exists())

    def test_record_builds_public_library_objects_from_all_options(self) -> None:
        output = self.root / "recorded.fdr"
        effective_header = make_header(FDRDataref("sim/test/value", 2.5, "Test value=with equals"))
        source = Mock(header=effective_header)
        sink = Mock()
        result_document = record_result(output)

        with (
            patch("xpwebapi.fdr.cli.LiveFDRSampleSource", return_value=source) as source_type,
            patch("xpwebapi.fdr.cli.FDRWriter") as writer_type,
            patch("xpwebapi.fdr.cli.FDRRecorder") as recorder_type,
            patch("xpwebapi.fdr.cli.signal.getsignal", return_value=signal.SIG_DFL),
            patch("xpwebapi.fdr.cli.signal.signal") as set_signal,
        ):
            writer_type.return_value.open.return_value = sink
            recorder_type.return_value.record.return_value = result_document
            result, stdout, stderr = self.capture_main(
                [
                    "record",
                    str(output),
                    "--host",
                    "xplane.local",
                    "--port",
                    "8087",
                    "--api-path",
                    "/web-api",
                    "--api-version",
                    "v3",
                    "--interval",
                    "0.25",
                    "--duration",
                    "30",
                    "--local-date",
                    "2026-08-07",
                    "--dataref",
                    "sim/test/value",
                    "--scale",
                    "sim/test/value=2.5",
                    "--comment",
                    "sim/test/value=Test value=with equals",
                    "--overwrite",
                ]
            )

        self.assertEqual(0, result)
        self.assertIn("Recorded 2 samples", stdout)
        self.assertIn(str(output), stdout)
        self.assertEqual("", stderr)
        source_kwargs = source_type.call_args.kwargs
        config = source_kwargs["config"]
        self.assertEqual(("xplane.local", 8087, "/web-api", "v3"), (config.host, config.port, config.api_path, config.api_version))
        self.assertEqual(0.25, source_kwargs["sample_interval_seconds"])
        requested_header = source_kwargs["header"]
        self.assertEqual(date(2026, 8, 7), requested_header.local_date)
        self.assertEqual("2026-08-07", requested_header.metadata_value("DATE"))
        self.assertEqual((FDRDataref("sim/test/value", 2.5, "Test value=with equals"),), requested_header.datarefs)
        writer_type.return_value.open.assert_called_once_with(effective_header, output, overwrite=True)
        recorder_type.assert_called_once_with(source=source, sink=sink)
        recorder_type.return_value.record.assert_called_once()
        self.assertEqual(30.0, recorder_type.return_value.record.call_args.kwargs["maximum_duration"])
        self.assertGreaterEqual(set_signal.call_count, 4)

    def test_record_option_relationships_fail_before_connection(self) -> None:
        output = self.root / "recorded.fdr"
        cases = (
            ["--scale", "sim/test/value=2"],
            ["--comment", "sim/test/value=comment"],
            ["--dataref", "sim/test/value", "--dataref", "sim/test/value"],
            ["--dataref", "sim/test/value", "--scale", "sim/test/value=2", "--scale", "sim/test/value=3"],
            ["--dataref", "sim/test/value", "--comment", "sim/test/value=a", "--comment", "sim/test/value=b"],
        )

        with patch("xpwebapi.fdr.cli.LiveFDRSampleSource") as source_type:
            for options in cases:
                with self.subTest(options=options):
                    result, stdout, stderr = self.capture_main(["record", str(output), *options])
                    self.assertEqual(2, result)
                    self.assertEqual("", stdout)
                    self.assertIn("invalid arguments", stderr)
            source_type.assert_not_called()

    def test_record_rejects_protocol_invalid_values_and_mandatory_collisions_before_connection(self) -> None:
        output = self.root / "recorded.fdr"
        mandatory_ids = (
            "longitude",
            "latitude",
            "altitude_msl_ft",
            "heading_magnetic_deg",
            "pitch_deg",
            "roll_deg",
        )
        mandatory_paths = (
            "sim/flightmodel/position/longitude",
            "sim/flightmodel/position/latitude",
            "sim/flightmodel/position/elevation",
            "sim/cockpit2/gauges/indicators/heading_electric_deg_mag_pilot",
            "sim/cockpit2/gauges/indicators/pitch_electric_deg_pilot",
            "sim/cockpit2/gauges/indicators/roll_electric_deg_pilot",
        )
        cases = (
            *(["--dataref", path] for path in ("sim/test/value[-1]", "sim/test/value[01]", "sim/test/value[]", "sim/test/value[abc]", "sim/test/value[")),
            ["--dataref", " sim/test/value"],
            ["--dataref", "sim/test/value "],
            ["--host", " xplane.local"],
            ["--host", "xplane.local "],
            ["--api-path", " /api"],
            ["--api-path", "/api "],
            ["--api-version", " v2"],
            ["--api-version", "v2 "],
            *(["--dataref", path] for path in mandatory_ids),
            *(["--dataref", path] for path in mandatory_paths),
        )

        with patch("xpwebapi.fdr.cli.LiveFDRSampleSource") as source_type:
            for options in cases:
                with self.subTest(options=options):
                    result, stdout, stderr = self.capture_main(["record", str(output), *options])
                    self.assertEqual(2, result)
                    self.assertEqual("", stdout)
                    self.assertIn("invalid arguments", stderr)
            source_type.assert_not_called()

    def test_record_rejects_invalid_numeric_and_date_options(self) -> None:
        output = self.root / "recorded.fdr"
        cases = (
            ["--port", "0"],
            ["--interval", "0"],
            ["--interval", "nan"],
            ["--duration", "-1"],
            ["--duration", "inf"],
            ["--local-date", "2026-02-30"],
            ["--dataref", "sim/test/value", "--scale", "sim/test/value=nan"],
        )

        with patch("xpwebapi.fdr.cli.LiveFDRSampleSource") as source_type:
            for options in cases:
                with self.subTest(options=options):
                    result, stdout, stderr = self.capture_main(["record", str(output), *options])
                    self.assertEqual(2, result)
                    self.assertEqual("", stdout)
                    self.assertNotEqual("", stderr)
            source_type.assert_not_called()

    def test_record_checks_overwrite_before_connecting(self) -> None:
        output = self.root / "recorded.fdr"
        output.write_text("existing\n", encoding="utf-8")

        with patch("xpwebapi.fdr.cli.LiveFDRSampleSource") as source_type:
            result, stdout, stderr = self.capture_main(["record", str(output), "--local-date", "2026-08-07"])

        self.assertEqual(1, result)
        self.assertEqual("", stdout)
        self.assertIn("already exists", stderr)
        self.assertEqual("existing\n", output.read_text(encoding="utf-8"))
        source_type.assert_not_called()

    def test_record_connection_failure_is_diagnostic_only_and_restores_signals(self) -> None:
        output = self.root / "recorded.fdr"
        previous: dict[int, object] = {signal.SIGINT: object(), signal.SIGTERM: object()}
        calls: list[tuple[int, Any]] = []

        def current_handler(signum: int) -> Any:
            return previous[signum]

        with (
            patch("xpwebapi.fdr.cli.LiveFDRSampleSource", side_effect=ConnectionError("X-Plane unavailable")),
            patch("xpwebapi.fdr.cli.signal.getsignal", side_effect=current_handler),
            patch("xpwebapi.fdr.cli.signal.signal", side_effect=lambda signum, handler: calls.append((signum, handler))),
        ):
            result, stdout, stderr = self.capture_main(["record", str(output), "--local-date", "2026-08-07"])

        self.assertEqual(1, result)
        self.assertEqual("", stdout)
        self.assertIn("record failed", stderr)
        self.assertIn("X-Plane unavailable", stderr)
        self.assertFalse(output.exists())
        for signum, handler in previous.items():
            self.assertIn((signum, handler), calls)

    def test_failed_recording_preserves_partial_but_never_exposes_final_output(self) -> None:
        output = self.root / "recorded.fdr"
        source = FailingSource(make_header())

        with (
            patch("xpwebapi.fdr.cli.LiveFDRSampleSource", return_value=source),
            patch("xpwebapi.fdr.cli.signal.getsignal", return_value=signal.SIG_DFL),
            patch("xpwebapi.fdr.cli.signal.signal"),
        ):
            result, stdout, stderr = self.capture_main(["record", str(output), "--local-date", "2026-08-07"])

        partials = list(self.root.glob(f".{output.name}.*.partial"))
        self.assertEqual(1, result)
        self.assertEqual("", stdout)
        self.assertIn("live source failed", stderr)
        self.assertFalse(output.exists())
        self.assertEqual(1, len(partials))
        self.assertGreater(partials[0].stat().st_size, 0)
        self.assertIn(str(partials[0]), stderr)
        self.assertEqual(1, source.close_count)

    def test_record_returns_130_for_a_graceful_keyboard_interrupt(self) -> None:
        output = self.root / "recorded.fdr"
        source = Mock(header=make_header())
        sink = Mock()

        with (
            patch("xpwebapi.fdr.cli.LiveFDRSampleSource", return_value=source),
            patch("xpwebapi.fdr.cli.FDRWriter") as writer_type,
            patch("xpwebapi.fdr.cli.FDRRecorder") as recorder_type,
            patch("xpwebapi.fdr.cli.signal.getsignal", return_value=signal.SIG_DFL),
            patch("xpwebapi.fdr.cli.signal.signal"),
        ):
            writer_type.return_value.open.return_value = sink
            recorder_type.return_value.record.return_value = record_result(output, termination="keyboard_interrupt")
            result, stdout, stderr = self.capture_main(["record", str(output), "--local-date", "2026-08-07"])

        self.assertEqual(130, result)
        self.assertEqual("", stdout)
        self.assertEqual("", stderr)

    def test_signal_requested_recording_returns_130_and_restores_handlers(self) -> None:
        output = self.root / "recorded.fdr"
        source = Mock(header=make_header())
        sink = Mock()
        installed: dict[int, Any] = {}

        def remember_handler(signum: int, handler: Any) -> None:
            installed[signum] = handler

        def request_interrupt(**_kwargs: Any) -> FDRRecordResult:
            installed[signal.SIGINT](signal.SIGINT, None)
            return record_result(output, termination="stop_requested")

        with (
            patch("xpwebapi.fdr.cli.LiveFDRSampleSource", return_value=source),
            patch("xpwebapi.fdr.cli.FDRWriter") as writer_type,
            patch("xpwebapi.fdr.cli.FDRRecorder") as recorder_type,
            patch("xpwebapi.fdr.cli.signal.getsignal", return_value=signal.SIG_DFL),
            patch("xpwebapi.fdr.cli.signal.signal", side_effect=remember_handler),
        ):
            writer_type.return_value.open.return_value = sink
            recorder_type.return_value.record.side_effect = request_interrupt
            result, stdout, stderr = self.capture_main(["record", str(output), "--local-date", "2026-08-07"])

        self.assertEqual(130, result)
        self.assertEqual("", stdout)
        self.assertEqual("", stderr)
        self.assertEqual(signal.SIG_DFL, installed[signal.SIGINT])
        self.assertEqual(signal.SIG_DFL, installed[signal.SIGTERM])

    def test_signal_after_source_construction_exits_130_before_opening_writer(self) -> None:
        output = self.root / "recorded.fdr"
        source = Mock(header=make_header())
        installed: dict[int, Any] = {}

        def remember_handler(signum: int, handler: Any) -> None:
            installed[signum] = handler

        def construct_source(**_kwargs: Any) -> Mock:
            installed[signal.SIGINT](signal.SIGINT, None)
            return source

        with (
            patch("xpwebapi.fdr.cli.LiveFDRSampleSource", side_effect=construct_source),
            patch("xpwebapi.fdr.cli.FDRWriter") as writer_type,
            patch("xpwebapi.fdr.cli.signal.getsignal", return_value=signal.SIG_DFL),
            patch("xpwebapi.fdr.cli.signal.signal", side_effect=remember_handler),
        ):
            result, stdout, stderr = self.capture_main(["record", str(output), "--local-date", "2026-08-07"])

        self.assertEqual(130, result)
        self.assertEqual("", stdout)
        self.assertEqual("", stderr)
        self.assertFalse(output.exists())
        source.close.assert_called_once_with()
        writer_type.assert_not_called()
        self.assertEqual(signal.SIG_DFL, installed[signal.SIGINT])
        self.assertEqual(signal.SIG_DFL, installed[signal.SIGTERM])

    def test_signal_after_writer_open_exits_130_before_constructing_recorder(self) -> None:
        output = self.root / "recorded.fdr"
        source = Mock(header=make_header())
        sink = Mock()
        installed: dict[int, Any] = {}

        def remember_handler(signum: int, handler: Any) -> None:
            installed[signum] = handler

        def open_writer(*_args: Any, **_kwargs: Any) -> Mock:
            installed[signal.SIGTERM](signal.SIGTERM, None)
            return sink

        with (
            patch("xpwebapi.fdr.cli.LiveFDRSampleSource", return_value=source),
            patch("xpwebapi.fdr.cli.FDRWriter") as writer_type,
            patch("xpwebapi.fdr.cli.FDRRecorder") as recorder_type,
            patch("xpwebapi.fdr.cli.signal.getsignal", return_value=signal.SIG_DFL),
            patch("xpwebapi.fdr.cli.signal.signal", side_effect=remember_handler),
        ):
            writer_type.return_value.open.side_effect = open_writer
            result, stdout, stderr = self.capture_main(["record", str(output), "--local-date", "2026-08-07"])

        self.assertEqual(130, result)
        self.assertEqual("", stdout)
        self.assertEqual("", stderr)
        self.assertFalse(output.exists())
        sink.abort.assert_called_once_with()
        source.close.assert_called_once_with()
        recorder_type.assert_not_called()
        self.assertEqual(signal.SIG_DFL, installed[signal.SIGINT])
        self.assertEqual(signal.SIG_DFL, installed[signal.SIGTERM])

    def test_signal_during_recording_before_first_sample_exits_130_without_final(self) -> None:
        output = self.root / "recorded.fdr"
        source = InterruptBeforeSampleSource(make_header())

        def remember_handler(signum: int, handler: Any) -> None:
            if signum == signal.SIGINT and callable(handler):
                source.signal_handler = handler

        with (
            patch("xpwebapi.fdr.cli.LiveFDRSampleSource", return_value=source),
            patch("xpwebapi.fdr.cli.signal.getsignal", return_value=signal.SIG_DFL),
            patch("xpwebapi.fdr.cli.signal.signal", side_effect=remember_handler),
        ):
            result, stdout, stderr = self.capture_main(["record", str(output), "--local-date", "2026-08-07"])

        self.assertEqual(130, result)
        self.assertEqual("", stdout)
        self.assertEqual("", stderr)
        self.assertFalse(output.exists())
        self.assertEqual(1, source.close_count)

    def test_keyboard_interrupt_before_recording_is_exit_130_without_output(self) -> None:
        output = self.root / "recorded.fdr"
        with (
            patch("xpwebapi.fdr.cli.LiveFDRSampleSource", side_effect=KeyboardInterrupt),
            patch("xpwebapi.fdr.cli.signal.getsignal", return_value=signal.SIG_DFL),
            patch("xpwebapi.fdr.cli.signal.signal"),
        ):
            result, stdout, stderr = self.capture_main(["record", str(output), "--local-date", "2026-08-07"])

        self.assertEqual(130, result)
        self.assertEqual("", stdout)
        self.assertEqual("", stderr)
        self.assertFalse(output.exists())

    def test_signal_interrupts_initial_value_readiness_without_waiting_for_timeout(self) -> None:
        output = self.root / "recorded.fdr"
        installed: dict[int, Any] = {}

        def remember_handler(signum: int, handler: Any) -> None:
            installed[signum] = handler

        def interrupt_during_startup(**kwargs: Any) -> None:
            installed[signal.SIGINT](signal.SIGINT, None)
            kwargs["wait"](threading.Event(), 30.0)
            self.fail("the CLI wait did not interrupt startup")

        with (
            patch("xpwebapi.fdr.cli.LiveFDRSampleSource", side_effect=interrupt_during_startup),
            patch("xpwebapi.fdr.cli.signal.getsignal", return_value=signal.SIG_DFL),
            patch("xpwebapi.fdr.cli.signal.signal", side_effect=remember_handler),
        ):
            result, stdout, stderr = self.capture_main(["record", str(output), "--local-date", "2026-08-07"])

        self.assertEqual(130, result)
        self.assertEqual("", stdout)
        self.assertEqual("", stderr)
        self.assertFalse(output.exists())

    def test_console_script_is_declared(self) -> None:
        project = Path(__file__).parents[1] / "pyproject.toml"

        self.assertIn('xpwebapi-fdr = "xpwebapi.fdr.cli:main"', project.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
