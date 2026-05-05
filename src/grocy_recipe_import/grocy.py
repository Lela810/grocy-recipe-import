from __future__ import annotations

import base64
from typing import Any

import requests

from grocy_recipe_import.config import Config


class GrocyClient:
    def __init__(self, config: Config) -> None:
        self._timeout = config.request_timeout_seconds
        self._session = requests.Session()
        self._session.headers.update(
            {
                "GROCY-API-KEY": config.grocy_api_key,
                "Accept": "application/json",
            }
        )
        self._api_base = config.grocy_api_base.rstrip("/")

    def list_recipes(self) -> list[dict[str, Any]]:
        return self._get_json("/objects/recipes")

    def get_recipe(self, recipe_id: int) -> dict[str, Any]:
        return self._get_json(f"/objects/recipes/{recipe_id}")

    def list_products(self) -> list[dict[str, Any]]:
        return self._get_json("/objects/products")

    def list_product_groups(self) -> list[dict[str, Any]]:
        return self._get_json("/objects/product_groups")

    def list_locations(self) -> list[dict[str, Any]]:
        return self._get_json("/objects/locations")

    def list_quantity_units(self) -> list[dict[str, Any]]:
        return self._get_json("/objects/quantity_units")

    def list_recipe_positions(self, recipe_id: int) -> list[dict[str, Any]]:
        return self._get_json("/objects/recipes_pos", params={"query[]": f"recipe_id={recipe_id}"})

    def create_recipe(self, payload: dict[str, Any]) -> int:
        response = self._post_json("/objects/recipes", payload)
        return int(response["created_object_id"])

    def update_recipe(self, recipe_id: int, payload: dict[str, Any]) -> None:
        self._put_json(f"/objects/recipes/{recipe_id}", payload)

    def create_recipe_position(self, payload: dict[str, Any]) -> int:
        response = self._post_json("/objects/recipes_pos", payload)
        return int(response["created_object_id"])

    def create_product(self, payload: dict[str, Any]) -> int:
        response = self._post_json("/objects/products", payload)
        return int(response["created_object_id"])

    def create_product_group(self, payload: dict[str, Any]) -> int:
        response = self._post_json("/objects/product_groups", payload)
        return int(response["created_object_id"])

    def create_quantity_unit(self, payload: dict[str, Any]) -> int:
        response = self._post_json("/objects/quantity_units", payload)
        return int(response["created_object_id"])

    def delete_object(self, entity: str, object_id: int) -> None:
        self._delete(f"/objects/{entity}/{object_id}")

    def upload_recipe_picture(self, filename: str, content: bytes, content_type: str | None = None) -> None:
        encoded_name = base64.b64encode(filename.encode("utf-8")).decode("ascii")
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        self._put_binary(f"/files/recipepictures/{encoded_name}", content, headers=headers)

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self._session.get(f"{self._api_base}{path}", params=params, timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._session.post(f"{self._api_base}{path}", json=payload, timeout=self._timeout)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = self._extract_error_detail(response)
            raise requests.HTTPError(f"{exc} | Grocy response: {detail}", response=response) from exc
        if response.content:
            return response.json()
        return {}

    def _put_json(self, path: str, payload: dict[str, Any]) -> None:
        response = self._session.put(f"{self._api_base}{path}", json=payload, timeout=self._timeout)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = self._extract_error_detail(response)
            raise requests.HTTPError(f"{exc} | Grocy response: {detail}", response=response) from exc

    def _put_binary(self, path: str, content: bytes, headers: dict[str, str] | None = None) -> None:
        response = self._session.put(
            f"{self._api_base}{path}",
            data=content,
            headers=headers,
            timeout=self._timeout,
        )
        response.raise_for_status()

    def _delete(self, path: str) -> None:
        response = self._session.delete(f"{self._api_base}{path}", timeout=self._timeout)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = self._extract_error_detail(response)
            raise requests.HTTPError(f"{exc} | Grocy response: {detail}", response=response) from exc

    def _extract_error_detail(self, response: requests.Response) -> str:
        try:
            data = response.json()
            if isinstance(data, dict) and data.get("error_message"):
                return str(data["error_message"])
            return str(data)
        except Exception:
            return response.text.strip() or "<empty response body>"
