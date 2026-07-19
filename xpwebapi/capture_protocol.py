"""Strict version-1 request protocol for the read-only capture worker."""

from __future__ import annotations

import codecs
import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_DATAREF_PATH = re.compile(r"^[^\[\]]+(?:\[(?:0|[1-9]\d*)\])?$")


def _nonempty_trimmed(value: str, *, name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{name} must be nonempty and already trimmed")
    return value


def _dataref_path(value: str) -> str:
    _nonempty_trimmed(value, name="dataref path")
    if _DATAREF_PATH.fullmatch(value) is None:
        raise ValueError("dataref path has a malformed or negative array index")
    return value


def _strict_float(value: object, *, name: str, minimum: float, inclusive: bool) -> float:
    if type(value) is not float:
        raise ValueError(f"{name} must be a float")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if value < minimum if inclusive else value <= minimum:
        qualifier = "at least" if inclusive else "greater than"
        raise ValueError(f"{name} must be {qualifier} {minimum}")
    return value


def _positive_float(value: object, *, name: str) -> float:
    return _strict_float(value, name=name, minimum=0.0, inclusive=False)


def _nonnegative_float(value: object, *, name: str) -> float:
    return _strict_float(value, name=name, minimum=0.0, inclusive=True)


def _optional_positive_float(value: object, *, name: str) -> float | None:
    if value is None:
        return None
    return _positive_float(value, name=name)


def _encoding_for_type(declared_type: str, encoding: str | None) -> None:
    if declared_type == "string":
        if encoding is None:
            raise ValueError("string refs require an encoding")
        try:
            codecs.lookup(encoding)
        except LookupError as exc:
            raise ValueError(f"unknown string encoding {encoding!r}") from exc
    elif encoding is not None:
        raise ValueError("numeric refs must not provide an encoding")


def _unique(values: tuple[str, ...], *, name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {name}")


class StrictModel(BaseModel):
    """Base for immutable protocol models without input coercion."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CaptureCorrelation(StrictModel):
    """Cross-repository campaign, route, and scenario identifiers."""

    campaign_id: str
    route_profile_id: str
    scenario_id: str

    @field_validator("campaign_id", "route_profile_id", "scenario_id")
    @classmethod
    def _validate_identifier(cls, value: str) -> str:
        return _nonempty_trimmed(value, name="correlation identifier")


class WebsocketCaptureConfig(StrictModel):
    """Bounded WebSocket capture connection settings."""

    kind: Literal["websocket"]
    host: str
    port: int
    api_path: str = "/api"
    api_version: str = "v2"
    http_timeout_seconds: float = 5.0
    open_timeout_seconds: float = 5.0
    close_timeout_seconds: float = 5.0

    @field_validator("host", "api_path", "api_version")
    @classmethod
    def _validate_string(cls, value: str) -> str:
        return _nonempty_trimmed(value, name="WebSocket string")

    @field_validator("port", mode="before")
    @classmethod
    def _validate_port(cls, value: object) -> object:
        if type(value) is not int or not 1 <= value <= 65535:
            raise ValueError("port must be an integer from 1 through 65535")
        return value

    @field_validator("http_timeout_seconds", "open_timeout_seconds", "close_timeout_seconds", mode="before")
    @classmethod
    def _validate_timeout(cls, value: object, info: Any) -> float:
        return _positive_float(value, name=info.field_name)


class UdpCaptureConfig(StrictModel):
    """Bounded beacon-discovered UDP capture settings."""

    kind: Literal["udp"]
    beacon_timeout_seconds: float = 5.0
    socket_timeout_seconds: float = 1.0
    liveness_timeout_seconds: float = 3.0

    @field_validator("beacon_timeout_seconds", "socket_timeout_seconds", "liveness_timeout_seconds", mode="before")
    @classmethod
    def _validate_timeout(cls, value: object, info: Any) -> float:
        return _positive_float(value, name=info.field_name)


class AircraftIdentityRef(StrictModel):
    """One DataRef assertion proving the loaded aircraft is Q4XP."""

    id: str
    path: str
    declared_type: Literal["int", "float", "double", "string"]
    encoding: str | None = None
    rate_hz: float = 1.0
    operator: Literal["equals", "contains"]
    expected_value: int | float | str

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return _nonempty_trimmed(value, name="identity ref id")

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return _dataref_path(value)

    @field_validator("encoding")
    @classmethod
    def _validate_encoding_text(cls, value: str | None) -> str | None:
        if value is not None:
            return _nonempty_trimmed(value, name="encoding")
        return value

    @field_validator("rate_hz", mode="before")
    @classmethod
    def _validate_rate(cls, value: object) -> float:
        return _positive_float(value, name="identity rate_hz")

    @model_validator(mode="after")
    def _validate_type_contract(self) -> "AircraftIdentityRef":
        _encoding_for_type(self.declared_type, self.encoding)
        if self.operator == "contains" and self.declared_type != "string":
            raise ValueError("contains is valid only for string identity refs")

        if self.declared_type == "int":
            valid_expected_value = type(self.expected_value) is int
        elif self.declared_type in {"float", "double"}:
            valid_expected_value = type(self.expected_value) is float and math.isfinite(self.expected_value)
        else:
            valid_expected_value = type(self.expected_value) is str
        if not valid_expected_value:
            raise ValueError("identity expected_value must exactly match declared_type and be finite")
        return self


class DatarefMatchIdentityReadiness(StrictModel):
    """Q4XP identity readiness established from matching DataRefs."""

    kind: Literal["dataref_match"]
    target_aircraft: Literal["FlyJSim Q4XP"]
    refs: tuple[AircraftIdentityRef, ...]

    @model_validator(mode="after")
    def _validate_refs(self) -> "DatarefMatchIdentityReadiness":
        if not self.refs:
            raise ValueError("identity readiness requires at least one ref")
        _unique(tuple(ref.id for ref in self.refs), name="identity ref id")
        _unique(tuple(ref.path for ref in self.refs), name="identity ref path")
        return self


class CaptureSampleGroup(StrictModel):
    """Fixed-cadence sampling group."""

    id: str
    rate_hz: float
    duration_seconds: float | None = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        return _nonempty_trimmed(value, name="sample group id")

    @field_validator("rate_hz", mode="before")
    @classmethod
    def _validate_rate(cls, value: object) -> float:
        return _positive_float(value, name="sample group rate_hz")

    @field_validator("duration_seconds", mode="before")
    @classmethod
    def _validate_duration(cls, value: object) -> float | None:
        return _optional_positive_float(value, name="duration_seconds")


class CaptureRef(StrictModel):
    """One read-only DataRef captured in a sample group."""

    id: str
    path: str
    declared_type: Literal["int", "float", "double", "string"]
    availability: Literal["required", "optional"]
    sample_group_id: str
    encoding: str | None = None

    @field_validator("id", "sample_group_id")
    @classmethod
    def _validate_id(cls, value: str, info: Any) -> str:
        return _nonempty_trimmed(value, name=info.field_name)

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return _dataref_path(value)

    @field_validator("encoding")
    @classmethod
    def _validate_encoding_text(cls, value: str | None) -> str | None:
        if value is not None:
            return _nonempty_trimmed(value, name="encoding")
        return value

    @model_validator(mode="after")
    def _validate_encoding(self) -> "CaptureRef":
        _encoding_for_type(self.declared_type, self.encoding)
        return self


class CaptureRetryPolicy(StrictModel):
    """Bounded retry and lifecycle timeout policy."""

    initial_attempts: int = 3
    reconnect_attempts: int = 3
    backoff_seconds: float = 0.5
    backoff_max_seconds: float = 5.0
    subscription_timeout_seconds: float = 10.0
    aircraft_identity_timeout_seconds: float = 300.0
    first_values_timeout_seconds: float = 30.0
    max_disconnect_seconds: float = 30.0
    stale_after_seconds: float = 3.0
    poll_interval_seconds: float = 0.25
    shutdown_timeout_seconds: float = 10.0

    @field_validator("initial_attempts", "reconnect_attempts", mode="before")
    @classmethod
    def _validate_attempts(cls, value: object, info: Any) -> object:
        if type(value) is not int or not 1 <= value <= 100:
            raise ValueError(f"{info.field_name} must be an integer from 1 through 100")
        return value

    @field_validator("backoff_seconds", "backoff_max_seconds", mode="before")
    @classmethod
    def _validate_backoff(cls, value: object, info: Any) -> float:
        return _nonnegative_float(value, name=info.field_name)

    @field_validator(
        "subscription_timeout_seconds",
        "aircraft_identity_timeout_seconds",
        "first_values_timeout_seconds",
        "max_disconnect_seconds",
        "stale_after_seconds",
        "poll_interval_seconds",
        "shutdown_timeout_seconds",
        mode="before",
    )
    @classmethod
    def _validate_timeout(cls, value: object, info: Any) -> float:
        return _positive_float(value, name=info.field_name)

    @model_validator(mode="after")
    def _validate_backoff_order(self) -> "CaptureRetryPolicy":
        if self.backoff_seconds > self.backoff_max_seconds:
            raise ValueError("backoff_seconds must not exceed backoff_max_seconds")
        return self


IdentityReadiness = Annotated[
    DatarefMatchIdentityReadiness,
    Field(discriminator="kind"),
]
CaptureTransportConfig = Annotated[
    WebsocketCaptureConfig | UdpCaptureConfig,
    Field(discriminator="kind"),
]


class CaptureRequest(StrictModel):
    """Canonical strict version-1 capture request."""

    protocol_version: Literal[1]
    capture_session_id: str
    sortie_id: str
    correlation: CaptureCorrelation
    identity_readiness: IdentityReadiness
    transport: CaptureTransportConfig
    sample_groups: tuple[CaptureSampleGroup, ...]
    refs: tuple[CaptureRef, ...]
    retry: CaptureRetryPolicy
    capture_limit_seconds: float | None = None
    stop_file: str | None = None

    @field_validator("protocol_version", mode="before")
    @classmethod
    def _validate_protocol_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("protocol_version must be exactly integer 1")
        return value

    @field_validator("capture_session_id", "sortie_id")
    @classmethod
    def _validate_identifier(cls, value: str, info: Any) -> str:
        return _nonempty_trimmed(value, name=info.field_name)

    @field_validator("stop_file")
    @classmethod
    def _validate_stop_file(cls, value: str | None) -> str | None:
        if value is not None:
            return _nonempty_trimmed(value, name="stop_file")
        return value

    @field_validator("capture_limit_seconds", mode="before")
    @classmethod
    def _validate_capture_limit(cls, value: object) -> float | None:
        return _optional_positive_float(value, name="capture_limit_seconds")

    @model_validator(mode="after")
    def _validate_relationships(self) -> "CaptureRequest":
        group_ids = tuple(group.id for group in self.sample_groups)
        identity_ids = tuple(ref.id for ref in self.identity_readiness.refs)
        capture_ids = tuple(ref.id for ref in self.refs)
        identity_paths = tuple(ref.path for ref in self.identity_readiness.refs)
        capture_paths = tuple(ref.path for ref in self.refs)

        _unique(group_ids + identity_ids + capture_ids, name="identifier")
        _unique(identity_paths + capture_paths, name="ref path")

        unknown_groups = {ref.sample_group_id for ref in self.refs}.difference(group_ids)
        if unknown_groups:
            raise ValueError(f"capture refs name unknown sample groups: {sorted(unknown_groups)!r}")

        if isinstance(self.transport, UdpCaptureConfig):
            all_refs = (*self.identity_readiness.refs, *self.refs)
            if any(ref.declared_type != "float" for ref in all_refs):
                raise ValueError("UDP capture accepts only float refs")
            rates = (*tuple(ref.rate_hz for ref in self.identity_readiness.refs), *tuple(group.rate_hz for group in self.sample_groups))
            if any(rate < 1.0 or rate > 100.0 or not rate.is_integer() for rate in rates):
                raise ValueError("UDP capture rates must be integral from 1 through 100 Hz")

        return self


@dataclass(frozen=True, slots=True)
class LoadedCaptureRequest:
    """Validated request paired with the SHA-256 of its exact source bytes."""

    request: CaptureRequest
    request_sha256: str


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_json_constant(constant: str) -> None:
    raise ValueError(f"non-finite JSON constant is not permitted: {constant}")


def _json_arrays_to_protocol_tuples(document: Any) -> Any:
    if not isinstance(document, dict):
        return document
    prepared = dict(document)
    identity = prepared.get("identity_readiness")
    if isinstance(identity, dict):
        prepared_identity = dict(identity)
        refs = prepared_identity.get("refs")
        if isinstance(refs, list):
            prepared_identity["refs"] = tuple(refs)
        prepared["identity_readiness"] = prepared_identity
    for field_name in ("sample_groups", "refs"):
        value = prepared.get(field_name)
        if isinstance(value, list):
            prepared[field_name] = tuple(value)
    return prepared


def load_capture_request(path: Path) -> LoadedCaptureRequest:
    """Read, decode, validate, and hash one exact request byte buffer."""

    request_bytes = path.read_bytes()
    document = json.loads(
        request_bytes,
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_json_constant,
    )
    request = CaptureRequest.model_validate(_json_arrays_to_protocol_tuples(document))
    return LoadedCaptureRequest(
        request=request,
        request_sha256=hashlib.sha256(request_bytes).hexdigest(),
    )


def _resolved_path(base: Path | None, value: Path) -> Path:
    candidate = value if value.is_absolute() else (base / value if base is not None else value)
    return candidate.resolve()


def _path_identity(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def resolve_stop_file(
    request_path: Path,
    request_value: Path | None,
    cli_value: Path | None,
) -> Path | None:
    """Resolve the request/CLI stop-file contract and reject pre-existing stops."""

    request_stop = _resolved_path(request_path.resolve().parent, request_value) if request_value is not None else None
    cli_stop = _resolved_path(None, cli_value) if cli_value is not None else None

    if request_stop is not None and cli_stop is not None and _path_identity(request_stop) != _path_identity(cli_stop):
        raise ValueError("request and CLI stop files must resolve to the same path")

    stop_file = request_stop if request_stop is not None else cli_stop
    if stop_file is not None and stop_file.exists():
        raise FileExistsError(stop_file)
    return stop_file
