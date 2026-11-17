import runpy
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Item
from app.db.session import engine
from app.recsys.vectors import normalize_vectors


@pytest.fixture
def sessions():
    """Real PostgreSQL schema, including the content invalidation trigger."""
    with engine.connect() as connection:
        transaction = connection.begin()
        schema = "test_recsys_" + uuid4().hex
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        Base.metadata.create_all(connection, checkfirst=False)
        migration = runpy.run_path(str(
            Path(__file__).parents[1] / "alembic/versions/0003_content_invalidation.py",
        ))
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
        try:
            yield sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
        finally:
            transaction.rollback()


@pytest.fixture
def catalog(sessions):
    vectors = normalize_vectors(np.random.default_rng(42).normal(size=(41, 1024)))
    with sessions.begin() as session:
        for index, vector in enumerate(vectors):
            session.add(Item(
                domain="movie" if index < 40 else "book",
                source="movielens" if index < 40 else "bookcrossing",
                external_id=str(index), title="100%_literal" if index == 0 else f"Movie {index:02}",
                genres=(["Action"] if index % 2 == 0 else ["Drama"])
                if index < 40 else ["Fiction"],
                creators=[], year=1980 + index if index else None,
                rating_count=index, rating_avg=8, embedding=vector,
            ))
    return vectors
