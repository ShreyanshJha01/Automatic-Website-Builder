from datetime import datetime, timedelta, timezone
import jwt
from pwdlib import PasswordHash

from app.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
)

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_access_token(user_id: int) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    return jwt.encode(
        {"sub": str(user_id), "exp": expires},
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


def create_preview_token(user_id: int, project_id: int, expires_minutes: int = 5) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    return jwt.encode(
        {"sub": str(user_id), "project_id": str(project_id), "type": "preview", "exp": expires},
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM,
    )


def decode_preview_token(token: str):
    payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    if payload.get("type") != "preview":
        raise ValueError("Token is not a preview token")
    return int(payload["sub"]), int(payload["project_id"])
