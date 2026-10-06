"""AI-Driven Smart Fire Evacuation System: Flask + Flask-SocketIO server."""

from __future__ import annotations

import logging

from apiflask import APIFlask
from flask import send_from_directory
from flask_cors import CORS

from app.config import Config
from app.db import SessionLocal, create_all, init_db
from app.extensions import socketio
from app.live.store import init_store
from app.notifications.fcm import init_fcm
from app.realtime.emitter import set_socketio

log = logging.getLogger(__name__)


def create_app(cfg: Config | None = None, start_engine: bool | None = None) -> APIFlask:
    cfg = cfg or Config()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = APIFlask(__name__, title="Smart Fire Evacuation API", version="1.0.0")
    app.config["FIRE"] = cfg
    app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024
    app.config["SPEC_FORMAT"] = "json"
    app.security_schemes = {"BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}
    CORS(app, origins=cfg.cors_origins, supports_credentials=True)

    init_db(cfg.database_url)
    if cfg.database_url.startswith("sqlite"):
        # SQLite is for local runs and tests; Postgres deployments use Alembic migrations.
        create_all()
    init_store(cfg.redis_url)
    init_fcm(cfg.firebase_credentials)
    cfg.upload_dir.mkdir(parents=True, exist_ok=True)

    from app.auth.routes import bp as auth_bp
    from app.buildings.routes import bp as buildings_bp
    from app.incidents.routes import bp as incidents_bp
    from app.positioning.routes import bp as positioning_bp
    from app.sensors.routes import bp as sensors_bp
    from app.signage.routes import bp as signage_bp
    from app.simulation.routes import bp as simulation_bp

    for bp in (auth_bp, buildings_bp, positioning_bp, sensors_bp, incidents_bp, simulation_bp, signage_bp):
        app.register_blueprint(bp, url_prefix="/api")

    @app.get("/api/health")
    @app.doc(tags=["system"])
    def health():
        return {"status": "ok", "engine_inprocess": cfg.engine_inprocess, "redis": cfg.uses_redis}

    @app.get("/uploads/<path:name>")
    @app.doc(hide=True)
    def uploads(name: str):
        return send_from_directory(cfg.upload_dir, name)

    @app.teardown_appcontext
    def remove_session(_exc=None):
        SessionLocal.remove()

    def allowed_origin(origin: str, environ: dict | None = None) -> bool:
        # Browsers: only the configured dashboard origins. Native clients (Flutter, Python)
        # send the server's own address as Origin; tokens travel in the Socket.IO auth payload,
        # not cookies, so same-origin connections are safe to accept.
        if origin in cfg.cors_origins or "*" in cfg.cors_origins:
            return True
        host = (environ or {}).get("HTTP_HOST", "")
        return bool(host) and origin.split("://", 1)[-1] == host

    socketio.init_app(app, cors_allowed_origins=allowed_origin, message_queue=cfg.redis_url or None)
    set_socketio(socketio)
    from app.realtime import sockets  # noqa: F401  (registers handlers)

    if start_engine is None:
        start_engine = cfg.engine_inprocess and not cfg.testing
    if start_engine:
        from app.engine.engine import Engine
        from app.live.store import get_store

        engine = Engine(cfg, get_store())
        engine.start_thread()
        app.extensions["fire_engine"] = engine
    return app
