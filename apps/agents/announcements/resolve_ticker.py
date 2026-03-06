from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

import yaml

from apps.core.config import get_settings

settings = get_settings()


@lru_cache(maxsize=1)
def _load_universe() -> dict:
    path = Path(settings.UNIVERSE_CONFIG_PATH)
    if not path.is_absolute():
        path = (Path(__file__).resolve().parents[3] / settings.UNIVERSE_CONFIG_PATH).resolve()
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def _alias_map() -> dict[str, str]:
    data = _load_universe()
    alias_to_ticker: dict[str, str] = {}
    for company in data.get("tracked_companies", []):
        ticker = str(company["ticker"]).upper()
        alias_to_ticker[ticker] = ticker
        # Index by canonical company_name so company_hint lookups work
        company_name = str(company.get("company_name", "")).strip()
        if company_name:
            alias_to_ticker[company_name.lower()] = ticker
        for alias in company.get("aliases", []):
            alias_to_ticker[str(alias).strip().lower()] = ticker
    return alias_to_ticker


@lru_cache(maxsize=1)
def _ticker_regex() -> re.Pattern[str]:
    data = _load_universe()
    tokens = [re.escape(str(item["ticker"])) for item in data.get("tracked_companies", [])]
    if not tokens:
        return re.compile(r"^$")
    return re.compile(r"\b(" + "|".join(sorted(tokens, key=len, reverse=True)) + r")\b", flags=re.IGNORECASE)


def resolve_ticker(headline: str, ticker_hint: str | None = None, company_hint: str | None = None) -> str | None:
    alias_map = _alias_map()

    if ticker_hint:
        hinted = ticker_hint.strip().upper()
        if hinted in alias_map:
            return hinted

    match = _ticker_regex().search(headline or "")
    if match:
        return match.group(1).upper()

    if company_hint:
        return alias_map.get(company_hint.strip().lower())

    lowered = (headline or "").lower()
    for alias, ticker in alias_map.items():
        if alias and alias in lowered:
            return ticker

    return None


def resolve_company_name(ticker: str | None) -> str | None:
    if not ticker:
        return None
    data = _load_universe()
    for company in data.get("tracked_companies", []):
        if str(company["ticker"]).upper() == ticker.upper():
            return str(company["company_name"])
    return None
