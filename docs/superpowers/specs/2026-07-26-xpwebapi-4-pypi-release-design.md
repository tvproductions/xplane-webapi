# xpwebapi 4.0.0 PyPI Release Design

## Purpose

Publish `xpwebapi` as a standalone, independently maintained Python library
under TV Productions. The release continues the history of
`devleaks/xplane-webapi`, acknowledges and thanks its original author, and
establishes `tvproductions/xplane-webapi` as the canonical source for future
maintenance and releases.

The first TV Productions release will be stable version `4.0.0`. The major
version identifies the maintained-fork boundary and the materially changed
runtime, dependency, and public API contracts. Issues discovered after
publication will be corrected through normal patch releases beginning with
`4.0.1`.

## Project Identity and Lineage

The PyPI distribution name and import package will both remain `xpwebapi`.
All active project links, documentation links, issue links, installation
instructions, badges, and release automation will point to
`tvproductions/xplane-webapi`.

The README and changelog will:

- identify the project as an independently maintained fork;
- thank Pierre Mareschal and `devleaks` for creating the original project;
- link to the upstream repository;
- identify the upstream `3.5.0` source line as the fork's inherited baseline;
- avoid implying that the fork is endorsed or currently maintained by the
  upstream author.

Historical changelog entries will remain intact. A new fork-lineage section
and a complete `4.0.0` entry will distinguish inherited history from TV
Productions maintenance.

The original MIT copyright and permission notice will be preserved. Duplicate
or inconsistent license files will be reconciled without removing upstream
attribution. TV Productions may add a copyright notice covering subsequent
modifications.

Original authorship will remain represented in package metadata. Current
maintenance and contact metadata will identify TV Productions separately.
The original author will not be listed as a current PyPI maintainer or owner
without explicit consent.

## Package Scope

`xpwebapi` is a standalone library and development tool for communicating with
the X-Plane Web API. Other projects may consume it from PyPI, but no consumer
repository changes are part of this release.

XPPython3 is an integration and development use case, not a runtime dependency.
XPPython3 plugins will not import or bundle `xpwebapi`. Documentation may
explain how `xpwebapi` supports development workflows around XPPython3 plugins,
but the package will not claim to be an XPPython3 plugin or ship
XPPython3-specific packaging.

The read-only capture worker will be documented as a general `xpwebapi`
facility. References that present it solely as q4xpcc development
infrastructure will be generalized. Its read-only guarantees and public
command-line behavior remain part of the release.

## Python Compatibility

Version `4.0.0` will support Python 3.12 and Python 3.13:

```toml
requires-python = ">=3.12,<3.14"
```

Python 3.13 is the primary development interpreter. Python 3.12 remains a
required compatibility target because it is useful in development environments
aligned with XPPython3. Package classifiers, lock data, documentation, local
tooling, and continuous integration will consistently reflect this contract.

The full blocking quality workflow will run on both supported Python minors.
No compatibility with Python 3.14 or later will be claimed until it is
explicitly validated.

## Release Tightening

Before publication, the repository will be audited and tightened in the
following areas:

- package version declarations and runtime version reporting;
- authors, maintainers, description, and canonical project URLs;
- README installation, lineage, support, and development instructions;
- changelog history and the `4.0.0` release entry;
- license files and distribution license metadata;
- documentation navigation, generated site URLs, and repository references;
- Python 3.12/3.13 constraints, classifiers, dependency resolution, and CI;
- wheel and source-distribution contents;
- stale build artifacts and accidental repository-only material;
- dedicated release automation and least-privilege permissions.

The audit will preserve useful upstream acknowledgements while removing stale
instructions that direct users to `devleaks` for current installation,
documentation, issues, or releases.

## Verification

Release verification will use the repository's approved `unittest`-based
quality workflow. It will include:

- the complete repository quality gate on Python 3.12 and Python 3.13;
- clean wheel and source-distribution builds from the intended release commit;
- inspection of archive contents and core package metadata;
- installation of built artifacts into clean Python 3.12 and Python 3.13
  environments;
- import, version, and public API smoke checks;
- an installed `xpwebapi-capture` command-line smoke check;
- documentation build verification;
- confirmation that the worktree, release commit, tag, GitHub release, and
  published artifacts all describe the same source state.

Publication will stop before an irreversible upload if metadata, archive
contents, supported-version validation, or source-state identity is incorrect.

## Publication

The PyPI project will be created under the name `xpwebapi` using Trusted
Publishing associated with `tvproductions/xplane-webapi`. A dedicated
least-privilege release workflow and protected GitHub `pypi` environment will
be used instead of a long-lived PyPI API token.

The intended publication sequence is:

1. Complete release tightening and verification.
2. Push the exact intended source state to the canonical GitHub repository.
3. Configure the pending or active PyPI Trusted Publisher for the dedicated
   release workflow.
4. Create and push the `v4.0.0` tag from the verified commit.
5. Build and publish immutable `4.0.0` artifacts through the release workflow.
6. Verify the PyPI project page, artifact metadata, installation, and hashes.
7. Create or finalize the corresponding GitHub release and documentation.
8. Add a courteous upstream PR note linking to the maintained fork and release.

The upstream pull request may remain open through publication. It may be closed
afterward with a concise explanation and links unless upstream engages.

## Error and Recovery Policy

PyPI artifacts will never be overwritten. If a defect is found after
publication, the affected release may be yanked when appropriate and the fix
will be published under the next patch version. A normal first correction will
therefore be `4.0.1`.

If the `xpwebapi` project name cannot be claimed despite the currently absent
public project page, publication will stop for an explicit naming decision.
No alternate distribution name will be selected automatically.

If Trusted Publishing cannot be configured or authenticated, no token-based
fallback will be introduced without explicit approval.

## Out of Scope

- Adding `xpwebapi` to any consumer project's dependencies.
- Changing XPPython3 or an XPPython3 plugin.
- Claiming endorsement by Laminar Research, XPPython3, or `devleaks`.
- Publishing an empty placeholder, release candidate, or alternate package
  name.
- Supporting Python versions outside 3.12 and 3.13 for `4.0.0`.
