# Structured Logging

**Date:** 2026-06-21
**Priority:** P2 - Medium
**Status:** Approved

## Goal

Add explicit, opt-in structured logging configuration for `xpwebapi`, with JSON file configuration validated by Pydantic, separate application and traffic logging, and per-component log levels.

## Background

The package currently uses standard module loggers such as `xpwebapi.rest`, `xpwebapi.ws`, `xpwebapi.udp`, and `xpwebapi.beacon`. It also defines a separate `webapi` logger for REST and WebSocket traffic. That split is useful, but users do not have a package-level way to configure text versus JSON output, traffic verbosity, or component-specific levels.

This is a library, so importing `xpwebapi` must not mutate global logging configuration. Users should opt in by calling a helper.

## Design

### Public API

Add `xpwebapi/logging_config.py` and re-export these names from `xpwebapi/__init__.py`:

```python
configure_logging
write_logging_config
LoggingConfig
JsonLogFormatter
```

Primary usage:

```python
import xpwebapi

xpwebapi.configure_logging(config_file="xpwebapi-logging.json")
```

Starter config generation:

```python
import xpwebapi

xpwebapi.write_logging_config("xpwebapi-logging.json")
```

Programmatic configuration remains supported for applications that do not want a file:

```python
xpwebapi.configure_logging(format="json", level="INFO", traffic_level="WARNING")
```

### Dependency

Add Pydantic v2 as a runtime dependency:

```toml
"pydantic>=2,<3"
```

Pydantic validates file and programmatic configuration. Invalid config should fail before logger handlers are modified.

### JSON Config Schema

Use JSON because Python has mature stdlib read/write support and Pydantic validates JSON-backed data cleanly.

```json
{
  "logging": {
    "format": "json",
    "level": "INFO",
    "traffic_level": "WARNING",
    "components": {
      "xpwebapi.rest": "DEBUG",
      "xpwebapi.ws": "INFO",
      "xpwebapi.beacon": "WARNING"
    }
  }
}
```

Model shape:

```python
class LoggingConfig(BaseModel):
    format: Literal["text", "json"] = "text"
    level: str = "INFO"
    traffic_level: str = "WARNING"
    components: dict[str, str] = Field(default_factory=dict)


class LoggingConfigFile(BaseModel):
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
```

Log levels are accepted as standard logging level names: `CRITICAL`, `ERROR`, `WARNING`, `INFO`, `DEBUG`, and `NOTSET`. Validation rejects unknown names.

### Logger Separation

Configure two roots deliberately:

- Application logs: `logging.getLogger("xpwebapi")`
- Traffic logs: `logging.getLogger("webapi")`

`configure_logging()` sets handlers and levels for both. The `webapi` traffic logger keeps `propagate = False` so traffic logs do not duplicate through the application logger.

Component overrides apply after root logger levels:

```python
for logger_name, level in config.components.items():
    logging.getLogger(logger_name).setLevel(level)
```

Only `xpwebapi.*` and `webapi` component names are accepted. This prevents a package helper from unexpectedly configuring unrelated application loggers.

### Formatting

`format = "text"` uses a compact standard formatter:

```text
%(asctime)s %(levelname)s %(name)s: %(message)s
```

`format = "json"` uses `JsonLogFormatter`, producing one JSON object per record with stable fields:

```json
{
  "timestamp": "2026-06-21T12:34:56.789Z",
  "level": "INFO",
  "logger": "xpwebapi.rest",
  "message": "rest api reachable",
  "module": "rest",
  "function": "rest_api_reachable",
  "line": 188
}
```

When exception info is present, include an `exception` string containing the formatted traceback. Existing log calls continue working; this design does not require changing every `logger.info(...)` call.

### File Handling

`configure_logging(config_file=...)`:

- Reads JSON from the provided file.
- Raises `FileNotFoundError` if the explicit file path is missing.
- Raises `ValueError` for invalid JSON with the file path in the message.
- Raises Pydantic validation errors for schema problems.
- Applies direct keyword overrides after file loading.
- Adds or replaces package-owned handlers only after validation succeeds.

`write_logging_config(path)`:

- Writes a valid starter JSON config with stable indentation and key order.
- Does not overwrite an existing file unless `overwrite=True`.
- Returns the written path as `Path`.
- The generated file must validate through the same Pydantic model used by `configure_logging()`.

### No Import-Time Side Effects

Importing `xpwebapi` must not configure handlers, read config files, or inspect the current working directory. Logging changes happen only when `configure_logging()` or `write_logging_config()` is called.

## Testing

Use `unittest` only.

Add `tests/test_logging_config.py` covering:

- `JsonLogFormatter` emits valid JSON with stable core fields.
- Exception records include an `exception` field.
- `LoggingConfig` accepts valid standard level names.
- `LoggingConfig` rejects unknown level names.
- Component validation rejects unrelated logger names.
- `write_logging_config()` writes a file that validates when read back.
- `write_logging_config()` does not overwrite existing files by default.
- `configure_logging()` keeps `xpwebapi` and `webapi` handlers separated.
- `configure_logging()` applies component-specific levels.
- Importing `xpwebapi` does not add handlers to `xpwebapi` or `webapi`.

## Success Criteria

- [ ] `xpwebapi.configure_logging()` is available from the package root.
- [ ] `xpwebapi.write_logging_config()` is available from the package root.
- [ ] JSON logging can be enabled explicitly through config file or kwargs.
- [ ] Application logs and traffic logs are configured separately.
- [ ] Per-component levels are supported for `xpwebapi.*` and `webapi`.
- [ ] Invalid logging config fails before mutating handlers.
- [ ] No import-time auto-configuration is added.
- [ ] `BACKLOG.md` marks P2 structured logging complete after verification passes.
