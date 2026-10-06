"""Optional MQTT bridge: topic ``sensors/<sensor_id>/reading``, JSON payload
``{"key": "<api key>", "smoke": 120, "temperature_c": 31.5, "flame": false}``.

Run:  python -m app.sensors.mqtt_ingest      (Docker Compose profile "mqtt")
"""

from __future__ import annotations

import json
import logging

from app.auth.security import secrets_match
from app.config import Config
from app.db import SessionLocal, init_db
from app.models import Sensor
from app.notifications.fcm import init_fcm
from app.realtime.emitter import init_external
from app.sensors.routes import process_reading

log = logging.getLogger("mqtt-ingest")


def handle_message(topic: str, payload: bytes) -> dict | None:
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != "sensors" or parts[2] != "reading" or not parts[1].isdigit():
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        log.warning("bad JSON on %s", topic)
        return None
    try:
        sensor = SessionLocal.get(Sensor, int(parts[1]))
        if sensor is None or not secrets_match(str(data.get("key", "")), sensor.api_key_hash):
            log.warning("rejected reading for sensor %s", parts[1])
            return None
        reading = {k: data.get(k) for k in ("smoke", "temperature_c", "flame", "alarm")}
        return process_reading(SessionLocal, sensor, reading)
    finally:
        SessionLocal.remove()


def main() -> None:
    import paho.mqtt.client as mqtt

    logging.basicConfig(level=logging.INFO)
    cfg = Config()
    if not cfg.mqtt_host:
        raise SystemExit("MQTT_HOST is not set")
    init_db(cfg.database_url)
    init_fcm(cfg.firebase_credentials)
    if cfg.redis_url:
        init_external(cfg.redis_url)

    def on_connect(client, _userdata, _flags, reason_code, _props=None):
        log.info("connected to %s (%s)", cfg.mqtt_host, reason_code)
        client.subscribe("sensors/+/reading", qos=1)

    def on_message(_client, _userdata, msg):
        try:
            handle_message(msg.topic, msg.payload)
        except Exception:
            log.exception("failed to process %s", msg.topic)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="fire-backend-ingest")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(cfg.mqtt_host, cfg.mqtt_port, keepalive=30)
    client.loop_forever()


if __name__ == "__main__":
    main()
