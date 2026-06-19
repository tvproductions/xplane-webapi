import unittest

from xpwebapi.exceptions import (
    XPWebAPIError,
    XPConnectionError,
    XPBeaconError,
    XPTimeoutError,
    XPVersionError,
)


class TestExceptionHierarchy(unittest.TestCase):
    def test_base_is_exception(self):
        self.assertTrue(issubclass(XPWebAPIError, Exception))

    def test_connection_error_is_xpwebapi_error(self):
        self.assertTrue(issubclass(XPConnectionError, XPWebAPIError))

    def test_beacon_error_is_connection_error(self):
        self.assertTrue(issubclass(XPBeaconError, XPConnectionError))

    def test_timeout_error_is_xpwebapi_error(self):
        self.assertTrue(issubclass(XPTimeoutError, XPWebAPIError))

    def test_version_error_is_xpwebapi_error(self):
        self.assertTrue(issubclass(XPVersionError, XPWebAPIError))

    def test_context_kwargs(self):
        err = XPWebAPIError("boom", host="127.0.0.1", port=8086)
        self.assertEqual(str(err), "boom")
        self.assertEqual(err.context, {"host": "127.0.0.1", "port": 8086})

    def test_context_empty_by_default(self):
        err = XPWebAPIError("oops")
        self.assertEqual(err.context, {})

    def test_beacon_error_context(self):
        err = XPBeaconError("no beacon", timeout=3.0)
        self.assertEqual(err.context, {"timeout": 3.0})
        self.assertIsInstance(err, XPConnectionError)

    def test_timeout_error_context(self):
        err = XPTimeoutError("timed out", host="10.0.0.1")
        self.assertEqual(err.context, {"host": "10.0.0.1"})

    def test_version_error_context(self):
        err = XPVersionError("unsupported", version="10.40")
        self.assertEqual(err.context, {"version": "10.40"})

    def test_catch_base_catches_all(self):
        for cls in (XPConnectionError, XPBeaconError, XPTimeoutError, XPVersionError):
            with self.assertRaises(XPWebAPIError):
                raise cls("test")


if __name__ == "__main__":
    unittest.main()
