"""Invalidate stale embeddings when their source content changes.

Revision ID: 0003
Revises: 0002

The HNSW index is created by build_embeddings after the initial bulk load.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE FUNCTION invalidate_item_embedding() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF ROW(NEW.domain, NEW.title, NEW.year, NEW.creators, NEW.genres, NEW.description,
                   NEW.meta->'tags', NEW.meta->'publisher')
               IS DISTINCT FROM
               ROW(OLD.domain, OLD.title, OLD.year, OLD.creators, OLD.genres, OLD.description,
                   OLD.meta->'tags', OLD.meta->'publisher') THEN
                NEW.embedding = NULL;
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER items_invalidate_embedding
        BEFORE UPDATE ON items
        FOR EACH ROW EXECUTE FUNCTION invalidate_item_embedding()
    """)


def downgrade():
    op.execute("DROP TRIGGER items_invalidate_embedding ON items")
    op.execute("DROP FUNCTION invalidate_item_embedding()")
