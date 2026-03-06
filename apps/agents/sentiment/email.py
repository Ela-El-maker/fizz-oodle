from __future__ import annotations

from datetime import date
from typing import Iterable
from jinja2 import Environment, FileSystemLoader

from apps.core.chart_builder import sentiment_stacked
from apps.core.email_service import EmailService


def build_subject(week_start: date) -> str:
    return f"🧠 Weekly Stock Sentiment — Week of {week_start.isoformat()}"


def render_digest_html(
    week_start: date,
    rows: list[dict],
    mood: str,
    human_summary: dict | None = None,
    human_summary_v2: dict | None = None,
) -> str:
    labels = [row["ticker"] for row in rows]
    bullish = [float(row["bullish_pct"]) for row in rows]
    neutral = [float(row["neutral_pct"]) for row in rows]
    bearish = [float(row["bearish_pct"]) for row in rows]
    chart_b64 = sentiment_stacked(labels, bullish, neutral, bearish)

    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template("sentiment.html")
    missing = [row["ticker"] for row in rows if int(row.get("mentions_count", 0)) == 0]
    missing_disclosure = None
    if missing:
        missing_disclosure = f"No or low signal posts for: {', '.join(missing[:12])}" + ("..." if len(missing) > 12 else "")
    return template.render(
        week_start=week_start.isoformat(),
        mood=mood,
        human_summary=human_summary or {},
        human_summary_v2=human_summary_v2 or {},
        chart_b64=chart_b64,
        missing_disclosure=missing_disclosure,
        rows=[
            {
                "ticker": row["ticker"],
                "name": row["company_name"],
                "bull": row["bullish_pct"],
                "bear": row["bearish_pct"],
                "neu": row["neutral_pct"],
                "mentions": row["mentions_count"],
                "wow": row["wow_delta"],
                "score": row["weighted_score"],
                "confidence": row["confidence"],
                "notable_quotes": row.get("notable_quotes", []),
            }
            for row in rows
        ],
    )


def send_digest_email(
    subject: str,
    html: str,
    recipients: Iterable[str] | str | None = None,
) -> tuple[bool, str | None]:
    result = EmailService().send_result(subject=subject, html=html, recipients=recipients)
    return bool(result.ok), result.error
