# xpwebapi FDR Toolkit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a supported, independently implemented `xpwebapi.fdr` subpackage and `xpwebapi-fdr` command in `xpwebapi 4.1.0` for strict FDR v3/v4 reading, canonical v4 writing, read-only live recording, and standards-conforming GeoJSON export.

**Architecture:** Keep format models, parsing, serialization, recording, conversion, and CLI orchestration in focused modules under the always-installed `xpwebapi.fdr` subpackage. Version 4 uses a canonical seven-column navigation core plus ordered `DREF`s; legacy version 3 retains its fixed positional schema separately and permits lossy v4 normalization only by explicit opt-in. Live recording composes the existing deadline-bounded read-only capture transport through a neutral observation factory, then streams to a sibling partial file and atomically commits only valid graceful results.

**Tech Stack:** Python 3.12/3.13, standard-library dataclasses/protocols/CSV/JSON/path and time APIs, existing `pydantic` capture configuration, `unittest`, `uv`, Ruff, ty, MkDocs Material, `uv_build`, GitHub Actions, PyPI Trusted Publishing.

## Global Constraints

- Follow `docs/superpowers/specs/2026-08-07-fdr-toolkit-design.md`.
- Tests use `unittest` only. Never add, invoke, suggest, or configure `pytest`.
- Independently implement the feature; do not copy code from `devleaks/xplane-webapi` or GPLv2 `hotbso/xgs`.
- Do not commit Laminar Research's complete example files. Commit only minimal, non-expressive fixtures constructed from documented format facts, with provenance recorded.
- Do not implement an entry-point plugin registry, optional dependency extra, X-Plane launcher, replay controller, landing scorer, KML exporter, OOOI detector, or ACARS reporter.
- Do not expose existing private transport adapter classes through `xpwebapi.fdr`.
- All X-Plane network access remains read-only. Tests must prove the WebSocket client is created with `read_only=True` and no write/command API is reachable through the FDR source.
- All numeric validation rejects booleans and non-finite values.
- Do not invent an absolute UTC date from the unzoned FDR `DATE` field.
- Do not silently discard version 3 legacy-only columns. Lossy v3-to-v4 normalization requires an explicit option and reports omitted fields.
- Canonical v4 output is UTF-8 with LF separators and begins with exact bytes `A\n4\n`.
- Path writes reject existing files unless `overwrite=True`; caller-owned streams are never closed and own their durability.
- A failed live path recording never appears at the requested final path. Preserve a non-empty sibling partial for diagnosis.
- GeoJSON coordinates are two-dimensional `[longitude, latitude]`; MSL altitude belongs in properties, not the coordinate tuple.
- Version declarations, workflow smoke expectations, changelog, and artifact checks all move together to `4.1.0` only after the feature surface is complete.

---

## Public Interfaces

The implementation should converge on this supported surface in `xpwebapi.fdr.__init__`:

```python
from xpwebapi.fdr import (
    FDRDataref,
    FDRHeader,
    FDRLegacyColumn,
    FDRMetadata,
    FDRNormalizationResult,
    FDRParseError,
    FDRRecordResult,
    FDRReader,
    FDRRecorder,
    FDRRecording,
    FDRSample,
    FDRSampleStream,
    FDRSampleSink,
    FDRSampleSource,
    FDRSourceSample,
    FDRValidationError,
    FDRStreamWriter,
    FDRWriter,
    LiveFDRSampleSource,
    recording_to_geojson,
)
```

Core call shapes:

```python
recording = FDRReader().read(path_or_text_stream)

with FDRReader().open(path_or_text_stream) as stream:
    header = stream.header
    for sample in stream:
        consume(sample)

FDRWriter().write(
    recording,
    path_or_text_stream,
    overwrite=False,
    allow_lossy_legacy=False,
)

with FDRWriter().open(header, path, overwrite=False) as sink:
    sink.write_sample(sample)
    sink.commit()

result = FDRRecorder(source=source, sink=sink, clock=clock).record(
    stop_event=stop_event,
    maximum_duration=duration,
)

feature_collection = recording_to_geojson(
    recording,
    first_utc_date=None,
)
```

`FDRReader.open()` returns a context-managed, single-pass `FDRSampleStream`. It closes only streams it opened from paths. `FDRWriter.open()` returns a context-managed `FDRStreamWriter` implementing `FDRSampleSink`; leaving the context without `commit()` aborts the final-name commit and preserves a populated path partial.

---

## File Structure

### Created

