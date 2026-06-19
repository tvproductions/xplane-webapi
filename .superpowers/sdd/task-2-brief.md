### Task 2: Backward Compatibility Aliases + Call Site Updates

**Files:**
- Modify: `xpwebapi/beacon.py`
- Modify: `xpwebapi/udp.py`
- Modify: `xpwebapi/__init__.py`
- Modify: `tests/test_exceptions.py`

**Interfaces:**
- Consumes: `XPBeaconError`, `XPVersionError`, `XPTimeoutError` from `xpwebapi.exceptions`
- Produces: `XPlaneNoBeacon(XPBeaconError)`, `XPlaneVersionNotSupported(XPVersionError)` in `beacon.py`; `XPlaneTimeout(XPTimeoutError)` in `udp.py`

- [ ] **Step 1: Add backward compat tests to `tests/test_exceptions.py`**

Append to the existing file:

```python
class TestBackwardCompat(unittest.TestCase):
    def test_xplane_no_beacon_is_beacon_error(self):
        from xpwebapi.beacon import XPlaneNoBeacon
        from xpwebapi.exceptions import XPBeaconError
        self.assertTrue(issubclass(XPlaneNoBeacon, XPBeaconError))

    def test_xplane_version_not_supported_is_version_error(self):
        from xpwebapi.beacon import XPlaneVersionNotSupported
        from xpwebapi.exceptions import XPVersionError
        self.assertTrue(issubclass(XPlaneVersionNotSupported, XPVersionError))

    def test_xplane_timeout_is_timeout_error(self):
        from xpwebapi.udp import XPlaneTimeout
        from xpwebapi.exceptions import XPTimeoutError
        self.assertTrue(issubclass(XPlaneTimeout, XPTimeoutError))

    def test_old_names_importable_from_package(self):
        from xpwebapi import XPlaneNoBeacon, XPlaneVersionNotSupported, XPlaneTimeout
        self.assertTrue(issubclass(XPlaneNoBeacon, Exception))
        self.assertTrue(issubclass(XPlaneVersionNotSupported, Exception))
        self.assertTrue(issubclass(XPlaneTimeout, Exception))

    def test_new_names_importable_from_package(self):
        from xpwebapi import XPWebAPIError, XPConnectionError, XPBeaconError, XPTimeoutError, XPVersionError
        self.assertTrue(issubclass(XPWebAPIError, Exception))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m unittest tests.test_exceptions.TestBackwardCompat -v`
Expected: FAIL — `XPlaneNoBeacon` is not a subclass of `XPBeaconError`

- [ ] **Step 3: Update `xpwebapi/beacon.py`**

Replace the existing exception class definitions (lines 32-37):

Old:
```python
class XPlaneNoBeacon(Exception):
    args = tuple("No beacon received from any running XPlane instance in network")


class XPlaneVersionNotSupported(Exception):
    args = tuple("XPlane version not supported")
```

New:
```python
from .exceptions import XPBeaconError, XPVersionError


class XPlaneNoBeacon(XPBeaconError):
    pass


class XPlaneVersionNotSupported(XPVersionError):
    pass
```

- [ ] **Step 4: Update `xpwebapi/udp.py`**

Replace the existing exception class definition (lines 28-29):

Old:
```python
class XPlaneTimeout(Exception):
    args = tuple("X-Plane timeout")
```

New:
```python
from .exceptions import XPTimeoutError


class XPlaneTimeout(XPTimeoutError):
    pass
```

- [ ] **Step 5: Update `xpwebapi/__init__.py`**

Add new exception imports and update `__all__`:

Old:
```python
from .api import Dataref, Command, DatarefValueType, DATAREF_DATATYPE
from .beacon import XPBeaconMonitor, BeaconData, XPlaneNoBeacon, XPlaneVersionNotSupported
from .rest import XPRestAPI
from .ws import XPWebsocketAPI, CALLBACK_TYPE
from .udp import XPUDPAPI, XPlaneTimeout

__all__ = [
    "Dataref",
    "Command",
    "DatarefValueType",
    "DATAREF_DATATYPE",
    "XPBeaconMonitor",
    "BeaconData",
    "XPlaneNoBeacon",
    "XPlaneVersionNotSupported",
    "XPRestAPI",
    "XPWebsocketAPI",
    "CALLBACK_TYPE",
    "XPUDPAPI",
    "XPlaneTimeout",
    "beacon",
    "rest_api",
    "ws_api",
    "udp_api",
    "version",
]
```

New:
```python
from .api import Dataref, Command, DatarefValueType, DATAREF_DATATYPE
from .beacon import XPBeaconMonitor, BeaconData, XPlaneNoBeacon, XPlaneVersionNotSupported
from .exceptions import XPWebAPIError, XPConnectionError, XPBeaconError, XPTimeoutError, XPVersionError
from .rest import XPRestAPI
from .ws import XPWebsocketAPI, CALLBACK_TYPE
from .udp import XPUDPAPI, XPlaneTimeout

__all__ = [
    "Dataref",
    "Command",
    "DatarefValueType",
    "DATAREF_DATATYPE",
    "XPBeaconMonitor",
    "BeaconData",
    "XPlaneNoBeacon",
    "XPlaneVersionNotSupported",
    "XPWebAPIError",
    "XPConnectionError",
    "XPBeaconError",
    "XPTimeoutError",
    "XPVersionError",
    "XPRestAPI",
    "XPWebsocketAPI",
    "CALLBACK_TYPE",
    "XPUDPAPI",
    "XPlaneTimeout",
    "beacon",
    "rest_api",
    "ws_api",
    "udp_api",
    "version",
]
```

- [ ] **Step 6: Update raise sites in `beacon.py`**

Find `raise XPlaneNoBeacon()` (line 320) and replace with:
```python
raise XPlaneNoBeacon("no beacon received", timeout=timeout)
```

Find `raise XPlaneVersionNotSupported()` (line 314) and replace with:
```python
raise XPlaneVersionNotSupported(f"beacon version {beacon_major_version}.{beacon_minor_version}.{application_host_id}")
```

- [ ] **Step 7: Update raise site in `udp.py`**

Find `raise XPlaneTimeout` (line 337) and replace with:
```python
raise XPlaneTimeout("UDP read timeout")
```

- [ ] **Step 8: Run all exception tests**

Run: `uv run python -m unittest tests.test_exceptions -v`
Expected: All tests PASS (11 hierarchy + 5 backward compat = 16)

- [ ] **Step 9: Commit**

```bash
git add xpwebapi/beacon.py xpwebapi/udp.py xpwebapi/__init__.py tests/test_exceptions.py
git commit -m "feat: backward compat exception aliases, update raise sites with context"
```
