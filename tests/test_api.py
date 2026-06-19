import base64
import unittest
from unittest.mock import MagicMock

from xpwebapi.api import (
    API,
    DATAREF_DATATYPE,
    Cache,
    CommandCache,
    Command,
    CommandMeta,
    DatarefCache,
    Dataref,
    DatarefMeta,
    DatarefValueType,
    ValueCache,
)


def mock_response(status_code: int, payload: dict | None = None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload or {}
    return response


class DummyAPI(API):
    def __init__(self, value: DatarefValueType | bytes | None = None):
        self.meta_by_path = {}
        self.value_to_return = value
        self.written = []
        self.executed = []
        self.monitored_datarefs = []
        self.command_events = []
        super().__init__(host="127.0.0.1", port=8086, api="/api", api_version="v1")

    @property
    def connected(self) -> bool:
        return True

    def get_rest_meta(self, obj: Dataref | Command, force: bool = False) -> DatarefMeta | CommandMeta | None:
        return self.meta_by_path.get(obj.path)

    def write_dataref(self, dataref: Dataref) -> bool | int:
        self.written.append(dataref)
        return True

    def dataref_value(self, dataref: Dataref, raw: bool = False, no_decode: bool = False) -> DatarefValueType | bytes | None:
        return self.value_to_return

    def execute_command(self, command: Command, duration: float = 0.0) -> bool | int:
        self.executed.append((command, duration))
        return True

    def monitor_dataref(self, dataref: Dataref) -> bool:
        self.monitored_datarefs.append(("monitor", dataref))
        return True

    def unmonitor_dataref(self, dataref: Dataref) -> bool:
        self.monitored_datarefs.append(("unmonitor", dataref))
        return True

    def register_command_is_active_event(self, path: str, on: bool = True) -> bool:
        self.command_events.append((path, on))
        return True


class TestDatarefMeta(unittest.TestCase):
    def test_construction(self):
        meta = DatarefMeta(name="sim/test/value", value_type="int", is_writable=True, id=42)
        self.assertEqual(meta.name, "sim/test/value")
        self.assertEqual(meta.value_type, "int")
        self.assertTrue(meta.is_writable)
        self.assertEqual(meta.ident, 42)

    def test_is_array_for_array_types(self):
        int_array = DatarefMeta(name="sim/test/int_array", value_type=DATAREF_DATATYPE.INTARRAY.value, is_writable=False, id=1)
        float_array = DatarefMeta(name="sim/test/float_array", value_type=DATAREF_DATATYPE.FLOATARRAY.value, is_writable=False, id=2)
        scalar = DatarefMeta(name="sim/test/scalar", value_type=DATAREF_DATATYPE.FLOAT.value, is_writable=False, id=3)
        self.assertTrue(int_array.is_array)
        self.assertTrue(float_array.is_array)
        self.assertFalse(scalar.is_array)

    def test_indices_are_unique_and_historical(self):
        meta = DatarefMeta(name="sim/test/array", value_type="int_array", is_writable=False, id=1)
        meta.append_index(3)
        meta.append_index(1)
        meta.append_index(3)
        self.assertEqual(meta.indices, [3, 1])

        meta._indices_requested = True
        meta.save_indices()
        meta.remove_index(3)
        self.assertEqual(meta.indices, [1])
        self.assertEqual(meta.last_indices(), [3, 1])


class TestCommandMeta(unittest.TestCase):
    def test_construction(self):
        meta = CommandMeta(name="sim/test/command", description="Test command", id=99)
        self.assertEqual(meta.name, "sim/test/command")
        self.assertEqual(meta.description, "Test command")
        self.assertEqual(meta.ident, 99)


class TestValueCache(unittest.TestCase):
    def test_get_rounding_supports_plain_root_and_wildcard(self):
        cache = ValueCache({"sim/test/plain": 2, "sim/test/root": 3, "sim/test/wild[*]": 1})
        self.assertEqual(cache.get_rounding("sim/test/plain"), 2)
        self.assertEqual(cache.get_rounding("sim/test/root[4]"), 3)
        self.assertEqual(cache.get_rounding("sim/test/wild[7]"), 1)
        self.assertIsNone(cache.get_rounding("sim/test/missing"))

    def test_changed_tracks_rounded_numeric_values(self):
        cache = ValueCache({"sim/test/value": 2})
        self.assertTrue(cache.changed("sim/test/value", 3.14159))
        self.assertFalse(cache.changed("sim/test/value", 3.14))
        self.assertTrue(cache.changed("sim/test/value", 3.15))

    def test_changed_returns_true_for_non_numeric_values(self):
        cache = ValueCache({"sim/test/value": 2})
        self.assertTrue(cache.changed("sim/test/value", "hello"))


class TestDatarefCache(unittest.TestCase):
    def test_meta_factory_creates_dataref_meta(self):
        meta = DatarefCache.meta(name="sim/test/value", value_type="int", is_writable=True, id=1)
        self.assertIsInstance(meta, DatarefMeta)
        self.assertEqual(meta.name, "sim/test/value")
        self.assertEqual(meta.value_type, "int")
        self.assertTrue(meta.is_writable)

    def test_lookup_by_name_and_id(self):
        cache = DatarefCache(DummyAPI())
        meta = DatarefMeta(name="sim/test/value", value_type="int", is_writable=True, id=7)
        cache._by_name = {meta.name: meta}
        cache._by_ids = {meta.ident: meta}
        self.assertIs(cache.get("sim/test/value"), meta)
        self.assertIs(cache.get_by_name("sim/test/value"), meta)
        self.assertIs(cache.get_by_id(7), meta)
        self.assertIsNone(cache.get_by_name("sim/test/missing"))
        self.assertIsNone(cache.get_by_id(99))
        self.assertEqual(cache.count, 1)
        self.assertTrue(cache.has_data)
        self.assertEqual(cache.equiv(7), "7(sim/test/value)")

    def test_load_uses_datarefs_endpoint(self):
        api = DummyAPI()
        api.session = MagicMock()
        api.session.get.return_value = mock_response(200, {"data": [{"name": "sim/test/value", "value_type": "int", "is_writable": True, "id": 7}]})
        cache = DatarefCache(api)
        cache.load()
        api.session.get.assert_called_once_with(f"{api.rest_url}/datarefs")
        self.assertIsInstance(cache.get_by_name("sim/test/value"), DatarefMeta)

    def test_failed_load_leaves_cache_empty(self):
        api = DummyAPI()
        api.session = MagicMock()
        api.session.get.return_value = mock_response(500)
        cache = DatarefCache(api)
        cache.load()
        self.assertEqual(cache.count, 0)
        self.assertFalse(cache.has_data)


class TestCommandCache(unittest.TestCase):
    def test_meta_factory_creates_command_meta(self):
        meta = CommandCache.meta(name="sim/test/command", description="Test command", id=2)
        self.assertIsInstance(meta, CommandMeta)
        self.assertEqual(meta.name, "sim/test/command")
        self.assertEqual(meta.description, "Test command")

    def test_lookup_by_name_and_id(self):
        cache = CommandCache(DummyAPI())
        meta = CommandMeta(name="sim/test/command", description="Test command", id=8)
        cache._by_name = {meta.name: meta}
        cache._by_ids = {meta.ident: meta}
        self.assertIs(cache.get("sim/test/command"), meta)
        self.assertIs(cache.get_by_name("sim/test/command"), meta)
        self.assertIs(cache.get_by_id(8), meta)
        self.assertIsNone(cache.get_by_name("sim/test/missing"))
        self.assertIsNone(cache.get_by_id(99))
        self.assertEqual(cache.count, 1)
        self.assertTrue(cache.has_data)
        self.assertEqual(cache.equiv(8), "8(sim/test/command)")

    def test_load_uses_commands_endpoint(self):
        api = DummyAPI()
        api.session = MagicMock()
        api.session.get.return_value = mock_response(200, {"data": [{"name": "sim/test/command", "description": "Test command", "id": 8}]})
        cache = CommandCache(api)
        cache.load()
        api.session.get.assert_called_once_with(f"{api.rest_url}/commands")
        self.assertIsInstance(cache.get_by_name("sim/test/command"), CommandMeta)


class TestCacheCompatibility(unittest.TestCase):
    def test_meta_factory_keeps_old_dataref_heuristic(self):
        meta = Cache.meta(name="sim/test/value", value_type="int", is_writable=True, id=1)
        self.assertIsInstance(meta, DatarefMeta)

    def test_meta_factory_keeps_old_command_heuristic(self):
        meta = Cache.meta(name="sim/test/command", description="Test command", id=2)
        self.assertIsInstance(meta, CommandMeta)

    def test_load_accepts_old_path_argument(self):
        api = DummyAPI()
        api.session = MagicMock()
        api.session.get.return_value = mock_response(200, {"data": [{"name": "sim/test/value", "value_type": "int", "is_writable": True, "id": 7}]})
        cache = Cache(api)
        cache.load("/datarefs")
        api.session.get.assert_called_once_with(f"{api.rest_url}/datarefs")
        self.assertIsInstance(cache.get_by_name("sim/test/value"), DatarefMeta)


class TestDataref(unittest.TestCase):
    def test_value_reads_from_api_when_no_local_value_exists(self):
        api = DummyAPI(value=12)
        dataref = Dataref(path="sim/test/value", api=api)
        self.assertEqual(dataref.value, 12)

    def test_setting_value_updates_local_value_and_timestamp(self):
        api = DummyAPI()
        dataref = Dataref(path="sim/test/value", api=api)
        before = dataref.last_updated
        dataref.value = 34
        self.assertEqual(dataref.value, 34)
        self.assertGreaterEqual(dataref.last_updated, before)

    def test_auto_save_writes_on_value_change(self):
        api = DummyAPI()
        dataref = Dataref(path="sim/test/value", api=api, auto_save=True)
        dataref.value = 56
        self.assertEqual(api.written, [dataref])

    def test_parse_scalar_value(self):
        api = DummyAPI()
        api.meta_by_path["sim/test/value"] = DatarefMeta(name="sim/test/value", value_type="int", is_writable=False, id=1)
        dataref = Dataref(path="sim/test/value", api=api)
        self.assertEqual(dataref.parse_raw_value(42), 42)

    def test_parse_data_value_decodes_base64(self):
        api = DummyAPI()
        api.meta_by_path["sim/test/data"] = DatarefMeta(name="sim/test/data", value_type=DATAREF_DATATYPE.DATA.value, is_writable=False, id=1)
        dataref = Dataref(path="sim/test/data", api=api)
        raw = base64.b64encode(b"abc").decode("ascii")
        self.assertEqual(dataref.parse_raw_value(raw), b"abc")

    def test_parse_array_element_uses_requested_indices(self):
        api = DummyAPI()
        meta = DatarefMeta(name="sim/test/array", value_type=DATAREF_DATATYPE.FLOATARRAY.value, is_writable=False, id=1)
        meta.append_index(0)
        meta.append_index(2)
        api.meta_by_path["sim/test/array"] = meta
        dataref = Dataref(path="sim/test/array[2]", api=api)
        self.assertEqual(dataref.parse_raw_value([10.0, 20.0]), 20.0)

    def test_parse_whole_array_when_no_indices_requested(self):
        api = DummyAPI()
        api.meta_by_path["sim/test/array"] = DatarefMeta(name="sim/test/array", value_type=DATAREF_DATATYPE.FLOATARRAY.value, is_writable=False, id=1)
        dataref = Dataref(path="sim/test/array", api=api)
        self.assertEqual(dataref.parse_raw_value([1.0, 2.0]), [1.0, 2.0])

    def test_write_monitor_and_unmonitor_delegate_to_api(self):
        api = DummyAPI()
        dataref = Dataref(path="sim/test/value", api=api)
        self.assertTrue(dataref.write())
        self.assertTrue(dataref.monitor())
        self.assertTrue(dataref.unmonitor())
        self.assertEqual(api.written, [dataref])
        self.assertEqual(api.monitored_datarefs, [("monitor", dataref), ("unmonitor", dataref)])


class TestCommand(unittest.TestCase):
    def test_execute_delegates_to_api(self):
        api = DummyAPI()
        command = Command(path="sim/test/command", api=api)
        self.assertTrue(command.execute(duration=1.5))
        self.assertEqual(api.executed, [(command, 1.5)])

    def test_monitor_and_unmonitor_delegate_to_api(self):
        api = DummyAPI()
        command = Command(path="sim/test/command", api=api)
        self.assertTrue(command.monitor())
        self.assertTrue(command.unmonitor())
        self.assertEqual(api.command_events, [("sim/test/command", True), ("sim/test/command", False)])


if __name__ == "__main__":
    unittest.main()
