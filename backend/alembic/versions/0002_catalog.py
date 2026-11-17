"""Catalog, dataset users, ratings, history and explanation cache.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("email", sa.Text(), unique=True),
        sa.Column("password_hash", sa.Text()),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("source", "external_id", name="uq_users_source_external_id"),
        sa.CheckConstraint("source IN ('web', 'movielens', 'bookcrossing')", name="ck_users_source"),
    )
    op.create_table(
        "items",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("year", sa.Integer()),
        sa.Column("creators", pg.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("genres", pg.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("description", sa.Text()),
        sa.Column("cover_url", sa.Text()),
        sa.Column("meta", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("embedding", Vector(1024)),
        sa.Column("rating_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("rating_avg", pg.REAL(), nullable=False, server_default=sa.text("0")),
        sa.UniqueConstraint("source", "external_id", name="uq_items_source_external_id"),
        sa.CheckConstraint("domain IN ('movie', 'book')", name="ck_items_domain"),
        sa.CheckConstraint("source IN ('movielens', 'bookcrossing')", name="ck_items_source"),
    )
    op.create_index("ix_items_domain_rating_count", "items",
                    ["domain", sa.text("rating_count DESC")])
    op.create_index("ix_items_genres", "items", ["genres"], postgresql_using="gin")
    op.create_index("ix_items_title_trgm", "items", ["title"], postgresql_using="gin",
                    postgresql_ops={"title": "gin_trgm_ops"})
    # HNSW is created after bulk embedding generation in stage 2.
    op.create_table(
        "ratings",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("item_id", sa.BigInteger(), sa.ForeignKey("items.id"), primary_key=True),
        sa.Column("value", sa.SmallInteger()),
        sa.Column("implicit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("rated_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "(implicit AND value IS NULL) OR "
            "(NOT implicit AND value IS NOT NULL AND value BETWEEN 1 AND 10)",
            name="ck_ratings_value",
        ),
    )
    op.create_index("ix_ratings_item_id", "ratings", ["item_id"])
    op.create_table(
        "interactions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("item_id", sa.BigInteger(), sa.ForeignKey("items.id"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False, server_default=sa.text("'view'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("kind = 'view'", name="ck_interactions_kind"),
    )
    op.create_index("ix_interactions_user_created", "interactions",
                    ["user_id", sa.text("created_at DESC")])
    op.create_table(
        "llm_cache",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("profile_hash", sa.Text(), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "domain", "profile_hash", name="uq_llm_cache_profile"),
        sa.CheckConstraint("domain IN ('movie', 'book')", name="ck_llm_cache_domain"),
    )


def downgrade():
    op.drop_table("llm_cache")
    op.drop_table("interactions")
    op.drop_table("ratings")
    op.drop_table("items")
    op.drop_table("users")
