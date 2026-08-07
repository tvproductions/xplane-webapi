---
title: Flight Data Recorder toolkit
---

# Flight Data Recorder toolkit

`xpwebapi.fdr` is the always-installed Flight Data Recorder (FDR) subpackage
in xpwebapi 4.1.0. It provides deterministic version 4 FDR construction,
strict version 4 reading and validation, read-only live recording, and GeoJSON
export. It is useful both for inspecting recorded flights and for creating
small, offline simulator inputs for a dependent project's tests.

The toolkit does not start X-Plane, control its replay UI, install a native
plugin, or decide whether another component passed a test.

## Commands

The installed `xpwebapi-fdr` command uses the same public library behavior as
the Python API:

```sh
# Strictly parse a version 4 recording. Successful validation is silent.
xpwebapi-fdr validate flight.fdr

# Inspect a human-readable summary, or request one compact JSON document.
xpwebapi-fdr inspect flight.fdr
xpwebapi-fdr inspect flight.fdr --json --first-utc-date 2026-08-07

# Write GeoJSON without replacing an existing file unless requested.
xpwebapi-fdr to-geojson flight.fdr flight.geojson
xpwebapi-fdr to-geojson flight.fdr flight.geojson --overwrite

# Read live navigation values through the read-only Web API transport.
xpwebapi-fdr record flight.fdr --duration 120 --interval 1.0 \
  --dataref sim/flightmodel/engine/ENGN_N2_[0] \
  --scale sim/flightmodel/engine/ENGN_N2_[0]=1.0 \
  --comment sim/flightmodel/engine/ENGN_N2_[0]='engine 1 N2 percent'
```

`record` never exposes DataRef writes or command execution. It subscribes to
the mandatory navigation values and declared optional DataRefs using the
existing read-only observation transport. A bounded duration or interrupt ends
a graceful recording after at least one valid sample. The writer uses a unique
sibling `.partial` file and publishes the requested final filename only after
flush, synchronization, and atomic commit. If recording fails, inspect or
recover the preserved `.partial` file instead of treating the final path as a
recording.

## Offline, deterministic fixtures

Use the immutable models when a test needs a known FDR stimulus and no running
simulator. This produces canonical UTF-8 version 4 output beginning with
`A\n4\n`; it does not use a wall clock, network connection, or ambient
simulator state.

```python
from datetime import date, time
from pathlib import Path

from xpwebapi.fdr import FDRHeader, FDRMetadata, FDRRecording, FDRSample, FDRWriter


header = FDRHeader(
    source_version=4,
    source_origin="A",
    comments=("synthetic integration fixture",),
    metadata=(FDRMetadata("DATE", "2026-08-07"),),
    datarefs=(),
    legacy_columns=(),
    local_date=date(2026, 8, 7),
)
sample = FDRSample(
    time_utc=time(12, 0),
    longitude=-87.9048,
    latitude=41.9742,
    altitude_msl_ft=640.0,
    heading_magnetic_deg=270.0,
    pitch_deg=2.0,
    roll_deg=-1.0,
    additional_values=(),
    legacy_values=(),
)
fixture = FDRRecording(header=header, samples=(sample,))
FDRWriter().write(fixture, Path("fixture.fdr"))
```

Then use `xpwebapi-fdr validate fixture.fdr` before passing it to other tools.
`FDRReader` and `FDRWriter` own streams opened from paths; caller-provided text
streams remain caller-owned.

## GeoJSON

`recording_to_geojson()` returns JSON-compatible values; the CLI serializes the
result atomically for a file. Point geometries use two-dimensional
`[longitude, latitude]` coordinates. FDR altitude is height above mean sea
level rather than WGS 84 ellipsoidal height, so it is intentionally represented
as point properties named `altitude_msl_ft` and `altitude_msl_m`, not as a
third coordinate. The exported path is a `LineString` unless it crosses the
antimeridian, in which case it is a `MultiLineString`.

```python
from datetime import date
import json

from xpwebapi.fdr import FDRReader, recording_to_geojson


recording = FDRReader().read("flight.fdr")
geojson = recording_to_geojson(recording, first_utc_date=date(2026, 8, 7))
print(json.dumps(geojson, allow_nan=False))
```

FDR contains an unzoned local `DATE` and Zulu times of day. Supplying
`first_utc_date` is the explicit opt-in that lets the converter emit absolute
UTC timestamps; the local `DATE` never invents an offset or an absolute UTC
date.

## Version 3 boundary

Version 3 file parsing is not yet available because the official Laminar
reference fixture needed to verify its fixed-column schema is not available in
this project. The version 4 reader therefore rejects version 3 input rather
than guessing a layout. This is a verification gate, not a claim of
interchangeable v3/v4 support.

The immutable model can represent a programmatically constructed legacy
recording with `FDRLegacyColumn` values. Writing or normalizing such a model to
version 4 is deliberately lossy and requires `allow_lossy_legacy=True`:

```python
result = FDRWriter().write(legacy_recording, "converted.fdr", allow_lossy_legacy=True)
print(result.omitted_legacy_field_ids)
```

The result lists each omitted legacy field. Do not use that opt-in to imply
byte-for-byte preservation or verified reading of a version 3 file.

## Composition for dependent projects

For test code, `FDRSampleSource` yields timestamped value mappings and
`FDRSampleSink` accepts validated `FDRSample` objects. A project can provide a
fixture source and use the included `FDRStreamWriter` as its sink, without a
registry or plugin discovery step. `FDRRecorder` maps standard navigation
values and DataRefs in header order, then commits only a graceful session.

```python
from threading import Event

from xpwebapi.fdr import FDRRecorder, FDRWriter


with FDRWriter().open(source.header, "fixture.fdr") as sink:
    result = FDRRecorder(source=source, sink=sink).record(stop_event=Event())
```

`source` is a project-owned `FDRSampleSource`; a live
`LiveFDRSampleSource` is available when X-Plane is actually running. Synthetic
sources, injected clocks, and a normal stream writer keep ordinary tests
offline and deterministic.

For a native X-Plane plugin integration test, use a deliberately separate
workflow:

1. Construct or record a deterministic FDR input and validate it.
2. Arrange X-Plane playback and configure the target native plugin.
3. Observe that plugin through its published DataRefs, files, logs, or another
   explicit output.
4. Assert the project-specific result from those observations.

FDR playback supplies simulator stimulus. Replay orchestration, native-plugin
installation, and plugin-output assertions remain a consumer responsibility;
acceptance of an FDR file by X-Plane is not a test result by itself.

## Package boundaries

- **Module**: one focused Python source file. A module is too small a boundary
  for the whole FDR feature.
- **Subpackage**: cooperating first-party modules under `xpwebapi.fdr`. It
  ships in every xpwebapi installation; there is no `fdr` extra.
- **Optional extra**: a packaging declaration for genuinely optional
  dependencies. It is neither a runtime feature flag nor a way to omit this
  subpackage from a wheel.
- **Python extension**: separately distributed Python code composed through
  documented interfaces. Entry-point discovery is deferred until independent
  providers need discovery rather than direct construction.
- **Companion distribution**: a separately versioned application that depends
  on xpwebapi, appropriate for an independent domain such as landing analysis.
- **Native X-Plane plugin**: code loaded inside X-Plane through an in-simulator
  host such as XPLM. xpwebapi is an external Web API client and toolkit; it
  does not load or host such plugins.

Examples are consumer applications, not plugins. Landing scoring, OOOI state,
ACARS-style reporting, KML, replay control, and plugin registries are outside
the FDR subpackage's supported scope.