- `xpwebapi/fdr/__init__.py`
- `xpwebapi/fdr/errors.py`
- `xpwebapi/fdr/models.py`
- `xpwebapi/fdr/reader.py`
- `xpwebapi/fdr/writer.py`
- `xpwebapi/fdr/recorder.py`
- `xpwebapi/fdr/geojson.py`
- `xpwebapi/fdr/cli.py`
- `tests/fixtures/fdr/README.md`
- `tests/fixtures/fdr/version3-minimal.fdr`
- `tests/fixtures/fdr/version4-minimal.fdr`
- `tests/fixtures/fdr/inherited-recorder-minimal.fdr`
- `tests/test_fdr_fixtures.py`
- `tests/test_fdr_models.py`
- `tests/test_fdr_reader.py`
- `tests/test_fdr_writer.py`
- `tests/test_fdr_geojson.py`
- `tests/test_fdr_recorder.py`
- `tests/test_fdr_cli.py`
- `docs/usage/fdr-toolkit.md`
- `docs/reference/fdr.md`

### Modified

- `xpwebapi/capture_transport.py`
- `tests/test_capture_transport.py`
- `examples/fdr.py`
- `README.md`
- `CHANGELOG.md`
- `docs/usage/index.md`
- `docs/reference/index.md`
- `mkdocs.yml`
- `pyproject.toml`
- `uv.lock`
- `xpwebapi/__init__.py`
- `tools/release.py`
- `tools/installed_smoke.py`
- `tests/test_documentation.py`
- `tests/test_release_metadata.py`
- `tests/test_release_tool.py`
- `.github/workflows/ci.yml`

---

### Task 1: Establish Verified Minimal Format Fixtures

**Files:**
- Create: `tests/fixtures/fdr/README.md`
- Create: `tests/fixtures/fdr/version3-minimal.fdr`
- Create: `tests/fixtures/fdr/version4-minimal.fdr`
- Create: `tests/fixtures/fdr/inherited-recorder-minimal.fdr`
- Create: `tests/test_fdr_fixtures.py`

**Interfaces:**
- Consumes: Laminar's installed `Instructions/FDR Example Version 3.fdr`, the official v3 field documentation, the official v4 sample, and local `examples/fdr.py` output shape.
- Produces: small committed fixtures whose provenance, grammar, line endings, and intended assertions are explicit.

- [ ] **Step 1: Obtain and inspect the official v3 reference before coding its parser**

Locate `Instructions/FDR Example Version 3.fdr` in a licensed X-Plane 12 installation. Record the X-Plane version, source path, first two header lines, record kinds, fixed column count, and navigation-field indices in `tests/fixtures/fdr/README.md`. If the file is unavailable, stop v3 parser work and request the reference file; do not infer the fixed layout from v4 or from an unrelated `.fms` format.

- [ ] **Step 2: Write a failing fixture-contract test**

Create `tests/test_fdr_fixtures.py` with `unittest` assertions for all three fixture names, provenance headings, exact v4 prefix, and the observed v3 fixed width:

```python
class FDRFixtureTests(unittest.TestCase):
    def test_minimal_fixtures_and_provenance_are_committed(self) -> None:
        for name in (
            "version3-minimal.fdr",
            "version4-minimal.fdr",
            "inherited-recorder-minimal.fdr",
        ):
            with self.subTest(name=name):
                self.assertTrue((FIXTURE_ROOT / name).is_file())
        provenance = (FIXTURE_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Laminar Research", provenance)
        self.assertIn("independently minimized", provenance)
```

- [ ] **Step 3: Run the focused test and confirm it fails for missing fixtures**

Run:

```powershell
uv run python -m unittest tests.test_fdr_fixtures -v
```

Expected: failure because the fixture files and provenance note do not exist yet.

- [ ] **Step 4: Construct and document minimal fixtures**

Create two-sample fixtures using factual headers and synthetic coordinates/times. The v4 fixture must include a `DREF` scale and `//` comment. The inherited fixture must retain the inherited recorder's valid mixed-separator/header spacing shape. The v3 fixture must preserve the official fixed width but use synthetic values; do not copy the full official sample.

- [ ] **Step 5: Run the fixture test**

Run the command from Step 3. Expected: PASS.

- [ ] **Step 6: Commit the fixture evidence**

```powershell
git add tests/fixtures/fdr tests/test_fdr_fixtures.py
git commit -m "test: add verified fdr format fixtures"
```

---

