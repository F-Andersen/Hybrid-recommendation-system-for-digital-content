from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import decode_session_token
from app.db.models import User
from app.db.session import get_db

Db = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def session_secret(settings: SettingsDep) -> str:
    if settings.jwt_secret == "change-me" or len(settings.jwt_secret.encode("utf-8")) < 32:
        raise HTTPException(status_code=503, detail="JWT_SECRET має містити щонайменше 32 байти")
    return settings.jwt_secret


SessionSecret = Annotated[str, Depends(session_secret)]


def optional_user(request: Request, db: Db, settings: SettingsDep) -> User | None:
    token = request.cookies.get("session")
    if token is None:
        return None
    try:
        user_id = decode_session_token(token, session_secret(settings))
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Сесія недійсна або закінчилася") from exc
    user = db.get(User, user_id)
    if user is None or user.source != "web" or not user.email or not user.password_hash:
        raise HTTPException(status_code=401, detail="Користувач сесії недоступний")
    return user


OptionalUser = Annotated[User | None, Depends(optional_user)]


def require_user(user: OptionalUser) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Потрібно увійти в обліковий запис")
    return user


CurrentUser = Annotated[User, Depends(require_user)]
