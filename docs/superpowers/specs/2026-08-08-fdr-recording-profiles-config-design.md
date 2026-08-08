# FDR Recording Profiles and JSON Configuration Design

> **Architecture superseded:** Profiles and adapter-neutral recording
> configuration are moving to `tvproductions/xplane-fdr`. Web API connection
> configuration remains in `xpwebapi`. This document remains the accepted
> source for detailed profile membership, composition, validation, and failure
> behavior, subject to that boundary change. See
> `docs/superpowers/handoffs/2026-08-08-xplane-fdr-extraction-handoff.md`.

## Purpose

Extend the approved `xpwebapi.fdr` recorder with useful stock-X-Plane
collection profiles and a strict, reusable JSON configuration format. The
feature must support a productive default recording without making
aircraft-specific or third-party DataRefs part of the package's built-in
contract.

This design supplements the broader
`2026-08-07-fdr-toolkit-design.md` specification. It does not change the FDR
reader, writer, GeoJSON, package-boundary, or simulator-orchestration decisions
in that specification.

## Goals

- Capture an authoritative mandatory trajectory from flight-model state.
- Provide composable `minimal`, `standard`, `systems`, `avionics`, and `full`
  recording profiles.
- Preserve repeated `--dataref`, `--scale`, and `--comment` CLI customization.
- Add a versioned JSON configuration contract for reusable recorder setup.
- Allow project-owned JSON to declare aircraft- and plugin-specific DataRefs.
- Resolve defaults, JSON, profiles, and CLI overrides deterministically.
- Validate the complete collection plan before connecting or creating output.
- Expose immutable configuration loading through the public Python API.
- Ship a JSON Schema for editor assistance without adding a runtime dependency.

## Non-Goals

- Adding third-party or aircraft-specific built-in profiles.
- Discovering profile providers through entry points.
- Supporting executable configuration, environment interpolation, or includes.
- Putting the output filename or overwrite permission in reusable JSON.
- Guaranteeing that every collected DataRef can be driven during FDR playback.
- Adding per-field sample rates; FDR v4 rows use one recording cadence.
- Reverse-engineering or converting X-Plane `.rep` files.

## Architecture

Two focused modules will be added:

