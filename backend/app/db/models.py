from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, REAL
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_users_source_external_id"),
        CheckConstraint("source IN ('web', 'movielens', 'bookcrossing')", name="ck_users_source"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_items_source_external_id"),
        CheckConstraint("domain IN ('movie', 'book')", name="ck_items_domain"),
        CheckConstraint("source IN ('movielens', 'bookcrossing')", name="ck_items_source"),
        Index("ix_items_domain_rating_count", "domain", text("rating_count DESC")),
        Index("ix_items_genres", "genres", postgresql_using="gin"),
        Index("ix_items_title_trgm", "title", postgresql_using="gin",
              postgresql_ops={"title": "gin_trgm_ops"}),
        Index("ix_items_embedding_hnsw", "embedding", postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    domain: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer)
    creators: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    genres: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    description: Mapped[str | None] = mapped_column(Text)
    cover_url: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))
    rating_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    rating_avg: Mapped[float] = mapped_column(REAL, server_default=text("0"))


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (
        CheckConstraint(
            "(implicit AND value IS NULL) OR "
            "(NOT implicit AND value IS NOT NULL AND value BETWEEN 1 AND 10)",
            name="ck_ratings_value",
        ),
        Index("ix_ratings_item_id", "item_id"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), primary_key=True)
    value: Mapped[int | None] = mapped_column(SmallInteger)
    implicit: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    rated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Interaction(Base):
    __tablename__ = "interactions"
    __table_args__ = (
        CheckConstraint("kind = 'view'", name="ck_interactions_kind"),
        Index("ix_interactions_user_created", "user_id", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    kind: Mapped[str] = mapped_column(Text, server_default=text("'view'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LlmCache(Base):
    __tablename__ = "llm_cache"
    __table_args__ = (
        UniqueConstraint("user_id", "domain", "profile_hash", name="uq_llm_cache_profile"),
        CheckConstraint("domain IN ('movie', 'book')", name="ck_llm_cache_domain"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    domain: Mapped[str] = mapped_column(Text)
    profile_hash: Mapped[str] = mapped_column(Text)
    payload: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
