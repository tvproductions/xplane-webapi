### Task 6: Expand UDP Coverage

**Files:**
- Modify: `xpwebapi/udp.py`
- Modify: `tests/test_udp.py`

**Interfaces:**
- Consumes: `make_rref_packet`
- Consumes: existing `UDPAPITestCase.make_api`
- Produces: additional disconnected, command, and monitor counter coverage
- Produces: UDP monitor/unmonitor counter parity with `Dataref.is_monitored`

- [ ] **Step 1: Add disconnected write and command tests**

Add to `TestXPUDPAPIWriteDataref`:

```python
def test_write_dataref_sends_packet_without_connection_probe(self):
    api = self.make_api()
    dataref = Dataref(path="sim/test/value", api=api)
    dataref.value = 1.25

    self.assertTrue(api.write_dataref(dataref))
    api.socket.sendto.assert_called_once()
```

Add to `TestXPUDPAPIExecuteCommand`:

```python
def test_execute_command_ignores_duration_for_udp_packet(self):
    api = self.make_api()
    command = Command(path="sim/test/command", api=api)

    self.assertTrue(api.execute_command(command, duration=2.0))

    message, _address = api.socket.sendto.call_args.args
    self.assertTrue(message.startswith(b"CMND\x00"))
    self.assertIn(b"sim/test/command", message)
```

- [ ] **Step 2: Add monitor counter tests**

Add to `TestXPUDPAPIRequestDataref`:

```python
def test_monitor_dataref_increments_dataref_monitor_count(self):
    api = self.make_api()
    dataref = Dataref(path="sim/test/value", api=api)

    with patch.object(XPUDPAPI, "connected", new_callable=PropertyMock, return_value=True):
        self.assertTrue(api.monitor_dataref(dataref))

    self.assertEqual(dataref.monitored_count, 1)
    self.assertTrue(dataref.is_monitored)


def test_unmonitor_datarefs_decrements_dataref_monitor_count(self):
    api = self.make_api()
    dataref = Dataref(path="sim/test/value", api=api)

    with patch.object(XPUDPAPI, "connected", new_callable=PropertyMock, return_value=True):
        api.monitor_dataref(dataref)
        result, effectives = api.unmonitor_datarefs({dataref.path: dataref})

    self.assertTrue(result)
    self.assertEqual(effectives, {})
    self.assertEqual(dataref.monitored_count, 0)
```

- [ ] **Step 3: Run UDP monitor counter tests to verify they expose the current defect**

Run: `uv run python -m unittest tests.test_udp.TestXPUDPAPIRequestDataref.test_monitor_dataref_increments_dataref_monitor_count tests.test_udp.TestXPUDPAPIRequestDataref.test_unmonitor_datarefs_decrements_dataref_monitor_count -v`

Expected: FAIL because `XPUDPAPI.monitor_dataref()` and `XPUDPAPI.unmonitor_datarefs()` do not currently update the `Dataref` monitor counter.

- [ ] **Step 4: Fix UDP monitor counter updates**

In `xpwebapi/udp.py`, replace `monitor_dataref` with:

```python
def monitor_dataref(self, dataref: Dataref) -> bool | int:
    """Starts monitoring single dataref.

    [description]

    Args:
        dataref (Dataref): Dataref to monitor

    Returns:
        bool if fails
        request id if succeeded
    """
    ret = self._request_dataref(dataref=dataref.path, freq=1)
    if ret:
        dataref.inc_monitor()
    return ret
```

Replace `unmonitor_datarefs` with:

```python
def unmonitor_datarefs(self, datarefs: dict, reason: str | None = None) -> Tuple[int | bool, Dict]:
    """Stops monitoring supplied datarefs.

    [description]

    Args:
        datarefs (dict): {path: Dataref} dictionary of datarefs
        reason (str | None): Documentation only string to identify call to function.

    Returns:
        Tuple[int | bool, Dict]: [description]
    """
    ret = True
    for dataref in datarefs.values():
        if dataref.monitored_count > 1:
            dataref.dec_monitor()
            continue
        r = self._request_dataref(dataref=dataref.path, freq=0)
        if r and dataref.is_monitored:
            dataref.dec_monitor()
        if not r:
            ret = False
    return ret, {}
```

- [ ] **Step 5: Re-run UDP monitor counter tests**

Run: `uv run python -m unittest tests.test_udp.TestXPUDPAPIRequestDataref.test_monitor_dataref_increments_dataref_monitor_count tests.test_udp.TestXPUDPAPIRequestDataref.test_unmonitor_datarefs_decrements_dataref_monitor_count -v`

Expected: PASS.

- [ ] **Step 6: Run targeted UDP tests**

Run: `uv run python -m unittest tests.test_udp -v`

Expected: all UDP tests pass.

- [ ] **Step 7: Commit UDP coverage and counter fix**

```powershell
git add xpwebapi/udp.py tests/test_udp.py
git commit -m "fix: track udp monitor counters"
```
