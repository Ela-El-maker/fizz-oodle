from __future__ import annotations

import base64
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def fig_to_b64_png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def top_movers_bar(labels: list[str], pct_changes: list[float], title: str = "Top Movers") -> str:
    fig, ax = plt.subplots(figsize=(10, 5))

    ax.barh(labels, pct_changes)
    ax.axvline(0, linewidth=1)
    ax.set_xlabel("% change")
    ax.set_title(title)

    return fig_to_b64_png(fig)


def sentiment_stacked(labels: list[str], bullish: list[float], neutral: list[float], bearish: list[float]) -> str:
    fig, ax = plt.subplots(figsize=(12, 6))
    x = range(len(labels))

    ax.bar(x, bullish, label="Bullish")
    ax.bar(x, neutral, bottom=bullish, label="Neutral")
    ax.bar(
        x,
        bearish,
        bottom=[b + n for b, n in zip(bullish, neutral)],
        label="Bearish",
    )

    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylabel("%")
    ax.set_title("Weekly Sentiment")
    ax.legend()

    return fig_to_b64_png(fig)
