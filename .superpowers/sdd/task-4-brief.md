### Task 4: Expand REST And Async REST Coverage

**Files:**
- Modify: `xpwebapi/rest.py`
- Modify: `tests/test_rest.py`
- Modify: `tests/test_async_rest.py`

**Interfaces:**
- Consumes: `mock_response`
- Consumes: existing `RestAPITestCase.make_api`
- Consumes: existing `AsyncRestAPITestCase.make_api`
- Produces: additional REST lifecycle, capabilities, version, cache, and parity tests
- Produces: fixed `XPRestAPI.set_api_version(None)` latest-version selection

- [ ] **Step 1: Import REST constants and caches in `tests/test_rest.py`**

Update the imports:

```python
from xpwebapi.api import DATAREF_DATATYPE, Command, CommandMeta, Dataref, DatarefCache, DatarefMeta
from xpwebapi.rest import V1_CAPABILITIES, XPRestAPI
```

- [ ] **Step 2: Add capabilities and API version tests**

Add this class after `TestXPRestAPIConnected`:

```python
class TestXPRestAPICapabilities(RestAPITestCase):
    def test_capabilities_are_cached_after_successful_fetch(self):
        api = self.make_api()
        payload = {"api": {"versions": ["v1", "v2"]}, "x-plane": {"version": "12.2.1"}}
        api.session.get.return_value = mock_response(200, payload)

        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertEqual(api.capabilities, payload)
            self.assertEqual(api.capabilities, payload)

        api.session.get.assert_called_once()

    def test_capabilities_fall_back_to_v1_probe(self):
        api = self.make_api()
        api.session.get.side_effect = [mock_response(404), mock_response(200, {"data": 1})]

        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertEqual(api.capabilities, V1_CAPABILITIES)

    def test_set_api_version_selects_latest_available_when_unspecified(self):
        api = self.make_api()
        api._capabilities = {"api": {"versions": ["v1", "v3", "v2"]}, "x-plane": {"version": "12.2.1"}}

        api.set_api_version()

        self.assertEqual(api.version, "v3")
        self.assertEqual(api._api_version, "/v3")
```

- [ ] **Step 3: Run latest-version test to verify it exposes the current defect**

Run: `uv run python -m unittest tests.test_rest.TestXPRestAPICapabilities.test_set_api_version_selects_latest_available_when_unspecified -v`

Expected: FAIL because `set_api_version(None)` logs the selected version but does not assign it to `api_version`.

- [ ] **Step 4: Fix latest-version assignment in `xpwebapi/rest.py`**

Replace this block inside `XPRestAPI.set_api_version`:

```python
if api_version is None:
    if api_versions is None:
        logger.error("cannot determine api, api not set")
        return
    sorted_apis = natsorted(api_versions, reverse=True)
    api = sorted_apis[0]  # takes the latest one, hoping it is the latest in time...
    logger.info(f"selected api {api} ({sorted_apis})")
```

with:

```python
if api_version is None:
    if api_versions is None:
        logger.error("cannot determine api, api not set")
        return
    sorted_apis = natsorted(api_versions, reverse=True)
    api_version = sorted_apis[0]  # takes the latest one, hoping it is the latest in time...
    logger.info(f"selected api {api_version} ({sorted_apis})")
```

- [ ] **Step 5: Re-run latest-version test**

Run: `uv run python -m unittest tests.test_rest.TestXPRestAPICapabilities.test_set_api_version_selects_latest_available_when_unspecified -v`

Expected: PASS.

- [ ] **Step 6: Add REST metadata miss and selected array write tests**

Add to `TestXPRestAPIGetRestMeta`:

```python
def test_get_rest_meta_returns_none_for_empty_metadata(self):
    api = self.make_api()
    dataref = Dataref(path="sim/test/value", api=api)
    api.session.get.return_value = mock_response(200, {"data": []})

    with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
        self.assertIsNone(api.get_rest_meta(dataref))
```

Add to `TestXPRestAPIWriteDataref`:

```python
def test_write_dataref_rejects_missing_new_value(self):
    api = self.make_api()
    dataref = self.make_dataref(api)

    with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
        self.assertFalse(api.write_dataref(dataref))

    api.session.patch.assert_not_called()


def test_write_dataref_selected_array_element_adds_index_to_url(self):
    api = self.make_api()
    dataref = Dataref(path="sim/test/array[2]", api=api)
    dataref._cached_meta = DatarefMeta(name=dataref.path, value_type=DATAREF_DATATYPE.FLOATARRAY.value, is_writable=True, id=31)
    dataref.value = 8.5
    api.session.patch.return_value = mock_response(200, {"result": "ok"})

    with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
        self.assertTrue(api.write_dataref(dataref))

    url = api.session.patch.call_args.args[0]
    self.assertTrue(url.endswith("/datarefs/31/value?index=2"))
```

- [ ] **Step 7: Add cache lifecycle tests**

Add this class:

```python
class TestXPRestAPICaches(RestAPITestCase):
    def test_invalidate_caches_clears_loaded_caches(self):
        api = self.make_api()
        api.all_datarefs = DatarefCache(api)
        api.all_commands = MagicMock()

        api.invalidate_caches()

        self.assertIsNone(api.all_datarefs)
        self.assertIsNone(api.all_commands)

    def test_get_dataref_meta_by_id_returns_none_without_cache(self):
        api = self.make_api()

        self.assertIsNone(api.get_dataref_meta_by_id(99))
        self.assertIsNone(api.get_dataref_meta_by_name("sim/test/value"))
```

- [ ] **Step 8: Add async REST helper parity smoke test**

Add this method to `TestAsyncXPRestAPIDatarefValue`:

```python
async def test_shared_mock_response_supports_async_rest(self):
    api = self.make_api()
    dataref = self.make_dataref(api)
    api.session.get.side_effect = [mock_response(200, {"data": 1}), mock_response(200, {"data": 77})]

    self.assertEqual(await api.dataref_value(dataref), 77)
```

- [ ] **Step 9: Run targeted REST tests**

Run: `uv run python -m unittest tests.test_rest tests.test_async_rest -v`

Expected: all REST and async REST tests pass.

- [ ] **Step 10: Commit REST coverage and latest-version fix**

```powershell
git add xpwebapi/rest.py tests/test_rest.py tests/test_async_rest.py
git commit -m "fix: cover rest api version selection"
```
