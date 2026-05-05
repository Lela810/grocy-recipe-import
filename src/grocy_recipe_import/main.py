from __future__ import annotations

import argparse
import logging
import time

import requests

from grocy_recipe_import.config import Config
from grocy_recipe_import.importer import RecipeImporter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Importiert Rezept-URLs aus Grocy per recipe-scrapers")
    parser.add_argument("mode", nargs="?", choices=["once", "loop"], default="loop")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = Config.from_env()
    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    importer = RecipeImporter(config)

    logger = logging.getLogger(__name__)

    try:
        importer.check_connection()
    except requests.HTTPError as exc:
        key = config.grocy_api_key
        key_hint = f"{key[:4]}...{key[-4:]}" if len(key) >= 8 else "(too short)"
        if exc.response is not None and exc.response.status_code == 401:
            logger.critical(
                "Grocy authentication failed (401 Unauthorized). "
                "URL: %s | API key used (first/last 4 chars): %s "
                "| Check GROCY_API_KEY in docker-compose.yml. Container will sleep to prevent restart loop.",
                config.grocy_api_base,
                key_hint,
            )
        else:
            logger.critical(
                "Grocy API error during startup: %s | URL: %s. Container will sleep to prevent restart loop.",
                exc,
                config.grocy_api_base,
            )
        _sleep_forever()
    except Exception as exc:
        logger.critical(
            "Could not reach Grocy at %s: %s | Check GROCY_BASE_URL in docker-compose.yml. Container will sleep to prevent restart loop.",
            config.grocy_base_url,
            exc,
        )
        _sleep_forever()

    if args.mode == "once":
        importer.run_once()
        return
    importer.run_forever()


def _sleep_forever() -> None:
    """Block forever so Docker does not restart the container on a fatal config error."""
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
