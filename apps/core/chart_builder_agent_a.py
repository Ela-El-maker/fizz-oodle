from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date
import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


@dataclass(slots=True)
class ChartRenderResult:
    generated: bool
    b64_png: str
    path: str | None
    error: str | None


def _safe_float(value: float | None) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except Exception:
        return 0.0


def build_agent_a_top_movers_chart(
    *,
    rows: list[dict],
    target_date: date,
    output_dir: str,
    nasi_value: float | None,
    nasi_pct: float | None,
    volume_overlay: bool,
    top_n: int = 10,
) -> ChartRenderResult:
    if not rows:
        return ChartRenderResult(generated=False, b64_png="", path=None, error="no_rows")

    def _abs_pct(row: dict) -> float:
        pct = row.get("pct_change")
        return abs(float(pct)) if isinstance(pct, (int, float)) else -1.0

    ranked = sorted(rows, key=_abs_pct, reverse=True)[: max(1, int(top_n))]
    labels = [str(r.get("ticker") or "N/A") for r in ranked]
    pct_vals = [_safe_float(r.get("pct_change")) for r in ranked]
    volumes = [_safe_float(r.get("volume")) for r in ranked]

    colors = []
    for pct in pct_vals:
        if pct > 0:
            colors.append("#16a34a")
        elif pct < 0:
            colors.append("#dc2626")
        else:
            colors.append("#6b7280")

    fig, ax1 = plt.subplots(figsize=(11, 6))
    y_pos = list(range(len(labels)))
    ax1.barh(y_pos, pct_vals, color=colors, alpha=0.95)
    ax1.set_yticks(y_pos)
    ax1.set_yticklabels(labels)
    ax1.invert_yaxis()
    ax1.axvline(0, color="#111827", linewidth=1)
    ax1.set_xlabel("% change")
    ax1.set_title(
        f"Top Movers — {target_date.isoformat()} | NASI {nasi_value if nasi_value is not None else 'N/A'}"
        f"{f' ({nasi_pct:+.2f}%)' if isinstance(nasi_pct, (int, float)) else ''}"
    )
    ax1.grid(axis="x", linestyle="--", alpha=0.25)

    if volume_overlay:
        ax2 = ax1.twiny()
        ax2.plot(volumes, y_pos, color="#2563eb", marker="o", linewidth=1.2, alpha=0.8)
        ax2.set_xlabel("Volume")
        ax2.grid(False)

    fig.tight_layout()

    try:
        out_dir = Path(output_dir).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"briefing_top_movers_{target_date.isoformat()}.png"

        png_buf = io.BytesIO()
        fig.savefig(png_buf, format="png", dpi=160, bbox_inches="tight")
        fig.savefig(out_path, format="png", dpi=160, bbox_inches="tight")
        plt.close(fig)
        png_buf.seek(0)
        b64 = base64.b64encode(png_buf.read()).decode("utf-8")
        return ChartRenderResult(generated=True, b64_png=b64, path=str(out_path), error=None)
    except Exception as exc:  # noqa: PERF203
        plt.close(fig)
        return ChartRenderResult(generated=False, b64_png="", path=None, error=str(exc))
