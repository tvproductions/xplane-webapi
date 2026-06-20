## What I implemented

- Updated `tests/test_beacon.py` to import `BEACON_MONITOR_STATUS`.
- Added `TestXPBeaconMonitorStatus` coverage for:
  - `receiving_beacon` returning `True` when `BeaconData` exists.
  - `receiving_beacon` incrementing `_already_warned` when no beacon data exists.
  - `stop_monitor()` setting status to `BEACON_MONITOR_STATUS.NOT_RUNNING` when already stopped.
- Added `TestXPBeaconMonitorCallbacks.test_set_callback_ignores_none` to verify `set_callback(None)` is a no-op.

## What I tested and test results

- `uv run python -m unittest tests.test_beacon -v`
  - Result: 17 tests run, all passed.
- `uv run python -m unittest discover -v`
  - Result: 187 tests run, all passed.
- `uv run ruff check xpwebapi tests`
  - Result: passed with `All checks passed!`
- `uv run ruff format --check xpwebapi tests`
  - Result: passed with `19 files already formatted`

## TDD Evidence

### RED before implementation

Command:

```powershell
uv run python -m unittest tests.test_beacon.TestXPBeaconMonitorStatus.test_receiving_beacon_returns_true_when_data_exists -v
```

Output:

```text
TestXPBeaconMonitorStatus (unittest.loader._FailedTest.TestXPBeaconMonitorStatus) ... ERROR

======================================================================
ERROR: TestXPBeaconMonitorStatus (unittest.loader._FailedTest.TestXPBeaconMonitorStatus)
----------------------------------------------------------------------
AttributeError: module 'tests.test_beacon' has no attribute 'TestXPBeaconMonitorStatus'. Did you mean: 'TestXPBeaconMonitorSameHost'?

----------------------------------------------------------------------
Ran 1 test in 0.000s

FAILED (errors=1)
```

### GREEN after implementation

Command:

```powershell
uv run python -m unittest tests.test_beacon -v
```

Output:

```text
Ran 17 tests in 0.007s

OK
```

Additional final verification:

```powershell
uv run python -m unittest discover -v
uv run ruff check xpwebapi tests
uv run ruff format --check xpwebapi tests
```

Results:

```text
Ran 187 tests in 1.563s

OK

All checks passed!

19 files already formatted
```

## Files changed

- `tests/test_beacon.py`
- `.superpowers/sdd/task-7-report.md`

## Self-review findings, if any

- No issues found in the requested scope.
- Kept the change limited to the test file; no production code changes were needed.

## Any issues or concerns

- `uv` execution required sandbox escalation in this environment due launch permissions, but all required commands completed successfully once run with approval.
