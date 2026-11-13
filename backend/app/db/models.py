from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base. Tables are added in stage 1 (docs/IMPLEMENTATION.md, section 03)."""
