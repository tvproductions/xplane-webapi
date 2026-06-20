### Task 2: Refactor Existing Tests To Use Helpers

**Files:**
- Modify: `tests/test_api.py`
- Modify: `tests/test_rest.py`
- Modify: `tests/test_async_rest.py`
- Modify: `tests/test_udp.py`
- Modify: `tests/test_beacon.py`

**Interfaces:**
- Consumes: `tests.helpers.mock_response`
- Consumes: `tests.helpers.DummyAPI`
- Consumes: `tests.helpers.make_rref_packet`
- Consumes: `tests.helpers.make_beacon_packet`
- Consumes: `tests.helpers.make_dataref_meta`
- Consumes: `tests.helpers.make_command_meta`
- Consumes: `tests.helpers.encoded_data`
- Produces: existing tests with duplicated helper code removed

- [ ] **Step 1: Update `tests/test_api.py` imports**

Replace the local `MagicMock` import and local helper definitions with:

```python
import base64
import unittest

from tests.helpers import DummyAPI, mock_response
from xpwebapi.api import (
    DATAREF_DATATYPE,
    Cache,
    CommandCache,
    Command,
    CommandMeta,
    DatarefCache,
    Dataref,
    DatarefMeta,
    ValueCache,
)
```

Delete the local `mock_response` function and `DummyAPI` class from `tests/test_api.py`.

- [ ] **Step 2: Update `tests/test_rest.py` imports**

Replace the local `mock_response` function with the shared helper:

```python
import base64
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

import httpx

from tests.helpers import mock_response
from xpwebapi.api import DATAREF_DATATYPE, Command, CommandMeta, Dataref, DatarefMeta
from xpwebapi.rest import XPRestAPI
```

- [ ] **Step 3: Update `tests/test_async_rest.py` imports**

Replace the local `mock_response` function with:

```python
from tests.helpers import mock_response
```

Keep `AsyncMock`, `MagicMock`, and existing async test classes unchanged.

- [ ] **Step 4: Update `tests/test_udp.py` imports**

Replace local `struct` usage and local `make_rref_packet` with:

```python
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from tests.helpers import make_rref_packet
from xpwebapi.api import Command, Dataref
from xpwebapi.exceptions import XPPacketError
from xpwebapi.udp import XPUDPAPI, XPlaneTimeout
```

- [ ] **Step 5: Update `tests/test_beacon.py` imports**

Replace local `struct` usage and local `make_beacon_packet` with:

```python
import socket
import unittest
from unittest.mock import MagicMock, patch

import xpwebapi
from tests.helpers import make_beacon_packet
from xpwebapi.beacon import BeaconData, XPBeaconMonitor, XPlaneNoBeacon, XPlaneVersionNotSupported
```

- [ ] **Step 6: Run the existing test suite**

Run: `uv run python -m unittest discover -v`

Expected: all existing tests pass with the same behavior as before the helper refactor.

- [ ] **Step 7: Commit helper refactor**

```powershell
git add tests/test_api.py tests/test_rest.py tests/test_async_rest.py tests/test_udp.py tests/test_beacon.py
git commit -m "test: reuse shared test helpers"
```
