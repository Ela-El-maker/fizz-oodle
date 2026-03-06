from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from apps.core.config import get_settings
from apps.core.runtime_overrides import get_agent_overrides_sync

settings = get_settings()


@dataclass(slots=True)
class BriefingSourceConfig:
    source_id: str
    channel: str
    type: str
    base_url: str
    tier: str = "secondary"
    required_for_success: bool = False
    enabled_by_default: bool = True
    timeout_secs: int = 30
    retries: int = 2
    backoff_base: float = 2.0
    rate_limit_rps: float = 0.3
    cache_ttl_seconds: int = 0
    use_conditional_get: bool = False
    max_items_per_run: int = 500
    source_trust_rank: int = 3
    headline_weight: float = 0.5
    scope: str = "kenya_core"
    market_region: str = "kenya"
    signal_class: str = "news_signal"
    theme: str | None = None
    primary_use: str | None = None
    disabled_reason: str | None = None
    kenya_impact_enabled: bool = False
    kenya_impact_weight: float = 1.0
    premium: bool = False


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _apply_runtime_source_overrides(cfg: BriefingSourceConfig, patch: dict) -> BriefingSourceConfig:
    if not isinstance(patch, dict):
        return cfg

    enabled = patch.get("enabled")
    if isinstance(enabled, bool):
        cfg.enabled_by_default = enabled

    rate_limit_override = _to_float(patch.get("rate_limit_rps"))
    if rate_limit_override is not None and rate_limit_override > 0:
        cfg.rate_limit_rps = max(0.01, rate_limit_override)

    multiplier = _to_float(patch.get("rate_limit_multiplier"))
    if multiplier is not None and multiplier > 0:
        cfg.rate_limit_rps = max(0.01, round(cfg.rate_limit_rps * multiplier, 4))

    max_items = _to_int(patch.get("max_items_per_run"))
    if max_items is not None and max_items > 0:
        cfg.max_items_per_run = max_items

    retries = _to_int(patch.get("retries"))
    if retries is not None and retries >= 0:
        cfg.retries = retries

    timeout_secs = _to_int(patch.get("timeout_secs"))
    if timeout_secs is not None and timeout_secs > 0:
        cfg.timeout_secs = timeout_secs

    return cfg


def _load_yaml(path: str) -> dict:
    cfg_path = Path(path)
    if not cfg_path.is_absolute():
        cfg_path = (Path(__file__).resolve().parents[3] / path).resolve()
    with cfg_path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def get_briefing_source_configs() -> dict[str, BriefingSourceConfig]:
    runtime = get_agent_overrides_sync("briefing")
    runtime_source_overrides = runtime.get("sources", {}) if isinstance(runtime, dict) else {}
    data = _load_yaml("config/briefing_sources.yml")
    out: dict[str, BriefingSourceConfig] = {}
    for item in data.get("sources", []) or []:
        cfg = BriefingSourceConfig(
            source_id=str(item.get("source_id") or "").strip(),
            channel=str(item.get("channel") or "").strip(),
            type=str(item.get("type") or "").strip(),
            base_url=str(item.get("base_url") or "").strip(),
            tier=str(item.get("tier") or "secondary").strip(),
            required_for_success=bool(item.get("required_for_success", False)),
            enabled_by_default=bool(item.get("enabled_by_default", True)),
            timeout_secs=int(item.get("timeout_secs", 30) or 30),
            retries=int(item.get("retries", 2) or 2),
            backoff_base=float(item.get("backoff_base", 2) or 2),
            rate_limit_rps=float(item.get("rate_limit_rps", 0.3) or 0.3),
            cache_ttl_seconds=int(item.get("cache_ttl_seconds", 0) or 0),
            use_conditional_get=bool(item.get("use_conditional_get", False)),
            max_items_per_run=int(item.get("max_items_per_run", 500) or 500),
            source_trust_rank=int(item.get("source_trust_rank", 3) or 3),
            headline_weight=float(item.get("headline_weight", 0.5) or 0.5),
            scope=str(item.get("scope") or "kenya_core"),
            market_region=str(item.get("market_region") or "kenya"),
            signal_class=str(item.get("signal_class") or "news_signal"),
            theme=(str(item.get("theme")).strip() if item.get("theme") is not None else None),
            primary_use=(str(item.get("primary_use")).strip() if item.get("primary_use") is not None else None),
            disabled_reason=(
                str(item.get("disabled_reason")).strip() if item.get("disabled_reason") is not None else None
            ),
            kenya_impact_enabled=bool(item.get("kenya_impact_enabled", False)),
            kenya_impact_weight=float(item.get("kenya_impact_weight", 1.0) or 1.0),
            premium=bool(item.get("premium", False)),
        )
        cfg = _apply_runtime_source_overrides(
            cfg, runtime_source_overrides.get(cfg.source_id, {}) if isinstance(runtime_source_overrides, dict) else {}
        )
        if cfg.source_id and cfg.channel:
            out[cfg.source_id] = cfg
    return out


def get_channel_order() -> dict[str, list[str]]:
    runtime = get_agent_overrides_sync("briefing")
    data = _load_yaml("config/briefing_sources.yml")
    channels = data.get("channels", {}) or {}
    out: dict[str, list[str]] = {}
    for channel, source_ids in channels.items():
        out[channel] = [str(s).strip().lower() for s in (source_ids or []) if str(s).strip()]

    runtime_channel_order = runtime.get("channel_order", {}) if isinstance(runtime, dict) else {}
    if isinstance(runtime_channel_order, dict):
        for channel, source_ids in runtime_channel_order.items():
            if isinstance(source_ids, list):
                out[str(channel).strip()] = [str(s).strip().lower() for s in source_ids if str(s).strip()]
    return out
