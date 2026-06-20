# Custom Exception Hierarchy Completion Implementation Plan

**Goal:** Complete the exception hierarchy from `docs/superpowers/specs/2026-06-20-custom-exception-hierarchy-design.md` by adding `XPPacketError`, replacing UDP packet `ValueError` raises, and enriching UDP timeout context.

**Design:** See `docs/superpowers/specs/2026-06-20-custom-exception-hierarchy-design.md`.

**Constraints:**

- Preserve all existing public exception names and imports.
- Keep tests on stdlib `unittest`.
- Do not modify `examples/`.
- Keep the change scoped to exception exports, UDP raise sites, and tests.
- Do not add deprecation warnings for legacy aliases.

---

## Task 1: Add Packet Exception Tests

**Files:**
- Modify: `tests/test_exceptions.py`

**Interfaces:**
- Consumes `XPWebAPIError`
- Produces expected coverage for `XPPacketError`

- [ ] **Step 1: Update exception imports**

Add `XPPacketError` to the import from `xpwebapi.exceptions`.

- [ ] **Step 2: Add hierarchy test**

Add a test asserting:

```python
self.assertTrue(issubclass(XPPacketError, XPWebAPIError))
```

- [ ] **Step 3: Add context kwargs test**

Add a test that constructs:

```python
err = XPPacketError("invalid DREF packet length", packet_type="DREF", expected=509, actual=12)
```

Assert:

- `str(err) == "invalid DREF packet length"`
- `err.context == {"packet_type": "DREF", "expected": 509, "actual": 12}`

- [ ] **Step 4: Add package root import test**

Extend the existing package export test to import `XPPacketError` from `xpwebapi` and assert it is an exception subclass.

- [ ] **Step 5: Run targeted tests and confirm failure**

```powershell
uv run python -m unittest tests.test_exceptions -v
```

Expected: fails until `XPPacketError` exists and is exported.

---

## Task 2: Add UDP Exception Behavior Tests

**Files:**
- Modify: `tests/test_udp.py`

**Interfaces:**
- Consumes `XPUDPAPI`, `XPlaneTimeout`, `XPPacketError`

- [ ] **Step 1: Import `XPPacketError`**

Add:

```python
from xpwebapi.exceptions import XPPacketError
```

- [ ] **Step 2: Add DREF packet length error test**

Patch `xpwebapi.udp.struct.pack` so the DREF branch returns a deliberately malformed byte string. Then call `api.write_dataref(dataref)` and assert:

- `XPPacketError` is raised
- `err.context["packet_type"] == "DREF"`
- `err.context["expected"] == 509`
- `err.context["actual"]` matches the malformed byte length

- [ ] **Step 3: Add RREF packet length error test**

Patch `xpwebapi.udp.struct.pack` so the RREF request branch returns a deliberately malformed byte string. With `connected` patched to `True`, call:

```python
api._request_dataref("sim/test/value", freq=2)
```

Assert:

- `XPPacketError` is raised
- `err.context["packet_type"] == "RREF"`
- `err.context["expected"] == 413`
- `err.context["actual"]` matches the malformed byte length

- [ ] **Step 4: Add UDP timeout context test**

Extend the existing timeout test to capture the raised exception:

```python
with self.assertRaises(XPlaneTimeout) as caught:
    api.read_monitored_dataref_values()
```

Assert:

- `caught.exception.context["host"] == "127.0.0.1"`
- `caught.exception.context["port"] == 49000`

- [ ] **Step 5: Run targeted tests and confirm failure**

```powershell
uv run python -m unittest tests.test_udp -v
```

Expected: fails until UDP raise sites use `XPPacketError` and timeout context.

---

## Task 3: Implement `XPPacketError`

**Files:**
- Modify: `xpwebapi/exceptions.py`
- Modify: `xpwebapi/__init__.py`

**Interfaces:**
- Produces `XPPacketError`
- Preserves existing `XPWebAPIError`, `XPConnectionError`, `XPBeaconError`, `XPTimeoutError`, and `XPVersionError`

- [ ] **Step 1: Add exception subclass**

In `xpwebapi/exceptions.py`, add:

```python
class XPPacketError(XPWebAPIError):
    pass
```

- [ ] **Step 2: Export from package root**

Update `xpwebapi/__init__.py` to import `XPPacketError` from `.exceptions`.

- [ ] **Step 3: Add to `__all__`**

Add `"XPPacketError"` to `__all__` near the other custom exception names.

- [ ] **Step 4: Verify exception tests**

```powershell
uv run python -m unittest tests.test_exceptions -v
```

Expected: exception tests pass.

---

## Task 4: Replace UDP Packet `ValueError` Raises

**Files:**
- Modify: `xpwebapi/udp.py`

**Interfaces:**
- Consumes `XPPacketError`
- Preserves `XPlaneTimeout(XPTimeoutError)` legacy alias

- [ ] **Step 1: Update imports**

Change the exception import to include `XPPacketError`:

```python
from .exceptions import XPPacketError, XPTimeoutError
```

- [ ] **Step 2: Replace DREF packet length raise**

Replace:

```python
raise ValueError(f"invalid DREF packet length: {len(message)}")
```

with:

```python
raise XPPacketError("invalid DREF packet length", packet_type="DREF", expected=509, actual=len(message))
```

- [ ] **Step 3: Replace RREF packet length raise**

Replace:

```python
raise ValueError(f"invalid RREF packet length: {len(message)}")
```

with:

```python
raise XPPacketError("invalid RREF packet length", packet_type="RREF", expected=413, actual=len(message))
```

- [ ] **Step 4: Add timeout context**

Replace:

```python
raise XPlaneTimeout("UDP read timeout")
```

with:

```python
raise XPlaneTimeout("UDP read timeout", host=self.host, port=self.port)
```

- [ ] **Step 5: Verify UDP tests**

```powershell
uv run python -m unittest tests.test_udp -v
```

Expected: UDP tests pass.

---

## Task 5: Regression Verification

**Files:** None unless formatting changes are needed.

- [ ] **Step 1: Verify exception and UDP tests**

```powershell
uv run python -m unittest tests.test_exceptions tests.test_udp -v
```

- [ ] **Step 2: Run full unittest suite**

```powershell
uv run python -m unittest discover -v
```

- [ ] **Step 3: Run lint**

```powershell
uv run ruff check xpwebapi tests
```

- [ ] **Step 4: Run format check**

```powershell
uv run ruff format --check xpwebapi tests
```

- [ ] **Step 5: Verify package import**

```powershell
uv run python -c "import xpwebapi; print(xpwebapi.version)"
```

Expected: `3.5.0`

- [ ] **Step 6: Confirm no remaining packet `ValueError` raises**

```powershell
rg "raise ValueError|XPPacketError|XPlaneTimeout\\(\"UDP read timeout\"" xpwebapi tests
```

Expected:

- No UDP malformed packet length `ValueError` raises remain.
- `XPPacketError` appears in `exceptions.py`, `__init__.py`, `udp.py`, and tests.
- UDP timeout raise includes `host` and `port` context.
