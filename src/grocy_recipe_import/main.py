from __future__ import annotations

import argparse
import logging

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
    if args.mode == "once":
        importer.run_once()
        return
    importer.run_forever()


if __name__ == "__main__":
    main()