### Task 2: Implement Immutable Models and Validation Errors

**Files:**
- Create: `xpwebapi/fdr/errors.py`
- Create: `xpwebapi/fdr/models.py`
- Create: `xpwebapi/fdr/__init__.py`
- Create: `tests/test_fdr_models.py`

**Interfaces:**
- Produces immutable `FDRMetadata`, `FDRDataref`, `FDRLegacyColumn`, `FDRHeader`, `FDRSample`, `FDRRecording`, and `FDRNormalizationResult`.
- Produces `FDRParseError` and `FDRValidationError` with optional source/line context.

- [ ] **Step 1: Write failing model construction and rejection tests**

Cover direct valid construction, ordered duplicate metadata with last-value lookup, dataref scale/comment preservation, day rollover duration, explicit UTC-date resolution, invalid coordinates, booleans, NaN/infinity, duplicate DataRef paths, duplicate legacy column identifiers, additional-value width mismatch, and backward time-of-day handling.

Representative contract:

```python
sample = FDRSample(
    time_utc=time(23, 59, 59, 500000),
    longitude=-87.9048,
    latitude=41.9742,
    altitude_msl_ft=640.0,
    heading_magnetic_deg=270.0,
    pitch_deg=2.0,
    roll_deg=-1.0,
    additional_values=(0.75,),
    legacy_values=(),
)
self.assertEqual(timedelta(seconds=2), recording.duration)
```

- [ ] **Step 2: Run the model tests and confirm import failure**

```powershell
uv run python -m unittest tests.test_fdr_models -v
```

Expected: ERROR because `xpwebapi.fdr` does not exist.

- [ ] **Step 3: Implement public errors and strict dataclasses**

Use frozen, slotted dataclasses and shared validators in `models.py`. Store metadata and values as tuples. Validate with `type(value) in {int, float}` before finite checks so booleans are rejected. Expose:

```python
@dataclass(frozen=True, slots=True)
class FDRHeader:
    source_version: Literal[3, 4]
    source_origin: Literal["A", "I"]
    comments: tuple[str, ...]
    metadata: tuple[FDRMetadata, ...]
    datarefs: tuple[FDRDataref, ...]
    legacy_columns: tuple[FDRLegacyColumn, ...]
    local_date: date | None

    def metadata_value(self, key: str) -> str | None: ...

class FDRRecording:
    header: FDRHeader
    samples: tuple[FDRSample, ...]

    @property
    def duration(self) -> timedelta: ...
    def resolved_utc_datetimes(self, first_utc_date: date) -> tuple[datetime, ...]: ...
    def normalized_v4(
        self,
        *,
        allow_lossy_legacy: bool = False,
    ) -> FDRNormalizationResult: ...
```

For v3, retain every fixed value in `legacy_values` aligned with `legacy_columns`. `normalized_v4()` raises by default when legacy-only values would be omitted. With explicit opt-in it returns `FDRNormalizationResult(recording=..., omitted_legacy_field_ids=...)`.

- [ ] **Step 4: Export only the completed model/error surface**

Populate `xpwebapi/fdr/__init__.py` with explicit `__all__`; do not export unfinished reader/writer names yet.

- [ ] **Step 5: Run focused tests and static checks**

```powershell
uv run python -m unittest tests.test_fdr_models -v
uv run ruff check xpwebapi/fdr tests/test_fdr_models.py
uv run ruff format --check xpwebapi/fdr tests/test_fdr_models.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add xpwebapi/fdr tests/test_fdr_models.py
git commit -m "feat: add strict fdr data model"
```

---

### Task 3: Parse and Stream Version 4 Recordings

**Files:**
- Create: `xpwebapi/fdr/reader.py`
- Create: `tests/test_fdr_reader.py`
- Modify: `xpwebapi/fdr/__init__.py`

**Interfaces:**
- Produces `FDRReader.read(source)` and context-managed `FDRReader.open(source)`.
- Produces line-numbered `FDRParseError` for text/grammar failures and `FDRValidationError` for model failures.

- [ ] **Step 1: Write failing v4 reader tests**

Cover paths and `StringIO`, ownership/close behavior, `A` and `I`, `4` and `4 Version`, CR/LF/CRLF, whitespace, ordered `COMM`, known/unknown/duplicate four-character metadata, `DREF` scale/comments, optional column comments, exact sample width, malformed timestamps/numbers, duplicate DREF paths, and streaming without materializing all samples.

