"""Socket.IO emit helper usable from the API process and from the separate engine process.

Event names and payloads are documented as JSON Schema in ``contracts/events.schema.json``.
Every payload carries ``ts`` (epoch milliseconds) so clients can detect stale data.
"""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)

_socketio: Any = None


def set_socketio(sio: Any) -> None:
    global _socketio
    _socketio = sio


def init_external(redis_url: str) -> None:
    """Engine running in its own process emits through the Redis message queue."""
    from flask_socketio import SocketIO

    set_socketio(SocketIO(message_queue=redis_url))


def now_ms() -> int:
    return int(time.time() * 1000)


def emit(event: str, data: dict, room: str) -> None:
    if _socketio is None:
        return
    payload = {"ts": now_ms(), **data}
    try:
        _socketio.emit(event, payload, to=room)
    except Exception:  # pragma: no cover - never let a socket hiccup break the engine
        log.exception("emit %s to %s failed", event, room)


def building_room(building_id: int) -> str:
    """Rescuer/admin dashboards watching a building."""
    return f"building:{building_id}"


def residents_room(building_id: int) -> str:
    return f"residents:{building_id}"


def device_room(device_id: str) -> str:
    return f"device:{device_id}"


def signage_room(signage_id: int) -> str:
    return f"signage:{signage_id}"
