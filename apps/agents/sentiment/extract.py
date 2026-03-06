from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

import yaml

from apps.agents.sentiment.normalize import normalize_text
from apps.core.config import get_settings

settings = get_settings()


@lru_cache(maxsize=1)
def _universe() -> dict:
    cfg = Path(settings.UNIVERSE_CONFIG_PATH)
    if not cfg.is_absolute():
        cfg = (Path(__file__).resolve().parents[3] / settings.UNIVERSE_CONFIG_PATH).resolve()
    with cfg.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def ticker_company_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for row in _universe().get("tracked_companies", []):
        ticker = str(row.get("ticker", "")).upper().strip()
        name = str(row.get("company_name", "")).strip()
        if ticker:
            out[ticker] = name or ticker
    return out


@lru_cache(maxsize=1)
def alias_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for row in _universe().get("tracked_companies", []):
        ticker = str(row.get("ticker", "")).upper().strip()
        company_name = normalize_text(str(row.get("company_name", ""))).lower()
        aliases = row.get("aliases", []) or []
        if company_name:
            out[company_name] = ticker
        for alias in aliases:
            key = normalize_text(str(alias)).lower()
            if key:
                out[key] = ticker
        if ticker:
            out[ticker.lower()] = ticker
    return out


def company_name_for_ticker(ticker: str) -> str | None:
    return ticker_company_map().get(ticker.upper())


def extract_tickers(text: str) -> list[str]:
    body = normalize_text(text)
    if not body:
        return []

    low = body.lower()
    found: set[str] = set()

    # explicit ticker token match
    for ticker in ticker_company_map().keys():
        if re.search(rf"\b{re.escape(ticker.lower())}\b", low):
            found.add(ticker)

    # alias phrase match
    for alias, ticker in alias_map().items():
        if re.search(rf"\b{re.escape(alias)}\b", low):
            found.add(ticker)

    return sorted(found)
