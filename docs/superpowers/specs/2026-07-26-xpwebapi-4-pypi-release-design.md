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
- state that the upstream source reported version `3.5.0` when the fork's
  extension work began, while noting that upstream did not provide a
  corresponding changelog entry or release tag;
- avoid implying that the fork is endorsed or currently maintained by the
  upstream author.

Historical changelog entries will remain intact. A new fork-lineage section
and a complete `4.0.0` entry will distinguish inherited history from TV
Productions maintenance. Missing upstream changelog entries or releases will
not be invented.

The repository and distributions will contain one canonical `LICENSE` file.
It will preserve every upstream copyright notice currently present across
`LICENSE` and `LICENCE`, preserve the MIT permission and warranty text, and add
a TV Productions copyright notice for subsequent modifications. Package
metadata will reference this canonical file. The duplicate `LICENCE` file will
be removed only after its upstream notice is present in `LICENSE`.

Original authorship will remain represented in package metadata. Current
maintenance and contact metadata will identify Jeffry and TV Productions
separately. The PyPI ownership and publishing pattern will follow
`py-gzkit`: PyPI user `ahuimanu` will own the project, the canonical public
source will be under the `tvproductions` GitHub organization, and releases will
use a repository-bound Trusted Publisher. The original author will not be
listed as a current PyPI maintainer or owner without explicit consent.

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

The four versioned capture protocol schemas will be installed package data.
Their canonical copies will live under `xpwebapi/schemas/`, ship in both the
wheel and source distribution, and be readable through package-resource APIs
after installation. Source-tree and installed-artifact checks will verify that
the packaged schemas exactly match the models that generate them.

## Python Compatibility

Version `4.0.0` will support Python 3.12 and Python 3.13:

```toml
requires-python = ">=3.12,<3.14"
```

Python 3.13 is the primary development interpreter. Python 3.12 remains a
required compatibility target because it is useful in development environments
aligned with XPPython3. Package classifiers, lock data, documentation, local
tooling, and continuous integration will consistently reflect this contract.

Linting, formatting, typing, security, documentation, and packaging checks will
run once on Python 3.13. Runtime unit tests and installed-artifact smoke checks
will run on both Python 3.12 and Python 3.13. No compatibility with Python 3.14
or later will be claimed until it is explicitly validated.

## Documentation Site

TV Productions will publish and maintain the library documentation at:

`https://tvproductions.github.io/xplane-webapi/`

The upstream documentation at `https://devleaks.github.io/xplane-webapi/` is a
lineage reference, not the current documentation site. Active package metadata,
README links, badges, and navigation will use the TV Productions URL.

The canonical repository already contains a populated `gh-pages` branch, but
the TV Productions Pages endpoint returned GitHub Pages' 404 response during
design verification. Implementation will configure GitHub Pages to publish from
the root of the `gh-pages` branch, then deploy the maintained MkDocs site before
the PyPI release.

`mkdocs.yml` will define the canonical site URL, repository URL, repository
name, and edit URI for TV Productions. Public documentation will include
installation, usage, REST, async REST, WebSocket, UDP, beacon, logging,
exceptions, capture CLI, and capture protocol material. Internal planning and
agent-workflow material under `docs/superpowers/` will be excluded from the
published site and sitemap.

The existing docs deployment job will be tightened so it runs only after the
blocking quality checks succeed on `main`, receives only the permissions needed
to update `gh-pages`, and fails visibly if the build or deployment fails. The
release gate will require the TV Productions documentation homepage and key
usage/reference pages to return successful responses with TV Productions
canonical links.

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
- PyPI README rendering and absolute links;
- availability of the TV Productions documentation site;
- dedicated release automation and least-privilege permissions.

The audit will preserve useful upstream acknowledgements while removing stale
instructions that direct users to `devleaks` for current installation,
documentation, issues, or releases.

## Verification

Release verification will use the repository's approved `unittest`-based
quality workflow. It will include:

- the complete repository quality gate on Python 3.13;
- runtime unit tests on Python 3.12 and Python 3.13;
- one clean wheel and source-distribution build from the intended release
  commit;
- inspection of archive contents and core package metadata;
- installation of built artifacts into clean Python 3.12 and Python 3.13
  environments;
- import, version, and public API smoke checks;
- an installed `xpwebapi-capture` command-line smoke check;
- installed access to the four capture protocol schemas and equality checks
  against their generated canonical forms;
- strict validation of the long description and confirmation that its links
  resolve correctly from PyPI;
- documentation build verification;
- confirmation that the TV Productions documentation URL is publicly
  reachable before it is published in package metadata;
- confirmation that the worktree, release commit, tag, GitHub release, and
  published artifacts all describe the same source state.

Publication will stop before an irreversible upload if metadata, archive
contents, supported-version validation, or source-state identity is incorrect.
Existing contents of `dist/` are never release inputs. Local verification will
start from an empty artifact directory, and automated publication will build in
a clean runner. The known stale `xpwebapi-3.5.0` archives will not be reused.

## Publication

The PyPI project will be created under the name `xpwebapi`, owned by PyPI user
`ahuimanu`, using Trusted Publishing associated with the public
`tvproductions/xplane-webapi` repository. This follows the established
`py-gzkit` ownership and provenance pattern. A dedicated least-privilege
`release.yml` workflow and protected GitHub `pypi` environment will be used
instead of a long-lived PyPI API token.

The release workflow will trigger from version tags matching `v*`. It will
verify that the tag matches package and runtime version declarations, build the
wheel and source distribution exactly once in an empty `dist/` directory,
strictly validate them, and publish those same files without rebuilding. The
publish job alone will receive `id-token: write`; the GitHub release job alone
will receive `contents: write`. The protected `pypi` environment will require
manual approval. Successful publication will produce PyPI provenance
attestations tied to the public repository, release workflow, tag, and source
commit.

The intended publication sequence is:

1. Complete release tightening and local verification.
2. Push the exact intended source state and `release.yml` to the canonical
   public GitHub repository.
3. Let normal CI verify the pushed commit, deploy MkDocs to `gh-pages`, and
   confirm `https://tvproductions.github.io/xplane-webapi/` plus key
   usage/reference pages are public.
4. Create and protect the GitHub `pypi` environment with manual approval.
5. Only after every preceding check is green, register the pending PyPI
   publisher from PyPI user `ahuimanu` for project `xpwebapi`, GitHub owner
   `tvproductions`, repository `xplane-webapi`, workflow `release.yml`, and
   environment `pypi`.
6. In the same controlled release session, create and push the `v4.0.0` tag
   from the verified commit. A pending publisher does not reserve the project
   name, so no avoidable delay will be introduced between registration and
   first use.
7. Approve the protected publishing job, which will build once, validate, and
   publish those exact immutable `4.0.0` artifacts.
8. Verify the PyPI project page, provenance, README rendering, artifact
   metadata, installation, packaged schemas, and hashes.
9. Create or finalize the corresponding GitHub release and documentation.
10. Add a courteous upstream PR note linking to the maintained fork and
    release.

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
