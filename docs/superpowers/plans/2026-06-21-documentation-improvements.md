# Documentation Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the documentation backlog item by validating and improving example annotations, usage docs, and mkdocstrings API reference publishing.

**Architecture:** Keep MkDocs Material and mkdocstrings as the documentation stack. Add a small `unittest` contract test for docs/example structure, then update examples and docs to satisfy that contract.

**Tech Stack:** Python 3.12, stdlib `unittest`, MkDocs, mkdocstrings, MkDocs Material.

## Global Constraints

- Do not use, add, or suggest pytest.
- Keep examples behavior unchanged while adding annotations.
- Use the existing MkDocs deployment workflow on pushes to `main`.
- Keep docs concise and focused on reusable usage patterns.

---

### Task 1: Documentation Contract Tests

**Files:**
- Create: `tests/test_documentation.py`

**Interfaces:**
- Consumes: `examples/*.py`, `docs/usage/index.md`, `docs/reference/*.md`, `mkdocs.yml`
- Produces: focused `unittest` coverage for documentation requirements.

- [ ] Add tests that parse example files with `ast` and fail when functions or methods lack annotations.
- [ ] Add tests that assert usage docs contain `Connection lifecycle`, `Monitoring datarefs`, and `Executing commands`.
- [ ] Add tests that assert reference docs contain valid mkdocstrings directives and MkDocs navigation exposes reference pages.
- [ ] Run `uv run python -m unittest tests.test_documentation -v` and confirm it fails for the current missing annotations/reference docs.

### Task 2: Example Type Annotations

**Files:**
- Modify: `examples/*.py`

**Interfaces:**
- Consumes: tests from Task 1.
- Produces: all functions and methods in examples have parameter and return annotations.

- [ ] Annotate callback functions with `-> None`.
- [ ] Annotate utility functions with concrete return types such as `float`, `int | None`, `tuple[float, float]`, `dict[str, object]`, or `str`.
- [ ] Annotate example app constructors and lifecycle/reporting methods without changing runtime behavior.
- [ ] Run `uv run python -m unittest tests.test_documentation -v` and confirm the annotation test passes or exposes only remaining docs failures.

### Task 3: Usage and Reference Docs

**Files:**
- Modify: `docs/usage/index.md`
- Modify: `docs/reference/index.md`
- Create: focused files under `docs/reference/`
- Modify: `mkdocs.yml`

**Interfaces:**
- Consumes: existing public modules in `xpwebapi`.
- Produces: mkdocstrings-backed API reference pages and usage pattern docs.

- [ ] Replace the malformed reference directive with a valid index.
- [ ] Add mkdocstrings pages for the package root and primary modules: REST, async REST, WebSocket, UDP, beacon, core API, exceptions, and logging configuration.
- [ ] Update MkDocs nav so the reference pages are published.
- [ ] Expand usage docs with typed snippets for connection lifecycle, monitoring datarefs, and executing commands.
- [ ] Run `uv run python -m unittest tests.test_documentation -v` and `uv run mkdocs build --strict`.

### Task 4: Backlog and Final Validation

**Files:**
- Modify: `BACKLOG.md`

**Interfaces:**
- Consumes: passing docs contract and MkDocs build.
- Produces: backlog item marked complete.

- [ ] Mark `Documentation improvements` and its completed subitems checked.
- [ ] Run `uv run python tools\quality.py check`.
- [ ] Review `git diff --stat` and `git status -sb`.
