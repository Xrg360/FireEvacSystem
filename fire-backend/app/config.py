import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'fire.db'}"))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", ""))
    jwt_secret: str = field(default_factory=lambda: os.getenv("JWT_SECRET", "dev-secret-change-me"))
    jwt_access_minutes: int = field(default_factory=lambda: int(os.getenv("JWT_ACCESS_MINUTES", "60")))
    jwt_refresh_days: int = field(default_factory=lambda: int(os.getenv("JWT_REFRESH_DAYS", "30")))
    cors_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
    )
    engine_inprocess: bool = field(default_factory=lambda: _bool("ENGINE_INPROCESS", True))
    engine_tick_seconds: float = field(default_factory=lambda: float(os.getenv("ENGINE_TICK_SECONDS", "1.0")))
    firebase_credentials: str = field(default_factory=lambda: os.getenv("FIREBASE_CREDENTIALS", ""))
    mqtt_host: str = field(default_factory=lambda: os.getenv("MQTT_HOST", ""))
    mqtt_port: int = field(default_factory=lambda: int(os.getenv("MQTT_PORT", "1883")))
    upload_dir: Path = field(default_factory=lambda: Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads"))))
    model_dir: Path = field(default_factory=lambda: Path(os.getenv("MODEL_DIR", str(BASE_DIR / "ml_models"))))
    position_retention_days: int = field(default_factory=lambda: int(os.getenv("POSITION_RETENTION_DAYS", "7")))
    testing: bool = False

    @property
    def uses_redis(self) -> bool:
        return bool(self.redis_url)
