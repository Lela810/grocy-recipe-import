from __future__ import annotations

import html
import logging
import re
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from recipe_scrapers import scrape_html, scrape_me

from grocy_recipe_import.config import Config
from grocy_recipe_import.grocy import GrocyClient

LOGGER = logging.getLogger(__name__)
IMPORT_MARKER = "grocy-recipe-import"
IMPORT_ERROR_START = f"<!-- {IMPORT_MARKER}: error-start -->"
IMPORT_ERROR_END = f"<!-- {IMPORT_MARKER}: error-end -->"
ERROR_NAME_PREFIX = "FEHLER: "

UNICODE_FRACTIONS = {
    "1/4": ["¼"],
    "1/2": ["½"],
    "3/4": ["¾"],
    "1/3": ["⅓"],
    "2/3": ["⅔"],
    "1/8": ["⅛"],
    "3/8": ["⅜"],
    "5/8": ["⅝"],
    "7/8": ["⅞"],
}

UNIT_ALIASES = {
    "g": {"g", "gram", "grams", "gramm", "gramme"},
    "kg": {"kg", "kilogram", "kilograms", "kilogramm"},
    "ml": {"ml", "milliliter", "milliliters", "millilitre"},
    "dl": {"dl", "deciliter", "deciliters", "deziliter", "dezilitre"},
    "cl": {"cl", "centiliter", "centiliters", "zentiliter"},
    "l": {"l", "liter", "liters", "litre", "litres"},
    "tl": {"tl", "teeloeffel", "teaspoon", "teaspoons", "tsp"},
    "el": {"el", "essloeffel", "tablespoon", "tablespoons", "tbsp"},
    "stk": {"stk", "stueck", "st", "piece", "pieces", "pcs", "pc"},
    "cup": {"cup", "cups", "tasse", "tassen"},
}

LEADING_INGREDIENT_QUALIFIERS = {
    "wenig",
    "etwas",
    "some",
    "a little",
    "nach geschmack",
}


@dataclass
class ScrapedRecipe:
    source_url: str
    title: str
    ingredients: list[str]
    instructions: str
    servings_text: str | None
    base_servings: float
    total_time_minutes: int | None
    image_url: str | None


@dataclass
class IngredientCandidate:
    original_text: str
    normalized_name: str
    display_name: str
    amount: float | None
    unit_key: str | None
    note: str


@dataclass
class IngredientProcessingResult:
    recipe_positions: list[dict[str, Any]]
    non_measurable_notes: list[str]


