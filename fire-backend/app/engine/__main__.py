"""Standalone engine process (Docker):  python -m app.engine"""

import logging

from app.config import Config
from app.db import init_db
from app.engine.engine import Engine
from app.live.store import init_store
from app.notifications.fcm import init_fcm
from app.realtime.emitter import init_external


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config()
    if not cfg.redis_url:
        raise SystemExit("The standalone engine needs REDIS_URL (or run the API with ENGINE_INPROCESS=1)")
    init_db(cfg.database_url)
    store = init_store(cfg.redis_url)
    init_fcm(cfg.firebase_credentials)
    init_external(cfg.redis_url)
    Engine(cfg, store).run_forever()


if __name__ == "__main__":
    main()
