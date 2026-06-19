# Task 1 Report: Exception Hierarchy

## What Was Implemented

Created a typed exception hierarchy in `xpwebapi/exceptions.py`:

- `XPWebAPIError` — base exception, extends `Exception`, accepts `**context` kwargs stored on the instance
- `XPConnectionError` — extends `XPWebAPIError`
- `XPBeaconError` — extends `XPConnectionError`
- `XPTimeoutError` — extends `XPWebAPIError`
- `XPVersionError` — extends `XPWebAPIError`

Also created `tests/__init__.py` and `tests/test_exceptions.py` with 11 unit tests covering hierarchy, context storage, and catch-all behavior.

## What Was Tested and Results

11 tests in `tests/test_exceptions.py`:

| Test | Result |
|------|--------|
| `test_base_is_exception` | ok |
| `test_connection_error_is_xpwebapi_error` | ok |
| `test_beacon_error_is_connection_error` | ok |
| `test_timeout_error_is_xpwebapi_error` | ok |
| `test_version_error_is_xpwebapi_error` | ok |
| `test_context_kwargs` | ok |
| `test_context_empty_by_default` | ok |
| `test_beacon_error_context` | ok |
| `test_timeout_error_context` | ok |
| `test_version_error_context` | ok |
| `test_catch_base_catches_all` | ok |

Ruff lint: All checks passed.

## TDD Evidence

### RED (failing output)

```
ERROR: test_exceptions (unittest.loader._FailedTest.test_exceptions)
----------------------------------------------------------------------
ImportError: Failed to import test module: test_exceptions
Traceback (most recent call last):
  File "tests\test_exceptions.py", line 3, in <module>
    from xpwebapi.exceptions import (
    ...<5 lines>...
    )
ModuleNotFoundError: No module named 'xpwebapi.exceptions'

----------------------------------------------------------------------
Ran 1 test in 0.000s

FAILED (errors=1)
```

### GREEN (passing output)

```
test_base_is_exception ... ok
test_beacon_error_context ... ok
test_beacon_error_is_connection_error ... ok
test_catch_base_catches_all ... ok
test_connection_error_is_xpwebapi_error ... ok
test_context_empty_by_default ... ok
test_context_kwargs ... ok
test_timeout_error_context ... ok
test_timeout_error_is_xpwebapi_error ... ok
test_version_error_context ... ok
test_version_error_is_xpwebapi_error ... ok

----------------------------------------------------------------------
Ran 11 tests in 0.000s

OK
```

## Files Changed

| File | Action |
|------|--------|
| `xpwebapi/exceptions.py` | Created |
| `tests/__init__.py` | Created (empty) |
| `tests/test_exceptions.py` | Created |

## Self-Review Findings

- Implementation matches the brief exactly — no deviations.
- All 11 tests pass; ruff lint is clean.
- The `**context` pattern on `XPWebAPIError.__init__` correctly propagates to all subclasses via `pass` inheritance, verified by the context tests.
- No concerns.
