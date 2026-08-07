# xpwebapi FDR Toolkit Design

## Purpose

Add a supported Flight Data Recorder toolkit to `xpwebapi` for release as
version `4.1.0`. The toolkit will turn the repository's inherited FDR example
and upstream's newer reader/GeoJSON experiment into a cohesive, tested public
subpackage. It must be useful both for recording live X-Plane sessions and for
constructing deterministic flight fixtures used by dependent projects such as
native X-Plane plugins.

The toolkit is an independently implemented first-party feature. The existing
`devleaks/xplane-webapi` examples establish the X-Plane FDR use case and file
shape, but example code will not become the public implementation by being
copied into the package. The `hotbso/xgs` project is a behavioral reference for
the kinds of landing observations that recorded flights can exercise; its
GPLv2-licensed implementation will not be copied into this MIT-licensed
project.

## Terminology and Boundaries

The project uses the following terms consistently:

- **Module**: one Python source file inside a package. A module is appropriate
  for one focused responsibility but is too small a boundary for the complete
  FDR feature.
- **Subpackage**: a first-party namespace containing cooperating modules.
  `xpwebapi.fdr` will be a subpackage and will ship in every `xpwebapi`
  installation.
- **Optional extra**: a packaging declaration that installs additional
  dependencies, such as a possible future `xpwebapi[kml]`. An extra is not a
  runtime feature flag and does not remove subpackage code from the wheel.
- **Python extension**: separately distributed Python code composed with
  `xpwebapi` through documented interfaces. Runtime discovery through package
  entry points is reserved for a demonstrated third-party discovery need.
- **Companion distribution**: a separately versioned first-party project that
  depends on `xpwebapi`, such as a possible future landing-analysis package.
  Domain applications with their own users and release cadence belong here.
- **Native X-Plane plugin**: compiled or hosted code loaded into X-Plane and
  integrated through XPLM or another in-simulator plugin host. `xpwebapi` is an
  external Web API client and development toolkit; it does not load or host
  native X-Plane plugins.

The examples in `devleaks/xplane-webapi`, including `fdr.py`, `xgs.py`,
`oooi.py`, and `posreport.py`, are external applications that use the Python
library. They are not plugins or supported library facilities. This design
promotes only the cohesive FDR responsibilities. Geometry, landing scoring,
OOOI state detection, and position reporting remain separate future candidates.

## Format References

The implementation will be checked against:

- the X-Plane 12 desktop manual's FDR loading and replay behavior at
  `https://x-plane.com/manuals/desktop/12/`;
- the X-Plane 12 `FDR Example Version 4.fdr` reference sample mirrored in
  `devleaks/xplane-webapi` under `docs/`;
- a valid X-Plane version 3 reference fixture obtained before version 3 parser
  work begins;
- RFC 7946 for GeoJSON geometry, feature properties, coordinate reference
  system, and antimeridian behavior.

Reference samples are verification inputs, not source code to copy into the
implementation. Large third-party fixtures will not be redistributed unless
their license permits it.

## Goals

- Read and validate X-Plane FDR format versions 3 and 4.
- Generate deterministic canonical version 4 FDR files without requiring a
  running simulator.
- Record live Web API values into the same model and file format.
- Preserve known and unknown metadata without silently discarding it.
- Preserve each optional DataRef's conversion factor and comment.
- Export valid GeoJSON suitable for inspection and downstream tooling.
- Provide command-line workflows for recording, inspection, validation, and
  conversion.
- Give dependent projects stable composition interfaces for synthetic sources,
  live sources, and output sinks.
- Make offline behavior completely testable without X-Plane or network access.
- Retain compatibility with files produced by the inherited `examples/fdr.py`
  recorder where their contents are valid and unambiguous.

## Non-Goals

- Hosting or loading XPLM, XPPython3, or other in-simulator plugins.
- Copying or reimplementing the UI, scoring text, or complete behavior of
  `hotbso/xgs`.