```python
with FDRReader().open(StringIO(V4_TEXT)) as stream:
    self.assertEqual(4, stream.header.source_version)
    self.assertEqual("custom", stream.header.metadata_value("ZZZZ"))
    samples = tuple(stream)
self.assertEqual(2, len(samples))
```

- [ ] **Step 2: Run the reader tests and confirm missing reader failures**

```powershell
uv run python -m unittest tests.test_fdr_reader -v
```

- [ ] **Step 3: Implement incremental lexical parsing**

Read with `newline=None` from owned path streams. Wrap caller streams in a non-owning chunked line normalizer so bare CR, LF, and CRLF are accepted without materializing the entire input. Parse record kind plus comma-separated payload without treating free-text comments as CSV schema. Parse version with a leading integer regex. Build the header before yielding samples. Normalize errors to:

```text
<source>:<line>: <concise explanation>
```

- [ ] **Step 4: Implement stream ownership and full-read composition**

The stream closes owned path handles on exit and never closes caller streams. `read()` consumes `open()` and returns one validated `FDRRecording`, avoiding a second parser.

- [ ] **Step 5: Run reader/model tests and lint**

```powershell
uv run python -m unittest tests.test_fdr_models tests.test_fdr_reader -v
uv run ruff check xpwebapi/fdr tests/test_fdr_reader.py
uv run ruff format --check xpwebapi/fdr tests/test_fdr_reader.py
```

- [ ] **Step 6: Commit**

```powershell
git add xpwebapi/fdr tests/test_fdr_reader.py
git commit -m "feat: parse fdr version 4 recordings"
```

---

### Task 4: Add Verified Legacy Version 3 Parsing

**Files:**
- Modify: `xpwebapi/fdr/reader.py`
- Modify: `xpwebapi/fdr/models.py`
- Modify: `tests/test_fdr_reader.py`
- Modify: `tests/test_fdr_models.py`

**Interfaces:**
- Consumes the exact v3 fixed schema documented in Task 1.
- Produces common navigation fields plus aligned `FDRLegacyColumn`/`legacy_values` preservation.

- [ ] **Step 1: Add failing v3 fixture and malformed-width tests**

Assert the official fixed width observed in Task 1, documented navigation index mapping, `TIME` metadata plus elapsed-seconds resolution, midnight rollover, version suffix support, retained legacy values, line-numbered malformed rows, and explicit lossy normalization behavior.

- [ ] **Step 2: Run focused tests and confirm v3 rejection**

```powershell
uv run python -m unittest tests.test_fdr_reader.FDRReaderTests.test_reads_verified_version3_fixture tests.test_fdr_models -v
```

Expected: failure because only v4 parsing is implemented.

- [ ] **Step 3: Implement a separate v3 grammar branch**

Keep the fixed legacy schema as a named tuple constant backed by the verified fixture documentation. Do not route v3 rows through `7 + len(datarefs)`. Require valid v3 `TIME` metadata, resolve its first fixed field as elapsed seconds from that Zulu start time, and map only documented longitude, latitude, MSL altitude, magnetic heading, pitch, and roll indices to common fields. Preserve all fixed values separately.

- [ ] **Step 4: Enforce explicit lossy conversion**

`recording.normalized_v4()` must raise `FDRValidationError` when legacy-only values exist unless `allow_lossy_legacy=True`. The opt-in result must identify omitted legacy fields so CLI/library callers can report them.

- [ ] **Step 5: Run all FDR parsing/model tests**

```powershell
uv run python -m unittest tests.test_fdr_fixtures tests.test_fdr_models tests.test_fdr_reader -v
```

- [ ] **Step 6: Commit**

```powershell
git add xpwebapi/fdr tests/test_fdr_reader.py tests/test_fdr_models.py
git commit -m "feat: parse legacy fdr version 3"
```

---

### Task 5: Write Canonical Version 4 Atomically and Incrementally

**Files:**
- Create: `xpwebapi/fdr/writer.py`
- Create: `tests/test_fdr_writer.py`
- Modify: `xpwebapi/fdr/__init__.py`

**Interfaces:**
- Produces `FDRWriter.write()` for complete recordings.
- Produces `FDRWriter.open()` and `FDRStreamWriter.write_sample()/commit()/abort()`.
- `FDRStreamWriter` satisfies `FDRSampleSink` once that protocol is introduced.

- [ ] **Step 1: Write failing deterministic writer tests**

