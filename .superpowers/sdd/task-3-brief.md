### Task 3: Expand Core Object And Cache Coverage

**Files:**
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: `DummyAPI`
- Consumes: `make_dataref_meta`
- Consumes: `make_command_meta`
- Produces: additional `Dataref`, `Command`, and cache edge-case tests

- [ ] **Step 1: Add imports from helpers**

Ensure `tests/test_api.py` imports:

```python
from tests.helpers import DummyAPI, encoded_data, make_command_meta, make_dataref_meta, mock_response
```

- [ ] **Step 2: Add `Dataref` indexed path and string tests**

Add these methods to `TestDataref`:

```python
def test_indexed_path_parses_base_path_and_index(self):
    api = DummyAPI()
    dataref = Dataref(path="sim/test/array[4]", api=api)

    self.assertEqual(dataref.name, "sim/test/array[4]")
    self.assertEqual(dataref.path, "sim/test/array")
    self.assertEqual(dataref.index, 4)


def test_string_representation_includes_index_and_value(self):
    api = DummyAPI()
    dataref = Dataref(path="sim/test/array[4]", api=api)
    dataref.value = 12.5

    self.assertEqual(str(dataref), "sim/test/array[4]=12.5")


def test_get_string_value_decodes_data_bytes_and_strips_nulls(self):
    api = DummyAPI(value=b"ABC\x00\x00")
    api.meta_by_path["sim/test/data"] = make_dataref_meta(name="sim/test/data", value_type=DATAREF_DATATYPE.DATA.value)
    dataref = Dataref(path="sim/test/data", api=api)

    self.assertEqual(dataref.get_string_value("ascii"), "ABC")


def test_set_string_value_encodes_data_value(self):
    api = DummyAPI()
    api.meta_by_path["sim/test/data"] = make_dataref_meta(name="sim/test/data", value_type=DATAREF_DATATYPE.DATA.value)
    dataref = Dataref(path="sim/test/data", api=api)

    dataref.set_string_value("ABC", "ascii")

    self.assertEqual(dataref.value, b"ABC")
    self.assertEqual(dataref.b64encoded, encoded_data(b"ABC"))
```

- [ ] **Step 3: Add invalid metadata and monitor counter tests**

Add these methods to `TestDataref`:

```python
def test_invalid_meta_properties_record_errors(self):
    api = DummyAPI()
    dataref = Dataref(path="sim/test/missing", api=api)

    self.assertFalse(dataref.valid)
    self.assertIsNone(dataref.ident)
    self.assertIsNone(dataref.value_type)
    self.assertFalse(dataref.is_writable)
    self.assertGreaterEqual(dataref._err, 3)


def test_monitor_counter_tracks_nested_monitoring(self):
    api = DummyAPI()
    dataref = Dataref(path="sim/test/value", api=api)

    dataref.inc_monitor()
    dataref.inc_monitor()

    self.assertTrue(dataref.is_monitored)
    self.assertEqual(dataref.monitored_count, 2)
    self.assertTrue(dataref.dec_monitor())
    self.assertFalse(dataref.dec_monitor())
    self.assertEqual(dataref.monitored_count, 0)
```

- [ ] **Step 4: Add `Command` metadata tests**

Add these methods to `TestCommand`:

```python
def test_command_metadata_properties_use_cached_meta(self):
    api = DummyAPI()
    api.meta_by_path["sim/test/command"] = make_command_meta(ident=44)
    command = Command(path="sim/test/command", api=api)

    self.assertTrue(command.valid)
    self.assertEqual(command.ident, 44)
    self.assertEqual(command.description, "Test command")


def test_command_invalid_metadata_records_errors(self):
    api = DummyAPI()
    command = Command(path="sim/test/missing", api=api)

    self.assertFalse(command.valid)
    self.assertIsNone(command.ident)
    self.assertIsNone(command.description)
    self.assertGreaterEqual(command._err, 2)
```

- [ ] **Step 5: Add cache save behavior test**

Add this import:

```python
from tempfile import TemporaryDirectory
```

Add this method to `TestDatarefCache`:

```python
def test_save_writes_loaded_metadata_json(self):
    api = DummyAPI()
    cache = DatarefCache(api)
    meta = make_dataref_meta(name="sim/test/value", ident=7)
    cache._raw = [{"name": meta.name, "value_type": meta.value_type, "is_writable": meta.is_writable, "id": meta.ident}]
    cache._by_name = {meta.name: meta}
    cache._by_ids = {meta.ident: meta}

    with TemporaryDirectory() as tmpdir:
        filename = f"{tmpdir}/datarefs.json"
        cache.save(filename)
        with open(filename, encoding="utf-8") as handle:
            content = handle.read()

    self.assertIn("sim/test/value", content)
    self.assertIn('"id": 7', content)
```

- [ ] **Step 6: Run targeted core tests**

Run: `uv run python -m unittest tests.test_api -v`

Expected: all `tests.test_api` tests pass.

- [ ] **Step 7: Commit core coverage**

```powershell
git add tests/test_api.py
git commit -m "test: expand core object coverage"
```
