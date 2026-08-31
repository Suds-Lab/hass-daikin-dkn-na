"""Native Engine.IO v3 / Socket.IO v2 long-polling client.

The dkncloudna.com backend is a Socket.IO **v2** server (Engine.IO **v3**),
confirmed live: the handshake returns length-prefixed framing
``97:0{...}2:40`` regardless of the requested EIO version. ``python-socketio``
v5 only speaks EIO4 (fails here with "OPEN packet not returned"), and pinning
the old v4 client conflicts with Home Assistant's bundled version. So we
implement just the slice of the protocol the app uses - **polling transport
only**, mirroring ``socket.service.js`` (``transports:['polling']``).

Protocol summary (Engine.IO v3 XHR-polling, string payloads):
  * payload framing: ``<charLen>:<packet>`` repeated.
  * engine.io packet types: 0 open, 1 close, 2 ping, 3 pong, 4 message, 6 noop.
  * socket.io packet (inside a ``4`` message): 0 CONNECT, 1 DISCONNECT, 2 EVENT,
    3 ACK, 4 ERROR, optionally prefixed with ``/namespace,``.
  * namespace connect  -> send ``40/{id}::dknUsa,``
  * inbound event      -> ``42/{id}::dknUsa,["device-data",{mac,data}]``
  * outbound control   -> ``42/{id}::dknUsa,["create-machine-event",{...}]``
  * client sends engine.io ping ``2`` every ``pingInterval`` (15 s), expects ``3``.
"""

from __future__ import annotations

import asyncio
import inspect
import itertools
import json
import logging
import time
from typing import Any, Awaitable, Callable, Optional, Union

import aiohttp

from .const import (
    EVENT_CREATE_MACHINE,
    EVENT_DEVICE_DATA,
    SCOPE,
    SOCKET_PATH,
    SOCKET_URL,
)
from .exceptions import DknAuthError, DknConnectionError

_LOGGER = logging.getLogger(__name__)

DeviceDataCb = Callable[[str, dict], Union[None, Awaitable[None]]]
EventCb = Callable[[str, list], Union[None, Awaitable[None]]]
TokenRefresh = Callable[[], Awaitable[str]]

# engine.io packet type codes
_EIO_OPEN, _EIO_CLOSE, _EIO_PING, _EIO_PONG, _EIO_MESSAGE, _EIO_UPGRADE, _EIO_NOOP = "0123456"
# socket.io packet type codes
_SIO_CONNECT, _SIO_DISCONNECT, _SIO_EVENT, _SIO_ACK, _SIO_ERROR = range(5)

_counter = itertools.count()


def _cache_buster() -> str:
    # socket.io-client uses a unique 't' query param per request.
    return f"{int(time.time() * 1000):x}-{next(_counter)}"


def decode_payload(data: str) -> list[str]:
    """Split an Engine.IO v3 string payload into individual packets."""
    packets: list[str] = []
    i, n = 0, len(data)
    while i < n:
        colon = data.find(":", i)
        if colon == -1:
            break
        length = int(data[i:colon])
        start = colon + 1
        packets.append(data[start:start + length])
        i = start + length
    return packets


def encode_payload(packet: str) -> str:
    """Frame a single packet for an Engine.IO v3 string POST body."""
    return f"{len(packet)}:{packet}"


def parse_sio(packet: str) -> tuple[int, str, Optional[Any]]:
    """Parse a socket.io packet body (the part after the engine.io '4')."""
    sio_type = int(packet[0])
    rest = packet[1:]
    namespace = "/"
    if rest.startswith("/"):
        comma = rest.find(",")
        if comma == -1:
            return sio_type, rest, None
        namespace, rest = rest[:comma], rest[comma + 1:]
    # An optional numeric ack id may precede the JSON; try parsing the body
    # as-is first, then again with any leading ack-id digits stripped.
    k = 0
    while k < len(rest) and rest[k].isdigit():
        k += 1
    data: Optional[Any] = None
    for candidate in (rest, rest[k:]):
        if not candidate:
            data = None
            break
        try:
            data = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue
    return sio_type, namespace, data


