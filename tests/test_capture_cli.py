"""Command-line contract tests for the read-only capture worker."""

from __future__ import annotations

import io
import json
import os
import signal
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal
from unittest.mock import patch

from xpwebapi.capture_cli import (
    build_parser,
    emit_version_json,
    install_signal_handlers,
    main,
    preflight_paths,
    run_capture,
    validate_cli_mode,
)
from xpwebapi.capture_events import SourceProvenance, VersionJsonDocument
from xpwebapi.capture_runner import CaptureInterruption, CaptureOutcome


PROVENANCE = SourceProvenance(
    package_name="xpwebapi",
    package_version="3.5.0",
    python_version="3.12.0",
    git_state="available",
    git_root="C:/src/xplane-webapi",
    git_revision="0123456789abcdef0123456789abcdef01234567",
    git_origin="https://github.com/tvproductions/xplane-webapi.git",
    git_dirty=False,
    read_only=True,
)


def request_document(*, stop_file: str | None = None) -> dict[str, object]:
    return {
        "protocol_version": 1,
        "capture_session_id": "capture-1",
        "sortie_id": "sortie-1",
        "correlation": {
            "campaign_id": "campaign",
            "route_profile_id": "route",
            "scenario_id": "scenario",
        },
        "identity_readiness": {
            "kind": "dataref_match",
            "target_aircraft": "FlyJSim Q4XP",
            "refs": [
                {
                    "id": "aircraft",
                    "path": "sim/aircraft/view/acf_relative_path",
                    "declared_type": "string",
                    "encoding": "utf-8",
                    "rate_hz": 1.0,
                    "operator": "contains",
                    "expected_value": "Q4XP",
                }
            ],
        },
        "transport": {
            "kind": "websocket",
            "host": "127.0.0.1",
            "port": 8086,
            "api_path": "/api",
            "api_version": "v2",
            "http_timeout_seconds": 0.2,
            "open_timeout_seconds": 0.2,
            "close_timeout_seconds": 0.2,
        },
        "sample_groups": [{"id": "fast", "rate_hz": 10.0, "duration_seconds": 0.2}],
        "refs": [
            {
                "id": "speed",
                "path": "sim/flightmodel/position/groundspeed",
                "declared_type": "float",
                "availability": "required",
                "sample_group_id": "fast",
                "encoding": None,
            }
        ],
        "retry": {
            "initial_attempts": 1,
            "reconnect_attempts": 1,
            "backoff_seconds": 0.0,
            "backoff_max_seconds": 0.0,
            "subscription_timeout_seconds": 0.2,
            "aircraft_identity_timeout_seconds": 0.2,
            "first_values_timeout_seconds": 0.2,
            "max_disconnect_seconds": 0.2,
            "stale_after_seconds": 2.0,
            "poll_interval_seconds": 0.01,
            "shutdown_timeout_seconds": 0.2,
        },
        "capture_limit_seconds": None,
        "stop_file": stop_file,
    }


def outcome(state: Literal["complete", "failed", "interrupted"], *, clean: bool = False) -> CaptureOutcome:
    return CaptureOutcome(
        terminal_state=state,
        termination="requested",
        reason=None,
        transport_ready=False,
        aircraft_ready=False,
        sample_count=0,
        gap_count=0,
        retry_count=0,
        clean_shutdown=clean,
    )


class CaptureCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.request = self.root / "request.json"
        self.events = self.root / "events.jsonl"
        self.status = self.root / "status.json"
        self.request.write_text(json.dumps(request_document()), encoding="utf-8")

    def capture_main(self, arguments: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(arguments)
        return result, stdout.getvalue(), stderr.getvalue()

    def capture_arguments(self, *, stop_file: Path | None = None) -> list[str]:
        arguments = [
            "--request",
            str(self.request),
            "--events",
            str(self.events),
            "--status",
            str(self.status),
        ]
        if stop_file is not None:
            arguments.extend(("--stop-file", str(stop_file)))
        return arguments

    def test_help_exits_zero_on_stdout(self) -> None:
        result, stdout, stderr = self.capture_main(["--help"])

        self.assertEqual(0, result)
        self.assertIn("xpwebapi-capture", stdout)
        self.assertIn("--version-json", stdout)
        self.assertEqual("", stderr)

    def test_version_json_is_exact_and_does_not_enter_capture_mode(self) -> None:
        expected = (
            '{"git_dirty":false,"git_origin":"https://github.com/tvproductions/xplane-webapi.git",'
            '"git_revision":"0123456789abcdef0123456789abcdef01234567",'
            '"git_root":"C:/src/xplane-webapi","git_state":"available",'
            '"package_name":"xpwebapi","package_version":"3.5.0","python_version":"3.12.0",'
            '"read_only":true,"supported_transports":["udp","websocket"],'
            '"worker":"xpwebapi-capture","worker_protocol_version":1}\n'
        )
        with (
            patch("xpwebapi.capture_cli.resolve_source_provenance", return_value=PROVENANCE),
            patch("xpwebapi.capture_cli.run_capture", side_effect=AssertionError("capture mode entered")),
        ):
            result, stdout, stderr = self.capture_main(["--version-json"])

        self.assertEqual(0, result)
        self.assertEqual(expected, stdout)
        self.assertEqual("", stderr)
        self.assertEqual(["request.json"], sorted(path.name for path in self.root.iterdir()))

    def test_version_json_keeps_unavailable_git_fields_null(self) -> None:
        unavailable = PROVENANCE.model_copy(
            update={
                "git_state": "unavailable",
                "git_root": None,
                "git_revision": None,
                "git_origin": None,
                "git_dirty": None,
            }
        )
        with patch("xpwebapi.capture_cli.resolve_source_provenance", return_value=unavailable):
            result, stdout, stderr = self.capture_main(["--version-json"])

        document = json.loads(stdout)
        self.assertEqual(0, result)
        self.assertEqual("unavailable", document["git_state"])
        for field in ("git_root", "git_revision", "git_origin", "git_dirty"):
            self.assertIsNone(document[field])
        self.assertEqual("", stderr)

    def test_emit_version_json_is_compact_sorted_and_lf_terminated(self) -> None:
        document = VersionJsonDocument(
            **PROVENANCE.model_dump(mode="python"),
            supported_transports=("udp", "websocket"),
            worker="xpwebapi-capture",
            worker_protocol_version=1,
        )
        stream = io.StringIO()

        emit_version_json(document, stream)

        rendered = stream.getvalue()
        self.assertTrue(rendered.endswith("\n"))
        self.assertFalse(rendered.endswith("\n\n"))
        self.assertNotIn(": ", rendered)
        self.assertEqual(sorted(json.loads(rendered)), list(json.loads(rendered)))

    def test_version_json_rejects_every_capture_argument(self) -> None:
        options = (("--request", self.request), ("--events", self.events), ("--status", self.status), ("--stop-file", self.root / "stop"))
        for option, value in options:
            with self.subTest(option=option):
                result, stdout, stderr = self.capture_main(["--version-json", option, str(value)])
                self.assertEqual(2, result)
                self.assertEqual("", stdout)
                self.assertIn("cannot be combined", stderr)

    def test_capture_mode_requires_request_events_and_status(self) -> None:
        for arguments in ([], ["--request", str(self.request)], ["--events", str(self.events), "--status", str(self.status)]):
            with self.subTest(arguments=arguments):
                result, stdout, stderr = self.capture_main(arguments)
                self.assertEqual(2, result)
                self.assertEqual("", stdout)
                self.assertIn("requires --request, --events, and --status", stderr)

    def test_build_parser_and_validate_cli_mode_accept_capture(self) -> None:
        namespace = build_parser().parse_args(self.capture_arguments())
        self.assertIsNone(validate_cli_mode(namespace))

    def test_main_returns_capture_outcome_exit_codes_verbatim(self) -> None:
        cases = ((outcome("complete", clean=True), 0), (outcome("complete", clean=False), 3), (outcome("failed"), 3), (outcome("interrupted"), 130))
        for capture_outcome, expected in cases:
            with self.subTest(expected=expected), patch("xpwebapi.capture_cli.run_capture", return_value=capture_outcome):
                result, stdout, stderr = self.capture_main(self.capture_arguments())
                self.assertEqual(expected, result)
                self.assertEqual("", stdout)
                self.assertEqual("", stderr)

    def test_invalid_json_is_exit_two_and_creates_no_outputs(self) -> None:
        self.request.write_text("{broken", encoding="utf-8")

        result, stdout, stderr = self.capture_main(self.capture_arguments())

        self.assertEqual(2, result)
        self.assertEqual("", stdout)
        self.assertIn("capture preflight failed", stderr)
        self.assertFalse(self.events.exists())
        self.assertFalse(self.status.exists())

    def test_missing_output_parent_is_exit_two(self) -> None:
        self.events = self.root / "missing" / "events.jsonl"

        result, _stdout, stderr = self.capture_main(self.capture_arguments())

        self.assertEqual(2, result)
        self.assertIn("capture preflight failed", stderr)
        self.assertFalse(self.status.exists())

    def test_existing_events_is_refused_without_modification(self) -> None:
        self.events.write_text("existing events\n", encoding="utf-8")

        result, _stdout, stderr = self.capture_main(self.capture_arguments())

        self.assertEqual(2, result)
        self.assertIn("already exists", stderr)
        self.assertEqual("existing events\n", self.events.read_text(encoding="utf-8"))
        self.assertFalse(self.status.exists())

    def test_existing_status_is_refused_without_creating_events(self) -> None:
        self.status.write_text("existing status\n", encoding="utf-8")

        result, _stdout, stderr = self.capture_main(self.capture_arguments())

        self.assertEqual(2, result)
        self.assertIn("already exists", stderr)
        self.assertFalse(self.events.exists())
        self.assertEqual("existing status\n", self.status.read_text(encoding="utf-8"))

    def test_preexisting_stop_file_is_refused_without_outputs(self) -> None:
        stop = self.root / "stop"
        stop.write_text("stop\n", encoding="utf-8")

        result, _stdout, stderr = self.capture_main(self.capture_arguments(stop_file=stop))

        self.assertEqual(2, result)
        self.assertIn("already exists", stderr)
        self.assertFalse(self.events.exists())
        self.assertFalse(self.status.exists())

    def test_matching_request_and_cli_stop_files_are_passed_resolved(self) -> None:
        self.request.write_text(json.dumps(request_document(stop_file="stop.signal")), encoding="utf-8")
        stop = self.root / "stop.signal"
        capture_outcome = outcome("complete", clean=True)
        with patch("xpwebapi.capture_cli.CaptureRunner") as runner_type, patch("xpwebapi.capture_cli.resolve_source_provenance", return_value=PROVENANCE):
            runner_type.return_value.run.return_value = capture_outcome
            result = run_capture(
                self.request,
                self.events,
                self.status,
                stop,
                threading.Event(),
                threading.Event(),
            )

        self.assertIs(capture_outcome, result)
        self.assertEqual(stop.resolve(), runner_type.call_args.kwargs["stop_file"])

    def test_conflicting_request_and_cli_stop_files_are_refused(self) -> None:
        self.request.write_text(json.dumps(request_document(stop_file="request.stop")), encoding="utf-8")

        result, _stdout, stderr = self.capture_main(self.capture_arguments(stop_file=self.root / "cli.stop"))

        self.assertEqual(2, result)
        self.assertIn("same path", stderr)
        self.assertFalse(self.events.exists())
        self.assertFalse(self.status.exists())

    def test_identical_and_relative_absolute_output_aliases_are_refused(self) -> None:
        aliases = (
            (self.events, self.events),
            (self.root / "." / "same", (self.root / "same").resolve()),
        )
        for events, status in aliases:
            with self.subTest(events=events, status=status):
                with self.assertRaises(ValueError):
                    preflight_paths(events, status, None)

    def test_symlink_output_alias_is_refused(self) -> None:
        target = self.root / "target"
        target.mkdir()
        link = self.root / "link"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")

        with self.assertRaises(ValueError):
            preflight_paths(target / "evidence", link / "evidence", None)

    @unittest.skipUnless(os.path.normcase("A") == os.path.normcase("a"), "filesystem paths are case-sensitive")
    def test_case_folded_output_alias_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            preflight_paths(self.root / "CaseName", self.root / "casename", None)

    def test_request_and_stop_file_aliases_with_outputs_are_refused(self) -> None:
        for attribute in ("events", "status"):
            with self.subTest(attribute=attribute):
                setattr(self, attribute, self.request)
                result, _stdout, stderr = self.capture_main(self.capture_arguments())
                self.assertEqual(2, result)
                self.assertIn("alias", stderr)
                setattr(self, attribute, self.root / f"{attribute}.out")

        stop = self.root / "stop"
        self.events = stop
        result, _stdout, stderr = self.capture_main(self.capture_arguments(stop_file=stop))
        self.assertEqual(2, result)
        self.assertIn("alias", stderr)

    def test_provenance_is_resolved_before_output_mutation(self) -> None:
        capture_outcome = outcome("complete", clean=True)

        def provenance() -> SourceProvenance:
            self.assertFalse(self.events.exists())
            self.assertFalse(self.status.exists())
            return PROVENANCE

        with patch("xpwebapi.capture_cli.resolve_source_provenance", side_effect=provenance), patch("xpwebapi.capture_cli.CaptureRunner") as runner_type:
            runner_type.return_value.run.return_value = capture_outcome
            result = run_capture(
                self.request,
                self.events,
                self.status,
                None,
                threading.Event(),
                threading.Event(),
            )

        self.assertIs(capture_outcome, result)

    def test_competing_events_file_created_after_preflight_is_not_truncated(self) -> None:
        def racing_provenance() -> SourceProvenance:
            self.events.write_text("competing\n", encoding="utf-8")
            return PROVENANCE

        with patch("xpwebapi.capture_cli.resolve_source_provenance", side_effect=racing_provenance):
            result, _stdout, stderr = self.capture_main(self.capture_arguments())

        self.assertEqual(2, result)
        self.assertIn("already exists", stderr)
        self.assertEqual("competing\n", self.events.read_text(encoding="utf-8"))
        self.assertFalse(self.status.exists())

    def test_status_reservation_race_rolls_back_owned_empty_events(self) -> None:
        real_open = Path.open

        def racing_open(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            if path == self.status and mode == "xb" and not self.status.exists():
                with real_open(self.status, "wb") as stream:
                    stream.write(b"competing status\n")
            return real_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", new=racing_open):
            result, _stdout, stderr = self.capture_main(self.capture_arguments())

        self.assertEqual(2, result)
        self.assertFalse(self.events.exists())
        self.assertEqual("competing status\n", self.status.read_text(encoding="utf-8"))
        self.assertIn("already exists", stderr)

    def test_status_race_does_not_delete_changed_event_reservation(self) -> None:
        real_open = Path.open

        def racing_open(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            if path == self.status and mode == "xb" and not self.status.exists():
                with real_open(self.events, "wb") as stream:
                    stream.write(b"changed ownership\n")
                with real_open(self.status, "wb") as stream:
                    stream.write(b"competing status\n")
            return real_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", new=racing_open):
            result, _stdout, _stderr = self.capture_main(self.capture_arguments())

        self.assertEqual(2, result)
        self.assertEqual("changed ownership\n", self.events.read_text(encoding="utf-8"))

    def test_status_race_does_not_delete_event_when_reservation_identity_changed(self) -> None:
        real_open = Path.open

        def racing_open(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            if path == self.status and mode == "xb" and not self.status.exists():
                with real_open(self.status, "wb") as stream:
                    stream.write(b"competing status\n")
            return real_open(path, mode, *args, **kwargs)

        with (
            patch.object(Path, "open", new=racing_open),
            patch("xpwebapi.capture_output.os.fstat") as fstat,
        ):
            fstat.return_value.st_dev = -1
            fstat.return_value.st_ino = -1
            result, _stdout, _stderr = self.capture_main(self.capture_arguments())

        self.assertEqual(2, result)
        self.assertTrue(self.events.exists())
        self.assertEqual(0, self.events.stat().st_size)

    def test_run_capture_passes_hash_provenance_and_lazy_transport_factory(self) -> None:
        capture_outcome = outcome("complete", clean=True)
        with patch("xpwebapi.capture_cli.resolve_source_provenance", return_value=PROVENANCE), patch("xpwebapi.capture_cli.CaptureRunner") as runner_type:
            runner_type.return_value.run.return_value = capture_outcome
            result = run_capture(
                self.request,
                self.events,
                self.status,
                None,
                threading.Event(),
                threading.Event(),
            )

        kwargs = runner_type.call_args.kwargs
        self.assertIs(capture_outcome, result)
        self.assertEqual(64, len(kwargs["request_sha256"]))
        self.assertEqual(PROVENANCE, kwargs["provenance"])
        self.assertFalse(hasattr(kwargs["transport_factory"], "open"))

    def test_signal_handlers_set_both_events_and_preserve_signal_identity(self) -> None:
        stop_event = threading.Event()
        interrupted_event = threading.Event()
        interruption = CaptureInterruption()
        handlers: dict[int, Any] = {}

        def remember(signum: int, handler: Any) -> None:
            handlers[signum] = handler

        with patch("xpwebapi.capture_cli.signal.signal", side_effect=remember):
            install_signal_handlers(stop_event, interrupted_event, interruption)

        handlers[signal.SIGTERM](signal.SIGTERM, None)
        handlers[signal.SIGINT](signal.SIGINT, None)
        self.assertTrue(stop_event.is_set())
        self.assertTrue(interrupted_event.is_set())
        self.assertEqual("SIGTERM", interruption.get())

    def test_programmatic_stop_does_not_invent_signal_identity(self) -> None:
        capture_outcome = outcome("complete", clean=True)
        stop_event = threading.Event()
        stop_event.set()
        interruption = CaptureInterruption()
        with patch("xpwebapi.capture_cli.resolve_source_provenance", return_value=PROVENANCE), patch("xpwebapi.capture_cli.CaptureRunner") as runner_type:
            runner_type.return_value.run.return_value = capture_outcome
            run_capture(
                self.request,
                self.events,
                self.status,
                None,
                stop_event,
                threading.Event(),
                interruption,
            )

        self.assertIsNone(interruption.get())

    def test_unexpected_runtime_failure_returns_three_and_preserves_partial_evidence(self) -> None:
        def fail_after_partial(*_args: Any, **_kwargs: Any) -> CaptureOutcome:
            self.events.write_text("partial evidence\n", encoding="utf-8")
            self.status.write_text("partial status\n", encoding="utf-8")
            raise RuntimeError("capture failed after startup")

        with patch("xpwebapi.capture_cli.run_capture", side_effect=fail_after_partial):
            result, stdout, stderr = self.capture_main(self.capture_arguments())

        self.assertEqual(3, result)
        self.assertEqual("", stdout)
        self.assertIn("capture runtime failed", stderr)
        self.assertEqual("partial evidence\n", self.events.read_text(encoding="utf-8"))
        self.assertEqual("partial status\n", self.status.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
