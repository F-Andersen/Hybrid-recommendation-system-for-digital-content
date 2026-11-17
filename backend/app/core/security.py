"""Argon2 password hashing and strictly validated, seven-day JWT sessions."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

SESSION_SECONDS = 7 * 24 * 60 * 60
ISSUER = "hybrid-recommender"
AUDIENCE = "web"
password_hasher = PasswordHasher()
_dummy_hash = password_hasher.hash("unregistered-account-placeholder")


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        valid = password_hasher.verify(password_hash or _dummy_hash, password)
        return valid and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def create_session_token(user_id: int, secret: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode({
        "sub": str(user_id), "iat": now, "exp": now + timedelta(seconds=SESSION_SECONDS),
        "iss": ISSUER, "aud": AUDIENCE, "jti": uuid4().hex,
    }, secret, algorithm="HS256")


def decode_session_token(token: str, secret: str) -> int:
    if len(token) > 4096:
        raise jwt.InvalidTokenError("Завеликий токен сесії")
    payload = jwt.decode(token, secret, algorithms=["HS256"], issuer=ISSUER, audience=AUDIENCE,
                         options={"require": ["sub", "iat", "exp", "iss", "aud", "jti"]})
    subject = payload["sub"]
    if (not isinstance(subject, str) or not subject.isascii() or not subject.isdigit()
            or len(subject) > 19 or not 1 <= int(subject) <= 2 ** 63 - 1):
        raise jwt.InvalidTokenError("Некоректний користувач сесії")
    return int(subject)
