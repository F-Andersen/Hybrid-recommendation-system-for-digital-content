import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        local, separator, domain = value.rpartition("@")
        label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
        if (not separator or not 1 <= len(local) <= 64
                or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)
                or local.startswith(".") or local.endswith(".") or ".." in local
                or not re.fullmatch(rf"{label}(?:\.{label})+", domain)):
            raise ValueError("Укажіть коректну електронну адресу")
        return value


class RegisterRequest(LoginRequest):
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("display_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(character) < 32 for character in value):
            raise ValueError("Укажіть ім'я без керувальних символів")
        return value

    @field_validator("password")
    @classmethod
    def nonblank_password(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("Пароль не може бути порожнім або містити нульовий символ")
        return value


class UserProfile(BaseModel):
    id: int
    email: str
    display_name: str
    created_at: datetime
    rating_counts: dict[str, int]
