### Task 7: Expand Beacon Coverage

**Files:**
- Modify: `tests/test_beacon.py`

**Interfaces:**
- Consumes: `make_beacon_packet`
- Consumes: existing `BeaconMonitorTestCase.make_monitor`
- Produces: additional receiving beacon, status, callback, and monitor lifecycle tests

- [ ] **Step 1: Import status enum**

Update imports:

```python
from xpwebapi.beacon import BEACON_MONITOR_STATUS, BeaconData, XPBeaconMonitor, XPlaneNoBeacon, XPlaneVersionNotSupported
```

- [ ] **Step 2: Add receiving beacon warning behavior tests**

Add this class after `TestXPBeaconMonitorSameHost`:

```python
class TestXPBeaconMonitorStatus(BeaconMonitorTestCase):
    def test_receiving_beacon_returns_true_when_data_exists(self):
        monitor = self.make_monitor()
        monitor.data = BeaconData(host="127.0.0.1", port=49000, hostname="xp", xplane_version=121400, role=1)

        self.assertTrue(monitor.receiving_beacon)

    def test_receiving_beacon_increments_warning_counter_when_no_data(self):
        monitor = self.make_monitor()

        with patch("xpwebapi.beacon.logger.warning"):
            self.assertFalse(monitor.receiving_beacon)

        self.assertEqual(monitor._already_warned, 1)

    def test_stop_monitor_marks_status_not_running_when_already_stopped(self):
        monitor = self.make_monitor()

        with patch("xpwebapi.beacon.logger.warning"):
            monitor.stop_monitor()

        self.assertEqual(monitor.status, BEACON_MONITOR_STATUS.NOT_RUNNING)
```

- [ ] **Step 3: Add callback no-op test**

Add this method to `TestXPBeaconMonitorCallbacks`:

```python
def test_set_callback_ignores_none(self):
    monitor = self.make_monitor()

    monitor.set_callback(None)
    monitor.callback(connected=False, beacon_data=None, same_host=None)

    self.assertEqual(monitor._callback, set())
```

- [ ] **Step 4: Run targeted beacon tests**

Run: `uv run python -m unittest tests.test_beacon -v`

Expected: all beacon tests pass.

- [ ] **Step 5: Commit beacon coverage**

```powershell
git add tests/test_beacon.py
git commit -m "test: expand beacon coverage"
```
