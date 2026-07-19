"""Contract tests for the repository hygiene skill."""

from __future__ import annotations

import importlib.util
import io
import re
import sys
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".codex" / "skills" / "hygiene" / "scripts" / "hygiene.py"


def direct_dependency_names(requirements: list[str]) -> list[str]:
    """Return normalized direct dependency names from PEP 508 requirements."""
    names = []
    for requirement in requirements:
        match = re.match(r"[A-Za-z0-9_.-]+", requirement)
        if match is None:
            raise ValueError(f"Invalid direct dependency requirement: {requirement}")
        names.append(match.group(0))
    return names


def load_hygiene_module():
    spec = importlib.util.spec_from_file_location("xplane_webapi_hygiene", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def dependency_payload(*, stale: bool = True) -> dict[str, Any]:
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
        "roots": [{"id": "project:dev"}, {"id": "project"}],
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
    def test_skill_uses_script_as_canonical_full_strength_workflow(self) -> None:
        skill = (ROOT / ".codex" / "skills" / "hygiene" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn(
            "uv run python .codex/skills/hygiene/scripts/hygiene.py",
            skill,
        )
        self.assertIn(
            "uv run python .codex/skills/hygiene/scripts/hygiene.py --dependencies",
            skill,
        )
        self.assertIn("full-strength", skill)
        self.assertIn("stdlib `unittest` only", skill)

    def test_dependabot_config_matches_weekly_grouped_uv_policy(self) -> None:
        config = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        with (ROOT / "pyproject.toml").open("rb") as pyproject_file:
            pyproject = tomllib.load(pyproject_file)
        runtime_names = direct_dependency_names(pyproject["project"]["dependencies"])
        development_names = direct_dependency_names(pyproject["dependency-groups"]["dev"])

        expected = """version: 2
updates:
  - package-ecosystem: "uv"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
      time: "09:00"
      timezone: "America/Chicago"
    open-pull-requests-limit: 4
    groups:
      runtime-dependencies:
        patterns:
{runtime_patterns}
      development-dependencies:
        patterns:
{development_patterns}
""".format(
            runtime_patterns="\n".join(f'          - "{name}"' for name in runtime_names),
            development_patterns="\n".join(f'          - "{name}"' for name in development_names),
        )
        self.assertEqual(config, expected)

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

    def test_dependency_parser_retains_scalar_root_compatibility(self) -> None:
        hygiene = load_hygiene_module()
        payload = dependency_payload()
        payload["roots"] = ["project:dev", "project"]

        outdated = hygiene.find_outdated_dependencies(payload)

        self.assertEqual(
            [(item.name, item.current, item.latest, item.group) for item in outdated],
            [
                ("coverage", "7.14.1", "7.15.2", "development"),
                ("packaging", "25.0", "26.2", "runtime"),
            ],
        )

    def test_dependency_parser_rejects_missing_empty_or_malformed_roots(self) -> None:
        hygiene = load_hygiene_module()

        invalid_roots = (
            None,
            [],
            "project",
            [{"id": ""}],
            [{}],
            [{"id": None}],
            [{"id": 7}],
            [42],
        )
        for roots in invalid_roots:
            with self.subTest(roots=roots), self.assertRaises(ValueError):
                payload = dependency_payload()
                if roots is None:
                    del payload["roots"]
                else:
                    payload["roots"] = roots
                hygiene.find_outdated_dependencies(payload)

    def test_dependency_parser_rejects_unresolved_roots(self) -> None:
        hygiene = load_hygiene_module()
        payload = dependency_payload()
        del payload["resolution"]["project"]

        with self.assertRaises(ValueError):
            hygiene.find_outdated_dependencies(payload)

    def test_dependency_parser_rejects_unsupported_root_kinds(self) -> None:
        hygiene = load_hygiene_module()
        invalid_kinds = (None, "workspace", {}, {"group": ""}, {"other": "dev"})

        for kind in invalid_kinds:
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                payload = dependency_payload()
                payload["resolution"]["project"]["kind"] = kind
                hygiene.find_outdated_dependencies(payload)

    def test_dependency_parser_rejects_malformed_dependency_lists(self) -> None:
        hygiene = load_hygiene_module()
        invalid_dependencies = (None, {}, "packaging")

        for dependencies in invalid_dependencies:
            with self.subTest(dependencies=dependencies), self.assertRaises(ValueError):
                payload = dependency_payload()
                payload["resolution"]["project"]["dependencies"] = dependencies
                hygiene.find_outdated_dependencies(payload)

    def test_dependency_parser_rejects_malformed_or_unresolved_dependency_references(self) -> None:
        hygiene = load_hygiene_module()
        invalid_dependencies = ([{}], [{"id": ""}], [{"id": None}], [{"id": 7}], ["packaging"])

        for dependencies in invalid_dependencies:
            with self.subTest(dependencies=dependencies), self.assertRaises(ValueError):
                payload = dependency_payload()
                payload["resolution"]["project"]["dependencies"] = dependencies
                hygiene.find_outdated_dependencies(payload)

        payload = dependency_payload()
        del payload["resolution"]["packaging"]
        with self.assertRaises(ValueError):
            hygiene.find_outdated_dependencies(payload)

    def test_dependency_parser_rejects_invalid_direct_dependency_records(self) -> None:
        hygiene = load_hygiene_module()
        invalid_updates = (
            {"name": ""},
            {"name": None},
            {"version": ""},
            {"version": None},
            {"latest_version": 26},
        )

        for update in invalid_updates:
            with self.subTest(update=update), self.assertRaises(ValueError):
                payload = dependency_payload()
                payload["resolution"]["packaging"].update(update)
                hygiene.find_outdated_dependencies(payload)

    def test_dependency_parser_rejects_payloads_without_direct_dependencies(self) -> None:
        hygiene = load_hygiene_module()
        payload = dependency_payload()
        payload["resolution"]["project"]["dependencies"] = []
        payload["resolution"]["project:dev"]["dependencies"] = []

        with self.assertRaises(ValueError):
            hygiene.find_outdated_dependencies(payload)

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

    def test_dependency_audit_reports_invalid_data_for_malformed_payloads(self) -> None:
        hygiene = load_hygiene_module()
        import json

        payload = dependency_payload()
        payload["roots"] = []
        runner = MagicMock(
            return_value=SimpleNamespace(
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
            )
        )

        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            result = hygiene.audit_dependencies(runner=runner)

        self.assertEqual(result, 2)
        self.assertIn("invalid uv dependency data", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