class ProductMatcher:
    def __init__(
        self,
        products: list[dict[str, Any]],
        quantity_units: list[dict[str, Any]],
        locations: list[dict[str, Any]],
        product_groups: list[dict[str, Any]],
        client: GrocyClient,
        auto_created_products_group_name: str | None,
    ) -> None:
        self._client = client
        self._products = [product for product in products if product.get("name")]
        self._normalized_products = sorted(
            ((self._normalize(product["name"]), product) for product in self._products),
            key=lambda item: len(item[0]),
            reverse=True,
        )
        self._canonical_unit_by_alias = self._build_canonical_unit_alias_map()
        self._unit_alias_to_id = self._build_unit_alias_map(quantity_units)
        self._default_location_id = self._resolve_default_location_id(locations)
        self._default_unit_id = self._resolve_default_unit_id(quantity_units)
        self._auto_created_products_group_id = self._resolve_auto_created_products_group_id(
            product_groups,
            auto_created_products_group_name,
        )

    def process_ingredients(self, ingredients: list[str]) -> IngredientProcessingResult:
        recipe_positions: list[dict[str, Any]] = []
        non_measurable_notes: list[str] = []
        for ingredient in ingredients:
            matched = self.match_or_create(ingredient)
            if matched is None:
                if ingredient.strip():
                    non_measurable_notes.append(ingredient.strip())
                continue
            recipe_positions.append(matched)
        return IngredientProcessingResult(
            recipe_positions=recipe_positions,
            non_measurable_notes=non_measurable_notes,
        )

    def match_or_create(self, ingredient: str) -> dict[str, Any] | None:
        candidate = self._parse_ingredient(ingredient)
        if candidate is None:
            return None

        if candidate.amount is None:
            return None

        matched_product = self._match_product(candidate.normalized_name)
        if matched_product is None:
            matched_product = self._create_product(candidate)

        unit_id = self._ensure_unit_id(candidate.unit_key) if candidate.unit_key else None
        result = {
            "product_id": int(matched_product["id"]),
            "amount": candidate.amount,
            "note": candidate.note,
        }
        if unit_id is not None:
            result["qu_id"] = unit_id
        return result

    def _match_product(self, normalized_ingredient: str) -> dict[str, Any] | None:
        exact = [product for normalized_name, product in self._normalized_products if normalized_name == normalized_ingredient]
        if len(exact) == 1:
            return exact[0]

        ingredient_tokens = self._token_set(normalized_ingredient)
        token_candidates: list[tuple[tuple[int, int], dict[str, Any]]] = []
        for normalized_name, product in self._normalized_products:
            product_tokens = self._token_set(normalized_name)
            if not product_tokens:
                continue
            if product_tokens.issubset(ingredient_tokens):
                score = (len(product_tokens), len(normalized_name))
                token_candidates.append((score, product))

        if not token_candidates:
            return None

        token_candidates.sort(key=lambda item: item[0], reverse=True)
        best_score = token_candidates[0][0]
        best = [product for score, product in token_candidates if score == best_score]
        if len(best) == 1:
            return best[0]
        return None

    def _token_set(self, normalized_value: str) -> set[str]:
        return {token for token in normalized_value.split() if token}

    def _create_product(self, candidate: IngredientCandidate) -> dict[str, Any]:
        unit_id = self._ensure_unit_id(candidate.unit_key) if candidate.unit_key else self._default_unit_id
        payload = {
            "name": candidate.display_name,
            "location_id": self._default_location_id,
            "qu_id_stock": unit_id,
            "qu_id_purchase": unit_id,
            "qu_id_consume": unit_id,
            "qu_id_price": unit_id,
            "active": 1,
        }
        if self._auto_created_products_group_id is not None:
            payload["product_group_id"] = self._auto_created_products_group_id
        product_id = self._client.create_product(payload)
        product = {"id": product_id, "name": candidate.display_name}
        self._products.append(product)
        self._normalized_products.insert(0, (candidate.normalized_name, product))
        return product

    def _parse_ingredient(self, ingredient: str) -> IngredientCandidate | None:
        text = ingredient.strip()
        if not text:
            return None

        normalized = self._normalize(self._replace_unicode_fractions(text))
        if not normalized:
            return None

        amount = self._extract_amount(text)
        remainder = self._strip_leading_amount(text) if amount is not None else text
        remainder_normalized = self._normalize(self._replace_unicode_fractions(remainder))
        unit_key = self._extract_unit_key(remainder_normalized)
        if amount is not None and unit_key is None:
            unit_key = "stk"
        display_source = self._strip_leading_unit(remainder) if unit_key is not None else remainder
        display_name = self._display_name_from_text(display_source)
        normalized_name = self._normalize(display_name)
        if not normalized_name:
            return None

        return IngredientCandidate(
            original_text=text,
            normalized_name=normalized_name,
            display_name=display_name,
            amount=amount,
            unit_key=unit_key,
            note=text,
        )

    def _build_canonical_unit_alias_map(self) -> dict[str, str]:
        alias_map: dict[str, str] = {}
        for canonical, aliases in UNIT_ALIASES.items():
            alias_map[self._normalize(canonical)] = canonical
            for alias in aliases:
                alias_map[self._normalize(alias)] = canonical
        return alias_map

    def _build_unit_alias_map(self, quantity_units: list[dict[str, Any]]) -> dict[str, int]:
        aliases: dict[str, int] = {}
        for quantity_unit in quantity_units:
            if int(quantity_unit.get("active", 1)) != 1:
                continue
            unit_id = int(quantity_unit["id"])
            for field in ("name", "name_plural", "description"):
                value = quantity_unit.get(field)
                if value:
                    aliases[self._normalize(value)] = unit_id

        for normalized_alias, canonical in self._canonical_unit_by_alias.items():
            canonical_normalized = self._normalize(canonical)
            if normalized_alias in aliases:
                aliases[canonical_normalized] = aliases[normalized_alias]

        for normalized_alias, canonical in self._canonical_unit_by_alias.items():
            canonical_normalized = self._normalize(canonical)
            if canonical_normalized in aliases:
                aliases[normalized_alias] = aliases[canonical_normalized]
        return aliases

    def _ensure_unit_id(self, unit_key: str) -> int | None:
        normalized_unit_key = self._normalize(unit_key)
        unit_id = self._unit_alias_to_id.get(normalized_unit_key)
        if unit_id is not None:
            return unit_id

        canonical = self._canonical_unit_by_alias.get(normalized_unit_key)
        if canonical is None:
            return None

        new_unit_id = self._client.create_quantity_unit(
            {
                "name": canonical,
                "name_plural": canonical,
                "active": 1,
            }
        )
        for alias, alias_canonical in self._canonical_unit_by_alias.items():
            if alias_canonical == canonical:
                self._unit_alias_to_id[alias] = new_unit_id
        self._unit_alias_to_id[self._normalize(canonical)] = new_unit_id
        return new_unit_id

    def _resolve_default_location_id(self, locations: list[dict[str, Any]]) -> int:
        active_locations = [location for location in locations if int(location.get("active", 1)) == 1]
        if not active_locations:
            raise ValueError("Keine aktive Grocy-Location fuer automatisch angelegte Produkte gefunden")
        return int(active_locations[0]["id"])

    def _resolve_default_unit_id(self, quantity_units: list[dict[str, Any]]) -> int:
        preferred_names = {"piece", "stueck", "stuck", "stk"}
        for quantity_unit in quantity_units:
            if int(quantity_unit.get("active", 1)) != 1:
                continue
            for field in ("name", "name_plural"):
                value = quantity_unit.get(field)
                if value and self._normalize(value) in preferred_names:
                    return int(quantity_unit["id"])

        active_units = [quantity_unit for quantity_unit in quantity_units if int(quantity_unit.get("active", 1)) == 1]
        if not active_units:
            raise ValueError("Keine aktive Mengeneinheit fuer automatisch angelegte Produkte gefunden")
        return int(active_units[0]["id"])

    def _resolve_auto_created_products_group_id(
        self,
        product_groups: list[dict[str, Any]],
        auto_created_products_group_name: str | None,
    ) -> int | None:
        if not auto_created_products_group_name:
            return None

        normalized_target = self._normalize(auto_created_products_group_name)
        for product_group in product_groups:
            group_name = product_group.get("name") or ""
            if self._normalize(group_name) == normalized_target:
                return int(product_group["id"])

        return self._client.create_product_group(
            {
                "name": auto_created_products_group_name,
                "description": "Automatisch vom Grocy Recipe Importer angelegt",
                "active": 1,
            }
        )

    def _extract_amount(self, ingredient: str) -> float | None:
        value = self._replace_unicode_fractions(ingredient)
        match = re.match(r"^\s*(\d+(?:[.,]\d+)?\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?)", value)
        if match is None:
            return None
        token = match.group(1).replace(",", ".").strip()
        if " " in token and "/" in token:
            whole, fraction = token.split(maxsplit=1)
            return float(whole) + float(Fraction(fraction))
        if "/" in token:
            return float(Fraction(token))
        return float(token)

    def _strip_leading_amount(self, ingredient: str) -> str:
        value = self._replace_unicode_fractions(ingredient)
        value = re.sub(r"^\s*(\d+(?:[.,]\d+)?\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?)(?:\s*[xX])?\s*", "", value)
        return value.strip()

    def _extract_unit_key(self, normalized_ingredient: str) -> str | None:
        parts = normalized_ingredient.split()
        if not parts:
            return None

        if len(parts) >= 2:
            candidate = " ".join(parts[:2])
            if candidate in self._canonical_unit_by_alias:
                return self._canonical_unit_by_alias[candidate]

        candidate = parts[0]
        if candidate in self._canonical_unit_by_alias:
            return self._canonical_unit_by_alias[candidate]
        return None

    def _strip_leading_unit(self, ingredient: str) -> str:
        value = ingredient.strip()
        parts = value.split()
        if not parts:
            return value
        if len(parts) >= 2 and self._normalize(" ".join(parts[:2])) in self._canonical_unit_by_alias:
            return " ".join(parts[2:]).strip()
        if self._normalize(parts[0]) in self._canonical_unit_by_alias:
            return " ".join(parts[1:]).strip()
        return value

    def _display_name_from_text(self, value: str) -> str:
        text = self._replace_unicode_fractions(value)
        text = re.sub(r"\([^)]*\)", " ", text)
        text = re.sub(r"\s*,\s*.*$", "", text)
        text = re.sub(r"\s+", " ", text).strip(" ,")
        lower_text = text.lower()
        for qualifier in sorted(LEADING_INGREDIENT_QUALIFIERS, key=len, reverse=True):
            if lower_text.startswith(f"{qualifier} "):
                text = text[len(qualifier):].strip()
                break
        return text or value.strip()

    def _replace_unicode_fractions(self, value: str) -> str:
        result = value
        for fraction, glyphs in UNICODE_FRACTIONS.items():
            for glyph in glyphs:
                result = result.replace(glyph, f" {fraction}")
        return result

    def _normalize(self, value: str) -> str:
        cleaned = value.lower()
        cleaned = cleaned.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
        cleaned = re.sub(r"\([^)]*\)", " ", cleaned)
        cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()


