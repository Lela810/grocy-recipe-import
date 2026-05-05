from __future__ import annotations

import os
from dataclasses import dataclass


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    grocy_base_url: str
    grocy_api_key: str
    import_mode: str
    poll_interval_seconds: int
    request_timeout_seconds: int
    match_products: bool
    auto_created_products_group_name: str | None
    log_level: str

    @property
    def grocy_api_base(self) -> str:
        base = self.grocy_base_url.rstrip("/")
        if base.endswith("/api"):
            return base
        return f"{base}/api"

    @classmethod
    def from_env(cls) -> "Config":
        grocy_base_url = os.getenv("GROCY_BASE_URL", "").strip()
        grocy_api_key = os.getenv("GROCY_API_KEY", "").strip()
        import_mode = os.getenv("IMPORT_MODE", "replace").strip().lower()

        if not grocy_base_url:
            raise ValueError("GROCY_BASE_URL ist nicht gesetzt")
        if not grocy_api_key:
            raise ValueError("GROCY_API_KEY ist nicht gesetzt")
        if import_mode not in {"replace", "copy"}:
            raise ValueError("IMPORT_MODE muss 'replace' oder 'copy' sein")

        return cls(
            grocy_base_url=grocy_base_url,
            grocy_api_key=grocy_api_key,
            import_mode=import_mode,
            poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "300")),
            request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30")),
            match_products=_parse_bool(os.getenv("MATCH_PRODUCTS"), True),
            auto_created_products_group_name=os.getenv("AUTO_CREATED_PRODUCTS_GROUP_NAME", "").strip() or None,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
