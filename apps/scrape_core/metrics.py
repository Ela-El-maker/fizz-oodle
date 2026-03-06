from __future__ import annotations


def new_source_metrics() -> dict:
    return {
        "items_found": 0,
        "items_inserted": 0,
        "duplicates": 0,
        "duration_ms": 0,
        "error_type": None,
        "error": None,
        "status": "success",
        "cache_hit": False,
        "not_modified_count": 0,
        "rate_limited_count": 0,
        "breaker_state": "closed",
    }


def finalize_source_metrics(metrics: dict, *, status: str, duration_ms: int) -> dict:
    metrics["status"] = status
    metrics["duration_ms"] = int(max(0, duration_ms))
    return metrics
