from __future__ import annotations

import re

from bs4 import BeautifulSoup

from apps.core.config import get_settings
from apps.core.http import fetch_text

settings = get_settings()

async def extract_details(url: str, *, timeout_secs: int | None = None) -> str | None:
    try:
        html = await fetch_text(
            url,
            timeout_secs=timeout_secs if timeout_secs is not None else int(settings.ANNOUNCEMENTS_DETAILS_ENRICH_TIMEOUT_SECONDS),
        )
    except Exception:
        return None

    soup = BeautifulSoup(html, "lxml")
    chunks: list[str] = []
    for p in soup.select("p")[:8]:
        text = " ".join(p.get_text(" ", strip=True).split())
        if text:
            chunks.append(text)

    if not chunks:
        body = soup.get_text(" ", strip=True)
        body = re.sub(r"\s+", " ", body)
        if body:
            chunks.append(body[:1200])

    if not chunks:
        return None

    details = " ".join(chunks)
    return details[:1200]