Cover exact `A\n4\n`, LF-only output, UTF-8, stable metadata/comment/DREF ordering, stable finite float rendering, direct-stream ownership, width validation, write/read round trip, v3 refusal and explicit lossy write, existing-target rejection, overwrite behavior, and no final-name commit before completion.

- [ ] **Step 2: Run writer tests and confirm missing writer errors**

```powershell
uv run python -m unittest tests.test_fdr_writer -v
```

- [ ] **Step 3: Implement one canonical serializer**

Both complete and streaming writes must call the same header and sample rendering helpers. Never call `datetime.now()`, read environment variables, sort caller-provided metadata, or infer field order.

- [ ] **Step 4: Implement durable path commit semantics**

Create a unique sibling `.<destination>.<token>.partial` with exclusive creation. On commit after at least one sample: flush, `os.fsync()`, close, then use a no-replace same-volume link/rename strategy when `overwrite=False`, or `os.replace()` when `overwrite=True`. On failure preserve a non-empty partial and never create the final name. Streams only flush; they are not closed or fsynced by the writer.

- [ ] **Step 5: Run writer/reader tests and checks**

```powershell
uv run python -m unittest tests.test_fdr_reader tests.test_fdr_writer -v
uv run ruff check xpwebapi/fdr tests/test_fdr_writer.py
uv run ruff format --check xpwebapi/fdr tests/test_fdr_writer.py
```

- [ ] **Step 6: Commit**

```powershell
git add xpwebapi/fdr tests/test_fdr_writer.py
git commit -m "feat: write canonical fdr version 4"
```

---

### Task 6: Export Standards-Conforming GeoJSON

**Files:**
- Create: `xpwebapi/fdr/geojson.py`
- Create: `tests/test_fdr_geojson.py`
- Modify: `xpwebapi/fdr/__init__.py`

**Interfaces:**
- Produces `recording_to_geojson(recording, *, first_utc_date=None) -> dict[str, object]`.

- [ ] **Step 1: Write failing GeoJSON tests**

Assert `FeatureCollection`, point `properties` as a geometry sibling, `[lon, lat]` only, `altitude_msl_ft`, `altitude_msl_m`, heading/pitch/roll, ordered optional values keyed by DataRef path, UTC time-of-day, absent absolute timestamps by default, RFC 3339 `Z` timestamps with explicit UTC date, no path for fewer than two points, `LineString` normally, and `MultiLineString` at the antimeridian.

- [ ] **Step 2: Run tests and confirm missing converter failure**

```powershell
uv run python -m unittest tests.test_fdr_geojson -v
```

- [ ] **Step 3: Implement point features and optional absolute time**

Return JSON-compatible built-ins only. Convert feet to metres with exact factor `0.3048`. Resolve rollovers through the recording model rather than duplicating time logic.

- [ ] **Step 4: Implement antimeridian-safe path splitting**

When consecutive longitude delta magnitude exceeds 180 degrees, interpolate the boundary latitude, close the current segment at `+180` or `-180`, and begin the next at the opposite boundary. Ensure every child line has at least two positions.

- [ ] **Step 5: Run focused tests and serialize with strict JSON**

```powershell
uv run python -m unittest tests.test_fdr_geojson -v
uv run python -c "import json; from pathlib import Path; from xpwebapi.fdr import FDRReader, recording_to_geojson; r=FDRReader().read(Path('tests/fixtures/fdr/version4-minimal.fdr')); json.dumps(recording_to_geojson(r), allow_nan=False)"
```

- [ ] **Step 6: Commit**

```powershell
git add xpwebapi/fdr tests/test_fdr_geojson.py
git commit -m "feat: export fdr recordings to geojson"
```

---

### Task 7: Extract a Neutral Read-Only Observation Factory

**Files:**
- Modify: `xpwebapi/capture_transport.py`
- Modify: `tests/test_capture_transport.py`
- Create: `tests/test_fdr_recorder.py`
- Create: `xpwebapi/fdr/recorder.py`

**Interfaces:**
- Preserves `create_capture_transport(request, ...) -> CaptureTransport` unchanged.
- Adds an internal/public-at-module-level `create_observation_transport(config, *, identity_refs=(), subscription_timeout_seconds, ...) -> CaptureTransport` used by both capture and FDR code.
- Begins `LiveFDRSampleSource`, but does not yet implement final recording/commit behavior.

- [ ] **Step 1: Write capture regression tests before refactoring**

Add assertions that the existing factory delegates equivalent config, identity gating, timeout, WebSocket, UDP, close, and callback behavior. Confirm all existing capture tests remain unchanged at their public call sites.

