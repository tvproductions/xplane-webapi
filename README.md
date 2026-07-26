# xpwebapi

`xpwebapi` is a Python client and development toolkit for the Laminar Research
X-Plane Web API, including REST, async REST, WebSocket, UDP, beacon discovery,
and a strictly read-only capture worker.

This is an independently maintained fork of
[`devleaks/xplane-webapi`](https://github.com/devleaks/xplane-webapi).
TV Productions thanks Pierre Mareschal and `devleaks` for creating the original
library. The upstream source reported version 3.5.0 when this fork's extension
work began; TV Productions maintains releases beginning with 4.0.0.

This project is not endorsed by or affiliated with the upstream maintainer or
Laminar Research. X-Plane is a trademark of Laminar Research.

## Installation

Requires Python 3.12 or 3.13.

```sh
pip install xpwebapi
```

## Quick start

```python
import xpwebapi

with xpwebapi.rest_api(api_version="v2") as api:
    clock = api.dataref("sim/cockpit2/clock_timer/local_time_seconds")
    print(api.dataref_value(clock))
```

## Read-only capture worker

The installed `xpwebapi-capture` command records a bounded, versioned stream of
configured X-Plane DataRefs without exposing command execution or DataRef
writes. WebSocket is the primary capture transport.
UDP is the diagnostic/fallback capture transport.

See the [capture guide](https://tvproductions.github.io/xplane-webapi/usage/read-only-capture/)
and [capture protocol reference](https://tvproductions.github.io/xplane-webapi/reference/capture/).

## Documentation

Full documentation is available at
https://tvproductions.github.io/xplane-webapi/.

## Development

```sh
git clone https://github.com/tvproductions/xplane-webapi.git
cd xplane-webapi
uv sync
uv run python -m unittest discover -v
```

## License

MIT. See [`LICENSE`](https://github.com/tvproductions/xplane-webapi/blob/main/LICENSE).
