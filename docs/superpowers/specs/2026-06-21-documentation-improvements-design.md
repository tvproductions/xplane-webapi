# Documentation Improvements Design

## Goal

Complete the actionable documentation backlog item by making examples type-annotated, expanding user-facing usage guidance, and publishing real API reference pages through the existing MkDocs and mkdocstrings pipeline.

## Current State

The project already uses MkDocs Material and has `mkdocstrings` plus `mkdocstrings-python` in the development dependency group. GitHub Actions already deploys MkDocs on pushes to `main`. The remaining issues are content and validation:

- `docs/reference/index.md` uses `# ::: xpwebapi`, which renders as text instead of a mkdocstrings directive.
- `docs/usage/index.md` has basic samples but does not clearly cover connection lifecycle, monitoring datarefs, or executing commands as reusable patterns.
- `examples/` is excluded from `ruff` and `ty`, so example annotation coverage needs a separate lightweight guard.

## Approach

Use the existing docs stack. Do not add a new documentation generator or change the deployment model.

1. Add `unittest` coverage for documentation contracts:
   - every Python function or method in `examples/*.py` has a return annotation;
   - every non-`self`/`cls` parameter in `examples/*.py` has a type annotation;
   - usage docs include the required pattern sections;
   - reference docs contain valid mkdocstrings directives;
   - MkDocs navigation exposes reference subpages.
2. Type-annotate examples in place. Preserve example behavior and keep broad example utility types pragmatic where the code is demonstration-heavy.
3. Replace the single malformed reference page with an index plus focused module pages using mkdocstrings directives.
4. Expand usage docs with concise, typed examples for connection lifecycle, dataref monitoring, and command execution.

## Validation

Run the new focused `unittest` module first, then run:

```powershell
uv run mkdocs build --strict
uv run python tools\quality.py check
```

The repo forbids other Python test frameworks; validation uses only stdlib `unittest`.
