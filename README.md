# Grocy Recipe Import

This project imports online recipes into Grocy.

It looks for Grocy recipes where the recipe name is a URL, scrapes that page, and updates Grocy with the imported data.

## Requirements

- A running Grocy instance with API enabled
- A Grocy API key
- Docker and Docker Compose

## Scraper Package

This project uses the Python package recipe-scrapers:

- Package repository: [recipe-scrapers](https://github.com/hhursev/recipe-scrapers)
- Supported websites list: [All supported scrapers](https://github.com/hhursev/recipe-scrapers#scrapers)

## Docker Compose Environment Variables

You can configure the importer through the `environment` section in `docker-compose.yml`:

- `GROCY_BASE_URL`: Base URL of your Grocy instance (for example `http://grocy:9283` or `https://grocy.example.com`).
- `GROCY_API_KEY`: API key generated in Grocy. Required for API access.
- `IMPORT_MODE`: Import behavior. Use `replace` to overwrite the URL placeholder recipe, or `copy` to create a new recipe.
- `POLL_INTERVAL_SECONDS`: Interval in seconds between automatic import cycles in loop mode.
- `REQUEST_TIMEOUT_SECONDS`: HTTP timeout in seconds for Grocy and recipe source requests.
- `MATCH_PRODUCTS`: `true` or `false`. When enabled, ingredients are matched to Grocy products and recipe positions are created.
- `AUTO_CREATED_PRODUCTS_GROUP_NAME`: Name of the product group for auto-created products when no suitable product exists.
- `LOG_LEVEL`: Logging verbosity (for example `DEBUG`, `INFO`, `WARNING`, `ERROR`).

## Setup

1. Edit the environment section in docker-compose.yml and set at least:

- `GROCY_BASE_URL`
- `GROCY_API_KEY`

2. Start the importer:

```bash
docker compose up -d
```

3. Check logs:

```bash
docker compose logs -f grocy-recipe-import
```

## How To Import A Recipe

1. In Grocy, create a new recipe.
2. Put the recipe URL into the recipe name field, for example `https://example.com/recipe/...`.
3. Save the recipe.
4. Wait for the importer loop or restart the container to trigger another cycle.

## Update Or Stop

- Pull latest image and restart:

```bash
docker compose pull
docker compose up -d
```

- Stop the importer:

```bash
docker compose down
```

## Notes

- Import mode is controlled by `IMPORT_MODE` in docker-compose.yml (`replace` or `copy`).
- Ingredient matching depends on your existing Grocy products and recipe source quality.
- If scraping fails, error details are written back to the Grocy recipe.

## AI Disclosure

This entire project and its documentation were created with AI.
