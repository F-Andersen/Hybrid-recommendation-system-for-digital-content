"""Exercise actual PostgreSQL upserts in an isolated, rolled-back schema."""

import csv

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.models import Item, Rating, User
from scripts.enrich_openlibrary import OpenLibraryClient, enrich
from scripts.import_bookcrossing import import_dataset as import_books
from scripts.import_movielens import import_dataset as import_movies


def write_csv(path, columns, rows, delimiter=",", encoding="utf-8"):
    with path.open("w", encoding=encoding, newline="") as stream:
        writer = csv.writer(stream, delimiter=delimiter)
        writer.writerow(columns)
        writer.writerows(rows)


@pytest.fixture
def movie_files(tmp_path):
    write_csv(tmp_path / "movies.csv", ["movieId", "title", "genres"], [
        (1, "Toy Story (1995)", "Adventure|Animation"), (2, "Film", "(no genres listed)"),
    ])
    write_csv(tmp_path / "ratings.csv", ["userId", "movieId", "rating", "timestamp"], [
        (1, 1, "4.5", 100), (1, 1, "5.0", 101), (2, 1, "0.5", 102), (1, 2, "3.0", 103),
        (3, 99, "4.0", 104), (3, 1, "8.0", 105),
    ])
    write_csv(tmp_path / "tags.csv", ["userId", "movieId", "tag", "timestamp"], [
        (1, 1, "animation", 100), (2, 1, "animation", 101), (1, 1, "fun", 102),
    ])
    write_csv(tmp_path / "links.csv", ["movieId", "imdbId", "tmdbId"], [
        (1, "0114709", "862"), (2, "0000002", ""),
    ])
    return tmp_path


@pytest.fixture
def book_files(tmp_path):
    write_csv(tmp_path / "BX-Books.csv", [
        "ISBN", "Book-Title", "Book-Author", "Year-Of-Publication", "Publisher",
        "Image-URL-S", "Image-URL-M", "Image-URL-L",
    ], [
        (f"000000000{i}", f"Book &amp; {i}", "René", "2000", "Publisher", "", "", "")
        for i in range(5)
    ], delimiter=";", encoding="latin-1")
    write_csv(tmp_path / "BX-Users.csv", ["User-ID", "Location", "Age"], [
        (user, "", "NULL") for user in range(1, 12)
    ], delimiter=";", encoding="latin-1")
    write_csv(tmp_path / "BX-Book-Ratings.csv", ["User-ID", "ISBN", "Book-Rating"], [
        (user, f"000000000{i}", 0 if user == 1 else 8)
        for user in range(1, 11) for i in range(5)
    ] + [(11, "0000000000", 5), (1, "unknown", 9)], delimiter=";", encoding="latin-1")
    return tmp_path


def counts(session):
    return tuple(session.scalar(select(func.count()).select_from(model))
                 for model in (User, Item, Rating))


def test_movie_import_is_repeatable_and_normalizes_data(sessions, movie_files):
    with sessions.begin() as session:
        result = import_movies(session, movie_files, "ml-latest-small")
        assert (result.users, result.items, result.ratings) == (2, 2, 3)
        assert (result.skipped, result.duplicates) == (2, 1)
        first_counts = counts(session)
        movie = session.scalar(select(Item).where(Item.external_id == "1"))
        assert (movie.title, movie.year) == ("Toy Story", 1995)
        assert movie.meta["tags"] == ["animation", "fun"]
        assert movie.meta["imdbId"] == "0114709"
        assert movie.rating_count == 2
        assert movie.rating_avg == pytest.approx(5.5)
        assert session.scalar(select(Item.genres).where(Item.external_id == "2")) == []
        assert session.scalar(select(Rating.rated_at)).tzinfo is not None
    with sessions.begin() as session:
        import_movies(session, movie_files, "ml-latest-small")
        assert counts(session) == first_counts
    with sessions.begin() as session, pytest.raises(ValueError, match="змішувати"):
        import_movies(session, movie_files, "ml-1m")


