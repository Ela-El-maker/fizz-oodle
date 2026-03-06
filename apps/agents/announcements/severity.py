from __future__ import annotations


_BASE_SEVERITY_SCORES = {
    "trading_suspension": 0.90,
    "profit_warning": 0.80,
    "merger_acquisition": 0.75,
    "rights_issue": 0.70,
    "earnings": 0.60,
    "dividend": 0.55,
    "regulatory_filing": 0.50,
    "board_change": 0.45,
    "agm_egm": 0.35,
    "other": 0.25,
}


def derive_severity(announcement_type: str, confidence: float | None) -> tuple[str, float]:
    ann_type = (announcement_type or "other").strip().lower()
    base = float(_BASE_SEVERITY_SCORES.get(ann_type, _BASE_SEVERITY_SCORES["other"]))

    conf = 0.5 if confidence is None else float(confidence)
    conf = max(0.0, min(1.0, conf))
    score = max(0.0, min(1.0, base + ((conf - 0.5) * 0.35)))

    if score >= 0.85:
        return "critical", round(score, 3)
    if score >= 0.65:
        return "high", round(score, 3)
    if score >= 0.40:
        return "medium", round(score, 3)
    return "low", round(score, 3)
