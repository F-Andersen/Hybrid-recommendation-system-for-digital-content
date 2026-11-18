"""Check TMDB credentials without printing secrets or changing catalogue data."""

import argparse
import json

import httpx

from app.core.config import get_settings
from app.integrations.tmdb import AuthMode, TmdbClient, TmdbError


def main() -> None:
    parser = argparse.ArgumentParser(description="Перевірка підключення до TMDB")
    parser.add_argument("--auth", choices=["auto", "key", "token", "both"], default="auto")
    args = parser.parse_args()
    modes: list[AuthMode] = ["key", "token"] if args.auth == "both" else [args.auth]
    settings = get_settings()
    results = []
    with httpx.Client(timeout=30) as http:
        for mode in modes:
            try:
                client = TmdbClient(http, settings, auth=mode)
                configuration = client.configuration()
                images = configuration.get("images")
                if not isinstance(images, dict) or not images.get("secure_base_url"):
                    raise TmdbError("У конфігурації TMDB немає адреси зображень")
                results.append({"auth": client.auth, "status": "ok"})
            except TmdbError as error:
                parser.exit(1, f"TMDB ({mode}): {error}\n")
    print(json.dumps({"tmdb": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
