"""Read-only access to the offline evaluation report written by scripts/evaluate.py."""

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.config import get_settings

router = APIRouter(prefix="/evaluation", tags=["evaluation"])

DOMAINS = ("movie", "book")
FILE_NAME = re.compile(r"^(movie|book)_\d{4}-\d{2}-\d{2}(_ndcg10|_by_k)?\.(png|csv)$")
MEDIA_TYPES = {"png": "image/png", "csv": "text/csv; charset=utf-8"}


class EvaluationResults(BaseModel):
    domains: dict[str, dict[str, Any] | None]


def eval_dir() -> Path:
    return get_settings().artifacts_dir / "eval"


def read_summary(domain: str) -> dict[str, Any] | None:
    path = eval_dir() / f"{domain}_latest.json"
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


@router.get("/results", response_model=EvaluationResults)
def results() -> EvaluationResults:
    return EvaluationResults(domains={domain: read_summary(domain) for domain in DOMAINS})


@router.get("/files/{name}")
def file(name: str) -> FileResponse:
    if not FILE_NAME.fullmatch(name):
        raise HTTPException(status_code=404, detail="Файл не знайдено")
    path = eval_dir() / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Файл не знайдено")
    return FileResponse(path, media_type=MEDIA_TYPES[name.rsplit(".", 1)[1]],
                        headers={"Cache-Control": "no-cache"})