- Providing a general runtime plugin registry in version `4.1.0`.
- Writing version 3 FDR files. Version 3 input remains supported, but new and
  converted output will use version 4.
- Promoting all existing examples into package APIs.
- Automating X-Plane startup, aircraft selection, FDR replay controls, or native
  plugin installation.
- Adding KML export, runway databases, landing ratings, OOOI messages, or ACARS
  reports to the FDR subpackage.
- Claiming that FDR playback can reproduce every simulator or third-party
  DataRef. The toolkit can generate and validate files; X-Plane and each plugin
  determine what replay actually drives or observes.

## Package Architecture

The implementation will use the following responsibilities:

```text
xpwebapi/fdr/
|-- __init__.py       stable supported imports
|-- errors.py         FDR-specific public exceptions
|-- models.py         immutable typed metadata, fields, samples, recordings
|-- reader.py         FDR v3/v4 text parsing and validation
|-- writer.py         deterministic FDR serialization
|-- recorder.py       source/sink composition and live Web API recording
|-- geojson.py        standards-conforming GeoJSON generation
`-- cli.py            record, inspect, validate, and to-geojson commands
```

`xpwebapi.fdr.__init__` will explicitly export the supported public surface.
Consumers will not need to import implementation modules. The command-line
layer will call the same public library behavior and will not contain a second
parser, serializer, or recorder implementation.

The subpackage will use the standard library and dependencies already required
by `xpwebapi`. It will therefore be installed by default, with no `fdr` extra.
Optional extras will be introduced only if a later capability needs a genuine
additional dependency.

## Data Model

An `FDRRecording` will contain:

- source format version `3` or `4`;
- source origin marker `A` or `I`;
- ordered comments;
- ordered known and unknown metadata fields;
- ordered `FDRDataref` declarations containing path, finite conversion factor,
  and optional comment;
- ordered samples;
- the unzoned local calendar date from `DATE`, when present.

Mandatory sample fields are UTC time, longitude, latitude, altitude above mean
sea level in feet, magnetic heading, pitch, and roll. Additional `DREF` fields
remain ordered and are preserved as finite numeric sample values. The reader will
accept surrounding whitespace but the writer will emit one canonical form.
The conversion factor is part of the declaration, not pre-applied to the stored
sample. This preserves the source values that X-Plane will scale during replay.

Models will reject booleans where a numeric value is required, non-finite
numbers, invalid latitude or longitude, duplicate field identifiers, sample
width mismatches, and timestamps that cannot be made monotonic. Models will be
safe to construct directly so dependent projects can create deterministic
fixtures without using private helpers.

FDR files provide an unzoned local `DATE` while mandatory sample times are
Zulu time-of-day. The format contains no UTC offset, so the reader will not
invent an absolute UTC date. It will preserve local date and UTC time-of-day as
separate values. When a subsequent time-of-day moves backward, duration
calculation will count a midnight rollover, but it cannot infer a silent gap of
one or more complete days. Callers that need absolute timestamps must provide
the first UTC calendar date explicitly. The live recorder will write the local
calendar date required by the format while retaining actual UTC instants only
for the active recording session.

## Public Composition Interfaces

The public API will favor ordinary construction and dependency injection over
global registries. It will provide:

- `FDRReader` for reading paths and text streams into `FDRRecording`, with a
  streaming sample iterator for large inputs;
- `FDRWriter` for atomically writing complete `FDRRecording` objects or
  incrementally accepting validated samples;
- `FDRRecorder` for consuming snapshots from a source and committing them to an
  FDR sink;
- a small `FDRSampleSource` protocol that yields timestamped values;
- a small `FDRSampleSink` protocol that accepts validated samples;
- `recording_to_geojson()` for producing a JSON-compatible feature collection.

Reader and writer instances will own streams they open from filesystem paths
and will not close caller-supplied text streams. Inputs will accept UTF-8 text
with CR, LF, or CRLF separators. Canonical output will use the header bytes
`A\n4\n`, UTF-8 encoding, and LF separators, matching the current X-Plane 12
version 4 reference sample. Path writers will reject an existing destination
unless `overwrite=True`; caller-supplied streams remain the caller's durability
responsibility.

The protocols are composition points, not dynamically discovered plugins. A
dependent project may supply an in-memory source, a fixture source, or another
adapter without registration. `xpwebapi` will provide the live Web API source
used by `FDRRecorder`. If multiple independently distributed providers later
need discovery, an entry-point group can be designed against these interfaces
without changing the FDR data model.

## Reader and Validation Behavior

The reader will parse files incrementally and report structural failures with
the source line number and a concise explanation. It will:

- accept origin marker `A` or `I`;
- parse the leading version integer while permitting explanatory text after it;
- preserve `COMM` entries in order;
- parse known metadata while retaining unknown four-character metadata keys;
- parse and retain each `DREF` path, conversion factor, and optional `//`
  comment;
