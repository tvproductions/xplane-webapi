# Python Wrapper for Laminar Research X-Plane Web API

See [X-Plane Web API](https://developer.x-plane.com/article/x-plane-web-api/).


[Documentation](https://devleaks.github.io/xplane-webapi/usage/)


# Installation


```sh
pip install 'xpwebapi @ git+https://github.com/devleaks/xplane-webapi.git'
```

For development, clone the repository and sync the development dependency group:


```sh
git clone https://github.com/devleaks/xplane-webapi.git
cd xplane-webapi
uv sync
```

## Read-only capture worker

The installed `xpwebapi-capture` command records a bounded, versioned stream of
configured X-Plane DataRefs without exposing command execution or DataRef
writes. WebSocket is the primary capture transport.
UDP is the diagnostic/fallback capture transport when WebSocket observation is not
available or when transport comparison is part of a test.

This worker is development infrastructure for q4xpcc. q4xpcc remains the
XPPython3 plugin, defines the watchlists and sorties, launches the worker, and
owns normalized evidence and final bundles. See the
[read-only capture guide](docs/usage/read-only-capture.md) and
[protocol reference](docs/reference/capture.md).
