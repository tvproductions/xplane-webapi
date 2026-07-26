import hashlib
import json
import math
import os
import unittest
from enum import Enum, IntEnum, StrEnum
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from pydantic import ValidationError

from xpwebapi.capture_protocol import (
    AircraftIdentityRef,
    CaptureRequest,
    load_capture_request,
    resolve_stop_file,
)


SCHEMA_ROOT = files("xpwebapi.schemas")


class CaptureSessionEnum(StrEnum):
    SESSION = "capture-20260719-001"


class AvailabilityEnum(str, Enum):
    REQUIRED = "required"


class ExpectedIntegerEnum(IntEnum):
    TWO = 2


class ExpectedFloatEnum(float, Enum):
    TWO = 2.0


class ExpectedStringEnum(StrEnum):
    Q4XP = "Q4XP"


def valid_request_payload(transport: str = "websocket") -> dict[str, Any]:
    transport_config: dict[str, object]
    if transport == "websocket":
        transport_config = {
            "kind": "websocket",
            "host": "127.0.0.1",
            "port": 8086,
            "api_path": "/api",
            "api_version": "v2",
            "http_timeout_seconds": 5.0,
            "open_timeout_seconds": 5.0,
            "close_timeout_seconds": 5.0,
        }
    elif transport == "udp":
        transport_config = {
            "kind": "udp",
            "beacon_timeout_seconds": 5.0,
            "socket_timeout_seconds": 1.0,
            "liveness_timeout_seconds": 3.0,
        }
    else:
        raise ValueError(f"unsupported fixture transport: {transport}")

    identity_ref: dict[str, object] = {
        "id": "q4xp_relative_path",
        "path": "sim/aircraft/view/acf_relative_path",
        "declared_type": "string",
        "encoding": "utf-8",
        "rate_hz": 1.0,
        "operator": "contains",
        "expected_value": "Q4XP",
    }
    if transport == "udp":
        identity_ref = {
            "id": "q4xp_engine_count",
            "path": "sim/aircraft/engine/acf_num_engines",
            "declared_type": "float",
            "encoding": None,
            "rate_hz": 1.0,
            "operator": "equals",
            "expected_value": 2.0,
        }

    return {
        "protocol_version": 1,
        "capture_session_id": "capture-20260719-001",
        "sortie_id": "sortie-20260719-001",
        "correlation": {
            "campaign_id": "q4xp_shakedown",
            "route_profile_id": "kaus-kgls",
            "scenario_id": "kaus_kgls_live",
        },
        "identity_readiness": {
            "kind": "dataref_match",
            "target_aircraft": "FlyJSim Q4XP",
            "refs": (identity_ref,),
        },
        "transport": transport_config,
        "sample_groups": (
            {
                "id": "baseline_state",
                "rate_hz": 1.0,
                "duration_seconds": None,
            },
        ),
        "refs": (
            {
                "id": "sim_groundspeed",
                "path": "sim/flightmodel/position/groundspeed",
                "declared_type": "float",
                "availability": "required",
                "sample_group_id": "baseline_state",
                "encoding": None,
            },
        ),
        "retry": {
            "initial_attempts": 3,
            "reconnect_attempts": 3,
            "backoff_seconds": 0.5,
            "backoff_max_seconds": 5.0,
            "subscription_timeout_seconds": 10.0,
            "aircraft_identity_timeout_seconds": 300.0,
            "first_values_timeout_seconds": 30.0,
            "max_disconnect_seconds": 30.0,
            "stale_after_seconds": 3.0,
            "poll_interval_seconds": 0.25,
            "shutdown_timeout_seconds": 10.0,
        },
        "capture_limit_seconds": None,
        "stop_file": None,
    }


