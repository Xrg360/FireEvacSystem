"""Firebase Cloud Messaging: high-priority data messages that wake the app into a full-screen alarm.

Push is optional: without ``FIREBASE_CREDENTIALS`` messages are logged and skipped, and phones
that have the app open still get the alarm over the socket.
"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)

_app = None
_lock = threading.Lock()
_enabled = False


def init_fcm(credentials_path: str) -> bool:
    global _app, _enabled
    if not credentials_path:
        log.info("FCM disabled (FIREBASE_CREDENTIALS not set)")
        return False
    with _lock:
        if _app is not None:
            return _enabled
        try:
            import firebase_admin
            from firebase_admin import credentials

            _app = firebase_admin.initialize_app(credentials.Certificate(credentials_path))
            _enabled = True
            log.info("FCM enabled")
        except Exception:
            log.exception("Could not initialise Firebase; push disabled")
            _enabled = False
    return _enabled


def is_enabled() -> bool:
    return _enabled


def send_alarm(tokens: list[str], data: dict[str, str], title: str, body: str) -> dict:
    """Send to many devices. Returns {'sent': n, 'failed': n, 'invalid_tokens': [...]}."""
    tokens = [t for t in tokens if t]
    if not tokens:
        return {"sent": 0, "failed": 0, "invalid_tokens": []}
    if not _enabled:
        log.info("FCM disabled; would notify %d devices: %s", len(tokens), title)
        return {"sent": 0, "failed": 0, "invalid_tokens": [], "skipped": len(tokens)}
    from firebase_admin import messaging

    sent = failed = 0
    invalid: list[str] = []
    payload = {k: str(v) for k, v in {**data, "title": title, "body": body}.items()}
    for i in range(0, len(tokens), 500):
        batch = tokens[i : i + 500]
        message = messaging.MulticastMessage(
            tokens=batch,
            data=payload,  # data-only: the app builds a full-screen alarm notification itself
            android=messaging.AndroidConfig(priority="high", ttl=300),
        )
        resp = messaging.send_each_for_multicast(message)
        sent += resp.success_count
        failed += resp.failure_count
        for token, r in zip(batch, resp.responses, strict=True):
            if not r.success and r.exception is not None and "registration" in str(r.exception).lower():
                invalid.append(token)
    return {"sent": sent, "failed": failed, "invalid_tokens": invalid}
