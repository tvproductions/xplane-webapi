import base64
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

import httpx

from xpwebapi.api import DATAREF_DATATYPE, Command, CommandMeta, Dataref, DatarefMeta
from xpwebapi.rest import XPRestAPI


def mock_response(status_code: int, payload: dict | None = None):
    response = MagicMock()
    response.status_code = status_code
    response.reason_phrase = "OK" if status_code == 200 else "Error"
    response.text = ""
    response.json.return_value = payload or {}
    return response


class RestAPITestCase(unittest.TestCase):
    def make_api(self):
        api = XPRestAPI(host="127.0.0.1", port=8086, api="/api", api_version="v1")
        api.session = MagicMock()
        api._show_stats = False
        return api

    def make_dataref(self, api, value_type="int", is_writable=True, ident=10):
        dataref = Dataref(path="sim/test/value", api=api)
        dataref._cached_meta = DatarefMeta(name=dataref.path, value_type=value_type, is_writable=is_writable, id=ident)
        return dataref

    def make_command(self, api, ident=20):
        command = Command(path="sim/test/command", api=api)
        command._cached_meta = CommandMeta(name=command.path, description="Test command", id=ident)
        return command


class TestXPRestAPIConnected(RestAPITestCase):
    def test_connected_returns_true_for_successful_count_probe(self):
        api = self.make_api()
        api.session.get.return_value = mock_response(200, {"data": 1})
        self.assertTrue(api.connected)
        self.assertEqual(api._unreach_count, 0)

    def test_connected_returns_false_for_non_200_response(self):
        api = self.make_api()
        api.session.get.return_value = mock_response(503)
        self.assertFalse(api.connected)

    def test_connected_returns_false_for_connect_error(self):
        api = self.make_api()
        api.session.get.side_effect = httpx.ConnectError("failed")
        self.assertFalse(api.connected)


class TestXPRestAPIGetRestMeta(RestAPITestCase):
    def test_get_rest_meta_returns_cached_meta(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertIs(api.get_rest_meta(dataref), dataref._cached_meta)
        api.session.get.assert_not_called()

    def test_get_rest_meta_fetches_dataref_meta(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)
        api.session.get.return_value = mock_response(200, {"data": [{"name": dataref.path, "value_type": "int", "is_writable": True, "id": 7}]})
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            meta = api.get_rest_meta(dataref)
        self.assertIsInstance(meta, DatarefMeta)
        self.assertEqual(meta.ident, 7)
        self.assertIs(dataref._cached_meta, meta)

    def test_get_rest_meta_fetches_command_meta(self):
        api = self.make_api()
        command = Command(path="sim/test/command", api=api)
        api.session.get.return_value = mock_response(200, {"data": [{"name": command.path, "description": "Test command", "id": 8}]})
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            meta = api.get_rest_meta(command)
        self.assertIsInstance(meta, CommandMeta)
        self.assertEqual(meta.ident, 8)
        self.assertIs(command._cached_meta, meta)


class TestXPRestAPIDatarefValue(RestAPITestCase):
    def test_dataref_value_returns_scalar(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        api.session.get.return_value = mock_response(200, {"data": 42})
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertEqual(api.dataref_value(dataref), 42)

    def test_dataref_value_decodes_base64_string(self):
        api = self.make_api()
        dataref = self.make_dataref(api, value_type=DATAREF_DATATYPE.DATA.value)
        encoded = base64.b64encode(b"abc").decode("ascii")
        api.session.get.return_value = mock_response(200, {"data": encoded})
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertEqual(api.dataref_value(dataref), b"abc")

    def test_dataref_value_raw_returns_encoded_string(self):
        api = self.make_api()
        dataref = self.make_dataref(api, value_type=DATAREF_DATATYPE.DATA.value)
        encoded = base64.b64encode(b"abc").decode("ascii")
        api.session.get.return_value = mock_response(200, {"data": encoded})
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertEqual(api.dataref_value(dataref, raw=True), encoded)

    def test_dataref_value_returns_none_when_not_connected(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=False):
            self.assertIsNone(api.dataref_value(dataref))

    def test_dataref_value_returns_none_for_error_response(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        api.session.get.return_value = mock_response(404)
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertIsNone(api.dataref_value(dataref))


class TestXPRestAPIWriteDataref(RestAPITestCase):
    def test_write_dataref_success(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        dataref.value = 99
        api.session.patch.return_value = mock_response(200, {"result": "ok"})
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertTrue(api.write_dataref(dataref))
        api.session.patch.assert_called_once()

    def test_write_dataref_rejects_unwritable_dataref(self):
        api = self.make_api()
        dataref = self.make_dataref(api, is_writable=False)
        dataref.value = 99
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertFalse(api.write_dataref(dataref))
        api.session.patch.assert_not_called()

    def test_write_dataref_returns_false_when_not_connected(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=False):
            self.assertFalse(api.write_dataref(dataref))

    def test_write_dataref_returns_false_for_error_response(self):
        api = self.make_api()
        dataref = self.make_dataref(api)
        dataref.value = 99
        api.session.patch.return_value = mock_response(400)
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertFalse(api.write_dataref(dataref))


class TestXPRestAPIExecuteCommand(RestAPITestCase):
    def test_execute_command_success(self):
        api = self.make_api()
        command = self.make_command(api)
        api.session.post.return_value = mock_response(200, {"result": "ok"})
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertTrue(api.execute_command(command))
        api.session.post.assert_called_once()

    def test_execute_command_uses_command_duration(self):
        api = self.make_api()
        command = self.make_command(api)
        command.duration = 2.5
        api.session.post.return_value = mock_response(200, {"result": "ok"})
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertTrue(api.execute_command(command))
        payload = api.session.post.call_args.kwargs["json"]
        self.assertEqual(payload["duration"], 2.5)

    def test_execute_command_returns_false_when_not_connected(self):
        api = self.make_api()
        command = self.make_command(api)
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=False):
            self.assertFalse(api.execute_command(command))

    def test_execute_command_returns_false_for_error_response(self):
        api = self.make_api()
        command = self.make_command(api)
        api.session.post.return_value = mock_response(500, {"error": "boom"})
        with patch.object(XPRestAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertFalse(api.execute_command(command))


if __name__ == "__main__":
    unittest.main()
