import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.core.config import get_settings
from app.recsys.als import load_available_models

router = APIRouter(prefix="/admin", tags=["admin"])


class ReloadResponse(BaseModel):
    loaded: dict[str, bool]


def require_admin(x_admin_token: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().admin_token
    if not expected or expected == "change-me":
        raise HTTPException(status_code=503, detail="Токен адміністратора не налаштовано")
    if x_admin_token is None or not secrets.compare_digest(
        x_admin_token.encode("utf-8"), expected.encode("utf-8"),
    ):
        raise HTTPException(status_code=401, detail="Потрібен коректний токен адміністратора")


@router.post("/reload-models", response_model=ReloadResponse, dependencies=[Depends(require_admin)])
async def reload_models(request: Request) -> ReloadResponse:
    try:
        models = await run_in_threadpool(
            load_available_models, get_settings().artifacts_dir, strict=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Не вдалося прочитати артефакти ALS") from exc
    if not models or request.app.state.als_models.keys() - models.keys():
        raise HTTPException(
            status_code=503, detail="Артефакти ALS відсутні; чинні моделі збережено",
        )
    request.app.state.als_models = models
    return ReloadResponse(loaded={domain: domain in models for domain in ("movie", "book")})