- treat human-readable column comments as optional annotations rather than
  schema;
- derive the schema from the seven mandatory columns followed by the ordered
  `DREF` declarations;
- require every sample to contain exactly seven plus the declared `DREF` count
  columns;
- reject malformed numbers and timestamps rather than printing warnings;
- detect midnight rollover when calculating duration or resolving an explicit
  caller-supplied UTC date;
- expose duplicate metadata as ordered input while defining the last value as
  the effective lookup value.

`FDRParseError` will describe invalid source text. `FDRValidationError` will
describe a structurally valid parse that violates the recording model.
Library code will not print diagnostics directly.

## Writer and Recording Behavior

`FDRWriter` will serialize any valid `FDRRecording` as version 4
deterministically. Given the same model, it will produce identical UTF-8 bytes
and LF line endings. It will never derive dates, clocks, aircraft identity, or
field order from ambient process state. A version 3 recording can therefore be
read and normalized into version 4 output without claiming to preserve its
original bytes.

`FDRRecorder` will compose a sample source and sink. Live recording will use
the repository's read-only capture and observation machinery rather than a
second write-capable WebSocket lifecycle. Implementation may extract a shared
internal observation-source abstraction, but it will not import private
transport classes as a new public dependency. The live adapter will subscribe
to the mandatory fields plus configured optional DataRefs, wait for required
initial values, and then sample at a configured interval. It will support a
bounded duration and graceful interrupt.

Path-based live recording will stream into a uniquely created sibling partial
file. A graceful stop after at least one valid sample will flush and synchronize
the file before atomically moving it to the destination. An unexpected failure
will leave the partial file for diagnosis or recovery and will never present it
under the requested final name. Failures before the first valid sample will not
masquerade as successful recordings.

The recording engine will accept injected clocks and sample sources. Tests and
dependent projects can therefore run complete recording sessions without
sleeping, opening sockets, or starting X-Plane.

## GeoJSON Behavior

GeoJSON conversion will return a standards-conforming `FeatureCollection`.
Each sample will produce a point feature whose `properties` are a sibling of
`geometry`, not nested inside it. A final line-string feature will describe the
ordered flight path when at least two locations exist.

Coordinates will use two-dimensional GeoJSON order: longitude, then latitude.
FDR altitude is height above mean sea level, while RFC 7946 defines a third
coordinate as height relative to the WGS 84 ellipsoid; the converter will not
mislabel one as the other. Each point's properties will therefore include both
`altitude_msl_ft` and explicitly converted `altitude_msl_m`, along with UTC
time-of-day, heading, pitch, roll, and additional DataRef values. An absolute
RFC 3339 timestamp will be included only when the caller supplies the first UTC
calendar date.

Paths whose consecutive longitudes cross the antimeridian will be split into a
`MultiLineString`; other paths will use a `LineString`. The converter will not
write files itself; the CLI will serialize the returned JSON-compatible object.

## Command-Line Interface

One installed command, `xpwebapi-fdr`, will provide subcommands:

