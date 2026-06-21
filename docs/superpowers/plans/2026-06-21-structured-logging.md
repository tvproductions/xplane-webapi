# Structured Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build explicit, opt-in structured logging configuration for `xpwebapi` using JSON config files validated by Pydantic.

**Architecture:** Add a focused `xpwebapi.logging_config` module that owns config models, JSON formatting, starter config writing, and logger setup. Existing module loggers remain unchanged; the helper configures `xpwebapi` application logs separately from the existing `webapi` traffic logger.

**Tech Stack:** Python 3.12, stdlib `logging`, stdlib `json`, stdlib `unittest`, Pydantic v2, `uv`, `ruff`, `ty`.

## Global Constraints

- Use `unittest` only; do not add or reference any other test framework.
- Use JSON config, not TOML and not environment variables.
- Retain Python logging levels only: `CRITICAL`, `ERROR`, `WARNING`, `INFO`, `DEBUG`, `NOTSET`.
- Do not add import-time logging auto-configuration.
- Validate config before mutating logger handlers.
- Keep application logs on `xpwebapi` and traffic logs on `webapi`.
- Only allow component overrides for `xpwebapi.*` and `webapi`.
- Update `BACKLOG.md` only after verification passes.

---

## File Structure

- Modify `pyproject.toml`: add Pydantic v2 runtime dependency.
- Modify `uv.lock`: update through `uv add "pydantic>=2,<3"` or equivalent lock refresh.
- Create `xpwebapi/logging_config.py`: Pydantic config models, JSON formatter, config file writer, and logger configuration helper.
- Modify `xpwebapi/__init__.py`: re-export logging helper public API.
- Create `tests/test_logging_config.py`: focused `unittest` coverage for models, formatter, file handling, logger separation, component overrides, and import side effects.
- Modify `BACKLOG.md`: mark P2 structured logging complete after all validation commands pass.

---

### Task 1: Add Pydantic Dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: existing project dependency management through `uv`.
- Produces: importable `pydantic.BaseModel`, `pydantic.Field`, and `pydantic.field_validator` for later tasks.

- [ ] **Step 1: Add Pydantic dependency**

Run:

```powershell
uv add "pydantic>=2,<3"
```

Expected:

```text
pyproject.toml and uv.lock updated with pydantic>=2,<3
```

- [ ] **Step 2: Verify Pydantic imports**

Run:

```powershell
uv run python -c "from pydantic import BaseModel, Field, field_validator; print(BaseModel.__name__)"
```

Expected:

```text
BaseModel
```

- [ ] **Step 3: Commit dependency update**

Run:

```powershell
git add pyproject.toml uv.lock
git commit -m "build: add pydantic dependency"
```

Expected:

```text
[branch <commit>] build: add pydantic dependency
```

---

### Task 2: Add Logging Models And JSON Formatter

**Files:**
- Create: `xpwebapi/logging_config.py`
- Create: `tests/test_logging_config.py`

**Interfaces:**
- Consumes: `pydantic.BaseModel`, `pydantic.Field`, `pydantic.field_validator`, stdlib `logging`, stdlib `json`.
- Produces:
  - `LoggingConfig`
  - `LoggingConfigFile`
  - `JsonLogFormatter`
  - `_normalize_level_name(level: str) -> str`

- [ ] **Step 1: Write failing formatter and model tests**

Create `tests/test_logging_config.py` with this initial content:

```python
import json
import logging
import sys
import unittest

from pydantic import ValidationError

from xpwebapi.logging_config import JsonLogFormatter, LoggingConfig


class TestJsonLogFormatter(unittest.TestCase):
    def test_json_formatter_emits_stable_core_fields(self):
        record = logging.LogRecord(
            name="xpwebapi.rest",
            level=logging.INFO,
            pathname="rest.py",
            lineno=188,
            msg="rest api reachable",
            args=(),
            exc_info=None,
            func="rest_api_reachable",
        )

        payload = json.loads(JsonLogFormatter().format(record))

        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["logger"], "xpwebapi.rest")
        self.assertEqual(payload["message"], "rest api reachable")
        self.assertEqual(payload["module"], "rest")
        self.assertEqual(payload["function"], "rest_api_reachable")
        self.assertEqual(payload["line"], 188)
        self.assertRegex(payload["timestamp"], r"^\d{4}-\d{2}-\d{2}T.*Z$")
        self.assertNotIn("exception", payload)

    def test_json_formatter_includes_exception_text(self):
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            exc_info = sys.exc_info()
            record = logging.getLogger("xpwebapi.rest").makeRecord(
                name="xpwebapi.rest",
                level=logging.ERROR,
                fn="rest.py",
                lno=200,
                msg="request failed",
                args=(),
                exc_info=exc_info,
                func="dataref_value",
                extra=None,
            )

        payload = json.loads(JsonLogFormatter().format(record))

        self.assertEqual(payload["level"], "ERROR")
        self.assertIn("RuntimeError: boom", payload["exception"])


class TestLoggingConfig(unittest.TestCase):
    def test_logging_config_accepts_standard_python_levels(self):
        config = LoggingConfig(
            format="json",
            level="debug",
            traffic_level="WARNING",
            components={"xpwebapi.rest": "INFO", "webapi": "ERROR"},
        )

        self.assertEqual(config.format, "json")
        self.assertEqual(config.level, "DEBUG")
        self.assertEqual(config.traffic_level, "WARNING")
        self.assertEqual(config.components["xpwebapi.rest"], "INFO")
        self.assertEqual(config.components["webapi"], "ERROR")

    def test_logging_config_rejects_unknown_level_names(self):
        with self.assertRaises(ValidationError):
            LoggingConfig(level="NOTICE")

    def test_logging_config_rejects_unrelated_component_names(self):
        with self.assertRaises(ValidationError):
            LoggingConfig(components={"urllib3": "DEBUG"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
uv run python -m unittest tests.test_logging_config -v
```

Expected:

```text
ModuleNotFoundError: No module named 'xpwebapi.logging_config'
```

- [ ] **Step 3: Implement models and formatter**

Create `xpwebapi/logging_config.py` with this content:

```python
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
    if name == "webapi" or name.startswith("xpwebapi."):
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
        self.components = {_validate_component_name(name): _normalize_level_name(level) for name, level in self.components.items()}
        return self


class LoggingConfigFile(BaseModel):
    """Top-level JSON config file schema."""

    model_config = ConfigDict(extra="forbid")

    logging: LoggingConfig = Field(default_factory=LoggingConfig)


class JsonLogFormatter(logging.Formatter):
    """Format log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
uv run python -m unittest tests.test_logging_config -v
```

Expected:

```text
Ran 5 tests

OK
```

- [ ] **Step 5: Commit models and formatter**

Run:

```powershell
git add xpwebapi/logging_config.py tests/test_logging_config.py
git commit -m "feat: add structured logging config models"
```

Expected:

```text
[branch <commit>] feat: add structured logging config models
```

---

### Task 3: Add Config File IO And Logger Configuration

**Files:**
- Modify: `xpwebapi/logging_config.py`
- Modify: `tests/test_logging_config.py`

**Interfaces:**
- Consumes:
  - `LoggingConfig`
  - `LoggingConfigFile`
  - `JsonLogFormatter`
  - `PYTHON_LEVELS`
- Produces:
  - `configure_logging(config_file: str | Path | None = None, *, format: Literal["text", "json"] | None = None, level: str | None = None, traffic_level: str | None = None, components: Mapping[str, str] | None = None, stream: TextIO | None = None) -> LoggingConfig`
  - `write_logging_config(path: str | Path, *, config: LoggingConfig | None = None, overwrite: bool = False) -> Path`

- [ ] **Step 1: Add failing IO and logger setup tests**

Append these imports to `tests/test_logging_config.py`:

```python
import importlib
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
```

Extend the existing import from `xpwebapi.logging_config`:

```python
from xpwebapi.logging_config import JsonLogFormatter, LoggingConfig, configure_logging, write_logging_config
```

Append these helper and test classes:

```python
class IsolatedLoggerState:
    def __init__(self, *names: str) -> None:
        self.names = names
        self.state = {}

    def __enter__(self) -> "IsolatedLoggerState":
        for name in self.names:
            logger = logging.getLogger(name)
            self.state[name] = (logger.handlers[:], logger.level, logger.propagate)
            logger.handlers.clear()
            logger.setLevel(logging.NOTSET)
            logger.propagate = True
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        for name, (handlers, level, propagate) in self.state.items():
            logger = logging.getLogger(name)
            logger.handlers.clear()
            logger.handlers.extend(handlers)
            logger.setLevel(level)
            logger.propagate = propagate


class TestLoggingConfigFileIO(unittest.TestCase):
    def test_write_logging_config_writes_valid_starter_config(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "xpwebapi-logging.json"

            written = write_logging_config(path)

            self.assertEqual(written, path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            config = LoggingConfig.model_validate(raw["logging"])
            self.assertEqual(config.format, "text")
            self.assertEqual(config.level, "INFO")
            self.assertEqual(config.traffic_level, "WARNING")

    def test_write_logging_config_does_not_overwrite_by_default(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "xpwebapi-logging.json"
            path.write_text("{}", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                write_logging_config(path)

    def test_configure_logging_raises_value_error_for_invalid_json(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "xpwebapi-logging.json"
            path.write_text("{", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "xpwebapi-logging.json"):
                configure_logging(config_file=path)

    def test_configure_logging_raises_file_not_found_for_explicit_missing_file(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "missing.json"

            with self.assertRaises(FileNotFoundError):
                configure_logging(config_file=path)


class TestConfigureLogging(unittest.TestCase):
    def test_configure_logging_separates_application_and_traffic_loggers(self):
        app_stream = StringIO()

        with IsolatedLoggerState("xpwebapi", "webapi"):
            config = configure_logging(format="json", level="DEBUG", traffic_level="ERROR", stream=app_stream)

            app_logger = logging.getLogger("xpwebapi")
            traffic_logger = logging.getLogger("webapi")

            self.assertEqual(config.format, "json")
            self.assertEqual(app_logger.level, logging.DEBUG)
            self.assertEqual(traffic_logger.level, logging.ERROR)
            self.assertEqual(len(app_logger.handlers), 1)
            self.assertEqual(len(traffic_logger.handlers), 1)
            self.assertIsInstance(app_logger.handlers[0].formatter, JsonLogFormatter)
            self.assertIsInstance(traffic_logger.handlers[0].formatter, JsonLogFormatter)
            self.assertIsNot(app_logger.handlers[0], traffic_logger.handlers[0])
            self.assertFalse(traffic_logger.propagate)

    def test_configure_logging_applies_component_levels(self):
        with IsolatedLoggerState("xpwebapi", "webapi", "xpwebapi.rest", "xpwebapi.ws"):
            configure_logging(level="WARNING", components={"xpwebapi.rest": "DEBUG", "xpwebapi.ws": "ERROR"})

            self.assertEqual(logging.getLogger("xpwebapi").level, logging.WARNING)
            self.assertEqual(logging.getLogger("xpwebapi.rest").level, logging.DEBUG)
            self.assertEqual(logging.getLogger("xpwebapi.ws").level, logging.ERROR)

    def test_configure_logging_validates_before_mutating_handlers(self):
        foreign_handler = logging.NullHandler()

        with IsolatedLoggerState("xpwebapi", "webapi"):
            app_logger = logging.getLogger("xpwebapi")
            app_logger.addHandler(foreign_handler)

            with self.assertRaises(ValidationError):
                configure_logging(level="NOTICE")

            self.assertEqual(app_logger.handlers, [foreign_handler])

    def test_repeated_configure_logging_replaces_only_owned_handlers(self):
        foreign_handler = logging.NullHandler()

        with IsolatedLoggerState("xpwebapi", "webapi"):
            app_logger = logging.getLogger("xpwebapi")
            app_logger.addHandler(foreign_handler)

            configure_logging(level="INFO")
            configure_logging(level="DEBUG")

            self.assertIn(foreign_handler, app_logger.handlers)
            owned_handlers = [handler for handler in app_logger.handlers if getattr(handler, "_xpwebapi_owned_handler", False)]
            self.assertEqual(len(owned_handlers), 1)
            self.assertEqual(app_logger.level, logging.DEBUG)

    def test_importing_package_does_not_configure_logging_handlers(self):
        import xpwebapi

        with IsolatedLoggerState("xpwebapi", "webapi"):
            before = {
                "xpwebapi": logging.getLogger("xpwebapi").handlers[:],
                "webapi": logging.getLogger("webapi").handlers[:],
            }

            importlib.reload(xpwebapi)

            self.assertEqual(logging.getLogger("xpwebapi").handlers, before["xpwebapi"])
            self.assertEqual(logging.getLogger("webapi").handlers, before["webapi"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
uv run python -m unittest tests.test_logging_config -v
```

