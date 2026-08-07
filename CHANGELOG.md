# Changelog

All notable changes to this project will be documented in this file.

## 4.1.0 (unreleased)

### Added

- Supported `xpwebapi.fdr` subpackage for immutable FDR models, strict version
  4 reading, deterministic canonical version 4 writing, read-only live
  recording, GeoJSON conversion, and source/sink composition.
- Installed `xpwebapi-fdr` command with `record`, `inspect`, `validate`, and
  `to-geojson` subcommands.
- FDR usage and API reference documentation, including downstream native-plugin
  testing boundaries and partial-file recovery behavior.

### Compatibility

- Version 3 file parsing is not planned for this release: it remains gated on the
  official reference fixture required to verify its fixed-column schema. The
  version 4 reader rejects v3 files rather than inferring the layout.
- Programmatically constructed legacy models may be written as version 4 only
  with explicit lossy-conversion opt-in; omitted legacy field identifiers are
  reported to the caller.

## 4.0.0 - 2026-07-26

First independently maintained TV Productions release and first PyPI release.
The upstream source reported version 3.5.0 when extension work began, but it
contained no corresponding upstream changelog entry or release tag; no missing
upstream releases are inferred here.

### Added

- Async REST client support.
- Typed metadata caches, typed exceptions, retries, and structured logging.
- Context-managed cleanup and REST connection pooling.
- Strictly read-only capture worker, installed CLI, versioned JSON protocols,
  and packaged JSON Schemas.
- Expanded API reference, usage guidance, examples, and `unittest` coverage.

### Changed

- TV Productions is the canonical maintainer and release source.
- HTTP and WebSocket transports use current `httpx` and `websockets` clients.
- Supported Python versions are 3.12 and 3.13.
- CI, security, typing, documentation, and release verification are blocking.

### Attribution

TV Productions thanks Pierre Mareschal and `devleaks` for the original
`xplane-webapi` project. Historical entries below are retained from upstream.

## 3.2.0 - 2025-08-09

Breaking change, `api.execute()` is now more explicitely `api.execute_command()`.

## 3.1.0 - 2025-07-31

Added callback to UDP dataref monitoring, like other rest and/or websocket API. Wow.

## 3.0.0 - 2025-07-07

Breaking change.

Datarefs of value type "data" are returned as *bytes*.
The API only performs BASE64 encode/decode with no further interpretation.

Convenience methods `get_string_value(encoding: str)` and `set_string_value(value: str, encoding: str)` are provided
to Dataref to get/set string values.
In all cases, string encoding need to be provided. There is no default encoding.

Note: It is possible to use python package `chardet` to guess encoding from bytes.

## 2.0.1 - 2025-06-15

Allows for multiple callback functions.
`set_callback` adds callback to list of callbacks, all called in turn.

In a next release, all handlers will be set of handlers.

## 2.0.0 - 2025-06-04

Refactor handlers.

## 1.2.O - 2025-06-03

Changed beacon callback prototype to pass beacon data and «same host» information in one call.

## 1.1.O - 2025-06-02

Using [natsort](https://github.com/SethMMorton/natsort/wiki) for version ordering as returned from X-Plane API *capabilities*.

Improved documentation.

## 1.0.O - 2025-05-30

Initial release