class TestCaptureRequestStrictModels(unittest.TestCase):
    def assert_invalid(self, payload: dict[str, Any]) -> None:
        with self.assertRaises(ValidationError):
            CaptureRequest.model_validate(payload)

    def test_complete_websocket_request_is_valid_and_frozen(self):
        request = CaptureRequest.model_validate(valid_request_payload())

        self.assertEqual(request.protocol_version, 1)
        self.assertEqual(request.transport.kind, "websocket")
        self.assertIsInstance(request.sample_groups, tuple)
        with self.assertRaises(ValidationError):
            setattr(request, "capture_session_id", "different")

    def test_complete_udp_request_is_valid(self):
        request = CaptureRequest.model_validate(valid_request_payload("udp"))

        self.assertEqual(request.transport.kind, "udp")

    def test_aircraft_identity_timeout_accepts_explicit_unbounded_wait(self):
        payload = valid_request_payload()
        payload["retry"]["aircraft_identity_timeout_seconds"] = None

        request = CaptureRequest.model_validate(payload)

        self.assertIsNone(request.retry.aircraft_identity_timeout_seconds)

    def test_protocol_version_is_exactly_integer_one(self):
        for value in (0, 2, "1", 1.0, True):
            with self.subTest(value=value):
                payload = valid_request_payload()
                payload["protocol_version"] = value
                self.assert_invalid(payload)

    def test_unknown_fields_are_rejected_at_every_model_boundary(self):
        paths = (
            ("top-level", lambda payload: payload.__setitem__("command", "sim/test")),
            ("correlation", lambda payload: payload["correlation"].__setitem__("extra", True)),
            ("identity", lambda payload: payload["identity_readiness"].__setitem__("write", True)),
            ("identity ref", lambda payload: payload["identity_readiness"]["refs"][0].__setitem__("value", 1)),
            ("transport", lambda payload: payload["transport"].__setitem__("method", "POST")),
            ("sample group", lambda payload: payload["sample_groups"][0].__setitem__("extra", True)),
            ("capture ref", lambda payload: payload["refs"][0].__setitem__("command", "begin")),
            ("retry", lambda payload: payload["retry"].__setitem__("forever", True)),
        )
        for label, mutate in paths:
            with self.subTest(model=label):
                payload = valid_request_payload()
                mutate(payload)
                self.assert_invalid(payload)

    def test_identifiers_and_paths_must_be_nonempty_and_trimmed(self):
        mutations = (
            lambda payload, value: payload.__setitem__("capture_session_id", value),
            lambda payload, value: payload.__setitem__("sortie_id", value),
            lambda payload, value: payload["correlation"].__setitem__("campaign_id", value),
            lambda payload, value: payload["correlation"].__setitem__("route_profile_id", value),
            lambda payload, value: payload["correlation"].__setitem__("scenario_id", value),
            lambda payload, value: payload["identity_readiness"]["refs"][0].__setitem__("id", value),
            lambda payload, value: payload["identity_readiness"]["refs"][0].__setitem__("path", value),
            lambda payload, value: payload["sample_groups"][0].__setitem__("id", value),
            lambda payload, value: payload["refs"][0].__setitem__("id", value),
            lambda payload, value: payload["refs"][0].__setitem__("path", value),
            lambda payload, value: payload["refs"][0].__setitem__("sample_group_id", value),
        )
        for index, mutate in enumerate(mutations):
            for value in ("", " ", " padded"):
                with self.subTest(field=index, value=value):
                    payload = valid_request_payload()
                    mutate(payload, value)
                    self.assert_invalid(payload)

    def test_websocket_strings_must_be_nonempty_and_trimmed(self):
        for field in ("host", "api_path", "api_version"):
            for value in ("", " ", " padded"):
                with self.subTest(field=field, value=value):
                    payload = valid_request_payload()
                    payload["transport"][field] = value
                    self.assert_invalid(payload)

    def test_duplicate_sample_group_ids_are_rejected(self):
        payload = valid_request_payload()
        payload["sample_groups"] += ({"id": "baseline_state", "rate_hz": 2.0, "duration_seconds": 1.0},)
        self.assert_invalid(payload)

    def test_duplicate_capture_ref_ids_and_paths_are_rejected(self):
        for field in ("id", "path"):
            with self.subTest(field=field):
                payload = valid_request_payload()
                duplicate = dict(payload["refs"][0])
                duplicate["id"] = "second_ref"
                duplicate["path"] = "sim/test/second"
                duplicate[field] = payload["refs"][0][field]
                payload["refs"] += (duplicate,)
                self.assert_invalid(payload)

    def test_duplicate_identity_ref_ids_and_paths_are_rejected(self):
        for field in ("id", "path"):
            with self.subTest(field=field):
                payload = valid_request_payload()
                duplicate = dict(payload["identity_readiness"]["refs"][0])
                duplicate["id"] = "second_identity"
                duplicate["path"] = "sim/test/identity"
                duplicate[field] = payload["identity_readiness"]["refs"][0][field]
                payload["identity_readiness"]["refs"] += (duplicate,)
                self.assert_invalid(payload)

    def test_identity_and_capture_ref_namespaces_must_not_collide(self):
        for field in ("id", "path"):
            with self.subTest(field=field):
                payload = valid_request_payload()
                payload["refs"][0][field] = payload["identity_readiness"]["refs"][0][field]
                self.assert_invalid(payload)

    def test_sample_group_and_ref_identifier_namespaces_must_not_collide(self):
        payload = valid_request_payload()
        payload["sample_groups"][0]["id"] = payload["refs"][0]["id"]
        payload["refs"][0]["sample_group_id"] = payload["refs"][0]["id"]

        self.assert_invalid(payload)

    def test_capture_ref_must_name_an_existing_sample_group(self):
        payload = valid_request_payload()
        payload["refs"][0]["sample_group_id"] = "unknown"
        self.assert_invalid(payload)

    def test_identity_readiness_requires_at_least_one_ref(self):
        payload = valid_request_payload()
        payload["identity_readiness"]["refs"] = ()
        self.assert_invalid(payload)

    def test_nonfinite_rates_timeouts_backoffs_and_durations_are_rejected(self):
        mutations = (
            lambda payload, value: payload["identity_readiness"]["refs"][0].__setitem__("rate_hz", value),
            lambda payload, value: payload["sample_groups"][0].__setitem__("rate_hz", value),
            lambda payload, value: payload["sample_groups"][0].__setitem__("duration_seconds", value),
            lambda payload, value: payload["transport"].__setitem__("http_timeout_seconds", value),
            lambda payload, value: payload["retry"].__setitem__("backoff_seconds", value),
            lambda payload, value: payload["retry"].__setitem__("subscription_timeout_seconds", value),
            lambda payload, value: payload.__setitem__("capture_limit_seconds", value),
        )
        for index, mutate in enumerate(mutations):
            for value in (math.nan, math.inf, -math.inf):
                with self.subTest(field=index, value=value):
                    payload = valid_request_payload()
                    mutate(payload, value)
                    self.assert_invalid(payload)

    def test_udp_timeouts_must_be_finite_and_positive(self):
        for field in ("beacon_timeout_seconds", "socket_timeout_seconds", "liveness_timeout_seconds"):
            for value in (0.0, -1.0, math.inf):
                with self.subTest(field=field, value=value):
                    payload = valid_request_payload("udp")
                    payload["transport"][field] = value
                    self.assert_invalid(payload)

    def test_rates_timeouts_and_optional_durations_must_be_positive(self):
        mutations = (
            lambda payload, value: payload["identity_readiness"]["refs"][0].__setitem__("rate_hz", value),
            lambda payload, value: payload["sample_groups"][0].__setitem__("rate_hz", value),
            lambda payload, value: payload["sample_groups"][0].__setitem__("duration_seconds", value),
            lambda payload, value: payload["transport"].__setitem__("open_timeout_seconds", value),
            lambda payload, value: payload["retry"].__setitem__("poll_interval_seconds", value),
            lambda payload, value: payload.__setitem__("capture_limit_seconds", value),
        )
        for index, mutate in enumerate(mutations):
            for value in (0.0, -0.5):
                with self.subTest(field=index, value=value):
                    payload = valid_request_payload()
                    mutate(payload, value)
                    self.assert_invalid(payload)

    def test_retry_backoffs_are_nonnegative_and_ordered(self):
        for field in ("backoff_seconds", "backoff_max_seconds"):
            payload = valid_request_payload()
            payload["retry"][field] = -0.1
            with self.subTest(field=field):
                self.assert_invalid(payload)

        payload = valid_request_payload()
        payload["retry"]["backoff_seconds"] = 5.5
        payload["retry"]["backoff_max_seconds"] = 5.0
        self.assert_invalid(payload)

    def test_attempt_counts_are_strict_integers_from_one_through_one_hundred(self):
        for field in ("initial_attempts", "reconnect_attempts"):
            for value in (0, 101, -1, 3.0, "3", True):
                with self.subTest(field=field, value=value):
                    payload = valid_request_payload()
                    payload["retry"][field] = value
                    self.assert_invalid(payload)

    def test_string_refs_require_known_encoding_and_numeric_refs_forbid_it(self):
        payload = valid_request_payload()
        payload["identity_readiness"]["refs"][0]["encoding"] = None
        self.assert_invalid(payload)

        payload = valid_request_payload()
        payload["identity_readiness"]["refs"][0]["encoding"] = "not-a-codec"
        self.assert_invalid(payload)

        payload = valid_request_payload()
        payload["refs"][0]["encoding"] = "utf-8"
        self.assert_invalid(payload)

    def test_string_capture_ref_requires_known_encoding(self):
        for encoding in (None, "not-a-codec"):
            with self.subTest(encoding=encoding):
                payload = valid_request_payload()
                payload["refs"][0]["declared_type"] = "string"
                payload["refs"][0]["encoding"] = encoding
                self.assert_invalid(payload)

    def test_identity_operator_and_expected_value_must_match_declared_type(self):
        cases = (
            ("int", "equals", 7, None),
            ("float", "equals", 7.0, None),
            ("double", "equals", 7.0, None),
            ("string", "equals", "Q4XP", "utf-8"),
            ("string", "contains", "Q4", "utf-8"),
        )
        for declared_type, operator, expected_value, encoding in cases:
            with self.subTest(declared_type=declared_type, operator=operator):
                payload = valid_request_payload()
                ref = payload["identity_readiness"]["refs"][0]
                ref.update(
                    declared_type=declared_type,
                    operator=operator,
                    expected_value=expected_value,
                    encoding=encoding,
                )
                CaptureRequest.model_validate(payload)

        invalid_cases = (
            ("int", "contains", 7, None),
            ("float", "contains", 7.0, None),
            ("double", "contains", 7.0, None),
            ("int", "equals", 7.0, None),
            ("float", "equals", 7, None),
            ("double", "equals", "7.0", None),
            ("string", "equals", 7, "utf-8"),
            ("int", "equals", True, None),
        )
        for declared_type, operator, expected_value, encoding in invalid_cases:
            with self.subTest(invalid=(declared_type, operator, expected_value)):
                payload = valid_request_payload()
                ref = payload["identity_readiness"]["refs"][0]
                ref.update(
                    declared_type=declared_type,
                    operator=operator,
                    expected_value=expected_value,
                    encoding=encoding,
                )
                self.assert_invalid(payload)

    def test_numeric_identity_expected_value_must_be_finite(self):
        for declared_type in ("float", "double"):
            for value in (math.nan, math.inf, -math.inf):
                with self.subTest(declared_type=declared_type, value=value):
                    payload = valid_request_payload()
                    ref = payload["identity_readiness"]["refs"][0]
                    ref.update(declared_type=declared_type, encoding=None, operator="equals", expected_value=value)
                    self.assert_invalid(payload)

    def test_udp_accepts_only_float_refs(self):
        for location in ("identity", "capture"):
            for declared_type in ("int", "double", "string"):
                with self.subTest(location=location, declared_type=declared_type):
                    payload = valid_request_payload("udp")
                    if location == "identity":
                        ref = payload["identity_readiness"]["refs"][0]
                        ref.update(declared_type=declared_type, operator="equals")
                        if declared_type == "int":
                            ref.update(encoding=None, expected_value=1)
                        elif declared_type == "double":
                            ref.update(encoding=None, expected_value=1.0)
                    else:
                        ref = payload["refs"][0]
                        ref.update(declared_type=declared_type)
                        if declared_type == "string":
                            ref["encoding"] = "utf-8"
                    self.assert_invalid(payload)

    def test_udp_rates_must_be_integral_from_one_through_one_hundred(self):
        mutations = (
            lambda payload, value: payload["identity_readiness"]["refs"][0].__setitem__("rate_hz", value),
            lambda payload, value: payload["sample_groups"][0].__setitem__("rate_hz", value),
        )
        for index, mutate in enumerate(mutations):
            for value in (0.0, 2.5, 101.0):
                with self.subTest(field=index, value=value):
                    payload = valid_request_payload("udp")
                    mutate(payload, value)
                    self.assert_invalid(payload)

    def test_websocket_port_must_be_strict_integer_in_range(self):
        for value in (0, 65536, -1, True, 8086.0, "8086"):
            with self.subTest(value=value):
                payload = valid_request_payload()
                payload["transport"]["port"] = value
                self.assert_invalid(payload)

    def test_dataref_array_index_must_be_one_nonnegative_integer_suffix(self):
        for path in (
            "sim/test/value[0]",
            "sim/test/value[25]",
        ):
            with self.subTest(valid=path):
                payload = valid_request_payload()
                payload["refs"][0]["path"] = path
                CaptureRequest.model_validate(payload)

        for path in (
            "sim/test/value[",
            "sim/test/value]",
            "sim/test/value[]",
            "sim/test/value[-1]",
            "sim/test/value[1.0]",
            "sim/test/value[abc]",
            "sim/test/value[1]extra",
            "sim/test/value[1][2]",
        ):
            with self.subTest(invalid=path):
                payload = valid_request_payload()
                payload["refs"][0]["path"] = path
                self.assert_invalid(payload)

    def test_transport_and_identity_discriminators_are_required_and_exact(self):
        for field, value in (("transport", "rest"), ("identity_readiness", "command")):
            with self.subTest(field=field, value=value):
                payload = valid_request_payload()
                payload[field]["kind"] = value
                self.assert_invalid(payload)

            with self.subTest(field=field, value="missing"):
                payload = valid_request_payload()
                del payload[field]["kind"]
                self.assert_invalid(payload)

            with self.subTest(field=field, value=1):
                payload = valid_request_payload()
                payload[field]["kind"] = 1
                self.assert_invalid(payload)

    def test_strict_mode_rejects_scalar_path_enum_and_collection_coercion(self):
        class Availability(Enum):
            REQUIRED = "required"

        mutations = (
            lambda payload: payload.__setitem__("capture_session_id", 123),
            lambda payload: payload.__setitem__("stop_file", Path("capture.stop")),
            lambda payload: payload["sample_groups"][0].__setitem__("rate_hz", 1),
            lambda payload: payload["refs"][0].__setitem__("availability", Availability.REQUIRED),
            lambda payload: payload.__setitem__("sample_groups", list(payload["sample_groups"])),
            lambda payload: payload["identity_readiness"].__setitem__("refs", list(payload["identity_readiness"]["refs"])),
            lambda payload: payload.__setitem__("refs", list(payload["refs"])),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                payload = valid_request_payload()
                mutate(payload)
                self.assert_invalid(payload)

    def test_typed_string_enums_are_rejected_before_string_and_literal_coercion(self):
        mutations = (
            lambda payload: payload.__setitem__("capture_session_id", CaptureSessionEnum.SESSION),
            lambda payload: payload["refs"][0].__setitem__("availability", AvailabilityEnum.REQUIRED),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                payload = valid_request_payload()
                mutate(payload)
                self.assert_invalid(payload)

        CaptureRequest.model_validate(valid_request_payload())

    def test_typed_enums_are_rejected_before_identity_expected_value_coercion(self):
        cases = (
            ("int", None, ExpectedIntegerEnum.TWO),
            ("float", None, ExpectedFloatEnum.TWO),
            ("string", "utf-8", ExpectedStringEnum.Q4XP),
        )
        for declared_type, encoding, expected_value in cases:
            with self.subTest(declared_type=declared_type):
                payload = valid_request_payload()
                payload["identity_readiness"]["refs"][0].update(
                    declared_type=declared_type,
                    encoding=encoding,
                    operator="equals",
                    expected_value=expected_value,
                )
                self.assert_invalid(payload)

        CaptureRequest.model_validate(valid_request_payload())

    def test_aircraft_identity_ref_is_strict_when_validated_directly(self):
        with self.assertRaises(ValidationError):
            AircraftIdentityRef.model_validate(
                {
                    "id": "identity",
                    "path": "sim/test/value",
                    "declared_type": "float",
                    "rate_hz": "1.0",
                    "operator": "equals",
                    "expected_value": 1.0,
                }
            )


class TestCaptureRequestFileLoading(unittest.TestCase):
    def test_load_hashes_and_validates_the_exact_bytes(self):
        raw_bytes = json.dumps(valid_request_payload(), indent=3).encode("utf-8") + b"\r\n"
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "request.json"
            path.write_bytes(raw_bytes)

            loaded = load_capture_request(path)

        self.assertEqual(loaded.request.capture_session_id, "capture-20260719-001")
        self.assertEqual(loaded.request_sha256, hashlib.sha256(raw_bytes).hexdigest())

    def test_load_rejects_duplicate_json_object_keys(self):
        duplicate_json = b'{"protocol_version":1,"protocol_version":1}'
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "request.json"
            path.write_bytes(duplicate_json)

            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_capture_request(path)

    def test_load_rejects_json_nan_and_infinity_constants(self):
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant), TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "request.json"
                text = json.dumps(valid_request_payload()).replace("null", constant, 1)
                path.write_text(text, encoding="utf-8")

                with self.assertRaises(ValueError):
                    load_capture_request(path)

    def test_checked_schema_is_the_exact_canonical_model_schema(self):
        checked_schema = json.loads(SCHEMA_ROOT.joinpath("capture-request-v1.schema.json").read_text(encoding="utf-8"))

        self.assertEqual(checked_schema, CaptureRequest.model_json_schema())


class TestResolveStopFile(unittest.TestCase):
    def test_absent_request_and_cli_values_return_none(self):
        self.assertIsNone(resolve_stop_file(Path("request.json"), None, None))

    def test_relative_request_stop_file_resolves_against_request_parent(self):
        with TemporaryDirectory() as tmpdir:
            request_path = Path(tmpdir) / "requests" / "request.json"

            resolved = resolve_stop_file(request_path, Path("capture.stop"), None)

        self.assertEqual(resolved, (request_path.parent / "capture.stop").resolve())

    def test_relative_cli_stop_file_resolves_against_working_directory(self):
        with TemporaryDirectory() as tmpdir:
            old_cwd = Path.cwd()
            try:
                os.chdir(tmpdir)
                resolved = resolve_stop_file(Path("requests/request.json"), None, Path("capture.stop"))
            finally:
                os.chdir(old_cwd)

        self.assertEqual(resolved, (Path(tmpdir) / "capture.stop").resolve())

    def test_request_and_cli_values_may_resolve_to_same_path(self):
        with TemporaryDirectory() as tmpdir:
            request_path = Path(tmpdir) / "request.json"
            stop_path = Path(tmpdir) / "capture.stop"

            resolved = resolve_stop_file(request_path, Path("capture.stop"), stop_path)

        self.assertEqual(resolved, stop_path.resolve())

    def test_stop_file_cli_and_request_must_agree(self):
        with self.assertRaises(ValueError):
            resolve_stop_file(Path("request.json"), Path("request.stop"), Path("cli.stop"))

    def test_preexisting_stop_file_is_rejected(self):
        with TemporaryDirectory() as tmpdir:
            stop_path = Path(tmpdir) / "capture.stop"
            stop_path.write_text("stop\n", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                resolve_stop_file(Path(tmpdir) / "request.json", stop_path, None)


if __name__ == "__main__":
    unittest.main()
