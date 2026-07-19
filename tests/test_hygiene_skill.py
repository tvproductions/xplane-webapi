"""Contract tests for the repository hygiene skill."""

from __future__ import annotations

import importlib.util
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".codex" / "skills" / "hygiene" / "scripts" / "hygiene.py"


def load_hygiene_module():
    spec = importlib.util.spec_from_file_location("xplane_webapi_hygiene", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def dependency_payload(*, stale: bool = True) -> dict[str, object]:
    packaging = {
        "name": "packaging",
        "version": "25.0",
        "kind": "package",
    }
    coverage = {
        "name": "coverage",
        "version": "7.14.1",
        "kind": "package",
    }
    if stale:
        packaging["latest_version"] = "26.2"
        coverage["latest_version"] = "7.15.2"

    return {
        "roots": ["project:dev", "project"],
        "resolution": {
            "project": {
                "name": "xpwebapi",
                "kind": "package",
                "dependencies": [{"id": "packaging"}],
            },
            "project:dev": {
                "name": "xpwebapi",
                "kind": {"group": "dev"},
                "dependencies": [{"id": "coverage"}],
            },
            "packaging": packaging,
            "coverage": coverage,
        },
    }


class HygieneSkillTests(unittest.TestCase):
    def test_local_hygiene_runs_full_deterministic_sequence(self) -> None:
        hygiene = load_hygiene_module()
        runner = MagicMock(return_value=SimpleNamespace(returncode=0))

        result = hygiene.run_local_hygiene(runner=runner)

        self.assertEqual(result, 0)
        self.assertEqual(
            [call.args[0] for call in runner.call_args_list],
            [
                ("git", "status", "--short", "--branch"),
                ("uv", "lock", "--check", "--offline"),
                ("uv", "run", "python", "tools/quality.py", "check"),
                ("uv", "run", "python", "tools/quality.py", "pre-commit"),
            ],
        )

    def test_local_hygiene_stops_on_first_failure(self) -> None:
        hygiene = load_hygiene_module()
        runner = MagicMock(
            side_effect=[
                SimpleNamespace(returncode=0),
                SimpleNamespace(returncode=7),
                SimpleNamespace(returncode=0),
            ]
        )

        result = hygiene.run_local_hygiene(runner=runner)

        self.assertEqual(result, 7)
        self.assertEqual(runner.call_count, 2)

    def test_dependency_parser_classifies_runtime_and_development_drift(self) -> None:
        hygiene = load_hygiene_module()

        outdated = hygiene.find_outdated_dependencies(dependency_payload())

        self.assertEqual(
            [(item.name, item.current, item.latest, item.group) for item in outdated],
            [
                ("coverage", "7.14.1", "7.15.2", "development"),
                ("packaging", "25.0", "26.2", "runtime"),
            ],
        )

    def test_dependency_parser_accepts_current_direct_dependencies(self) -> None:
        hygiene = load_hygiene_module()

        self.assertEqual(hygiene.find_outdated_dependencies(dependency_payload(stale=False)), [])

    def test_dependency_audit_distinguishes_registry_failure_from_drift(self) -> None:
        hygiene = load_hygiene_module()
        registry_runner = MagicMock(return_value=SimpleNamespace(returncode=9, stdout="", stderr="registry unavailable"))

        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            result = hygiene.audit_dependencies(runner=registry_runner)

        self.assertEqual(result, 9)
        self.assertIn("registry unavailable", stderr.getvalue())

    def test_dependency_audit_fails_when_direct_dependencies_are_stale(self) -> None:
        hygiene = load_hygiene_module()
        import json

        runner = MagicMock(
            return_value=SimpleNamespace(
                returncode=0,
                stdout=json.dumps(dependency_payload()),
                stderr="",
            )
        )

        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            result = hygiene.audit_dependencies(runner=runner)

        self.assertEqual(result, 1)
        self.assertIn("development: coverage 7.14.1 -> 7.15.2", stdout.getvalue())
        self.assertIn("runtime: packaging 25.0 -> 26.2", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
