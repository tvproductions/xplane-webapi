"""Installed JSON Schema resources for the capture protocol."""

from __future__ import annotations

SCHEMA_FILENAMES: tuple[str, ...] = (
    "capture-event-v1.schema.json",
    "capture-request-v1.schema.json",
    "capture-status-v1.schema.json",
    "capture-version-v1.schema.json",
)

__all__ = ["SCHEMA_FILENAMES"]