class RecipeImporter:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._client = GrocyClient(config)
        self._http = requests.Session()

    def run_forever(self) -> None:
        while True:
            self.run_once()
            time.sleep(self._config.poll_interval_seconds)

    def run_once(self) -> None:
        recipes = self._client.list_recipes()
        source_recipes = [recipe for recipe in recipes if self._is_source_recipe(recipe)]

        if not source_recipes:
            LOGGER.info("Keine URL-Rezepte zum Import gefunden")
            return

        matcher: ProductMatcher | None = None
        non_measurable_notes: list[str] = []
        if self._config.match_products:
            matcher = ProductMatcher(
                self._client.list_products(),
                self._client.list_quantity_units(),
                self._client.list_locations(),
                self._client.list_product_groups(),
                self._client,
                self._config.auto_created_products_group_name,
            )

        for recipe in source_recipes:
            recipe_id = int(recipe["id"])
            source_url = recipe["name"].strip()
            current_description = recipe.get("description") or ""
            LOGGER.info("Importiere Rezept aus %s", source_url)
            try:
                scraped = self._scrape_recipe(source_url)
                recipe_positions: list[dict[str, Any]] = []
                non_measurable_notes = []
                if matcher is not None:
                    processed = matcher.process_ingredients(scraped.ingredients)
                    recipe_positions = processed.recipe_positions
                    non_measurable_notes = processed.non_measurable_notes

                target_recipe_id = self._upsert_recipe(recipe, scraped, non_measurable_notes)
                if self._config.import_mode == "replace":
                    current_description = self._build_description(scraped, non_measurable_notes)
                position_errors = self._sync_recipe_positions(target_recipe_id, recipe_positions)
                if position_errors:
                    self._append_recipe_position_errors(target_recipe_id, position_errors)
                self._sync_picture(target_recipe_id, scraped)
                if self._config.import_mode == "copy":
                    self._mark_source_recipe_as_processed(recipe_id, current_description, target_recipe_id, source_url)
                LOGGER.info("Rezept erfolgreich importiert: %s", scraped.title)
            except Exception as exc:
                LOGGER.exception("Import fuer %s fehlgeschlagen: %s", source_url, exc)
                self._store_import_error(recipe_id, source_url, current_description, exc)

    def _upsert_recipe(
        self,
        source_recipe: dict[str, Any],
        scraped: ScrapedRecipe,
        non_measurable_notes: list[str],
    ) -> int:
        payload = {
            "name": scraped.title,
            "description": self._build_description(scraped, non_measurable_notes),
            "base_servings": scraped.base_servings,
            "desired_servings": scraped.base_servings,
            "not_check_shoppinglist": 0,
            "type": "normal",
        }

        if scraped.image_url:
            payload["picture_file_name"] = self._make_picture_filename(scraped.image_url)

        if self._config.import_mode == "replace":
            recipe_id = int(source_recipe["id"])
            self._client.update_recipe(recipe_id, payload)
            return recipe_id

        return self._client.create_recipe(payload)

    def _sync_recipe_positions(
        self,
        recipe_id: int,
        recipe_positions: list[dict[str, Any]],
    ) -> list[str]:
        errors: list[str] = []
        existing_positions = self._client.list_recipe_positions(recipe_id)
        for position in existing_positions:
            self._client.delete_object("recipes_pos", int(position["id"]))

        merged_positions = self._merge_recipe_positions(recipe_positions)
        for matched in merged_positions:
            payload = {
                "recipe_id": recipe_id,
                "product_id": matched["product_id"],
                "amount": matched["amount"],
                "note": matched["note"],
                "price_factor": 1,
            }
            if "qu_id" in matched:
                payload["qu_id"] = matched["qu_id"]
            creation_error = self._create_recipe_position_with_fallback(payload)
            if creation_error is not None:
                message = (
                    f"Produkt-ID {matched['product_id']} (Menge {matched['amount']}) "
                    f"konnte nicht als Rezeptzutat angelegt werden: {creation_error}"
                )
                LOGGER.warning(message)
                errors.append(message)

        deduplicated_count = self._deduplicate_recipe_positions(recipe_id)
        if deduplicated_count > 0:
            LOGGER.warning(
                "%s doppelte Rezeptzutat(en) fuer Rezept %s entfernt",
                deduplicated_count,
                recipe_id,
            )
        return errors

    def _deduplicate_recipe_positions(self, recipe_id: int) -> int:
        positions = self._client.list_recipe_positions(recipe_id)
        seen_keys: set[tuple[int, float, int | None, str]] = set()
        removed_count = 0

        for position in sorted(positions, key=lambda item: int(item.get("id", 0))):
            product_id = int(position.get("product_id") or 0)
            amount = round(float(position.get("amount") or 0.0), 6)
            qu_id = int(position["qu_id"]) if position.get("qu_id") is not None else None
            note = (position.get("note") or "").strip().lower()
            key = (product_id, amount, qu_id, note)

            if key in seen_keys:
                self._client.delete_object("recipes_pos", int(position["id"]))
                removed_count += 1
                continue

            seen_keys.add(key)

        return removed_count

    def _create_recipe_position_with_fallback(self, payload: dict[str, Any]) -> Exception | None:
        try:
            self._client.create_recipe_position(payload)
            return None
        except Exception as first_error:
            first_error_text = str(first_error)
            conversion_error = "Provided qu_id doesn't have a related conversion for that product"

            if conversion_error in first_error_text and "qu_id" in payload:
                fallback_payload = dict(payload)
                fallback_payload["only_check_single_unit_in_stock"] = 1

                try:
                    self._client.create_recipe_position(fallback_payload)
                    LOGGER.info(
                        "Rezeptzutat fuer Produkt-ID %s mit only_check_single_unit_in_stock=1 angelegt (fehlende QU-Umrechnung)",
                        payload.get("product_id"),
                    )
                    return None
                except Exception as second_error:
                    fallback_payload_no_qu = dict(fallback_payload)
                    fallback_payload_no_qu.pop("qu_id", None)

                    try:
                        self._client.create_recipe_position(fallback_payload_no_qu)
                        LOGGER.info(
                            "Rezeptzutat fuer Produkt-ID %s ohne qu_id angelegt (fehlende QU-Umrechnung)",
                            payload.get("product_id"),
                        )
                        return None
                    except Exception:
                        return second_error

            return first_error

    def _merge_recipe_positions(self, recipe_positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: "OrderedDict[tuple[int, int | None], dict[str, Any]]" = OrderedDict()
        for position in recipe_positions:
            product_id = int(position["product_id"])
            qu_id = int(position["qu_id"]) if "qu_id" in position and position["qu_id"] is not None else None
            key = (product_id, qu_id)
            if key not in merged:
                merged[key] = {
                    "product_id": product_id,
                    "amount": float(position["amount"]),
                    "note": position.get("note", ""),
                }
                if qu_id is not None:
                    merged[key]["qu_id"] = qu_id
                continue

            merged[key]["amount"] = float(merged[key]["amount"]) + float(position["amount"])
            previous_note = (merged[key].get("note") or "").strip()
            next_note = (position.get("note") or "").strip()
            if next_note and next_note not in previous_note:
                merged[key]["note"] = f"{previous_note}; {next_note}".strip("; ")
        return list(merged.values())

    def _append_recipe_position_errors(self, recipe_id: int, errors: list[str]) -> None:
        if not errors:
            return

        recipe = self._client.get_recipe(recipe_id)
        description = recipe.get("description") or ""
        cleaned = self._strip_recipe_position_error_block(description)
        errors_html = "".join(f"<li>{html.escape(error)}</li>" for error in errors)
        block = "\n".join(
            [
                f"<!-- {IMPORT_MARKER}: position-errors-start -->",
                "<h3>Hinweis zu nicht importierten Rezeptzutaten</h3>",
                f"<ul>{errors_html}</ul>",
                f"<!-- {IMPORT_MARKER}: position-errors-end -->",
            ]
        )
        self._client.update_recipe(recipe_id, {"description": f"{cleaned}\n{block}".strip()})

    def _strip_recipe_position_error_block(self, description: str) -> str:
        return re.sub(
            rf"\s*{re.escape(f'<!-- {IMPORT_MARKER}: position-errors-start -->')}.*?{re.escape(f'<!-- {IMPORT_MARKER}: position-errors-end -->')}\s*",
            "\n",
            description,
            flags=re.DOTALL,
        ).strip()

    def _sync_picture(self, recipe_id: int, scraped: ScrapedRecipe) -> None:
        if not scraped.image_url:
            return
        picture_name = self._make_picture_filename(scraped.image_url)
        response = self._http.get(scraped.image_url, timeout=self._config.request_timeout_seconds)
        response.raise_for_status()
        self._client.upload_recipe_picture(picture_name, response.content, response.headers.get("Content-Type"))
        self._client.update_recipe(recipe_id, {"picture_file_name": picture_name})

    def _mark_source_recipe_as_processed(
        self,
        recipe_id: int,
        existing_description: str,
        target_recipe_id: int,
        source_url: str,
    ) -> None:
        marker = f"<!-- {IMPORT_MARKER}: copied target={target_recipe_id} source={html.escape(source_url)} -->"
        description = self._strip_import_error(existing_description or "")
        if IMPORT_MARKER not in description:
            description = f"{description}\n{marker}".strip()
        self._client.update_recipe(recipe_id, {"description": description})

    def _scrape_recipe(self, url: str) -> ScrapedRecipe:
        scraper = self._create_scraper(url)
        title = scraper.title().strip()
        ingredients = [ingredient.strip() for ingredient in scraper.ingredients() if ingredient and ingredient.strip()]
        instructions = self._extract_instructions(scraper)
        servings_text = None
        try:
            servings_text = scraper.yields()
        except Exception:
            servings_text = None

        total_time_minutes = None
        try:
            total_time_minutes = scraper.total_time()
        except Exception:
            total_time_minutes = None

        image_url = None
        try:
            image_url = scraper.image()
        except Exception:
            image_url = None

        base_servings = self._parse_servings(servings_text)
        return ScrapedRecipe(
            source_url=url,
            title=title or url,
            ingredients=ingredients,
            instructions=instructions,
            servings_text=servings_text,
            base_servings=base_servings,
            total_time_minutes=total_time_minutes,
            image_url=image_url,
        )

    def _extract_instructions(self, scraper: Any) -> str:
        try:
            instructions_text = (scraper.instructions() or "").strip()
            if instructions_text:
                return instructions_text
        except Exception:
            instructions_text = ""

        try:
            instructions_list = scraper.instructions_list() or []
        except Exception:
            instructions_list = []

        cleaned_steps = [str(step).strip() for step in instructions_list if str(step).strip()]
        if cleaned_steps:
            return "\n".join(cleaned_steps)

        return instructions_text

    def _create_scraper(self, url: str):
        direct_error_message = "unbekannter Fehler"
        try:
            return scrape_me(url)
        except Exception as direct_error:
            direct_error_message = str(direct_error)
            LOGGER.warning(
                "Direktes Scraping fuer %s fehlgeschlagen, versuche HTML-Fallback: %s",
                url,
                direct_error,
            )

        try:
            response = self._http.get(url, timeout=self._config.request_timeout_seconds)
            response.raise_for_status()
            scraper = scrape_html(response.text, org_url=url, wild_mode=True)
            LOGGER.info("HTML-Fallback fuer %s erfolgreich", url)
            return scraper
        except Exception as html_error:
            raise RuntimeError(
                "Direktes Scraping fehlgeschlagen: "
                f"{direct_error_message}. HTML-Fallback ebenfalls fehlgeschlagen: {html_error}"
            ) from html_error

    def _build_description(self, scraped: ScrapedRecipe, non_measurable_notes: list[str]) -> str:
        parts = [f"<!-- {IMPORT_MARKER}: source={html.escape(scraped.source_url)} -->"]
        parts.append(f"<p><strong>Quelle:</strong> <a href=\"{html.escape(scraped.source_url)}\">{html.escape(scraped.source_url)}</a></p>")

        meta: list[str] = []
        if scraped.servings_text:
            meta.append(f"Portionen: {html.escape(scraped.servings_text)}")
        if scraped.total_time_minutes is not None:
            meta.append(f"Gesamtzeit: {scraped.total_time_minutes} Minuten")
        if meta:
            parts.append(f"<p>{' | '.join(meta)}</p>")

        if non_measurable_notes:
            notes_html = "".join(f"<li>{html.escape(note)}</li>" for note in non_measurable_notes)
            parts.append("<h3>Hinweis zu nicht messbaren Zutaten</h3>")
            parts.append(f"<ul>{notes_html}</ul>")

        if scraped.instructions:
            instruction_steps = self._normalize_instruction_steps(scraped.instructions)
            if len(instruction_steps) > 1:
                instructions_html = "".join(f"<li>{html.escape(line)}</li>" for line in instruction_steps)
                parts.append(f"<h3>Zubereitung</h3><ol>{instructions_html}</ol>")
            else:
                text = instruction_steps[0] if instruction_steps else scraped.instructions
                parts.append(f"<h3>Zubereitung</h3><p>{html.escape(text)}</p>")

        return "\n".join(parts)

    def _normalize_instruction_steps(self, instructions: str) -> list[str]:
        lines = [line.strip() for line in instructions.splitlines() if line.strip()]
        if not lines:
            return []

        steps: list[str] = []
        current_parts: list[str] = []

        for line in lines:
            if self._is_step_marker(line):
                if current_parts:
                    steps.append(" ".join(current_parts).strip())
                    current_parts = []
                continue

            cleaned_line = self._strip_step_prefix(line)
            if cleaned_line:
                current_parts.append(cleaned_line)

        if current_parts:
            steps.append(" ".join(current_parts).strip())

        return steps or [self._strip_step_prefix(" ".join(lines))]

    def _is_step_marker(self, line: str) -> bool:
        return bool(re.fullmatch(r"(?i)(schritt|step)\s*\d+[:.]?", line.strip()))

    def _strip_step_prefix(self, line: str) -> str:
        cleaned = re.sub(r"(?i)^\s*(schritt|step)\s*\d+[:.]?\s*", "", line).strip()
        cleaned = re.sub(r"^\s*\d+[.):-]?\s*", "", cleaned).strip()
        return cleaned

    def _parse_servings(self, servings_text: str | None) -> float:
        if not servings_text:
            return 1.0
        match = re.search(r"(\d+(?:[.,]\d+)?)", servings_text)
        if match is None:
            return 1.0
        return float(match.group(1).replace(",", "."))

    def _make_picture_filename(self, image_url: str) -> str:
        suffix = Path(urlparse(image_url).path).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            suffix = ".jpg"
        return f"{uuid.uuid4().hex}{suffix}"

    def _store_import_error(
        self,
        recipe_id: int,
        source_url: str,
        existing_description: str,
        error: Exception,
    ) -> None:
        cleaned_description = self._strip_import_error(existing_description)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        error_block = "\n".join(
            [
                IMPORT_ERROR_START,
                "<h3>Importfehler</h3>",
                (
                    f"<p>Beim Import der URL <a href=\"{html.escape(source_url)}\">"
                    f"{html.escape(source_url)}</a> ist ein Fehler aufgetreten.</p>"
                ),
                f"<p>Zeitpunkt (UTC): {timestamp}</p>",
                f"<pre>{html.escape(str(error))}</pre>",
                IMPORT_ERROR_END,
            ]
        )
        description = f"{cleaned_description}\n{error_block}".strip()
        self._client.update_recipe(
            recipe_id,
            {
                "name": self._error_recipe_name(source_url),
                "description": description,
            },
        )

    def _strip_import_error(self, description: str) -> str:
        return re.sub(
            rf"\s*{re.escape(IMPORT_ERROR_START)}.*?{re.escape(IMPORT_ERROR_END)}\s*",
            "\n",
            description,
            flags=re.DOTALL,
        ).strip()

    def _is_source_recipe(self, recipe: dict[str, Any]) -> bool:
        name = (recipe.get("name") or "").strip()
        if self._is_error_recipe(name):
            return False
        if not self._is_url(name):
            return False
        description = recipe.get("description") or ""
        if self._config.import_mode == "copy" and IMPORT_MARKER in description:
            return False
        return True

    def _is_error_recipe(self, name: str) -> bool:
        return name.startswith(ERROR_NAME_PREFIX)

    def _error_recipe_name(self, source_url: str) -> str:
        return f"{ERROR_NAME_PREFIX}{source_url}"

    def _is_url(self, value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
