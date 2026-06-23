"""Axomind MCP — WebSocket listener.

Async WebSocket client that connects to the Axomind WS server (Node.js)
using the same authentication chain as the Flutter client:

  1. Three custom headers: x-ws-token, x-user-id, x-type_client
  2. The Node.js AuthServer forwards these to PHP (websocket_auth=1)
  3. PHP validates the token and returns the user_id
  4. AuthServer emits 'authenticatedConnection' → WSServer registers the client

Once connected, incoming messages are parsed as WebsocketTransit
({target, service, message, data}) and pushed into an in-memory buffer.

Two modes:
  - Hermes hybrid: user_poll_events() drains the buffer when Hermes calls it.
  - Daemon autonomous: daemon.py registers callbacks that fire on each event.

Reconnection uses exponential backoff with jitter (mirrors the Flutter client).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

import httpx

logger = logging.getLogger("axomind_mcp.ws_listener")

# ──────────────────────────────────────────────
# Configuration via environment variables
# ──────────────────────────────────────────────

# WS server URL — derived from the base URL host.
# In dev: ws://<host>:8080/  (base_api.dart: _wsScheme + _wsSubDomaine + _wsPort)
# In prod: wss://ws.<domain>/
# We derive from AXOMIND_BASE_URL if AXOMIND_WS_URL is not set.
_base = os.environ.get("AXOMIND_BASE_URL", "")
_derived_host = ""
if _base:
    # Extract host from http://<host>/app/bot_api.php → <host>
    _protoless = _base.split("://", 1)[-1]
    _derived_host = _protoless.split("/", 1)[0]

WS_URL = os.environ.get(
    "AXOMIND_WS_URL",
    f"ws://{_derived_host}:8080/" if _derived_host else "",
)
# Reconnection settings (mirrors Flutter client: base 2s, exponential, max 32s)
WS_RECONNECT_BASE_DELAY = float(os.environ.get("AXOMIND_WS_RECONNECT_DELAY", "2"))
WS_RECONNECT_MAX_DELAY = 32.0
WS_PING_INTERVAL = 30.0  # seconds — matches Node.js heartbeat


# ──────────────────────────────────────────────
# Event model — mirrors WebsocketTransit (websocket_transit.dart)
# ──────────────────────────────────────────────


@dataclass
class WSEvent:
    """A single WebSocket event received from the server.

    Mirrors the Flutter WebsocketTransit class:
    {target: str, service: str, message: str, data: Any}
    """

    target: str
    service: str
    message: str
    data: Any = None

    @classmethod
    def from_dict(cls, raw: dict) -> "WSEvent":
        return cls(
            target=str(raw.get("target", "")),
            service=str(raw.get("service", "")),
            message=str(raw.get("message", "")),
            data=raw.get("data"),
        )

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "service": self.service,
            "message": self.message,
            "data": self.data,
        }


# ──────────────────────────────────────────────
# Event buffer — thread-safe-ish deque (asyncio single-thread by design)
# ──────────────────────────────────────────────

# Buffer for Hermes hybrid mode: user_poll_events() drains this.
# In daemon mode, callbacks are used instead, but the buffer is still kept
# for debugging/inspection.
_event_buffer: deque[WSEvent] = deque(maxlen=200)

# Callbacks for daemon mode — registered by daemon.py.
# Each callback is async, receives the WSEvent.
_callbacks: list[Callable[[WSEvent], Awaitable[None]]] = []


def register_callback(cb: Callable[[WSEvent], Awaitable[None]]) -> None:
    """Register an async callback fired on each incoming WS event (daemon mode)."""
    _callbacks.append(cb)


def clear_callbacks() -> None:
    """Remove all registered callbacks."""
    _callbacks.clear()


def drain_events() -> list[dict]:
    """Drain the event buffer and return all pending events as dicts.

    Used by the user_poll_events MCP tool (Hermes hybrid mode).
    Returns events in chronological order (oldest first).
    """
    events = []
    while _event_buffer:
        events.append(_event_buffer.popleft().to_dict())
    return events


def peek_events() -> list[dict]:
    """Return pending events without draining the buffer (for debugging)."""
    return [e.to_dict() for e in _event_buffer]


def buffer_size() -> int:
    """Return the number of pending events in the buffer."""
    return len(_event_buffer)


# ──────────────────────────────────────────────
# WebSocket client — async, with reconnection
# ──────────────────────────────────────────────


class WSListener:
    """Async WebSocket client for the Axomind WS server.

    Authenticates with the same 3 headers as the Flutter client:
      - x-ws-token:   token_exchange from user_login
      - x-user-id:    user_id from user_login
      - x-type_client: type_client (e.g. the value from AXOMIND_USER_TYPE_CLIENT)

    Mirrors the Flutter WebSocketService.connect() flow exactly.
    """

    def __init__(
        self,
        token: str,
        user_id: str | int,
        type_client: str,
        ws_url: str = "",
    ) -> None:
        self._token = str(token)
        self._user_id = str(user_id)
        self._type_client = str(type_client)
        self._ws_url = ws_url or WS_URL
        self._is_connected = False
        self._manual_disconnect = False
        self._reconnect_attempts = 0
        self._task: asyncio.Task | None = None
        # Try to import websockets; if not available, the listener won't start.
        self._ws_lib = None

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    async def start(self) -> None:
        """Start the listener loop as a background asyncio task."""
        if self._task and not self._task.done():
            return
        self._manual_disconnect = False
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Signal the listener to stop and wait for cleanup."""
        self._manual_disconnect = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._is_connected = False

    async def _run_loop(self) -> None:
        """Main loop: connect → listen → reconnect on failure."""
        try:
            import websockets  # noqa: F811
            self._ws_lib = websockets
        except ImportError:
            logger.error(
                "websockets library not installed — WS listener disabled. "
                "Install with: pip install websockets"
            )
            return

        while not self._manual_disconnect:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"WS connection error: {e}")

            if self._manual_disconnect:
                break

            await self._schedule_reconnect()

    async def _connect_and_listen(self) -> None:
        """Connect to the WS server and listen for messages until disconnected."""
        if not self._ws_url:
            logger.error("WS_URL is not configured — cannot connect")
            return

        # Build headers — mirrors Flutter WebSocketService.connect():
        # headers = {'x-ws-token': token, 'x-user-id': userId, 'x-type_client': typeClient}
        headers = {
            "x-ws-token": self._token,
            "x-user-id": self._user_id,
            "x-type_client": self._type_client,
        }

        logger.info(
            f"Connecting to WS {self._ws_url} "
            f"(user={self._user_id}, type_client={self._type_client})"
        )

        # websockets.connect() with additional_headers for custom auth headers.
        # The Node.js AuthServer reads these during the HTTP upgrade handshake.
        async with self._ws_lib.connect(
            self._ws_url,
            additional_headers=headers,
            ping_interval=WS_PING_INTERVAL,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            self._is_connected = True
            self._reconnect_attempts = 0
            logger.info("WS connected — listening for events")

            async for raw_message in ws:
                await self._handle_message(raw_message)

    async def _handle_message(self, raw: str | bytes) -> None:
        """Parse incoming WS message and dispatch to buffer + callbacks."""
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            decoded = json.loads(raw)
            if not isinstance(decoded, dict):
                logger.debug(f"WS message ignored: non-dict payload")
                return

            event = WSEvent.from_dict(decoded)
            logger.debug(f"WS event: service={event.service}, message={event.message}")

            # Push to buffer (for Hermes hybrid mode / debugging)
            _event_buffer.append(event)

            # Fire callbacks (for daemon mode)
            for cb in _callbacks:
                try:
                    await cb(event)
                except Exception as e:
                    logger.error(f"WS callback error: {e}")

        except json.JSONDecodeError as e:
            logger.warning(f"WS message parse error: {e}")
        except Exception as e:
            logger.error(f"WS handle_message error: {e}")

    async def _schedule_reconnect(self) -> None:
        """Exponential backoff reconnection — mirrors Flutter _scheduleReconnect()."""
        import random

        base = WS_RECONNECT_BASE_DELAY * (2 ** self._reconnect_attempts)
        delay = min(base, WS_RECONNECT_MAX_DELAY)
        jitter = random.uniform(0, 1)
        final_delay = delay + jitter

        self._reconnect_attempts += 1
        logger.info(
            f"WS reconnecting in {final_delay:.1f}s "
            f"(attempt #{self._reconnect_attempts})"
        )

        await asyncio.sleep(final_delay)


# ──────────────────────────────────────────────
# Singleton instance — managed by daemon.py or _user.py
# ──────────────────────────────────────────────

_listener: WSListener | None = None


def get_listener() -> WSListener | None:
    """Return the active WS listener instance (or None if not started)."""
    return _listener


async def start_listener(token: str, user_id: str | int, type_client: str) -> WSListener:
    """Create and start a WS listener with the given session credentials.

    Called after a successful user_login() — uses the token + user_id
    from the session to authenticate on the WS server.
    """
    global _listener
    if _listener and _listener.is_connected:
        logger.info("WS listener already connected — skipping start")
        return _listener

    _listener = WSListener(token=token, user_id=user_id, type_client=type_client)
    await _listener.start()
    return _listener


async def stop_listener() -> None:
    """Stop the active WS listener if any."""
    global _listener
    if _listener:
        await _listener.stop()
        _listener = None