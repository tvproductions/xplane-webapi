# Superpowers Project Install

Source: https://github.com/obra/superpowers
Version: 6.2.0
Commit: 3dcbd5c4b48e02263fbf4a3c01e3fe4f81d584d9

This project vendors Superpowers for Codex in two places:

- `.codex/skills/`: project-local skills loaded by Codex for this repository.
- `.codex/plugins/superpowers/`: a self-contained copy of the Codex plugin
  metadata, assets, hooks, license, README, and skills.

The generic skills and plugin payload are copied from the tagged upstream
release. Repo-specific skills such as `code-quality`, `git-sync`, and `hygiene`
remain project-owned. Instructions in `AGENTS.md` take precedence.
