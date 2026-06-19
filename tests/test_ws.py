import json
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from xpwebapi.api import DATAREF_DATATYPE, Command, CommandMeta, Dataref, DatarefMeta
from xpwebapi.rest import REST_KW
from xpwebapi.ws import CALLBACK_TYPE, XPWebsocketAPI


class WebsocketAPITestCase(unittest.TestCase):
    def make_api(self):
        api = XPWebsocketAPI.__new__(XPWebsocketAPI)
        api.host = "127.0.0.1"
        api.port = 8086
        api.version = "v2"
        api._api_root_path = "/api"
        api._api_version = "/v2"
        api._status = 0
        api._stats = {}
        api._show_stats = False
        api._use_rest = False
        api._use_cache = False
        api._should_use_cache = False
        api._first_try = False
        api._warning_count = 0
        api._unreach_count = 0
        api._already_warned = 0
        api.req_number = 0
        api._requests = {}
        api._dataref_by_id = {}
        api.session = MagicMock()
        api.session.get.return_value = MagicMock(status_code=503)
        api.ws = MagicMock()
        api.callbacks = {callback_type.value: set() for callback_type in CALLBACK_TYPE}
        return api


class TestXPWebsocketAPISend(WebsocketAPITestCase):
    def test_send_increments_request_ids_and_writes_json(self):
        api = self.make_api()
        with patch.object(XPWebsocketAPI, "connected", new_callable=PropertyMock, return_value=True):
            first = api.send({"type": "first"})
            second = api.send({"type": "second"})

        self.assertEqual(first, 1)
        self.assertEqual(second, 2)
        self.assertIn(first, api._requests)
        sent_payload = json.loads(api.ws.send.call_args_list[0].args[0])
        self.assertEqual(sent_payload["req_id"], 1)

    def test_send_returns_false_when_not_connected(self):
        api = self.make_api()
        with patch.object(XPWebsocketAPI, "connected", new_callable=PropertyMock, return_value=False):
            with patch("xpwebapi.ws.logger.warning"):
                self.assertFalse(api.send({"type": "test"}))
        api.ws.send.assert_not_called()

    def test_send_returns_false_for_empty_payload(self):
        api = self.make_api()
        with patch.object(XPWebsocketAPI, "connected", new_callable=PropertyMock, return_value=True):
            with patch("xpwebapi.ws.logger.warning"):
                self.assertFalse(api.send({}))
        api.ws.send.assert_not_called()


class TestXPWebsocketAPIConnect(WebsocketAPITestCase):
    @patch("xpwebapi.ws.Client.connect")
    def test_connect_websocket_success(self, mock_connect):
        api = self.make_api()
        api.ws = None
        websocket = MagicMock()
        mock_connect.return_value = websocket

        with patch.object(XPWebsocketAPI, "rest_api_reachable", new_callable=PropertyMock, return_value=True):
            with patch.object(XPWebsocketAPI, "reload_caches"):
                api.connect_websocket()

        self.assertIs(api.ws, websocket)
        mock_connect.assert_called_once_with("ws://127.0.0.1:8086/api/v2")

    @patch("xpwebapi.ws.Client.connect")
    def test_connect_websocket_does_not_connect_when_rest_unreachable(self, mock_connect):
        api = self.make_api()
        api.ws = None
        with patch.object(XPWebsocketAPI, "rest_api_reachable", new_callable=PropertyMock, return_value=False):
            with patch("xpwebapi.ws.logger.warning"):
                api.connect_websocket()
        self.assertIsNone(api.ws)
        mock_connect.assert_not_called()

    def test_disconnect_websocket_closes_socket_and_runs_callback(self):
        api = self.make_api()
        websocket = api.ws
        callback = MagicMock()
        api.add_callback(CALLBACK_TYPE.ON_CLOSE, callback)

        api.disconnect_websocket()

        websocket.close.assert_called_once()
        self.assertIsNone(api.ws)
        callback.assert_called_once()


