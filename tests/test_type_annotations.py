import ast
import unittest
from pathlib import Path

from xpwebapi.api import API


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "xpwebapi"
LEGACY_TYPING_ALIASES = {"Dict", "List", "Optional", "Tuple"}


class TestTypeAnnotationModernization(unittest.TestCase):
    def test_api_protocol_declares_assigned_instance_members(self) -> None:
        expected = {
            "_api_root_path",
            "_api_version",
            "_roundings",
            "_show_stats",
            "_stats",
            "_status",
            "_use_cache",
            "_use_rest",
            "all_commands",
            "all_datarefs",
            "host",
            "port",
            "read_only",
            "session",
            "use_cache",
            "version",
        }

        self.assertEqual(set(API.__annotations__), expected)

    def test_source_does_not_use_legacy_collection_or_optional_aliases(self):
        offenders = []
        for filename in SOURCE_ROOT.glob("*.py"):
            tree = ast.parse(filename.read_text(encoding="utf-8"), filename=str(filename))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "typing":
                    for alias in node.names:
                        if alias.name in LEGACY_TYPING_ALIASES:
                            offenders.append(f"{filename.name}: imports typing.{alias.name}")
                if isinstance(node, ast.Name) and node.id in LEGACY_TYPING_ALIASES:
                    offenders.append(f"{filename.name}: uses {node.id}")

        self.assertEqual(offenders, [])

    def test_context_manager_enter_methods_return_self(self):
        offenders = []
        for filename in SOURCE_ROOT.glob("*.py"):
            tree = ast.parse(filename.read_text(encoding="utf-8"), filename=str(filename))
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                if node.name not in {"__enter__", "__aenter__"}:
                    continue
                if not isinstance(node.returns, ast.Name) or node.returns.id != "Self":
                    offenders.append(f"{filename.name}: {node.name}")

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
