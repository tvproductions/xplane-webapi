import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from tests.helpers import make_rref_packet
from xpwebapi.api import Command, Dataref
from xpwebapi.exceptions import XPPacketError
from xpwebapi.udp import XPUDPAPI, XPlaneTimeout


class UDPAPITestCase(unittest.TestCase):
    def make_api(self):
        with patch("xpwebapi.udp.socket.socket"):
            api = XPUDPAPI(host="127.0.0.1", port=49000)
        api.socket = MagicMock()
        self.addCleanup(lambda api=api: api.datarefs.clear())
        return api


class TestXPUDPAPIWriteDataref(UDPAPITestCase):
    def test_context_manager_stops_monitored_datarefs_and_closes_socket(self):
        api = self.make_api()
        api.datarefs = {0: "sim/test/value"}

        with patch.object(XPUDPAPI, "connected", new_callable=PropertyMock, return_value=True):
            with api as active:
                self.assertIs(active, api)

        api.socket.close.assert_called_once()
        self.assertEqual(api.datarefs, {})

    def test_write_dataref_sends_dref_packet(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)
        dataref.value = 3.5

        self.assertTrue(api.write_dataref(dataref))

        message, address = api.socket.sendto.call_args.args
        self.assertEqual(address, ("127.0.0.1", 49000))
        self.assertTrue(message.startswith(b"DREF\x00"))
        self.assertEqual(len(message), 509)

    def test_write_dataref_sends_packet_without_connection_probe(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)
        dataref.value = 1.25

        self.assertTrue(api.write_dataref(dataref))
        api.socket.sendto.assert_called_once()

    def test_write_dataref_raises_packet_error_for_invalid_dref_length(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)
        dataref.value = 3.5

        with patch("xpwebapi.udp.struct.pack", return_value=b"bad"):
            with self.assertRaises(XPPacketError) as caught:
                api.write_dataref(dataref)

        self.assertEqual(str(caught.exception), "invalid DREF packet length")
        self.assertEqual(caught.exception.context["packet_type"], "DREF")
        self.assertEqual(caught.exception.context["expected"], 509)
        self.assertEqual(caught.exception.context["actual"], 3)


class TestXPUDPAPIExecuteCommand(UDPAPITestCase):
    def test_execute_command_sends_cmnd_packet(self):
        api = self.make_api()
        command = Command(path="sim/test/command", api=api)

        self.assertTrue(api.execute_command(command))

        message, address = api.socket.sendto.call_args.args
        self.assertEqual(address, ("127.0.0.1", 49000))
        self.assertTrue(message.startswith(b"CMND\x00"))

    def test_execute_command_ignores_duration_for_udp_packet(self):
        api = self.make_api()
        command = Command(path="sim/test/command", api=api)

        self.assertTrue(api.execute_command(command, duration=2.0))

        message, _address = api.socket.sendto.call_args.args
        self.assertTrue(message.startswith(b"CMND\x00"))
        self.assertIn(b"sim/test/command", message)


class TestXPUDPAPIReadValues(UDPAPITestCase):
    def test_read_monitored_dataref_values_decodes_rref_packet(self):
        api = self.make_api()
        api.datarefs = {0: "sim/test/altitude", 1: "sim/test/speed"}
        api.socket.recvfrom.return_value = (make_rref_packet([(0, 5000.0), (1, 120.5)]), ("127.0.0.1", 49000))

        values = api.read_monitored_dataref_values()

        self.assertEqual(values["sim/test/altitude"], 5000.0)
        self.assertEqual(values["sim/test/speed"], 120.5)

    def test_read_monitored_dataref_values_normalizes_negative_zero(self):
        api = self.make_api()
        api.datarefs = {0: "sim/test/value"}
        api.socket.recvfrom.return_value = (make_rref_packet([(0, -0.0001)]), ("127.0.0.1", 49000))

        values = api.read_monitored_dataref_values()

        self.assertEqual(values["sim/test/value"], 0.0)

    def test_read_monitored_dataref_values_raises_typed_timeout(self):
        api = self.make_api()
        api.socket.recvfrom.side_effect = OSError("timeout")

        with self.assertRaises(XPlaneTimeout) as caught:
            api.read_monitored_dataref_values()

        self.assertEqual(caught.exception.context["host"], "127.0.0.1")
        self.assertEqual(caught.exception.context["port"], 49000)

    def test_dataref_value_reads_latest_monitored_value(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)
        api.datarefs = {0: dataref.path}
        api.socket.recvfrom.return_value = (make_rref_packet([(0, 42.0)]), ("127.0.0.1", 49000))

        self.assertEqual(api.dataref_value(dataref), 42.0)
        self.assertEqual(dataref.value, 42.0)


class TestXPUDPAPIRequestDataref(UDPAPITestCase):
    def test_request_dataref_sends_rref_packet(self):
        api = self.make_api()
        with patch.object(XPUDPAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertTrue(api._request_dataref("sim/test/value", freq=2))

        message, address = api.socket.sendto.call_args.args
        self.assertEqual(address, ("127.0.0.1", 49000))
        self.assertTrue(message.startswith(b"RREF\x00"))
        self.assertIn("sim/test/value", api.datarefs.values())

    def test_request_dataref_raises_packet_error_for_invalid_rref_length(self):
        api = self.make_api()
        with patch.object(XPUDPAPI, "connected", new_callable=PropertyMock, return_value=True):
            with patch("xpwebapi.udp.struct.pack", return_value=b"bad"):
                with self.assertRaises(XPPacketError) as caught:
                    api._request_dataref("sim/test/value", freq=2)

        self.assertEqual(str(caught.exception), "invalid RREF packet length")
        self.assertEqual(caught.exception.context["packet_type"], "RREF")
        self.assertEqual(caught.exception.context["expected"], 413)
        self.assertEqual(caught.exception.context["actual"], 3)

    def test_request_dataref_returns_false_when_not_connected(self):
        api = self.make_api()
        with patch.object(XPUDPAPI, "connected", new_callable=PropertyMock, return_value=False):
            self.assertFalse(api._request_dataref("sim/test/value", freq=2))

        api.socket.sendto.assert_not_called()

    def test_monitor_dataref_increments_dataref_monitor_count(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)

        with patch.object(XPUDPAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertTrue(api.monitor_dataref(dataref))

        self.assertEqual(dataref.monitored_count, 1)
        self.assertTrue(dataref.is_monitored)

    def test_unmonitor_datarefs_sends_zero_frequency_request(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)

        with patch.object(XPUDPAPI, "connected", new_callable=PropertyMock, return_value=True):
            api._request_dataref(dataref.path, freq=1)
            result, effectives = api.unmonitor_datarefs({dataref.path: dataref})

        self.assertTrue(result)
        self.assertEqual(effectives, {})
        self.assertNotIn(dataref.path, api.datarefs.values())

    def test_unmonitor_datarefs_decrements_dataref_monitor_count(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)

        with patch.object(XPUDPAPI, "connected", new_callable=PropertyMock, return_value=True):
            api.monitor_dataref(dataref)
            result, effectives = api.unmonitor_datarefs({dataref.path: dataref})

        self.assertTrue(result)
        self.assertEqual(effectives, {})
        self.assertEqual(dataref.monitored_count, 0)


if __name__ == "__main__":
    unittest.main()