class TestXPWebsocketAPICallbacks(WebsocketAPITestCase):
    def test_execute_callbacks_runs_registered_callbacks(self):
        api = self.make_api()
        callback = MagicMock()
        api.add_callback(CALLBACK_TYPE.ON_OPEN, callback)
        self.assertTrue(api.execute_callbacks(CALLBACK_TYPE.ON_OPEN))
        callback.assert_called_once()

    def test_execute_callbacks_returns_false_when_callback_raises(self):
        api = self.make_api()
        callback = MagicMock(side_effect=RuntimeError("boom"))
        api.add_callback(CALLBACK_TYPE.ON_OPEN, callback)
        with patch("xpwebapi.ws.logger.error"):
            self.assertFalse(api.execute_callbacks(CALLBACK_TYPE.ON_OPEN))

    def test_execute_callbacks_returns_true_when_no_callbacks_registered(self):
        api = self.make_api()
        self.assertTrue(api.execute_callbacks(CALLBACK_TYPE.ON_OPEN))


class TestXPWebsocketAPIPayloads(WebsocketAPITestCase):
    def test_set_dataref_value_sends_scalar_payload(self):
        api = self.make_api()
        meta = DatarefMeta(name="sim/test/value", value_type="float", is_writable=True, id=11)
        api.get_dataref_meta_by_name = MagicMock(return_value=meta)
        api.send = MagicMock(return_value=1)

        self.assertEqual(api.set_dataref_value("sim/test/value", 3.5), 1)

        payload = api.send.call_args.args[0]
        self.assertEqual(payload[REST_KW.TYPE.value], "dataref_set_values")
        self.assertEqual(payload[REST_KW.PARAMS.value][REST_KW.DATAREFS.value], [{"id": 11, "value": 3.5}])

    def test_set_dataref_value_sends_array_index_payload(self):
        api = self.make_api()
        meta = DatarefMeta(name="sim/test/array", value_type=DATAREF_DATATYPE.FLOATARRAY.value, is_writable=True, id=12)
        api.get_dataref_meta_by_name = MagicMock(return_value=meta)
        api.send = MagicMock(return_value=1)

        self.assertEqual(api.set_dataref_value("sim/test/array[4]", 7.5), 1)

        payload = api.send.call_args.args[0]
        entry = payload[REST_KW.PARAMS.value][REST_KW.DATAREFS.value][0]
        self.assertEqual(entry, {"id": 12, "value": 7.5, "index": 4})

    def test_register_command_is_active_event_sends_subscribe_payload(self):
        api = self.make_api()
        api.get_command_meta_by_name = MagicMock(return_value=CommandMeta(name="sim/test/command", description="Test", id=21))
        api.send = MagicMock(return_value=1)

        self.assertEqual(api.register_command_is_active_event("sim/test/command"), 1)

        payload = api.send.call_args.args[0]
        self.assertEqual(payload[REST_KW.TYPE.value], "command_subscribe_is_active")
        self.assertEqual(payload[REST_KW.PARAMS.value][REST_KW.COMMANDS.value], [{"id": 21}])

    def test_set_command_is_active_with_duration_sends_payload(self):
        api = self.make_api()
        api.get_command_meta_by_name = MagicMock(return_value=CommandMeta(name="sim/test/command", description="Test", id=22))
        api.send = MagicMock(return_value=1)

        self.assertEqual(api.set_command_is_active_with_duration("sim/test/command", duration=1.25), 1)

        payload = api.send.call_args.args[0]
        self.assertEqual(payload[REST_KW.TYPE.value], "command_set_is_active")
        self.assertEqual(payload[REST_KW.PARAMS.value][REST_KW.COMMANDS.value], [{"id": 22, "is_active": True, "duration": 1.25}])

    def test_write_dataref_uses_websocket_payload_when_rest_disabled(self):
        api = self.make_api()
        meta = DatarefMeta(name="sim/test/value", value_type="float", is_writable=True, id=23)
        dataref = Dataref(path="sim/test/value", api=api)
        dataref._cached_meta = meta
        dataref.value = 5.5
        api.get_rest_meta = MagicMock(return_value=meta)
        api.set_dataref_value = MagicMock(return_value=1)

        self.assertEqual(api.write_dataref(dataref), 1)
        api.set_dataref_value.assert_called_once_with(path="sim/test/value", value=5.5)

    def test_execute_command_uses_websocket_payload_when_rest_disabled(self):
        api = self.make_api()
        command = Command(path="sim/test/command", api=api)
        api.set_command_is_active_with_duration = MagicMock(return_value=1)

        self.assertEqual(api.execute_command(command, duration=0.5), 1)
        api.set_command_is_active_with_duration.assert_called_once_with(path="sim/test/command", duration=0.5)


if __name__ == "__main__":
    unittest.main()