- [ ] **Step 2: Write failing live-source tests with fake WebSocket clients**

Assert standard mandatory DataRefs plus declared optionals are subscribed, missing required refs fail before sampling, optional refs may be rejected, values are sampled at the injected cadence, altitude metres convert to feet, snapshots use injected aware UTC time, and constructed clients receive `read_only=True`.

- [ ] **Step 3: Run both focused modules and capture the baseline**

```powershell
uv run python -m unittest tests.test_capture_transport tests.test_fdr_recorder -v
```

Expected: existing capture tests pass; new FDR live-source tests fail.

- [ ] **Step 4: Refactor transport constructors around neutral inputs**

Change private adapters to accept transport config, identity refs, and subscription timeout directly instead of the full Q4XP-specific `CaptureRequest`. Implement `create_observation_transport()`. Make `create_capture_transport()` a compatibility wrapper. Empty identity refs allow immediate capture-purpose subscriptions; non-empty refs retain current gating.

- [ ] **Step 5: Implement source/protocol primitives**

In `recorder.py`, add:

```python
@dataclass(frozen=True, slots=True)
class FDRSourceSample:
    timestamp_utc: datetime
    values: Mapping[str, float]

class FDRSampleSource(Protocol):
    @property
    def header(self) -> FDRHeader: ...
    def samples(self, stop_event: threading.Event) -> Iterator[FDRSourceSample]: ...
    def close(self) -> None: ...

class FDRSampleSink(Protocol):
    def write_sample(self, sample: FDRSample) -> None: ...
```

Implement `LiveFDRSampleSource` using only `CaptureTransport`, `Observation`, `CaptureRef`, and the neutral factory. Do not import `_WebsocketCaptureTransport`.

- [ ] **Step 6: Run capture and FDR source tests**

```powershell
uv run python -m unittest tests.test_capture_transport tests.test_capture_runner tests.test_fdr_recorder -v
```

- [ ] **Step 7: Commit**

```powershell
git add xpwebapi/capture_transport.py xpwebapi/fdr/recorder.py tests/test_capture_transport.py tests/test_fdr_recorder.py
git commit -m "refactor: share read-only observation transport"
```

---

### Task 8: Implement Recorder Composition and Failure-Safe Partials

**Files:**
- Modify: `xpwebapi/fdr/recorder.py`
- Modify: `xpwebapi/fdr/writer.py`
- Modify: `xpwebapi/fdr/__init__.py`
- Modify: `tests/test_fdr_recorder.py`
- Modify: `tests/test_fdr_writer.py`

**Interfaces:**
- Produces `FDRRecorder.record()` and immutable `FDRRecordResult`.
- Makes `FDRStreamWriter` conform to `FDRSampleSink`.

- [ ] **Step 1: Add failing synthetic recorder tests**

Use fake clocks/sources/sinks; never sleep or open sockets. Cover source-to-sample mapping, cadence, bounded duration, stop event, graceful interrupt, at least one sample requirement, invalid/missing snapshot handling, optional DataRef ordering, cleanup deadlines, source/sink close errors, valid final commit, preserved partial on failure, and absence of final name on failure.

- [ ] **Step 2: Run recorder tests and confirm missing engine behavior**

```powershell
uv run python -m unittest tests.test_fdr_recorder -v
```

- [ ] **Step 3: Implement deterministic snapshot mapping**

Define named mandatory source keys and one conversion helper. Use source UTC timestamps for FDR time-of-day, convert elevation metres to MSL feet, and align optional values to header DataRef order. Reject incomplete or non-finite snapshots before they reach the sink.

- [ ] **Step 4: Implement lifecycle and result semantics**

`record()` owns no global signal handlers. It observes the supplied stop event and duration, closes the source in `finally`, commits only after graceful completion with at least one sample, and returns sample count/start/end/duration/termination plus partial/final paths where applicable.

- [ ] **Step 5: Run recorder/writer/capture regression tests**

```powershell
uv run python -m unittest tests.test_fdr_writer tests.test_fdr_recorder tests.test_capture_transport tests.test_capture_runner -v
```

- [ ] **Step 6: Commit**

```powershell
git add xpwebapi/fdr tests/test_fdr_recorder.py tests/test_fdr_writer.py
git commit -m "feat: record fdr streams safely"
```

---

### Task 9: Add the `xpwebapi-fdr` Command

