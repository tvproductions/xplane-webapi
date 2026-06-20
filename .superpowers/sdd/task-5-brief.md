### Task 5: Expand WebSocket Coverage

**Files:**
- Modify: `tests/test_ws.py`

**Interfaces:**
- Consumes: existing `WebsocketAPITestCase.make_api`
- Produces: additional bulk monitor, duplicate monitor, unmonitor, and callback registration coverage

- [ ] **Step 1: Add bulk monitor tests**

Add this class after `TestXPWebsocketAPIMessageHandling`:

```python
class TestXPWebsocketAPIMonitoring(WebsocketAPITestCase):
    def test_monitor_datarefs_subscribes_only_unmonitored_datarefs(self):
        api = self.make_api()
        first = Dataref(path="sim/test/first", api=api)
        first._cached_meta = DatarefMeta(name=first.path, value_type="float", is_writable=True, id=101)
        second = Dataref(path="sim/test/second", api=api)
        second._cached_meta = DatarefMeta(name=second.path, value_type="float", is_writable=True, id=102)
        second.inc_monitor()
        api.register_bulk_dataref_value_event = MagicMock(return_value=7)

        with patch.object(XPWebsocketAPI, "connected", new_callable=PropertyMock, return_value=True):
            result, effectives = api.monitor_datarefs({first.path: first, second.path: second}, reason="test")

        self.assertEqual(result, 7)
        self.assertEqual(set(effectives), {first.name, second.name})
        api.register_bulk_dataref_value_event.assert_called_once()
        bulk = api.register_bulk_dataref_value_event.call_args.kwargs["datarefs"]
        self.assertEqual(list(bulk), [101])
        self.assertEqual(first.monitored_count, 1)
        self.assertEqual(second.monitored_count, 2)

    def test_unmonitor_datarefs_skips_datarefs_still_monitored_elsewhere(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)
        dataref._cached_meta = DatarefMeta(name=dataref.path, value_type="float", is_writable=True, id=103)
        dataref.inc_monitor()
        dataref.inc_monitor()
        api.register_bulk_dataref_value_event = MagicMock(return_value=9)

        with patch.object(XPWebsocketAPI, "connected", new_callable=PropertyMock, return_value=True):
            result, effectives = api.unmonitor_datarefs({dataref.path: dataref}, reason="test")

        self.assertEqual(result, 0)
        self.assertEqual(effectives, {dataref.name: dataref})
        api.register_bulk_dataref_value_event.assert_not_called()
        self.assertEqual(dataref.monitored_count, 1)

    def test_monitor_datarefs_returns_false_when_disconnected(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)

        with patch.object(XPWebsocketAPI, "connected", new_callable=PropertyMock, return_value=False):
            self.assertEqual(api.monitor_datarefs({dataref.path: dataref}), (False, {}))
```

- [ ] **Step 2: Add callback set behavior test**

Add this method to `TestXPWebsocketAPICallbacks`:

```python
def test_add_callback_deduplicates_same_callable(self):
    api = self.make_api()
    callback = MagicMock()

    api.add_callback(CALLBACK_TYPE.ON_OPEN, callback)
    api.add_callback(CALLBACK_TYPE.ON_OPEN, callback)
    api.execute_callbacks(CALLBACK_TYPE.ON_OPEN)

    callback.assert_called_once()
```

- [ ] **Step 3: Run targeted WebSocket tests**

Run: `uv run python -m unittest tests.test_ws -v`

Expected: all WebSocket tests pass.

- [ ] **Step 4: Commit WebSocket coverage**

```powershell
git add tests/test_ws.py
git commit -m "test: expand websocket coverage"
```
