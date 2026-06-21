"""Logging configuration helpers for xpwebapi."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


LOGGING_FORMAT_TEXT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
PYTHON_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}


def _normalize_level_name(level: str) -> str:
    if not isinstance(level, str):
        raise TypeError("logging level must be a string")
    normalized = level.upper()
    if normalized not in PYTHON_LEVELS:
        valid = ", ".join(PYTHON_LEVELS)
        raise ValueError(f"unknown logging level {level!r}; expected one of: {valid}")
    return normalized


def _validate_component_name(name: str) -> str:
    if name == "webapi" or (name.startswith("xpwebapi.") and len(name) > len("xpwebapi.")):
        return name
    raise ValueError("component logger must be 'webapi' or start with 'xpwebapi.'")


class LoggingConfig(BaseModel):
    """Validated logging configuration."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["text", "json"] = "text"
    level: str = "INFO"
    traffic_level: str = "WARNING"
    components: dict[str, str] = Field(default_factory=dict)

    @field_validator("level", "traffic_level")
    @classmethod
    def _validate_level(cls, value: str) -> str:
        return _normalize_level_name(value)

    @model_validator(mode="after")
    def _validate_components(self) -> "LoggingConfig":
        self.components = {
            _validate_component_name(name): _normalize_level_name(level) for name, level in self.components.items()
        }
        return self


class LoggingConfigFile(BaseModel):
    """Top-level JSON config file schema."""

    model_config = ConfigDict(extra="forbid")

    logging: LoggingConfig = Field(default_factory=LoggingConfig)


class JsonLogFormatter(logging.Formatter):
    """Format log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True)