```text
xpwebapi/fdr/
|-- profiles.py    immutable built-in definitions and deterministic composition
`-- config.py      typed JSON loading, validation, and effective-plan resolution
```

Existing modules retain their current responsibilities:

- `cli.py` parses command-line arguments and identifies explicit CLI
  overrides.
- `recorder.py` subscribes and records an already resolved collection plan.
- `writer.py` serializes valid FDR models without knowing about profiles or
  configuration files.

The public `xpwebapi.fdr` namespace will expose `FDRRecordConfig`,
`FDRRecordingProfile`, `load_record_config()`, and read-only profile inspection.
The precise effective-plan merge helper may remain internal because argparse
state is not a reusable library abstraction.

## Mandatory Flight-State Spine

Every recording contains the seven fixed FDR v4 fields. UTC time comes from the
recorder clock. The six numeric fields use actual flight-model state:

| FDR field | Source DataRef | Conversion |
| --- | --- | --- |
| longitude | `sim/flightmodel/position/longitude` | none |
| latitude | `sim/flightmodel/position/latitude` | none |
| altitude MSL, ft | `sim/flightmodel/position/elevation` | metres to feet |
| magnetic heading, degrees | `sim/flightmodel/position/mag_psi` | none |
| pitch, degrees | `sim/flightmodel/position/theta` | none |
| roll, degrees | `sim/flightmodel/position/phi` | none |

The current branch's electrically driven heading, pitch, and roll indicator
sources will be replaced. Instrument power, failures, and display behavior must
not alter the authoritative trajectory used to reconstruct the flight.

All mandatory fields are required. Failure to resolve or initialize one is a
preflight error.

## Built-In Profiles

Profiles contain only stock `sim/...` DataRefs verified against X-Plane 12.
They are ordered immutable manifests. Profile composition retains the first
occurrence of a path and its column position.

### `minimal`

Adds no DREF columns beyond the mandatory flight-state spine.

### `standard`

Adds broadly useful cross-aircraft flight and configuration observations:

- `sim/cockpit2/gauges/indicators/airspeed_kts_pilot`
- `sim/cockpit2/gauges/indicators/true_airspeed_kts_pilot`
- `sim/cockpit2/gauges/indicators/ground_speed_kt`
- `sim/cockpit2/gauges/indicators/altitude_ft_pilot`
- `sim/cockpit2/gauges/indicators/vvi_fpm_pilot`
- `sim/cockpit2/temperature/outside_air_temp_degc`
- `sim/flightmodel/forces/g_axil`
- `sim/flightmodel/forces/g_nrml`
- `sim/flightmodel/forces/g_side`
- `sim/joystick/yoke_pitch_ratio`
- `sim/joystick/yoke_roll_ratio`
- `sim/joystick/yoke_heading_ratio`
- `sim/cockpit2/controls/flap_ratio`
- `sim/cockpit2/controls/speedbrake_ratio`
- `sim/cockpit2/controls/gear_handle_down`
- `sim/flightmodel2/gear/deploy_ratio[0]`
- `sim/flightmodel2/gear/deploy_ratio[1]`
- `sim/flightmodel2/gear/deploy_ratio[2]`

### `systems`

Adds common electrical, fuel, and engine observations for the first two
buses, tanks, and engines:

- `sim/cockpit2/electrical/battery_voltage_indicated_volts[0]`
- `sim/cockpit2/electrical/battery_voltage_indicated_volts[1]`
- `sim/flightmodel/weight/m_fuel[0]`
- `sim/flightmodel/weight/m_fuel[1]`

For each engine index `[0]` and `[1]`, it adds:

- `sim/cockpit2/engine/indicators/fuel_flow_kg_sec`
- `sim/cockpit2/engine/indicators/fuel_pressure_psi`
- `sim/cockpit2/engine/indicators/oil_temperature_deg_C`
- `sim/cockpit2/engine/indicators/oil_pressure_psi`
- `sim/cockpit2/engine/indicators/torque_n_mtr`
- `sim/cockpit2/engine/indicators/prop_speed_rsc`
- `sim/cockpit2/engine/indicators/N1_percent`
- `sim/cockpit2/engine/indicators/N2_percent`
- `sim/cockpit2/engine/indicators/ITT_deg_C`
- `sim/cockpit2/engine/indicators/EGT_deg_C`

The implementation appends the bracketed engine index to each listed base
path. Values that are irrelevant to a particular powerplant may be zero; their
presence keeps the stock profile predictable.

### `avionics`

Adds common instrument, autoflight, navigation, and radio state:

- `sim/cockpit2/gauges/actuators/barometer_setting_in_hg_pilot`
- `sim/cockpit2/autopilot/flight_director_command_bars_pilot`
- `sim/cockpit/autopilot/flight_director_roll`
- `sim/cockpit/autopilot/flight_director_pitch`
- `sim/cockpit/autopilot/autopilot_mode`
- `sim/cockpit2/autopilot/heading_mode`
- `sim/cockpit2/autopilot/altitude_mode`
- `sim/cockpit/autopilot/airspeed`
- `sim/cockpit/autopilot/airspeed_is_mach`
- `sim/cockpit/autopilot/heading_mag`
- `sim/cockpit/autopilot/vertical_velocity`
- `sim/cockpit/autopilot/altitude`
- `sim/cockpit2/radios/actuators/HSI_source_select_pilot`
- `sim/cockpit2/radios/actuators/hsi_obs_deg_mag_pilot`
- `sim/cockpit2/radios/indicators/nav1_hdef_dots_pilot`
- `sim/cockpit2/radios/indicators/nav1_vdef_dots_pilot`
- `sim/cockpit2/radios/actuators/nav1_frequency_hz`
- `sim/cockpit2/radios/actuators/nav2_frequency_hz`
- `sim/cockpit2/radios/actuators/com1_frequency_hz`
- `sim/cockpit2/radios/actuators/com2_frequency_hz`

This profile records observations. It does not add override DataRefs or promise
that X-Plane or an aircraft plugin will accept every observed value during
playback.

### `full`

`full` is deterministic shorthand for the ordered union of `standard`,
`systems`, and `avionics`. It does not create a second copy of those manifests.

### Defaults and availability

`standard` is the default profile when neither JSON nor CLI selects profiles.
An explicitly empty JSON profile list or `minimal` requests only the mandatory
spine. The default sample interval is `0.1` seconds (10 Hz). An omitted duration
records until a graceful interrupt.

Missing mandatory, built-in-profile, or explicitly configured DataRefs are
fatal preflight errors. The recorder will not silently narrow a requested
schema. Stock profiles are intentionally limited to globally registered
X-Plane DataRefs; third-party paths belong in project-owned JSON.

## JSON Configuration Contract

The recorder accepts `--config PATH`. The file is UTF-8 JSON with this shape:

```json
{
  "$schema": "https://tvproductions.github.io/xplane-webapi/schemas/fdr-record-config-v1.schema.json",
  "schema_version": 1,
  "profiles": ["standard", "systems"],
  "connection": {
    "host": "127.0.0.1",
    "port": 8086,
    "api_path": "/api",
    "api_version": "v2"
  },
  "sampling": {
    "interval_seconds": 0.1,
    "duration_seconds": 600
  },
  "metadata": {
    "aircraft_path": "Aircraft/Laminar Research/Cessna 172 SP/Cessna_172SP.acf",
    "tail_number": "N172SP",
    "local_date": "2026-08-08",
    "pressure_in_hg": 29.92,
    "isa_offset_c": 0,
    "wind_direction_deg": 270,
    "wind_speed_kt": 12,
    "comments": ["training configuration"]
  },
  "datarefs": [
    {
      "path": "vendor/aircraft/system/value",
      "scale": 1.0,
      "comment": "Third-party system measurement"
    }
  ]
}
```

`schema_version` is required and must be the integer `1`. `$schema` is optional
and, when present, must be a string. All other sections are optional and use
documented defaults. Unknown properties at every object level are errors.

Each `datarefs` entry requires a valid non-empty `path`. `scale` is optional
and defaults to `1.0`; when present it must be numeric, finite, and not a
boolean. `comment` is optional single-line text. Duplicate paths within one
JSON file are errors.

Connection values reuse the constraints of `WebsocketCaptureConfig`. Sampling
interval and duration must be finite and greater than zero; duration may be
omitted. Dates use ISO `YYYY-MM-DD`. Pressure, ISA offset, wind direction, and
wind speed must be finite; wind direction is in `[0, 360]` and wind speed is
nonnegative. Header comments and DataRef comments must be single-line strings.

The metadata object maps to FDR v4 header records `ACFT`, `TAIL`, `DATE`,
`PRES`, `DISA`, `WIND`, and `COMM`. Metadata omitted from the configuration is
not fabricated, except that the live recorder retains its existing behavior
of supplying the current local calendar date when no date is configured.

The output path and overwrite permission are deliberately absent. They remain
required or explicit CLI concerns so a reusable configuration cannot silently
choose or replace a recording artifact.

The package ships
`xpwebapi/schemas/fdr-record-config-v1.schema.json` as an installed resource.
The schema supports editors and external validators. Runtime loading uses the
standard library and the same typed semantic validation used by the public
Python API; it adds no JSON Schema dependency.

## Deterministic Composition and Precedence

Configuration is resolved in this order:

```text
library defaults < JSON configuration < explicit CLI options
```

DataRef column construction is:

1. Mandatory fixed FDR fields, which are not `DREF` declarations.
2. Profile DataRefs in selected profile order.
3. Custom JSON DataRefs in document order.
4. CLI DataRefs in argument order.

Multiple profiles form an ordered union. A path's first appearance establishes
its column position. Later definitions override only properties they explicitly
supply. Thus a CLI `--dataref` matching a configured path does not erase its
configured scale or comment unless matching `--scale` or `--comment` options
are also supplied. A newly introduced DataRef with no scale uses `1.0` and with
no comment uses no comment.

If one or more CLI `--profile NAME` options are present, their ordered list
replaces the JSON profile list. With no CLI profile option, the JSON selection
applies. With neither, `standard` applies. Profile names are case-sensitive.

Explicit CLI connection, sampling, and local-date values override matching
JSON fields. Metadata without a corresponding CLI flag remains JSON-only in
version 1, preventing a large set of rarely used command-line switches. The
existing repeated `--dataref`, `--scale`, and `--comment` interface remains
supported.

Duplicate DataRefs within the JSON source or within the CLI source are errors.
Duplicates caused by intentional cross-layer overrides are resolved by the
precedence rules above.

## Processing and Failure Semantics

The command completes configuration work before simulator or output side
effects:

1. Parse command-line syntax.
2. Read and parse JSON, if requested.
3. Validate JSON structure and semantics.
4. Resolve profiles, custom DataRefs, and explicit CLI overrides.
5. Validate the complete effective collection plan.
6. Connect to X-Plane and resolve every requested DataRef.
7. Wait for all required initial values.
8. Create the unique partial file and begin recording.

Configuration, profile, resolution, or DataRef preflight failure creates no
final output and no partial output. Once writer setup begins, the existing
partial-file preservation and atomic-commit rules continue to apply.

Invalid JSON reports its line and column. Structural and semantic errors report
the configuration path and a JSON property path, for example:

```text
flight.json: $.sampling.interval_seconds must be greater than zero
flight.json: $.datarefs[2].scale must be a finite number
flight.json: unknown profile "q4xp"
CLI --dataref vendor/value: DataRef is unavailable
```

Library code raises typed configuration or validation exceptions and does not
print. The CLI converts them into concise standard-error diagnostics and a
nonzero exit status.

## Public API

`FDRRecordConfig` is an immutable representation of the versioned semantic
configuration. It can be constructed programmatically or returned by
`load_record_config(path_or_stream)`. As with the existing reader and writer,
the loader owns streams it opens from paths and leaves caller-supplied text
streams open.

`FDRRecordingProfile` exposes a profile name, description, and ordered
`FDRDataref` declarations. Public inspection returns immutable values and does
not permit mutation of package-global manifests.

Library consumers may use these values to build their own recorder interface.
They are not required to instantiate argparse objects or invoke the CLI.

## Documentation

The FDR guide will document:

- the default `standard` profile and 10 Hz cadence;
- each built-in profile and its ordered fields;
- composition and override precedence;
- a complete starter JSON configuration;
- third-party DataRefs declared in project-owned JSON;
- CLI-only output and overwrite safety;
- the distinction between collected observation and guaranteed replay;
- configuration and preflight failure behavior.

CLI help will show `--config` and repeatable `--profile`. The package reference
will list the public immutable configuration and profile APIs. The JSON Schema
will be linked from documentation and included in built distributions.

## Testing and Verification

All automated tests use the repository's approved `unittest` workflow. No
pytest dependency, configuration, fixture, or invocation will be introduced.

Verification covers:

- exact mandatory flight-model DataRef selection and altitude conversion;
- exact contents and order of every built-in profile;
- `full` equivalence to the ordered profile union;
- default `standard` selection and explicit minimal selection;
- deterministic composition and first-position retention;
- strict JSON syntax, types, ranges, unknown fields, and schema versions;
- duplicate JSON and CLI DataRef rejection;
- third-party DataRef declarations;
- field-level cross-layer overrides and scalar CLI precedence;
- configuration-path and JSON-property-path diagnostics;
- missing mandatory, profile, and custom DataRef preflight failure;
- absence of final and partial output on configuration/preflight failure;
- configured metadata mapping into deterministic FDR headers;
- public path/stream ownership behavior;
- packaged JSON Schema availability from wheel and source distribution;
- CLI help and documented examples;
- regression coverage for config-free recording and explicit custom DataRefs.

Live simulator behavior remains an optional integration check. Unit and CLI
tests use injected sources and clocks and do not require X-Plane, a network, or
sleeping.

## Release Scope

This is part of the approved FDR feature release rather than a third-party
plugin system. Built-in profiles are first-party policy over stock X-Plane
DataRefs; arbitrary vendor paths are data supplied through the strict config
contract. Future named third-party profile discovery requires a separate
design and demonstrated need.
