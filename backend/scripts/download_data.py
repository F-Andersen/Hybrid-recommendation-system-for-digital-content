"""Download and safely extract dataset archives into the named data volume."""

import argparse
import gzip
import json
import shutil
import zipfile
from pathlib import Path

import httpx

from app.core.config import get_settings

MOVIELENS_URL = "https://files.grouplens.org/datasets/movielens/{variant}.zip"
BOOKCROSSING_URL = "https://www2.informatik.uni-freiburg.de/~cziegler/BX/BX-CSV-Dump.zip"
BX_FILES = ("BX-Books.csv", "BX-Book-Ratings.csv", "BX-Users.csv")
USER_AGENT = "HybridRecommender/0.1 (academic dataset preparation)"
BX_MIRROR_COMMIT = "b21eb595d30bb0a9cda840be937af02b9b7bfa77"
BX_MIRROR = f"https://raw.githubusercontent.com/zheng-da/BookCrossing/{BX_MIRROR_COMMIT}"


def download_bx_mirror(client: httpx.Client, directory: Path) -> tuple[int, int]:
    """Use original CSVs, not the mirror's fixed/preprocessed subsets."""
    downloaded = extracted = 0
    destination = directory / "bookcrossing"
    destination.mkdir(parents=True, exist_ok=True)
    for name in BX_FILES:
        target = destination / name
        archive = directory / f"{name}.gz"
        url = f"{BX_MIRROR}/{name}.gz"
        if not archive.exists():
            partial = archive.with_suffix(".gz.part")
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with partial.open("wb") as output:
                    for chunk in response.iter_bytes(1024 * 1024):
                        output.write(chunk)
            # Gzip CRC validation is completed while extracting below.
            partial.replace(archive)
            downloaded += 1
        if not target.exists():
            partial = target.with_suffix(".csv.part")
            try:
                with gzip.open(archive, "rb") as source, partial.open("wb") as output:
                    shutil.copyfileobj(source, output)
            except (gzip.BadGzipFile, EOFError):
                archive.unlink(missing_ok=True)
                partial.unlink(missing_ok=True)
                raise
            partial.replace(target)
            extracted += 1
        target.with_suffix(".source.json").write_text(
            json.dumps({"url": url, "commit": BX_MIRROR_COMMIT}, indent=2), encoding="utf-8",
        )
    return downloaded, extracted


def download_archive(client: httpx.Client, url: str, path: Path) -> bool:
    if path.exists() and zipfile.is_zipfile(path):
        print(f"Архів уже є: {path.name}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".zip.part")
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with partial.open("wb") as stream:
            for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                stream.write(chunk)
    if not zipfile.is_zipfile(partial):
        partial.unlink(missing_ok=True)
        raise ValueError(
            f"{url} повернув не ZIP-архів. Для Book-Crossing передайте перевірений "
            "URL через --bookcrossing-url або покладіть BX-CSV-Dump.zip у DATA_DIR."
        )
    partial.replace(path)
    # Preserve provenance; archives and manifests are excluded from Git.
    path.with_suffix(".source.json").write_text(
        json.dumps({"url": url}, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"Завантажено: {path.name} ({path.stat().st_size:,} байт)")
    return True


def extract_files(archive: Path, destination: Path, filenames: tuple[str, ...]) -> int:
    destination.mkdir(parents=True, exist_ok=True)
    extracted = 0
    with zipfile.ZipFile(archive) as zipped:
        by_name = {Path(member.filename).name: member for member in zipped.infolist()}
        missing = set(filenames) - by_name.keys()
        if missing:
            raise ValueError(f"У {archive.name} відсутні файли: {sorted(missing)}")
        for name in filenames:
            target = destination / name
            member = by_name[name]
            if target.exists() and target.stat().st_size == member.file_size:
                continue
            partial = target.with_suffix(target.suffix + ".part")
            with zipped.open(member) as source, partial.open("wb") as output:
                shutil.copyfileobj(source, output)
            partial.replace(target)
            extracted += 1
    return extracted


def main() -> None:
    parser = argparse.ArgumentParser(description="Завантаження датасетів")
    parser.add_argument("--dataset", choices=("all", "movielens", "bookcrossing"), default="all")
    parser.add_argument(
        "--variant", choices=("ml-latest-small", "ml-1m", "ml-25m"), default="ml-25m",
    )
    parser.add_argument("--bookcrossing-source", choices=("github", "official"), default="github")
    parser.add_argument("--bookcrossing-url", default=BOOKCROSSING_URL)
    args = parser.parse_args()
    directory = get_settings().data_dir
    downloaded = extracted = 0
    with httpx.Client(
        timeout=httpx.Timeout(120, connect=20), follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        if args.dataset in ("all", "movielens"):
            path = directory / f"{args.variant}.zip"
            downloaded += download_archive(client, MOVIELENS_URL.format(variant=args.variant), path)
            files = (
                ("movies.dat", "ratings.dat", "users.dat", "README") if args.variant == "ml-1m"
                else ("movies.csv", "ratings.csv", "tags.csv", "links.csv", "README.txt")
            )
            extracted += extract_files(path, directory / args.variant, files)
        if args.dataset in ("all", "bookcrossing"):
            path = directory / "BX-CSV-Dump.zip"
            if (path.exists() or args.bookcrossing_source == "official"
                    or args.bookcrossing_url != BOOKCROSSING_URL):
                downloaded += download_archive(client, args.bookcrossing_url, path)
                extracted += extract_files(path, directory / "bookcrossing", BX_FILES)
            else:
                new_downloads, new_files = download_bx_mirror(client, directory)
                downloaded += new_downloads
                extracted += new_files
    print(json.dumps({"downloaded": downloaded, "extracted": extracted}))


if __name__ == "__main__":
    main()
