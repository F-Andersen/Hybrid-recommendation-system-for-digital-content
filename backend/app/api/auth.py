from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db, SessionSecret, SettingsDep
from app.core.config import Settings
from app.core.security import (
    SESSION_SECONDS,
    create_session_token,
    hash_password,
    password_hasher,
    verify_password,
)
from app.db.models import Item, Rating, User
from app.schemas.auth import LoginRequest, RegisterRequest, UserProfile

router = APIRouter(prefix="/auth", tags=["auth"])


def user_profile(db: Session, user: User) -> UserProfile:
    counts = {"movie": 0, "book": 0}
    counts.update(dict(db.execute(select(Item.domain, func.count()).join(
        Rating, Rating.item_id == Item.id,
    ).where(Rating.user_id == user.id, Rating.implicit.is_(False)).group_by(Item.domain)).all()))
    return UserProfile(id=user.id, email=user.email, display_name=user.display_name,
                       created_at=user.created_at, rating_counts=counts)


def set_session(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie("session", token, max_age=SESSION_SECONDS, httponly=True,
                        secure=settings.session_cookie_secure, samesite="lax", path="/")


@router.post("/register", response_model=UserProfile, status_code=201)
def register(
    payload: RegisterRequest, response: Response, db: Db,
    settings: SettingsDep, secret: SessionSecret,
) -> UserProfile:
    user = User(email=payload.email, password_hash=hash_password(payload.password),
                display_name=payload.display_name, source="web")
    db.add(user)
    try:
        db.flush()
        token = create_session_token(user.id, secret)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if getattr(exc.orig, "sqlstate", None) != "23505":
            raise
        raise HTTPException(
            status_code=409, detail="Ця електронна адреса вже зареєстрована",
        ) from exc
    set_session(response, token, settings)
    return user_profile(db, user)


@router.post("/login", response_model=UserProfile)
def login(
    payload: LoginRequest, response: Response, db: Db, settings: SettingsDep, secret: SessionSecret,
) -> UserProfile:
    user = db.scalar(select(User).where(User.email == payload.email, User.source == "web"))
    if not verify_password(user.password_hash if user else None, payload.password) or user is None:
        raise HTTPException(status_code=401, detail="Неправильна адреса або пароль")
    if password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
        db.commit()
    set_session(response, create_session_token(user.id, secret), settings)
    return user_profile(db, user)


@router.post("/logout", status_code=204)
def logout(settings: SettingsDep) -> Response:
    response = Response(status_code=204)
    response.delete_cookie("session", path="/", httponly=True, samesite="lax",
                           secure=settings.session_cookie_secure)
    return response


@router.get("/me", response_model=UserProfile)
def me(db: Db, user: CurrentUser) -> UserProfile:
    return user_profile(db, user)
