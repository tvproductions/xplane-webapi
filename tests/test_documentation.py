"""Documentation and example contract tests."""

from __future__ import annotations

import ast
from pathlib import Path
import tomllib
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"
DOCS_DIR = REPO_ROOT / "docs"


class TestExampleAnnotations(unittest.TestCase):
    def test_examples_have_function_annotations(self) -> None:
        missing: list[str] = []

        for path in sorted(EXAMPLES_DIR.glob("*.py")):
            module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(module):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    if node.returns is None:
                        missing.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} {node.name} missing return annotation")

                    arguments = [
                        *node.args.posonlyargs,
                        *node.args.args,
                        *node.args.kwonlyargs,
                    ]
                    if node.args.vararg is not None:
                        arguments.append(node.args.vararg)
                    if node.args.kwarg is not None:
                        arguments.append(node.args.kwarg)

                    for argument in arguments:
                        if argument.arg in {"self", "cls"}:
                            continue
                        if argument.annotation is None:
                            missing.append(f"{path.relative_to(REPO_ROOT)}:{argument.lineno} {node.name}.{argument.arg} missing parameter annotation")

        self.assertEqual([], missing)


class TestDocumentationContent(unittest.TestCase):
    def test_read_only_capture_usage_documents_cli_contract(self) -> None:
        usage = (DOCS_DIR / "usage" / "read-only-capture.md").read_text(encoding="utf-8")
        normalized_usage = " ".join(usage.split())

        for option in [
            "xpwebapi-capture",
            "--request",
            "--events",
            "--status",
            "--stop-file",
            "--version-json",
        ]:
            with self.subTest(option=option):
                self.assertIn(option, normalized_usage)
        self.assertIn("mutually exclusive", normalized_usage)
        self.assertIn("no network calls", normalized_usage)
        self.assertIn("no filesystem mutation", normalized_usage)
        self.assertIn("may read local package, Git, and filesystem provenance", normalized_usage)

    def test_read_only_capture_usage_documents_operational_contract(self) -> None:
        usage = (DOCS_DIR / "usage" / "read-only-capture.md").read_text(encoding="utf-8")

        for contract in [
            "transport_ready_at_utc",
            "aircraft_ready_at_utc",
            "WebSocket is the primary transport",
            "UDP is a diagnostic fallback",
            "output_reservation_partial",
            "complete but unclean",
            "per-stage shutdown budget",
            "the consuming development tool owns",
        ]:
            with self.subTest(contract=contract):
                self.assertIn(contract, usage)

    def test_capture_reference_publishes_protocol_modules_and_exact_contracts(self) -> None:
        reference = (DOCS_DIR / "reference" / "capture.md").read_text(encoding="utf-8")
        normalized_reference = " ".join(reference.split())

        for directive in [
            "::: xpwebapi.capture_protocol",
            "::: xpwebapi.capture_events",
            "::: xpwebapi.capture_transport",
        ]:
            with self.subTest(directive=directive):
                self.assertIn(directive, reference)
        for contract in [
            "capture_started",
            "transport_ready",
            "aircraft_ready",
            "capture_interrupted",
            "preceding_sha256",
            "events_sha256",
            "events_size_bytes",
            "clean_shutdown",
            "CaptureInterruption",
            "request_sha256",
            "SourceProvenance",
        ]:
            with self.subTest(contract=contract):
                self.assertIn(contract, reference)
        self.assertIn("`open`, `subscribe`, `connected`, `liveness_state`, and `close`", reference)
        self.assertIn("Elapsed time is non-decreasing", normalized_reference)
        self.assertIn("committed hash and size become available only after flush and fsync succeed", normalized_reference)
        self.assertIn("awaiting_first_identity_packet", normalized_reference)
        self.assertNotIn("last_observation_elapsed", reference)
        self.assertNotIn("elapsed time strictly increase", normalized_reference)

    def test_capture_pages_are_published_and_linked(self) -> None:
        mkdocs = (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8")
        reference_index = (DOCS_DIR / "reference" / "index.md").read_text(encoding="utf-8")

        self.assertIn("Read-only capture: usage/read-only-capture.md", mkdocs)
        self.assertIn("Capture protocol: reference/capture.md", mkdocs)
        self.assertIn("[Capture protocol](capture.md)", reference_index)

    def test_readme_and_changelog_announce_read_only_capture(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

        self.assertIn("WebSocket is the primary capture transport", readme)
        self.assertIn("UDP is the diagnostic/fallback capture transport", readme)
        self.assertIn("## 4.0.0", changelog)
        self.assertIn("read-only capture worker", changelog)

    def test_public_materials_identify_the_maintained_fork(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

        self.assertIn("pip install xpwebapi", readme)
        self.assertIn("TV Productions", readme)
        self.assertIn("devleaks/xplane-webapi", readme)
        self.assertIn("independently maintained fork", readme)
        self.assertIn("https://tvproductions.github.io/xplane-webapi/", readme)
        self.assertNotIn("git+https://github.com/devleaks", readme)
        self.assertNotIn("development infrastructure for q4xpcc", readme)

        self.assertIn("## 4.0.0", changelog)
        self.assertIn("upstream source reported version 3.5.0", changelog)
        self.assertIn("no corresponding upstream changelog entry or release tag", changelog)

    def test_public_materials_have_no_stale_active_upstream_or_consumer_links(self) -> None:
        paths = (
            REPO_ROOT / "README.md",
            DOCS_DIR / "usage" / "index.md",
            DOCS_DIR / "usage" / "read-only-capture.md",
            DOCS_DIR / "reference" / "index.md",
            DOCS_DIR / "reference" / "capture.md",
            REPO_ROOT / "examples" / "template.py",
            REPO_ROOT / "examples" / "xpwsapp.py",
        )
        for path in paths:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(REPO_ROOT)):
                self.assertNotIn("devleaks.github.io/xplane-webapi", text)
                self.assertNotIn("git+https://github.com/devleaks/xplane-webapi.git", text)
                self.assertNotIn("q4xpcc", text)

    def test_mkdocs_uses_tvproductions_canonical_site_and_excludes_internal_plans(self) -> None:
        mkdocs = (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8")

        self.assertIn("site_url: https://tvproductions.github.io/xplane-webapi/", mkdocs)
        self.assertIn("repo_url: https://github.com/tvproductions/xplane-webapi", mkdocs)
        self.assertIn("repo_name: tvproductions/xplane-webapi", mkdocs)
        self.assertIn("edit_uri: edit/main/docs/", mkdocs)
        self.assertIn("exclude_docs:", mkdocs)
        self.assertIn("  superpowers/**", mkdocs)

    def test_capture_docs_describe_installed_schema_resources(self) -> None:
        reference = (DOCS_DIR / "reference" / "capture.md").read_text(encoding="utf-8")
        self.assertIn("xpwebapi.schemas", reference)
        for name in (
            "capture-event-v1.schema.json",
            "capture-request-v1.schema.json",
            "capture-status-v1.schema.json",
            "capture-version-v1.schema.json",
        ):
            with self.subTest(name=name):
                self.assertIn(name, reference)

    def test_governing_documents_record_final_capture_interfaces(self) -> None:
        paths = [
            DOCS_DIR / "superpowers" / "specs" / "2026-07-19-q4xpcc-read-only-capture-worker-design.md",
            DOCS_DIR / "superpowers" / "plans" / "2026-07-19-q4xpcc-read-only-capture-worker.md",
        ]
        for path in paths:
            document = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertIn("request_sha256", document)
                self.assertIn("SourceProvenance", document)
                self.assertIn("CaptureInterruption", document)
                self.assertIn("pre-readiness requested stop", document)
                self.assertIn("two-phase event/status commit", document)
                self.assertIn("complete-but-unclean", document)
                self.assertIn("per-stage transport shutdown budgets", document)
                self.assertIn("no cross-path rollback", document)
                self.assertIn("liveness_state", document)

    def test_task_seven_plan_declares_every_tracked_change(self) -> None:
        plan = (DOCS_DIR / "superpowers" / "plans" / "2026-07-19-q4xpcc-read-only-capture-worker.md").read_text(encoding="utf-8")
        task = plan.split("### Task 7: Documentation and Complete Verification", 1)[1]
        files_block = task.split("**Interfaces:**", 1)[0]
        commit_block = " ".join(task.split("**Step 6: Commit**", 1)[1].split())
        tracked_files = [
            "README.md",
            "CHANGELOG.md",
            "docs/usage/index.md",
            "docs/usage/read-only-capture.md",
            "docs/reference/index.md",
            "docs/reference/capture.md",
            "docs/superpowers/specs/2026-07-19-q4xpcc-read-only-capture-worker-design.md",
            "docs/superpowers/plans/2026-07-19-q4xpcc-read-only-capture-worker.md",
            "mkdocs.yml",
            "tests/test_documentation.py",
            "tests/test_capture_cli.py",
        ]

        for tracked_file in tracked_files:
            with self.subTest(tracked_file=tracked_file):
                self.assertIn(f"`{tracked_file}`", files_block)
                self.assertIn(tracked_file, commit_block)

    def test_readme_development_install_matches_project_metadata(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        dev_extra = pyproject.get("project", {}).get("optional-dependencies", {}).get("dev")

        if dev_extra is None:
            self.assertNotIn("xpwebapi[dev]", readme)
            self.assertIn("uv sync", readme)
        else:
            self.assertIn("xpwebapi[dev]", readme)

    def test_usage_docs_include_required_patterns(self) -> None:
        usage = (DOCS_DIR / "usage" / "index.md").read_text(encoding="utf-8")

        for heading in ["Connection lifecycle", "Monitoring datarefs", "Executing commands"]:
            with self.subTest(heading=heading):
                self.assertIn(f"## {heading}", usage)

    def test_reference_docs_use_valid_mkdocstrings_directives(self) -> None:
        reference_pages = sorted((DOCS_DIR / "reference").glob("*.md"))
        directives: dict[str, list[str]] = {}

        for path in reference_pages:
            lines = path.read_text(encoding="utf-8").splitlines()
            directives[path.name] = [line.strip() for line in lines if line.strip().startswith(":::")]

        self.assertIn("package.md", directives)
        self.assertIn("rest.md", directives)
        self.assertIn("websocket.md", directives)
        self.assertIn("udp.md", directives)
        self.assertNotIn("# :::", (DOCS_DIR / "reference" / "index.md").read_text(encoding="utf-8"))
        self.assertTrue(any("::: xpwebapi" == directive for directive in directives["package.md"]))
        self.assertTrue(any("::: xpwebapi.rest" == directive for directive in directives["rest.md"]))
        self.assertTrue(any("::: xpwebapi.ws" == directive for directive in directives["websocket.md"]))
        self.assertTrue(any("::: xpwebapi.udp" == directive for directive in directives["udp.md"]))

    def test_mkdocs_navigation_publishes_reference_pages(self) -> None:
        mkdocs = (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8")

        for nav_entry in [
            "Package: reference/package.md",
            "REST: reference/rest.md",
            "Async REST: reference/async-rest.md",
            "WebSocket: reference/websocket.md",
            "UDP: reference/udp.md",
            "Beacon: reference/beacon.md",
        ]:
            with self.subTest(nav_entry=nav_entry):
                self.assertIn(nav_entry, mkdocs)


if __name__ == "__main__":
    unittest.main()