- `record`: record a bounded or interruptible live session to an FDR file;
- `inspect`: print normalized metadata, fields, sample count, start, end, and
  duration;
- `validate`: perform strict parsing and validation without conversion;
- `to-geojson`: convert a valid recording to a GeoJSON file.

Commands will use exit status `0` for success and nonzero status for invalid
arguments, invalid FDR input, connection failure, or output failure. Machine-
readable output will go to standard output only when explicitly requested;
diagnostics will go to standard error. Existing files will not be overwritten
unless the user supplies an explicit overwrite option.

## Downstream Project Onboarding

Downstream projects will add a compatible `xpwebapi` development or test
dependency and import `xpwebapi.fdr`; they will not install a separate FDR
distribution or register a plugin. A typical integration-test flow is:

1. Construct an `FDRRecording` or supply an `FDRSampleSource` fixture.
2. Generate and validate deterministic FDR input.
3. Arrange X-Plane playback when simulator-level behavior is required.
4. Observe the target plugin through its published DataRefs, files, logs, or
   other explicit outputs.
5. Compare observations with expected results.

FDR playback supplies simulator stimulus; it is not by itself a plugin test
runner. The target plugin must be configured to process replay state when
applicable and must expose observable results. `xpwebapi.fdr` will not infer
success from the simulator merely accepting an FDR file.

Projects that only need offline algorithms can stop after parsing, validation,
or conversion and never run X-Plane. Project documentation will make clear
that simulator orchestration and native plugin installation remain the
consumer's responsibility.

## Relationship to Other Utilities

The upstream examples imply additional reusable domains:

- external WebSocket application lifecycle management;
- geodesic and runway geometry;
- aviation unit conversion;
- landing-event detection and scoring;
- OOOI phase detection;
- position and ACARS-style reporting;
- KML and other presentation formats.

Those domains will not be folded into `xpwebapi.fdr`. Common primitives will
be extracted only when the FDR implementation genuinely needs them. Larger
domain applications should prefer companion distributions so `xpwebapi`
remains a focused transport and development toolkit.

## Testing and Verification

All automated tests will use the repository's approved `unittest` workflow.
Verification will include:

- valid version 3 and version 4 fixtures;
- acceptance of both origin markers, all common text line separators, and
  version lines with explanatory suffixes;
- inherited-recorder compatibility fixtures;
- malformed marker, version, metadata, declaration, header, row-width,
  timestamp, coordinate, and numeric cases;
- DataRef conversion-factor and comment preservation;
- midnight rollover and multi-day duration;
- deterministic writer output and read/write round trips;
- version 3 input normalized to canonical version 4 output;
- synthetic source-to-recorder tests with injected clocks;
- valid GeoJSON structure, two-dimensional coordinate order, MSL altitude
  properties, explicit UTC-date resolution, and antimeridian splitting;
- CLI success, failure, overwrite protection, and stream separation;
- wheel and source-distribution checks for the complete subpackage and command;
- Python 3.12 and Python 3.13 installed-artifact smoke tests.

Live X-Plane tests will remain optional integration checks because they require
external simulator state. They will not replace deterministic unit and command
tests.

## Documentation and Release

Implementation will add public FDR usage and reference pages to the MkDocs
site, link the feature from the README, and reduce `examples/fdr.py` to a thin
consumer of the supported API. Documentation will use the terminology in this
specification and will avoid calling external Web API applications native
X-Plane plugins.

The implementation will bump the package to `4.1.0` because it adds a new
supported public subpackage and command-line surface without breaking the 4.x
API. The release will use the existing trusted publishing workflow after the
full repository quality gate and installed-artifact checks pass.

## Future Extension Criteria

A future optional extra is justified only by an optional third-party
dependency. A future entry-point plugin system is justified only when at least
one separately distributed provider must be discovered without direct
construction. A future companion distribution is justified when a domain such
as landing analysis has its own configuration, users, dependencies, and
release cadence.

These criteria keep the default installation predictable while leaving stable
composition seams for future growth.
