import csv
import gzip
import zipfile

import httpx
import pandas as pd
import pytest

from scripts.data_common import (
    ImportSummary,
    book_rating,
    movie_rating,
    normalize_isbn,
    parse_movie_title,
    read_bx,
)
from scripts.download_data import BX_FILES, download_archive, download_bx_mirror, extract_files
from scripts.enrich_openlibrary import OpenLibraryClient, extract_metadata
from scripts.import_bookcrossing import filter_k_core


@pytest.mark.parametrize(("raw", "title", "year"), [
    ("Toy Story (1995)", "Toy Story", 1995),
    ("Film (Director's Cut) (2001) ", "Film (Director's Cut)", 2001),
    ("No year", "No year", None),
    ("(1995) A Film", "(1995) A Film", None),
    ("Tom &amp; Jerry (1940)", "Tom & Jerry", 1940),
])
def test_movie_title(raw, title, year):
    assert parse_movie_title(raw) == (title, year)


@pytest.mark.parametrize(("raw", "expected"), [
    ("0-8044-2957-x", "080442957X"), (" 978 0 123 45678 9 ", "9780123456789"),
    ("", ""),
])
def test_isbn(raw, expected):
    assert normalize_isbn(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), [("0.5", 1), ("4.5", 9), (5.0, 10)])
def test_movie_rating(raw, expected):
    assert movie_rating(raw) == expected


@pytest.mark.parametrize("raw", ["0", "5.5", "3.7", "NaN", "inf", "invalid"])
def test_invalid_movie_rating(raw):
    with pytest.raises(ValueError):
        movie_rating(raw)


@pytest.mark.parametrize(("raw", "expected"), [
    ("0", (None, True)), (1, (1, False)), (10, (10, False)),
])
def test_book_rating(raw, expected):
    assert book_rating(raw) == expected


@pytest.mark.parametrize("raw", ["-1", "11", "1.5", "invalid"])
def test_invalid_book_rating(raw):
    with pytest.raises(ValueError):
        book_rating(raw)


def test_k_core_repeats_until_stable():
    frame = pd.DataFrame(
        [("1", "a"), ("1", "b"), ("2", "a"), ("2", "c"), ("3", "c")],
        columns=["User-ID", "ISBN"],
    )
    # The first pass leaves user 2 with a/c, which fail on the second pass.
    assert filter_k_core(frame, min_user=2, min_book=2).empty


def test_bx_counts_bad_rows_and_reads_latin1(tmp_path):
    path = tmp_path / "books.csv"
    with path.open("w", encoding="latin-1", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerows([("ISBN", "Book-Title"), ("1", "Les Misérables")])
        stream.write('"2";"broken";"extra column"\n')
    summary = ImportSummary()
    frame = read_bx(path, summary)
    assert frame["Book-Title"].tolist() == ["Les Misérables"]
    assert summary.skipped == 1


def test_download_and_extraction_are_repeatable(tmp_path):
    source = tmp_path / "source.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("dataset/ratings.csv", "user,item\n1,2\n")
        archive.writestr("../unrequested.txt", "unused")
    calls = []

    def request(req):
        calls.append(req)
        return httpx.Response(200, content=source.read_bytes())

    target = tmp_path / "cached.zip"
    with httpx.Client(transport=httpx.MockTransport(request)) as client:
        assert download_archive(client, "https://example.org/data.zip", target)
        assert not download_archive(client, "https://example.org/data.zip", target)
    assert len(calls) == 1
    output = tmp_path / "extracted"
    assert extract_files(target, output, ("ratings.csv",)) == 1
    assert extract_files(target, output, ("ratings.csv",)) == 0
    assert not (tmp_path / "unrequested.txt").exists()


def test_download_rejects_html_without_replacing_archive(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, text="<html>moved</html>"),
    )) as client, pytest.raises(ValueError, match="ZIP"):
        download_archive(client, "https://example.org/data.zip", tmp_path / "data.zip")
    assert not (tmp_path / "data.zip").exists()


def test_mirror_recovers_from_corrupt_gzip_and_reuses_local_files(tmp_path):
    calls = []

    def request(req):
        calls.append(req)
        content = b"not gzip" if len(calls) == 1 else gzip.compress(b"original CSV contents")
        return httpx.Response(200, content=content)

    with httpx.Client(transport=httpx.MockTransport(request)) as client:
        with pytest.raises(gzip.BadGzipFile):
            download_bx_mirror(client, tmp_path)
        assert not (tmp_path / f"{BX_FILES[0]}.gz").exists()
        assert download_bx_mirror(client, tmp_path) == (3, 3)
        assert download_bx_mirror(client, tmp_path) == (0, 0)
    assert len(calls) == 4
    assert all((tmp_path / "bookcrossing" / name).read_bytes() == b"original CSV contents"
               for name in BX_FILES)


def test_openlibrary_metadata_supports_both_description_shapes():
    assert extract_metadata({"details": {"description": {"value": "A &amp; B"},
        "subjects": ["Fiction", {"name": "Fiction"}, "History"]}}) == (
        "A & B", ["Fiction", "History"],
    )
    assert extract_metadata({"details": {"description": "Plain text"}}) == ("Plain text", [])
    assert extract_metadata({}) == (None, [])


def test_openlibrary_retries_and_caches_absent_books(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.enrich_openlibrary.time.sleep", lambda _: None)
    calls = []

    def request(req):
        calls.append(req)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"ISBN:080442957X": {"details": {"description": "Text"}}})

    with httpx.Client(transport=httpx.MockTransport(request)) as http:
        client = OpenLibraryClient(http, tmp_path)
        first = client.get_books(["080442957X", "0000000000"])
        assert first["0000000000"] == {}
        assert client.get_books(["080442957X", "0000000000"]) == first
        assert client.requests == 2
        assert client.cache_hits == 2
    assert len(calls) == 2


def test_openlibrary_does_not_cache_failed_request(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.enrich_openlibrary.time.sleep", lambda _: None)
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as http:
        client = OpenLibraryClient(http, tmp_path)
        with pytest.raises(httpx.HTTPStatusError):
            client.get_books(["080442957X"])
    assert list(tmp_path.glob("*.json")) == []
