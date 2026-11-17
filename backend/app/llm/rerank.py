"""Validate untrusted model choices and preserve a usable hybrid fallback."""

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.llm.prompts import response_schema

logger = logging.getLogger(__name__)


class ChatClient(Protocol):
    async def chat_json(
        self, messages: list[dict[str, str]], schema: dict[str, Any], model: str,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RerankChoice:
    n: int
    explanation: str


def clean_explanation(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value):
        return None
    value = " ".join(value.split())
    if not 10 <= len(value) <= 400 or len(re.findall(r"[А-Яа-яІіЇїЄєҐґ]", value)) < 10:
        return None
    return value


def validate_choices(payload: object, candidate_count: int) -> list[RerankChoice]:
    if not isinstance(payload, dict) or not isinstance(payload.get("recommendations"), list):
        raise ValueError("Відсутній список рекомендацій у відповіді LLM")
    choices, seen = [], set()
    for row in payload["recommendations"]:
        if not isinstance(row, dict):
            continue
        n = row.get("n")
        explanation = clean_explanation(row.get("explanation"))
        if (type(n) is not int or not 1 <= n <= candidate_count or n in seen
                or explanation is None):
            continue
        seen.add(n)
        choices.append(RerankChoice(n, explanation))
        if len(choices) == min(10, candidate_count):
            break
    return choices


async def rerank(
    client: ChatClient, messages: list[dict[str, str]], candidate_count: int, model: str,
) -> list[RerankChoice]:
    if not candidate_count:
        return []
    for attempt in range(2):
        try:
            payload = await client.chat_json(messages, response_schema(candidate_count), model)
            return validate_choices(payload, candidate_count)
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("LLM недоступна; повертаємо гібрид: %s", type(exc).__name__)
            break
        except (ValueError, TypeError) as exc:
            logger.warning("Некоректна відповідь LLM, спроба %s: %s", attempt + 1,
                           type(exc).__name__)
    return []
