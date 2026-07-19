"""Restricted raw-handle proxies for read-only API clients."""

import json
import socket
import struct
from typing import Any, Never

import httpx
from websockets.sync.client import ClientConnection

from .exceptions import XPReadOnlyViolation


READ_ONLY_WS_TYPES = frozenset(
    {"dataref_subscribe_values", "dataref_unsubscribe_values"}
)


def _forbidden_attribute(name: str) -> Never:
    raise XPReadOnlyViolation(f"read-only handle forbids attribute {name}")


class _ReadOnlyHttpClientProxy:
    def __init__(self, client: httpx.Client) -> None:
        self.__client = client

    def get(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return self.__client.get(*args, **kwargs)

    def close(self) -> None:
        self.__client.close()

    def __getattr__(self, name: str) -> Never:
        return _forbidden_attribute(name)


class _ReadOnlyAsyncHttpClientProxy:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.__client = client

    async def get(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return await self.__client.get(*args, **kwargs)

    async def aclose(self) -> None:
        await self.__client.aclose()

    def __getattr__(self, name: str) -> Never:
        return _forbidden_attribute(name)


class _ReadOnlyWebsocketProxy:
    def __init__(self, websocket: ClientConnection) -> None:
        self.__websocket = websocket

    def recv(self, *args: Any, **kwargs: Any) -> str | bytes:
        return self.__websocket.recv(*args, **kwargs)

    def close(self) -> None:
        self.__websocket.close()

    def send(self, message: str | bytes) -> None:
        if not isinstance(message, str):
            raise XPReadOnlyViolation("read-only WebSocket requires JSON text")
        try:
            payload = json.loads(message)
        except json.JSONDecodeError as exc:
            raise XPReadOnlyViolation("read-only WebSocket requires valid JSON") from exc
        if not isinstance(payload, dict) or payload.get("type") not in READ_ONLY_WS_TYPES:
            raise XPReadOnlyViolation("read-only WebSocket forbids action payload")
        self.__websocket.send(message)

    def __getattr__(self, name: str) -> Never:
        return _forbidden_attribute(name)


class _ReadOnlyDatagramSocketProxy:
    def __init__(
        self, udp_socket: socket.socket, destination: tuple[str, int]
    ) -> None:
        self.__socket = udp_socket
        self.__destination = destination

    def settimeout(self, value: float) -> None:
        self.__socket.settimeout(value)

    def recvfrom(self, size: int) -> tuple[bytes, Any]:
        return self.__socket.recvfrom(size)

    def close(self) -> None:
        self.__socket.close()

    def sendto(self, message: bytes, address: tuple[str, int]) -> int:
        if len(message) != 413 or address != self.__destination:
            raise XPReadOnlyViolation("read-only UDP packet shape or destination invalid")
        header, frequency, index, path_field = struct.unpack("<5sii400s", message)
        nul = path_field.find(b"\x00")
        path = path_field[:nul] if nul >= 0 else b""
        padding = path_field[nul + 1 :] if nul >= 0 else path_field
        if (
            header != b"RREF\x00"
            or frequency < 0
            or frequency > 100
            or index < 0
            or not path
            or any(padding)
        ):
            raise XPReadOnlyViolation("read-only UDP permits only valid RREF packets")
        try:
            path.decode("ascii")
        except UnicodeDecodeError as exc:
            raise XPReadOnlyViolation("read-only UDP requires an ASCII RREF path") from exc
        return self.__socket.sendto(message, address)

    def __getattr__(self, name: str) -> Never:
        return _forbidden_attribute(name)