class DknSocket:
    """A Socket.IO v2 polling connection to a single installation namespace."""

    def __init__(
        self,
        installation_id: str,
        token: str,
        *,
        session: Optional[aiohttp.ClientSession] = None,
        base_url: str = SOCKET_URL,
        on_device_data: Optional[DeviceDataCb] = None,
        on_event: Optional[EventCb] = None,
        token_refresh: Optional[TokenRefresh] = None,
    ):
        self.installation_id = installation_id
        self.namespace = f"/{installation_id}::{SCOPE}"
        self._token = token
        self._url = base_url.rstrip("/") + SOCKET_PATH  # .../socket.io/
        self._on_device_data = on_device_data
        self._on_event = on_event
        self._token_refresh = token_refresh

        self._session = session
        self._own_session = session is None

        self._sid: Optional[str] = None
        self._ping_interval = 15.0
        self._ping_timeout = 30.0
        self._closing = False
        self._ns_connected = asyncio.Event()
        self._poll_task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        # Liveness bookkeeping for the watchdog (monotonic clock).
        self._last_rx = 0.0
        self._ns_down_since: Optional[float] = None
        # Serialise reconnects so the poll loop and watchdog can't race two
        # overlapping handshakes onto the same connection.
        self._reconnect_lock = asyncio.Lock()

    # -- public API ---------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._ns_connected.is_set() and not self._closing

    def update_token(self, token: str) -> None:
        self._token = token

    async def connect(self, *, connect_timeout: float = 20.0) -> None:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        self._closing = False
        await self._handshake()
        self._last_rx = time.monotonic()
        # Connect to our namespace, then start the background loops.
        await self._send_packet(f"{_EIO_MESSAGE}{_SIO_CONNECT}{self.namespace},")
        self._poll_task = asyncio.create_task(self._poll_loop(), name=f"dkn-poll-{self.installation_id}")
        self._ping_task = asyncio.create_task(self._ping_loop(), name=f"dkn-ping-{self.installation_id}")
        self._watchdog_task = asyncio.create_task(
            self._watchdog_loop(), name=f"dkn-watchdog-{self.installation_id}"
        )
        try:
            await asyncio.wait_for(self._ns_connected.wait(), timeout=connect_timeout)
        except asyncio.TimeoutError as err:
            await self.disconnect()
            raise DknConnectionError("Timed out connecting to socket namespace") from err

    async def send_event(self, mac: str, prop: str, value: Any) -> None:
        """Emit ``create-machine-event`` (the control channel)."""
        payload = json.dumps(
            [EVENT_CREATE_MACHINE, {"mac": mac, "property": prop, "value": value}],
            separators=(",", ":"),
        )
        _LOGGER.debug("emit %s %s=%s", mac, prop, value)
        await self._send_packet(f"{_EIO_MESSAGE}{_SIO_EVENT}{self.namespace},{payload}")

    async def disconnect(self) -> None:
        self._closing = True
        for task in (self._poll_task, self._ping_task, self._watchdog_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        self._poll_task = self._ping_task = self._watchdog_task = None
        self._ns_connected.clear()
        self._ns_down_since = None
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()

    # -- transport ----------------------------------------------------------
    def _params(self, *, with_sid: bool = True) -> dict[str, str]:
        params = {"EIO": "3", "transport": "polling", "t": _cache_buster()}
        if with_sid and self._sid:
            params["sid"] = self._sid
        return params

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def _handshake(self) -> None:
        assert self._session is not None
        try:
            async with self._session.get(
                self._url,
                params=self._params(with_sid=False),
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status == 401:
                    await self._try_refresh()
                    return await self._handshake()
                if resp.status >= 400:
                    raise DknConnectionError(f"Handshake HTTP {resp.status}")
                text = await resp.text()
        except aiohttp.ClientError as err:
            raise DknConnectionError(f"Handshake failed: {err}") from err

        for packet in decode_payload(text):
            if packet and packet[0] == _EIO_OPEN:
                info = json.loads(packet[1:])
                self._sid = info["sid"]
                self._ping_interval = info.get("pingInterval", 15000) / 1000
                self._ping_timeout = info.get("pingTimeout", 30000) / 1000
                _LOGGER.debug("handshake sid=%s ping=%ss", self._sid, self._ping_interval)
        if not self._sid:
            raise DknConnectionError("Handshake did not return a sid")

    async def _get(self) -> str:
        assert self._session is not None
        total = self._ping_interval + self._ping_timeout + 10
        async with self._session.get(
            self._url,
            params=self._params(),
            headers=self._headers(),
            timeout=aiohttp.ClientTimeout(total=total),
        ) as resp:
            if resp.status == 401:
                await self._try_refresh()
                raise _Reconnect()
            if resp.status >= 400:
                raise DknConnectionError(f"Poll HTTP {resp.status}")
            return await resp.text()

    async def _send_packet(self, packet: str) -> None:
        assert self._session is not None
        body = encode_payload(packet)
        _LOGGER.debug("POST -> %r", body)
        async with self._session.post(
            self._url,
            params=self._params(),
            headers={**self._headers(), "Content-Type": "text/plain;charset=UTF-8"},
            data=body.encode("utf-8"),
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status == 401:
                await self._try_refresh()
                raise _Reconnect()
            if resp.status >= 400:
                raise DknConnectionError(f"Send HTTP {resp.status}")
            await resp.read()

    async def _try_refresh(self) -> None:
        if not self._token_refresh:
            raise DknAuthError("Socket auth expired and no token_refresh provided")
        self._token = await self._token_refresh()

    # -- loops --------------------------------------------------------------
    async def _ping_loop(self) -> None:
        try:
            while not self._closing:
                await asyncio.sleep(self._ping_interval)
                if self._closing:
                    return
                # A reconnect may be in flight (sid cleared); skip this beat and
                # resume keepalive once the poll loop/watchdog restores the sid.
                if self._sid is None:
                    continue
                try:
                    await self._send_packet(_EIO_PING)
                except _Reconnect:
                    # Token refreshed / transport reset mid-ping. The poll loop
                    # and watchdog own reconnection; keep looping so keepalive
                    # resumes afterwards instead of dying until a reload.
                    continue
                except (DknConnectionError, aiohttp.ClientError, asyncio.TimeoutError) as err:
                    _LOGGER.debug("ping failed (%s); watchdog will recover if needed", err)
        except asyncio.CancelledError:
            raise

    async def _poll_loop(self) -> None:
        backoff = 1.0
        try:
            while not self._closing:
                try:
                    text = await self._get()
                    _LOGGER.debug("GET <- %r", text)
                    self._last_rx = time.monotonic()
                    backoff = 1.0
                    for packet in decode_payload(text):
                        # Isolate each packet: a single malformed frame or a
                        # raising device-data callback must not kill the poll
                        # loop (which would freeze all entities until a reload).
                        try:
                            await self._handle_packet(packet)
                        except _Reconnect:
                            raise  # deliberate reconnect signal, not an error
                        except Exception:  # noqa: BLE001
                            _LOGGER.exception(
                                "installation %s: error handling packet %r",
                                self.installation_id, packet,
                            )
                except _Reconnect:
                    if self._closing:
                        return
                    await self._reconnect()
                except (DknConnectionError, aiohttp.ClientError, asyncio.TimeoutError) as err:
                    if self._closing:
                        return
                    _LOGGER.warning("socket poll error (%s); reconnecting in %ss", err, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    await self._reconnect()
                except Exception as err:  # noqa: BLE001
                    # Last-resort guard: never let an unexpected error terminate
                    # the loop. Back off and try to re-establish the connection.
                    if self._closing:
                        return
                    _LOGGER.exception(
                        "installation %s: unexpected poll error (%s); reconnecting in %ss",
                        self.installation_id, err, backoff,
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    await self._reconnect()
        except asyncio.CancelledError:
            raise

    def _mark_ns_up(self) -> None:
        self._ns_connected.set()
        self._ns_down_since = None

    def _mark_ns_down(self) -> None:
        self._ns_connected.clear()
        if self._ns_down_since is None and not self._closing:
            self._ns_down_since = time.monotonic()

    async def _reconnect(self) -> None:
        # One reconnect at a time: the poll loop and the watchdog can both ask
        # for a reconnect concurrently, and overlapping handshakes would tangle
        # the sid. Whoever gets the lock second re-checks and usually no-ops.
        async with self._reconnect_lock:
            if self._closing:
                return
            self._mark_ns_down()
            self._sid = None
            try:
                await self._handshake()
                await self._send_packet(f"{_EIO_MESSAGE}{_SIO_CONNECT}{self.namespace},")
                # Treat a successful re-handshake as fresh activity, and restart
                # the namespace-down grace window, so the watchdog gives this
                # attempt's CONNECT reply a full window to arrive before firing
                # again (avoids a re-handshake storm if the namespace is slow).
                now = time.monotonic()
                self._last_rx = now
                if self._ns_down_since is not None:
                    self._ns_down_since = now
            except (_Reconnect, DknConnectionError) as err:
                _LOGGER.debug("reconnect attempt failed: %s", err)

    async def _watchdog_loop(self) -> None:
        """Force a reconnect when the connection goes silent or loses its namespace.

        Two independent failure modes are covered:
          * **transport silent** - no inbound packet (not even a pong to our
            pings) for a full ping window; the server or network dropped us.
          * **namespace down** - the transport is alive (pongs still arrive) but
            our installation namespace has been disconnected too long, so no
            ``device-data`` will ever come. Without this, entities freeze at
            their last value until the user reloads the integration.
        """
        try:
            while not self._closing:
                await asyncio.sleep(self._ping_interval)
                if self._closing:
                    return
                if self._reconnect_lock.locked():
                    continue  # a reconnect is already running
                now = time.monotonic()
                window = self._ping_interval + self._ping_timeout
                silent = now - self._last_rx
                transport_silent = self._last_rx > 0 and silent > window
                ns_down = (
                    self._ns_down_since is not None
                    and now - self._ns_down_since > window
                )
                if transport_silent or ns_down:
                    reason = "transport silent" if transport_silent else "namespace down"
                    stale = silent if transport_silent else now - self._ns_down_since
                    _LOGGER.warning(
                        "installation %s watchdog: %s for %.0fs; forcing reconnect",
                        self.installation_id, reason, stale,
                    )
                    await self._reconnect()
        except asyncio.CancelledError:
            raise

    # -- packet handling ----------------------------------------------------
    async def _handle_packet(self, packet: str) -> None:
        if not packet:
            return
        # Any well-formed inbound packet is proof of life for the watchdog.
        self._last_rx = time.monotonic()
        etype = packet[0]
        if etype == _EIO_PING:          # server-initiated ping -> pong
            await self._send_packet(_EIO_PONG)
        elif etype == _EIO_PONG:        # reply to our ping
            return
        elif etype == _EIO_CLOSE:
            # Server tore down the engine.io session; the current sid is dead.
            # Reconnect instead of polling a closed session until it errors out.
            _LOGGER.debug("server closed engine.io; reconnecting")
            raise _Reconnect()
        elif etype == _EIO_MESSAGE:
            await self._handle_message(packet[1:])

    async def _handle_message(self, body: str) -> None:
        if not body:
            return
        sio_type, namespace, data = parse_sio(body)
        if namespace != self.namespace and namespace != "/":
            return
        if sio_type == _SIO_CONNECT and namespace == self.namespace:
            _LOGGER.info("installation %s namespace connected", self.installation_id)
            self._mark_ns_up()
        elif sio_type == _SIO_ERROR:
            # Namespace-level error (transport is still alive, so pings keep
            # succeeding). Mark it down and let the watchdog re-establish after
            # a grace period rather than hammering the server in a tight loop.
            _LOGGER.error(
                "installation %s namespace error: %s; watchdog will re-establish",
                self.installation_id, data,
            )
            self._mark_ns_down()
        elif sio_type == _SIO_EVENT and isinstance(data, list) and data:
            await self._dispatch_event(data)

    async def _dispatch_event(self, data: list) -> None:
        name = data[0]
        args = data[1:]
        if name == EVENT_DEVICE_DATA and args and self._on_device_data:
            payload = args[0] or {}
            mac = payload.get("mac")
            dev_data = payload.get("data", {}) or {}
            if mac:
                await _maybe_await(self._on_device_data(mac, dev_data))
        if self._on_event:
            await _maybe_await(self._on_event(name, args))


class _Reconnect(Exception):
    """Internal signal: token refreshed / transport reset, restart the session."""


async def _maybe_await(result: Any) -> None:
    if inspect.isawaitable(result):
        await result
