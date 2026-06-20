# Custom Exception Hierarchy Completion

**Date:** 2026-06-20
**Priority:** P0 — Critical
**Status:** Approved

## Goal

Complete the custom exception hierarchy by adding `XPPacketError` for malformed protocol packets and enriching existing raises with typed context kwargs.

## Background

The exception hierarchy was introduced in commits `5076fbf` and `148437b` with:
- `XPWebAPIError` base class with `**context` kwargs support
- `XPConnectionError`, `XPBeaconError`, `XPTimeoutError`, `XPVersionError` subclasses
- Legacy backward-compatible aliases (`XPlaneNoBeacon`, `XPlaneVersionNotSupported`, `XPlaneTimeout`)

Remaining gaps:
- Two `ValueError` raises in `udp.py` (lines 204, 308) for invalid DREF/RREF packet lengths are not using the hierarchy
- `XPlaneTimeout` raise in `udp.py:358` lacks context kwargs (no `host`, `port`)

## Design

### Hierarchy (Updated)

```
Exception
  └── XPWebAPIError              (existing — base, **context kwargs)
        ├── XPConnectionError    (existing)
        │     └── XPBeaconError  (existing)
        ├── XPTimeoutError       (existing)
        ├── XPVersionError       (existing)
        └── XPPacketError        (NEW — malformed protocol packets)
```

### Changes

#### 1. `xpwebapi/exceptions.py`

Add `XPPacketError(XPWebAPIError)`:

```python
class XPPacketError(XPWebAPIError):
    pass
```

#### 2. `xpwebapi/udp.py:204`

Replace `ValueError` with typed exception:

```python
# before
raise ValueError(f"invalid DREF packet length: {len(message)}")

# after
raise XPPacketError("invalid DREF packet length", packet_type="DREF", expected=509, actual=len(message))
```

#### 3. `xpwebapi/udp.py:308`

Same pattern for RREF:

```python
# before
raise ValueError(f"invalid RREF packet length: {len(message)}")

# after
raise XPPacketError("invalid RREF packet length", packet_type="RREF", expected=413, actual=len(message))
```

#### 4. `xpwebapi/udp.py:358`

Add context to bare `XPlaneTimeout`:

```python
# before
raise XPlaneTimeout("UDP read timeout")

# after
raise XPlaneTimeout("UDP read timeout", host=self.host, port=self.port)
```

#### 5. `xpwebapi/__init__.py`

Export `XPPacketError` in imports and `__all__`.

#### 6. `tests/test_exceptions.py`

Add tests for:
- `XPPacketError` is subclass of `XPWebAPIError`
- `XPPacketError` context kwargs (`packet_type`, `expected`, `actual`)
- Backward compat: `XPPacketError` importable from package root

### Not Changing

- `NotImplementedError` in `api.py:428` — standard Python pattern for abstract methods
- Catch-all `except Exception:` patterns — intentional resilience for threads, callbacks, decode operations
- Legacy exception aliases — no deprecation warnings at this time

## Testing

All changes must pass:
```bash
uv run python -m unittest discover -v
```

New tests verify:
- `XPPacketError` inheritance and context
- Existing `XPlaneTimeout` raise now carries `host` and `port` context

## Success Criteria

- [ ] All `raise` statements in library code use the custom exception hierarchy
- [ ] All typed exceptions carry relevant context kwargs
- [ ] Tests pass
- [ ] No breaking changes to public API (legacy aliases still work)
