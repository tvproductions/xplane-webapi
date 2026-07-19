import struct
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from tests.helpers import make_rref_packet
from xpwebapi.api import Command, Dataref
from xpwebapi.exceptions import XPPacketError, XPReadOnlyViolation
from xpwebapi.read_only import _ReadOnlyDatagramSocketProxy
from xpwebapi import udp as udp_module
from xpwebapi.udp import XPUDPAPI, XPlaneTimeout


class UDPAPITestCase(unittest.TestCase):
    def make_api(self):
        with patch("xpwebapi.udp.socket.socket"):
            api = XPUDPAPI(host="127.0.0.1", port=49000)
        api.socket = MagicMock()
        self.addCleanup(lambda api=api: api.datarefs.clear())
        return api


class TestReadOnlyDatagramSocketProxy(unittest.TestCase):
    def test_accepts_rref_and_rejects_dref_and_cmnd(self):
        raw_socket = MagicMock()
        raw_socket.sendto.return_value = 413
        destination = ("127.0.0.1", 49000)
        proxy = _ReadOnlyDatagramSocketProxy(raw_socket, destination)
        rref = struct.pack("<5sii400s", b"RREF\x00", 1, 0, b"sim/test/value")

        self.assertEqual(proxy.sendto(rref, destination), 413)
        for packet in (b"DREF\x00", b"CMND\x00sim/test/command"):
            with self.subTest(packet=packet):
                with self.assertRaises(XPReadOnlyViolation):
                    proxy.sendto(packet, destination)

        raw_socket.sendto.assert_called_once_with(rref, destination)

    def test_rejects_malformed_rref_packets(self):
        raw_socket = MagicMock()
        destination = ("127.0.0.1", 49000)
        proxy = _ReadOnlyDatagramSocketProxy(raw_socket, destination)
        malformed = (
            struct.pack("<5sii400s", b"RREF\x00", -1, 0, b"sim/test/value"),
            struct.pack("<5sii400s", b"RREF\x00", 1, -1, b"sim/test/value"),
            struct.pack("<5sii400s", b"RREF\x00", 1, 0, b""),
            struct.pack("<5sii400s", b"RREF\x00", 1, 0, b"sim/test/value\x00garbage"),
        )

        for packet in malformed:
            with self.subTest(packet=packet[:20]):
                with self.assertRaises(XPReadOnlyViolation):
                    proxy.sendto(packet, destination)

        raw_socket.sendto.assert_not_called()


class TestXPUDPAPIWriteDataref(UDPAPITestCase):
    def test_read_only_udp_rejects_high_level_dref_and_cmnd(self):
        raw_socket = MagicMock()
        with patch("xpwebapi.udp.socket.socket", return_value=raw_socket):
            api = XPUDPAPI(host="127.0.0.1", port=49000, read_only=True)
        dataref = Dataref(path="sim/test/value", api=api)
        dataref.value = 3.5
        command = Command(path="sim/test/command", api=api)

        with self.assertRaises(XPReadOnlyViolation):
            api.write_dataref(dataref)
        with self.assertRaises(XPReadOnlyViolation):
            api.execute_command(command)

        raw_socket.sendto.assert_not_called()

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


class TestXPUDPAPIConnectionProbe(UDPAPITestCase):
    def test_simple_connection_probe_skips_reuseport_when_constant_missing(self):
        api = self.make_api()
        probe_socket = MagicMock()
        probe_socket.recvfrom.side_effect = udp_module.socket.timeout
        had_reuseport = hasattr(udp_module.socket, "SO_REUSEPORT")
        reuseport = getattr(udp_module.socket, "SO_REUSEPORT", None)
        if had_reuseport:
            delattr(udp_module.socket, "SO_REUSEPORT")
            self.addCleanup(setattr, udp_module.socket, "SO_REUSEPORT", reuseport)

        with patch("xpwebapi.udp.socket.socket", return_value=probe_socket):
            self.assertFalse(api.simple_connection_probe())

        for call in probe_socket.setsockopt.call_args_list:
            self.assertNotEqual(call.args[0], udp_module.socket.SOL_SOCKET)


