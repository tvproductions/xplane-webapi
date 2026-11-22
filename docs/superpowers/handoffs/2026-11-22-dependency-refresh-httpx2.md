# Dependency refresh and HTTPX2 handoff

## Resume here

Start by checking `git status -sb` and `git log -1 --` followed by this file's
path. The containing commit is the save point for the toolchain and HTTPX2
refresh on `main`. The pre-refresh base is `1f170dd`. Read the
[release scope](https://github.com/tvproductions/xplane-webapi/blob/main/BACKLOG.md#release-scope)
before choosing release work.
The published baseline is v4.0.0. Shipping the Python 3.13 support removal
requires a new 5.0.0 PRD and an approved finite scope. If the next request is
Pydantic integration, start with the payload boundary in
[typed X-Plane API v3 flight management](https://github.com/tvproductions/xplane-webapi/issues/3).
Identify the response shapes and preserve existing caller behavior before any
implementation. The current request authorized HTTPX2, this handoff and Git
sync.

## What changed

The [adoption record](../skills-first-adoption.md) contains the verified runtime,
tool and workflow-stack pins. Fresh Codex processes loaded gz-skills 0.14.0 and
Superpowers 7.0.2 with 37 active project skills. Backplane 0.3.0 is installed
with activation disabled. Starter state lives under `.gz-starter/`. Python
3.12.16 and websockets 17.4 are locked. ty 0.0.69 passes the existing rules;
ty 0.0.108 reported 57 diagnostics before the HTTPX2 migration and needs a
separate typing change.

Both REST clients now use HTTPX2 2.16.2 and retain certificate selection through
`SSL_CERT_FILE`, then `SSL_CERT_DIR`, then certifi. The transport types exposed
through a normal `.session` and the exceptions raised by the transport now
come from `httpx2`. The existing pooling and read-only wrappers stay in use.

## Verification

The 77 focused sync and async REST tests passed. Both clients completed real
loopback HTTPS exchanges using each of `SSL_CERT_FILE` and `SSL_CERT_DIR` and
completed an HTTP exchange through a loopback proxy using `HTTP_PROXY`.
Repeat the repository hygiene gate, strict docs build, and isolated installed
wheel test if the save point has changed. Hosted CI and XPPython3 host behavior
require their own evidence.

## Pydantic opportunities

- Use the existing `TypeAdapter` at a typed REST response boundary for issue
  #3. Capture status already provides a local example of boundary validation.
  [TypeAdapter documentation](https://docs.pydantic.dev/latest/concepts/type_adapter/)
- Consider `pydantic-settings` when capture needs shared environment, file, and
  CLI configuration precedence. Preserve the current worker protocol and
  logging configuration. [Settings documentation](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- Consider Pydantic Extra Types coordinate validation when the FDR toolkit owns
  a typed geographic ingestion boundary. Confirm how it should handle invalid
  or missing coordinates in existing recordings.
  [Coordinate types](https://docs.pydantic.dev/latest/api/pydantic_extra_types_coordinate/)