def test_large_variant_filters_catalog_samples_users_and_replaces(sessions, movie_files):
    with sessions.begin() as session:
        import_movies(session, movie_files, "ml-latest-small")
        old_movie = session.scalar(select(Item.id).where(Item.external_id == "1"))
    # 25M-style data: film 1 has 3 ratings, film 2 only 1 -> filtered by min_movie_ratings=2
    write_csv(movie_files / "ratings.csv", ["userId", "movieId", "rating", "timestamp"], [
        (10, 1, "4.5", 100), (11, 1, "3.0", 101), (12, 1, "5.0", 102), (10, 2, "2.0", 103),
        (10, 1, "1.0", 99), (13, 1, "9.0", 104),
    ])
    with sessions.begin() as session, pytest.raises(ValueError, match="змішувати"):
        import_movies(session, movie_files, "ml-25m")
    with sessions.begin() as session:
        result = import_movies(session, movie_files, "ml-25m", replace=True,
                               min_movie_ratings=2)
        assert (result.items, result.users, result.ratings) == (1, 3, 3)
        assert (result.skipped, result.duplicates) == (1, 2)
        movie = session.scalar(select(Item).where(Item.external_id == "1"))
        assert movie.id == old_movie  # same movieId keeps its row (embedding, poster)
        assert movie.meta["dataset_variant"] == "ml-25m"
        assert movie.rating_count == 3
        assert session.scalar(select(Item).where(Item.external_id == "2")) is None
        externals = set(session.scalars(select(User.external_id).where(
            User.source == "movielens")))
        assert externals == {"10", "11", "12"}  # old users of the small variant removed
        value = session.scalar(select(Rating.value).join(User).where(User.external_id == "10"))
        assert value == 9  # latest of the duplicated (10, 1) ratings, scaled to 1-10
    with sessions.begin() as session:
        sampled = import_movies(session, movie_files, "ml-25m", replace=True,
                                min_movie_ratings=2, max_users=2)
        assert sampled.users == 2


def test_movielens_1m_dat_format(sessions, tmp_path):
    (tmp_path / "movies.dat").write_text("1::Amélie (2001)::Comedy|Romance\n", encoding="latin-1")
    (tmp_path / "ratings.dat").write_text("1::1::4::100\n", encoding="latin-1")
    with sessions.begin() as session:
        summary = import_movies(session, tmp_path, "ml-1m")
        assert (summary.users, summary.items, summary.ratings) == (1, 1, 1)
        assert session.scalar(select(Item.title)) == "Amélie"
        assert session.scalar(select(Rating.value)) == 8


def test_books_k_core_repeatability_and_enrichment_cache(sessions, book_files, tmp_path):
    with sessions.begin() as session:
        result = import_books(session, book_files)
        assert (result.users, result.items, result.ratings) == (10, 5, 50)
        assert (result.filtered, result.skipped) == (1, 1)
        assert session.scalar(select(func.count()).where(Rating.implicit)) == 5
        assert session.scalar(select(Rating.value).where(Rating.implicit)) is None
        assert session.scalar(select(Item.rating_avg)) == 8
        first_counts = counts(session)
    calls = []

    def request(req):
        calls.append(req)
        return httpx.Response(200, json={
            f"ISBN:000000000{i}": {
                "details": {"description": "Description", "subjects": ["Fiction"]},
            }
            for i in range(5)
        })

    with httpx.Client(transport=httpx.MockTransport(request)) as http:
        client = OpenLibraryClient(http, tmp_path / "cache")
        assert enrich(sessions, client)["descriptions"] == 5
        assert enrich(sessions, client)["cache_hits"] == 5
    assert len(calls) == 1
    with sessions.begin() as session:
        import_books(session, book_files)
        assert counts(session) == first_counts
        book = session.scalar(select(Item))
        assert book.description == "Description"
        assert book.genres == ["Fiction"]
        assert book.meta["publisher"] == "Publisher"
        assert book.title.startswith("Book & ")
        assert book.cover_url.endswith("?default=false")


@pytest.mark.parametrize(("value", "implicit"), [(None, False), (0, False), (11, False), (8, True)])
def test_database_rejects_inconsistent_ratings(sessions, movie_files, value, implicit):
    with sessions.begin() as session:
        import_movies(session, movie_files, "ml-latest-small")
    with pytest.raises(IntegrityError), sessions.begin() as session:
        rating = session.scalar(select(Rating))
        rating.value, rating.implicit = value, implicit
        session.flush()
