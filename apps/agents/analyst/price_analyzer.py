from __future__ import annotations

from dataclasses import dataclass
import math
import statistics


@dataclass(slots=True)
class PriceSignal:
    ticker: str
    price_signal: str  # up|down|flat|volatile|none
    momentum_pct: float | None
    volatility_pct: float | None
    volume_ratio: float | None
    today_close: float | None
    days: int


def _daily_returns(series: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(series)):
        prev = series[i - 1]
        curr = series[i]
        if prev in (None, 0):
            continue
        out.append((curr - prev) / prev)
    return out


def analyze_price_signal(*, ticker: str, history_rows: list[dict]) -> PriceSignal:
    rows = [r for r in history_rows if isinstance(r.get("close"), (int, float))]
    rows = sorted(rows, key=lambda r: str(r.get("date") or ""))[-5:]
    if len(rows) < 2:
        return PriceSignal(
            ticker=ticker,
            price_signal="none",
            momentum_pct=None,
            volatility_pct=None,
            volume_ratio=None,
            today_close=float(rows[-1]["close"]) if rows else None,
            days=len(rows),
        )

    prices = [float(r["close"]) for r in rows]
    first = prices[0]
    last = prices[-1]
    momentum_pct = ((last - first) / first) * 100.0 if first not in (0, None) else None

    returns = _daily_returns(prices)
    volatility_pct: float | None = None
    if len(returns) >= 2:
        volatility_pct = statistics.stdev(returns) * 100.0
    elif len(returns) == 1:
        volatility_pct = abs(returns[0]) * 100.0

    volumes = [float(r.get("volume") or 0.0) for r in rows if isinstance(r.get("volume"), (int, float))]
    volume_ratio: float | None = None
    if volumes:
        avg_vol = sum(volumes) / max(1, len(volumes))
        today_vol = volumes[-1]
        if avg_vol > 0:
            volume_ratio = today_vol / avg_vol

    signal = "flat"
    if momentum_pct is None:
        signal = "none"
    else:
        if momentum_pct > 1.0:
            signal = "up"
        elif momentum_pct < -1.0:
            signal = "down"
        else:
            signal = "flat"

    # Volatility override from section-3 target thresholds.
    if volatility_pct is not None and volatility_pct > 2.0:
        signal = "volatile"

    # Guard against NaN/inf from malformed input.
    if momentum_pct is not None and (math.isnan(momentum_pct) or math.isinf(momentum_pct)):
        momentum_pct = None
        signal = "none"
    if volatility_pct is not None and (math.isnan(volatility_pct) or math.isinf(volatility_pct)):
        volatility_pct = None

    return PriceSignal(
        ticker=ticker,
        price_signal=signal,
        momentum_pct=round(momentum_pct, 3) if momentum_pct is not None else None,
        volatility_pct=round(volatility_pct, 3) if volatility_pct is not None else None,
        volume_ratio=round(volume_ratio, 3) if volume_ratio is not None else None,
        today_close=last,
        days=len(rows),
    )