**Files:**
- Create: `xpwebapi/fdr/cli.py`
- Create: `tests/test_fdr_cli.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Adds `xpwebapi-fdr = "xpwebapi.fdr.cli:main"`.
- Adds `record`, `inspect`, `validate`, and `to-geojson` subcommands.

- [ ] **Step 1: Write failing parser and command tests**

Lock these command shapes:

```text
xpwebapi-fdr validate INPUT
xpwebapi-fdr inspect INPUT [--json] [--first-utc-date YYYY-MM-DD]
xpwebapi-fdr to-geojson INPUT OUTPUT [--first-utc-date YYYY-MM-DD] [--overwrite]
xpwebapi-fdr record OUTPUT [--host HOST] [--port PORT] [--api-path PATH]
    [--api-version VERSION] [--interval SECONDS] [--duration SECONDS]
    [--local-date YYYY-MM-DD] [--dataref PATH] [--scale PATH=FLOAT]
    [--comment PATH=TEXT] [--overwrite]
```

Test success output, invalid input, connection failure, overwrite protection, option relationships, JSON-only stdout for `--json`, human output, diagnostics only on stderr, interruption exit 130, and no final output on recording failure.

- [ ] **Step 2: Run CLI tests and confirm import/entry-point failures**

```powershell
uv run python -m unittest tests.test_fdr_cli -v
```

- [ ] **Step 3: Implement argparse and thin command handlers**

Command handlers call only public reader/writer/recorder/GeoJSON behavior. `validate` emits no stdout on success. `inspect --json` uses `allow_nan=False`, sorted keys, compact separators, and one LF. `to-geojson` writes through a sibling temporary and atomic commit. `record` installs signal handlers only in the CLI layer.

- [ ] **Step 4: Add and lock the console script**

Add the project script, then run:

```powershell
uv lock
uv sync --frozen
uv run xpwebapi-fdr --help
```

- [ ] **Step 5: Run CLI plus library tests**

```powershell
uv run python -m unittest tests.test_fdr_cli tests.test_fdr_reader tests.test_fdr_writer tests.test_fdr_recorder tests.test_fdr_geojson -v
```

- [ ] **Step 6: Commit**

```powershell
git add xpwebapi/fdr/cli.py tests/test_fdr_cli.py pyproject.toml uv.lock
git commit -m "feat: add fdr command line toolkit"
```

---

### Task 10: Publish Documentation, Thin Example, and Version 4.1.0 Contracts

**Files:**
- Create: `docs/usage/fdr-toolkit.md`
- Create: `docs/reference/fdr.md`
- Modify: `examples/fdr.py`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/usage/index.md`
- Modify: `docs/reference/index.md`
- Modify: `mkdocs.yml`
- Modify: `tests/test_documentation.py`
- Modify: `pyproject.toml`
- Modify: `xpwebapi/__init__.py`
- Modify: `tests/test_release_metadata.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Documents subpackage/module/extra/extension/companion/native-plugin terminology.
- Declares distribution/runtime/workflow version `4.1.0`.

- [ ] **Step 1: Write failing documentation and version-contract tests**

Assert MkDocs navigation links, API directive `::: xpwebapi.fdr`, all four CLI subcommands, GeoJSON MSL/2D behavior, v3 lossy warning, downstream onboarding workflow, read-only live behavior, partial-file recovery, terminology distinctions, no claim that examples are plugins, and synchronized `4.1.0` metadata/runtime/workflow smoke version.

- [ ] **Step 2: Run focused tests and confirm missing docs/version failures**

```powershell
uv run python -m unittest tests.test_documentation tests.test_release_metadata -v
```

- [ ] **Step 3: Write user and reference documentation**

Show offline fixture construction, validation, GeoJSON conversion, live recording, custom source/sink composition, and the dependent native-plugin test workflow. Explain that playback/orchestration and plugin-output assertions remain consumer responsibilities.

- [ ] **Step 4: Reduce `examples/fdr.py` to a supported API consumer**

Remove its custom WebSocket lifecycle, serializer, hard-coded year, direct `sys.path` modification, and private buffering. Keep it as a small executable example that imports `xpwebapi.fdr` and delegates to the supported command/library.

- [ ] **Step 5: Bump version and changelog together**

Set `pyproject.toml` and `xpwebapi.__version__`/`version` to `4.1.0`, update the CI installed-smoke literal to `4.1.0`, add a dated `4.1.0` changelog entry, and run `uv lock`.

- [ ] **Step 6: Build docs strictly and run focused tests**

```powershell
uv run python -m unittest tests.test_documentation tests.test_release_metadata -v
uv run mkdocs build --strict
```

- [ ] **Step 7: Commit**

```powershell
git add README.md CHANGELOG.md docs examples/fdr.py mkdocs.yml pyproject.toml uv.lock xpwebapi/__init__.py tests/test_documentation.py tests/test_release_metadata.py .github/workflows/ci.yml
git commit -m "docs: publish fdr toolkit guidance"
```

---

### Task 11: Verify Installed Artifacts and Release Readiness

**Files:**
- Modify: `tools/release.py`
- Modify: `tools/installed_smoke.py`
- Modify: `tests/test_release_tool.py`
- Modify: `.github/workflows/release.yml` only if the generic tag workflow requires a new FDR smoke assertion.

**Interfaces:**
- Requires the built wheel/sdist to contain the complete `xpwebapi/fdr` subpackage.
- Requires the installed wheel to import the public API and execute `xpwebapi-fdr validate` and `to-geojson` outside the checkout.

- [ ] **Step 1: Write failing archive and installed-command tests**

Extend release fixtures to require every FDR module in wheel and sdist. Update `VERSION` to `4.1.0`. Extend installed smoke mocks to locate both interpreter-local commands and validate a packaged minimal FDR input plus GeoJSON output.

- [ ] **Step 2: Run release tests and confirm missing requirements**

```powershell
uv run python -m unittest tests.test_release_tool -v
```

- [ ] **Step 3: Extend release and installed-smoke tooling**

Make `tools/release.py` require the FDR module set. Make `tools/installed_smoke.py` import the public names, create a temporary minimal v4 input, run interpreter-local `xpwebapi-fdr validate`, run `to-geojson`, parse the result, and retain the existing capture CLI/schema checks.

- [ ] **Step 4: Run the complete repository quality gate**

```powershell
uv sync --frozen
uv run python -m unittest discover -v
uv run ruff check .
uv run ruff format --check .
uv run python tools/quality.py check
uv run mkdocs build --strict
```

Expected: all commands PASS. Do not substitute another test runner.

- [ ] **Step 5: Build and validate immutable artifacts**

Use a clean `dist/` prepared according to repository release practice, then run:

```powershell
uv build --no-sources
uv tool run twine check --strict dist/*
uv run python tools/release.py check-dist dist
```

- [ ] **Step 6: Smoke-test the wheel on Python 3.12 and 3.13**

Create isolated virtual environments outside the source checkout, install the exact built wheel, and run `tools/installed_smoke.py 4.1.0` with both interpreters. Confirm the FDR command resolves from each interpreter's scripts directory.

- [ ] **Step 7: Review the final diff for forbidden scope and placeholders**

Search for `TODO`, `FIXME`, `NotImplementedError`, copied upstream snippets, `pytest`, private transport imports from `xpwebapi.fdr`, non-2D GeoJSON coordinates, old `4.0.0` release literals, and accidental full official fixtures. Resolve every hit or document why it is valid.

- [ ] **Step 8: Commit release verification changes**

```powershell
git add tools/release.py tools/installed_smoke.py tests/test_release_tool.py .github/workflows/release.yml
git commit -m "build: verify fdr release artifacts"
```

- [ ] **Step 9: Run final branch verification and request code review**

Re-run the complete commands from Steps 4-6 after the final commit. Use the repository's `requesting-code-review` workflow. Do not tag, push, or publish until review is resolved and the user explicitly authorizes the release operation.

---

## Completion Criteria

- `xpwebapi.fdr` imports from an installed 4.1.0 wheel on Python 3.12 and 3.13.
- Verified v3 and v4 fixtures parse; v3 legacy fields are retained and lossy normalization is explicit.
- Canonical v4 output is deterministic, round-trips, and starts with exact bytes `A\n4\n`.
- Live recording uses the shared read-only observation transport and is fully testable with injected fakes.
- Failed recording leaves no final-name artifact; graceful recording commits only after flush/fsync.
- GeoJSON validates structurally, uses 2D coordinates, exposes MSL altitude properties, and splits antimeridian crossings.
- `xpwebapi-fdr record|inspect|validate|to-geojson` obey stream and overwrite contracts.
- README/MkDocs explain terminology, composition, and downstream plugin-testing boundaries.
- Full `unittest` discovery, repository quality, strict docs, distribution validation, and installed-wheel smoke checks pass.
- No push, tag, PyPI publication, or GitHub release occurs without explicit user authorization.