class TestXPUDPAPIShutdown(UDPAPITestCase):
    def test_stop_rejects_invalid_timeout_before_side_effects(self):
        invalid_timeouts = (-1.0, float("nan"), float("inf"), float("-inf"))

        for timeout_seconds in invalid_timeouts:
            with self.subTest(timeout_seconds=timeout_seconds):
                api = self.make_api()
                api.udp_lsnr_not_running = MagicMock()
                api.udp_lsnr_not_running.is_set.return_value = False
                api.udp_thread = MagicMock()

                with self.assertRaises(ValueError):
                    api.stop(timeout_seconds=timeout_seconds)

                api.udp_lsnr_not_running.set.assert_not_called()
                api.udp_thread.join.assert_not_called()

    def test_stop_accepts_zero_timeout(self):
        api = self.make_api()
        api.udp_lsnr_not_running = MagicMock()
        api.udp_lsnr_not_running.is_set.return_value = False
        api.udp_thread = MagicMock()
        api.udp_thread.is_alive.side_effect = [True, False]

        api.stop(timeout_seconds=0.0)

        api.udp_thread.join.assert_called_once_with(0.0)

    def test_stop_rejects_invalid_resolved_default_before_side_effects(self):
        api = self.make_api()
        api.udp_lsnr_not_running = MagicMock()
        api.udp_lsnr_not_running.is_set.return_value = False

        with patch.object(udp_module, "BEACON_TIMEOUT", float("nan")):
            with self.assertRaises(ValueError):
                api.stop()

        api.udp_lsnr_not_running.set.assert_not_called()

    def test_stop_uses_supplied_timeout(self):
        api = self.make_api()
        api.udp_lsnr_not_running = MagicMock()
        api.udp_lsnr_not_running.is_set.return_value = False
        api.udp_thread = MagicMock()
        api.udp_thread.is_alive.side_effect = [True, False]

        api.stop(timeout_seconds=0.75)

        api.udp_thread.join.assert_called_once_with(0.75)

    def test_stop_retains_default_timeout(self):
        api = self.make_api()
        api.udp_lsnr_not_running = MagicMock()
        api.udp_lsnr_not_running.is_set.return_value = False
        api.udp_thread = MagicMock()
        api.udp_thread.is_alive.side_effect = [True, False]

        api.stop()

        api.udp_thread.join.assert_called_once_with(udp_module.BEACON_TIMEOUT)


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
    def test_monitor_dataref_uses_requested_frequency(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)

        with patch.object(XPUDPAPI, "connected", new_callable=PropertyMock, return_value=True):
            self.assertTrue(api.monitor_dataref(dataref, frequency_hz=4))

        message, _address = api.socket.sendto.call_args.args
        _header, frequency, _index, _path = struct.unpack("<5sii400s", message)
        self.assertEqual(frequency, 4)

    def test_monitor_dataref_rejects_non_integral_frequency(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)

        for frequency in (1.5, True, 0, -1):
            with self.subTest(frequency=frequency):
                with self.assertRaises(ValueError):
                    api.monitor_dataref(dataref, frequency_hz=frequency)

        api.socket.sendto.assert_not_called()

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

    def test_monitor_dataref_treats_zero_request_id_as_success(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)

        with patch.object(api, "_request_dataref", return_value=0):
            self.assertEqual(api.monitor_dataref(dataref), 0)

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

    def test_unmonitor_datarefs_treats_zero_request_id_as_success(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)
        dataref.inc_monitor()

        with patch.object(api, "_request_dataref", return_value=0):
            result, effectives = api.unmonitor_datarefs({dataref.path: dataref})

        self.assertTrue(result)
        self.assertEqual(effectives, {})
        self.assertEqual(dataref.monitored_count, 0)
        self.assertFalse(dataref.is_monitored)

    def test_unmonitor_datarefs_decrements_nested_monitor_before_unsubscribe(self):
        api = self.make_api()
        dataref = Dataref(path="sim/test/value", api=api)

        with patch.object(XPUDPAPI, "connected", new_callable=PropertyMock, return_value=True):
            api.monitor_dataref(dataref)
            api.monitor_dataref(dataref)

            api.socket.sendto.reset_mock()
            result, effectives = api.unmonitor_datarefs({dataref.path: dataref})

            self.assertTrue(result)
            self.assertEqual(effectives, {})
            self.assertEqual(dataref.monitored_count, 1)
            self.assertTrue(dataref.is_monitored)
            self.assertIn(dataref.path, api.datarefs.values())
            api.socket.sendto.assert_not_called()

            result, effectives = api.unmonitor_datarefs({dataref.path: dataref})

        self.assertTrue(result)
        self.assertEqual(effectives, {})
        self.assertEqual(dataref.monitored_count, 0)
        self.assertFalse(dataref.is_monitored)
        self.assertNotIn(dataref.path, api.datarefs.values())
        api.socket.sendto.assert_called_once()

        message, address = api.socket.sendto.call_args.args
        self.assertEqual(address, ("127.0.0.1", 49000))
        self.assertTrue(message.startswith(b"RREF\x00"))


if __name__ == "__main__":
    unittest.main()
