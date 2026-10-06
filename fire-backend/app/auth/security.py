"""Password hashing, JWTs and role guards."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from functools import wraps

import jwt
from apiflask import abort
from flask import current_app, g, request
from werkzeug.security import check_password_hash, generate_password_hash

from app.db import SessionLocal
from app.models import Role, User, UserStatus

ALGORITHM = "HS256"
STAFF_ROLES = {Role.SOCIETY_ADMIN, Role.RESCUER}


def hash_password(password: str) -> str:
    return generate_password_hash(password, method="scrypt")


def verify_password(password: str, hashed: str) -> bool:
    return check_password_hash(hashed, password)


def hash_secret(secret: str) -> str:
    """For sensor API keys and similar high-entropy secrets."""
    return hashlib.sha256(secret.encode()).hexdigest()


def secrets_match(secret: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_secret(secret), hashed)


def new_token(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)


def _cfg():
    return current_app.config["FIRE"]


def create_access_token(user: User, device_id: str | None = None, secret: str | None = None, minutes: int | None = None) -> str:
    cfg = None if secret else _cfg()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "society_id": user.society_id,
        "building_id": user.building_id,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=minutes or (cfg.jwt_access_minutes if cfg else 60)),
    }
    if device_id:
        payload["device_id"] = device_id
    return jwt.encode(payload, secret or cfg.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str, secret: str | None = None) -> dict:
    return jwt.decode(token, secret or _cfg().jwt_secret, algorithms=[ALGORITHM])


def _bearer() -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def current_user() -> User:
    return g.current_user


def login_required(roles: set[Role] | None = None, approved: bool = True):
    """Decorator: valid access token, optionally one of ``roles``; residents must be approved."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            token = _bearer()
            if not token:
                abort(401, "Missing bearer token")
            try:
                claims = decode_token(token)
            except jwt.ExpiredSignatureError:
                abort(401, "Token expired")
            except jwt.PyJWTError:
                abort(401, "Invalid token")
            if claims.get("type") != "access":
                abort(401, "Invalid token type")
            user = SessionLocal.get(User, int(claims["sub"]))
            if user is None:
                abort(401, "User no longer exists")
            if approved and user.status != UserStatus.APPROVED:
                abort(403, "Account awaiting approval by the society admin")
            if roles and user.role not in roles:
                abort(403, "Insufficient role")
            g.current_user = user
            g.claims = claims
            g.device_id = claims.get("device_id")
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def staff_required(fn):
    return login_required(STAFF_ROLES)(fn)


def admin_required(fn):
    return login_required({Role.SOCIETY_ADMIN})(fn)


def require_device() -> str:
    device_id = g.get("device_id")
    if not device_id:
        abort(400, "This endpoint must be called from the mobile app (token has no device)")
    return device_id


def ensure_society_access(society_id: int) -> None:
    if current_user().society_id != society_id:
        abort(404, "Not found")