Expected:

```text
ImportError: cannot import name 'configure_logging'
```

- [ ] **Step 3: Implement file IO and logger setup**

Update `xpwebapi/logging_config.py` imports:

```python
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, TextIO
```

Append this implementation to `xpwebapi/logging_config.py`:

```python
OWNED_HANDLER_ATTR = "_xpwebapi_owned_handler"


def _level_number(level: str) -> int:
    return PYTHON_LEVELS[_normalize_level_name(level)]


def _load_config_file(config_file: str | Path) -> LoggingConfig:
    path = Path(config_file)
    raw_text = path.read_text(encoding="utf-8")
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON logging config {path}: {exc}") from exc
    return LoggingConfigFile.model_validate(raw).logging


def _make_handler(config: LoggingConfig, stream: TextIO | None) -> logging.Handler:
    handler = logging.StreamHandler(stream)
    formatter: logging.Formatter
    if config.format == "json":
        formatter = JsonLogFormatter()
    else:
        formatter = logging.Formatter(LOGGING_FORMAT_TEXT)
    handler.setFormatter(formatter)
    setattr(handler, OWNED_HANDLER_ATTR, True)
    return handler


def _replace_owned_handlers(logger: logging.Logger, handler: logging.Handler) -> None:
    logger.handlers = [existing for existing in logger.handlers if not getattr(existing, OWNED_HANDLER_ATTR, False)]
    logger.addHandler(handler)


def _merge_config(
    base: LoggingConfig,
    *,
    format: Literal["text", "json"] | None,
    level: str | None,
    traffic_level: str | None,
    components: Mapping[str, str] | None,
) -> LoggingConfig:
    data = base.model_dump()
    if format is not None:
        data["format"] = format
    if level is not None:
        data["level"] = level
    if traffic_level is not None:
        data["traffic_level"] = traffic_level
    if components is not None:
        data["components"] = {**data["components"], **dict(components)}
    return LoggingConfig.model_validate(data)


def configure_logging(
    config_file: str | Path | None = None,
    *,
    format: Literal["text", "json"] | None = None,
    level: str | None = None,
    traffic_level: str | None = None,
    components: Mapping[str, str] | None = None,
    stream: TextIO | None = None,
) -> LoggingConfig:
    """Configure xpwebapi application and traffic logging explicitly."""

    base_config = _load_config_file(config_file) if config_file is not None else LoggingConfig()
    config = _merge_config(base_config, format=format, level=level, traffic_level=traffic_level, components=components)

    app_logger = logging.getLogger("xpwebapi")
    traffic_logger = logging.getLogger("webapi")

    app_handler = _make_handler(config, stream)
    traffic_handler = _make_handler(config, stream)

    _replace_owned_handlers(app_logger, app_handler)
    _replace_owned_handlers(traffic_logger, traffic_handler)

    app_logger.setLevel(_level_number(config.level))
    traffic_logger.setLevel(_level_number(config.traffic_level))
    app_logger.propagate = False
    traffic_logger.propagate = False

    for logger_name, logger_level in config.components.items():
        logging.getLogger(logger_name).setLevel(_level_number(logger_level))

    return config


def write_logging_config(path: str | Path, *, config: LoggingConfig | None = None, overwrite: bool = False) -> Path:
    """Write a starter JSON logging config file."""

    output_path = Path(path)
    if output_path.exists() and not overwrite:
        raise FileExistsError(output_path)

    config_file = LoggingConfigFile(logging=config or LoggingConfig())
    output_path.write_text(json.dumps(config_file.model_dump(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
uv run python -m unittest tests.test_logging_config -v
```

Expected:

```text
Ran 14 tests

OK
```

- [ ] **Step 5: Commit IO and logger setup**

Run:

```powershell
git add xpwebapi/logging_config.py tests/test_logging_config.py
git commit -m "feat: configure structured logging"
```

Expected:

```text
[branch <commit>] feat: configure structured logging
```

---

### Task 4: Export API, Update Backlog, And Validate

