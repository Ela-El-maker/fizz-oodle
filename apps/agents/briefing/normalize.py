from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import re


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_float(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (float, int)):
        return float(value)

    text = str(value).strip().upper()
    if not text or text in {"N/A", "-", "--"}:
        return None

    mult = 1.0
    if text.endswith("B"):
        mult = 1_000_000_000
        text = text[:-1]
    elif text.endswith("M"):
        mult = 1_000_000
        text = text[:-1]
    elif text.endswith("K"):
        mult = 1_000
        text = text[:-1]

    text = text.replace(",", "")
    text = re.sub(r"[^0-9.+-]", "", text)
    if not text:
        return None

    try:
        return float(text) * mult
    except ValueError:
        return None


def normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def payload_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def to_date(value: date | datetime | str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    # YYYY-MM-DD expected for this pipeline.
    return datetime.fromisoformat(value).date()
