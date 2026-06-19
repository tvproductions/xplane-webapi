# Task 2 Report: Backward Compatibility Aliases + Call Site Updates

## What I Implemented

1. **`tests/test_exceptions.py`** — Appended `TestBackwardCompat` class with 5 tests verifying:
   - `XPlaneNoBeacon` is a subclass of `XPBeaconError`
   - `XPlaneVersionNotSupported` is a subclass of `XPVersionError`
   - `XPlaneTimeout` is a subclass of `XPTimeoutError`
   - Old exception names remain importable from `xpwebapi`
   - New exception names are importable from `xpwebapi`

2. **`xpwebapi/beacon.py`** — Replaced `XPlaneNoBeacon(Exception)` and `XPlaneVersionNotSupported(Exception)` with subclasses of `XPBeaconError` and `XPVersionError` respectively. Updated raise sites with contextual messages:
   - `raise XPlaneNoBeacon("no beacon received", timeout=timeout)`
   - `raise XPlaneVersionNotSupported(f"beacon version {major}.{minor}.{host_id}")`

3. **`xpwebapi/udp.py`** — Replaced `XPlaneTimeout(Exception)` with subclass of `XPTimeoutError`. Updated raise site:
   - `raise XPlaneTimeout("UDP read timeout")`

4. **`xpwebapi/__init__.py`** — Added imports and `__all__` entries for `XPWebAPIError`, `XPConnectionError`, `XPBeaconError`, `XPTimeoutError`, `XPVersionError`.

## What I Tested and Test Results

- **RED phase**: Ran `TestBackwardCompat` before implementation — 3 FAILs + 1 ERROR (as expected)
- **GREEN phase**: All 16 tests pass (11 hierarchy + 5 backward compat)
- **Lint**: `ruff check xpwebapi/ tests/` — all checks passed
- **Full test suite**: `uv run python -m unittest discover` — 16/16 OK

## TDD Evidence

### RED (failing output)
```
test_new_names_importable_from_package ... ERROR
test_old_names_importable_from_package ... ok
test_xplane_no_beacon_is_beacon_error ... FAIL
test_xplane_timeout_is_timeout_error ... FAIL
test_xplane_version_not_supported_is_version_error ... FAIL
FAILED (failures=3, errors=1)
```

### GREEN (passing output)
```
Ran 16 tests in 0.000s
OK
```

## Files Changed

| File | Change |
|------|--------|
| `tests/test_exceptions.py` | Appended `TestBackwardCompat` class (5 tests) |
| `xpwebapi/beacon.py` | Exception classes now subclass new hierarchy; raise sites updated with context |
| `xpwebapi/udp.py` | `XPlaneTimeout` now subclasses `XPTimeoutError`; raise site updated |
| `xpwebapi/__init__.py` | Added new exception imports and `__all__` entries |

## Self-Review Findings

- All old exception names remain importable from both their original modules and the package root — full backward compatibility preserved.
- Raise sites now include contextual information (timeout values, version numbers) via the `context` kwargs mechanism from the base `XPWebAPIError`.
- Import placement was adjusted to satisfy `ruff` E402 (module-level imports at top of file).
- `noqa: F401` added to the `test_new_names_importable_from_package` test since the import itself is the assertion.
- No concerns identified.