**Files:**
- Modify: `xpwebapi/__init__.py`
- Modify: `BACKLOG.md`
- Test: `tests/test_logging_config.py`

**Interfaces:**
- Consumes:
  - `xpwebapi.logging_config.configure_logging`
  - `xpwebapi.logging_config.write_logging_config`
  - `xpwebapi.logging_config.LoggingConfig`
  - `xpwebapi.logging_config.JsonLogFormatter`
- Produces package-root imports:
  - `xpwebapi.configure_logging`
  - `xpwebapi.write_logging_config`
  - `xpwebapi.LoggingConfig`
  - `xpwebapi.JsonLogFormatter`

- [ ] **Step 1: Add failing package-root export test**

Append this test class to `tests/test_logging_config.py`:

```python
class TestPackageRootExports(unittest.TestCase):
    def test_logging_helpers_are_exported_from_package_root(self):
        import xpwebapi

        self.assertIs(xpwebapi.configure_logging, configure_logging)
        self.assertIs(xpwebapi.write_logging_config, write_logging_config)
        self.assertIs(xpwebapi.LoggingConfig, LoggingConfig)
        self.assertIs(xpwebapi.JsonLogFormatter, JsonLogFormatter)
        self.assertIn("configure_logging", xpwebapi.__all__)
        self.assertIn("write_logging_config", xpwebapi.__all__)
        self.assertIn("LoggingConfig", xpwebapi.__all__)
        self.assertIn("JsonLogFormatter", xpwebapi.__all__)
```

- [ ] **Step 2: Run export test to verify it fails**

Run:

```powershell
uv run python -m unittest tests.test_logging_config.TestPackageRootExports.test_logging_helpers_are_exported_from_package_root -v
```

Expected:

```text
AttributeError: module 'xpwebapi' has no attribute 'configure_logging'
```

- [ ] **Step 3: Export logging helpers**

Update `xpwebapi/__init__.py` imports:

```python
from .logging_config import JsonLogFormatter, LoggingConfig, configure_logging, write_logging_config
```

Add these names to `__all__`:

```python
    "JsonLogFormatter",
    "LoggingConfig",
    "configure_logging",
    "write_logging_config",
```

- [ ] **Step 4: Run export test to verify it passes**

Run:

```powershell
uv run python -m unittest tests.test_logging_config.TestPackageRootExports.test_logging_helpers_are_exported_from_package_root -v
```

Expected:

```text
OK
```

- [ ] **Step 5: Run full unittest suite**

Run:

```powershell
uv run python -m unittest discover -v
```

Expected:

```text
OK
```

- [ ] **Step 6: Run ruff**

Run:

```powershell
uv run ruff check .
```

Expected:

```text
All checks passed!
```

- [ ] **Step 7: Run type checker**

Run:

```powershell
uv run ty check
```

Expected:

```text
No errors
```

- [ ] **Step 8: Mark backlog item complete**

Update `BACKLOG.md`:

```markdown
### [x] Structured logging
- [x] Add JSON log formatter option
- [x] Separate request/response traffic logging from application logging
- [x] Configurable log levels per component via JSON configuration
```

- [ ] **Step 9: Run final verification after backlog update**

Run:

```powershell
uv run python -m unittest discover -v
uv run ruff check .
uv run ty check
```

Expected:

```text
unittest: OK
ruff: All checks passed!
ty: No errors
```

- [ ] **Step 10: Commit final feature state**

Run:

```powershell
git add BACKLOG.md xpwebapi/__init__.py tests/test_logging_config.py
git commit -m "feat: expose structured logging helpers"
```

Expected:

```text
[branch <commit>] feat: expose structured logging helpers
```

---

## Self-Review Notes

- Spec coverage:
  - Explicit helper: Task 3.
  - JSON config: Task 3.
  - Pydantic validation: Tasks 1 and 2.
  - Separate app and traffic loggers: Task 3.
  - Component levels: Task 3.
  - Root exports: Task 4.
  - Backlog completion: Task 4.
- Placeholder scan: no deferred implementation steps.
- Type consistency:
  - `LoggingConfig`, `LoggingConfigFile`, `JsonLogFormatter`, `configure_logging`, and `write_logging_config` names are consistent across tasks.
  - Public root export names match spec success criteria.
