import json
import logging
import sys
import unittest

from pydantic import ValidationError

from xpwebapi.logging_config import JsonLogFormatter, LoggingConfig


class TestJsonLogFormatter(unittest.TestCase):
    def test_json_formatter_emits_stable_core_fields(self):
        record = logging.LogRecord(
            name="xpwebapi.rest",
            level=logging.INFO,
            pathname="rest.py",
            lineno=188,
            msg="rest api reachable",
            args=(),
            exc_info=None,
            func="rest_api_reachable",
        )

        payload = json.loads(JsonLogFormatter().format(record))

        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["logger"], "xpwebapi.rest")
        self.assertEqual(payload["message"], "rest api reachable")
        self.assertEqual(payload["module"], "rest")
        self.assertEqual(payload["function"], "rest_api_reachable")
        self.assertEqual(payload["line"], 188)
        self.assertRegex(payload["timestamp"], r"^\d{4}-\d{2}-\d{2}T.*Z$")
        self.assertNotIn("exception", payload)

    def test_json_formatter_includes_exception_text(self):
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            exc_info = sys.exc_info()
            record = logging.getLogger("xpwebapi.rest").makeRecord(
                name="xpwebapi.rest",
                level=logging.ERROR,
                fn="rest.py",
                lno=200,
                msg="request failed",
                args=(),
                exc_info=exc_info,
                func="dataref_value",
                extra=None,
            )

        payload = json.loads(JsonLogFormatter().format(record))

        self.assertEqual(payload["level"], "ERROR")
        self.assertIn("RuntimeError: boom", payload["exception"])


class TestLoggingConfig(unittest.TestCase):
    def test_logging_config_accepts_standard_python_levels(self):
        config = LoggingConfig(
            format="json",
            level="debug",
            traffic_level="WARNING",
            components={"xpwebapi.rest": "INFO", "webapi": "ERROR"},
        )

        self.assertEqual(config.format, "json")
        self.assertEqual(config.level, "DEBUG")
        self.assertEqual(config.traffic_level, "WARNING")
        self.assertEqual(config.components["xpwebapi.rest"], "INFO")
        self.assertEqual(config.components["webapi"], "ERROR")

    def test_logging_config_rejects_unknown_level_names(self):
        with self.assertRaises(ValidationError):
            LoggingConfig(level="NOTICE")

    def test_logging_config_rejects_unrelated_component_names(self):
        with self.assertRaises(ValidationError):
            LoggingConfig(components={"urllib3": "DEBUG"})

    def test_logging_config_rejects_trailing_dot_only_component(self):
        with self.assertRaises(ValidationError):
            LoggingConfig(components={"xpwebapi.": "DEBUG"})


if __name__ == "__main__":
    unittest.main()
