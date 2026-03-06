from __future__ import annotations

from pathlib import Path

import yaml

from apps.agents.sentiment.connectors import PARSER_REGISTRY
from apps.agents.sentiment.types import CollectorFn, SentimentSourceConfig
from apps.core.config import get_settings
from apps.core.global_source_packs import source_allowed_by_pack
from apps.core.runtime_overrides import get_agent_overrides_sync

settings = get_settings()


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


def _apply_runtime_source_overrides(source: SentimentSourceConfig, patch: dict) -> SentimentSourceConfig:
    if not isinstance(patch, dict):
        return source

    enabled = patch.get("enabled")
    if isinstance(enabled, bool):
        source.enabled_by_default = enabled

    rate_limit_override = _to_float(patch.get("rate_limit_rps"))
    if rate_limit_override is not None and rate_limit_override > 0:
        source.rate_limit_rps = max(0.01, rate_limit_override)

    multiplier = _to_float(patch.get("rate_limit_multiplier"))
    if multiplier is not None and multiplier > 0:
        source.rate_limit_rps = max(0.01, round(source.rate_limit_rps * multiplier, 4))

    max_items = _to_int(patch.get("max_items_per_run"))
    if max_items is not None and max_items > 0:
        source.max_items_per_run = max_items

    retries = _to_int(patch.get("retries"))
    if retries is not None and retries >= 0:
        source.retries = retries

    timeout_secs = _to_int(patch.get("timeout_secs"))
    if timeout_secs is not None and timeout_secs > 0:
        source.timeout_secs = timeout_secs

    return source


def _load_yaml(path: str) -> dict:
    cfg_path = Path(path)
    if not cfg_path.is_absolute():
        cfg_path = (Path(__file__).resolve().parents[3] / path).resolve()
    with cfg_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _all_source_configs() -> list[SentimentSourceConfig]:
    data = _load_yaml(settings.SENTIMENT_CONFIG_PATH)
    source_items = data.get("sources", [])

    out: list[SentimentSourceConfig] = []
    for item in source_items:
        src = SentimentSourceConfig(
            source_id=item["source_id"],
            type=item["type"],
            base_url=item["base_url"],
            enabled_by_default=bool(item["enabled_by_default"]),
            parser=item["parser"],
            timeout_secs=int(item["timeout_secs"]),
            retries=int(item["retries"]),
            backoff_base=float(item["backoff_base"]),
            rate_limit_rps=float(item["rate_limit_rps"]),
            weight=float(item["weight"]),
            requires_auth=bool(item["requires_auth"]),
            tier=str(item.get("tier") or "secondary"),
            required_for_success=bool(item.get("required_for_success", False)),
            cache_ttl_seconds=int(item.get("cache_ttl_seconds", 0) or 0),
            use_conditional_get=bool(item.get("use_conditional_get", False)),
            max_items_per_run=int(item.get("max_items_per_run", 500) or 500),
            auth_env_key=item.get("auth_env_key"),
            scope=str(item.get("scope") or "kenya_extended"),
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
        out.append(src)
    return out


def get_source_configs() -> list[SentimentSourceConfig]:
    runtime = get_agent_overrides_sync("sentiment")
    runtime_source_overrides = runtime.get("sources", {}) if isinstance(runtime, dict) else {}
    enabled_override = {
        part.strip() for part in (settings.ENABLED_SENTIMENT_SOURCES or "").split(",") if part.strip()
    }
    out: list[SentimentSourceConfig] = []
    for src in _all_source_configs():
        src = _apply_runtime_source_overrides(
            src, runtime_source_overrides.get(src.source_id, {}) if isinstance(runtime_source_overrides, dict) else {}
        )
        if src.type == "sitemap" and not settings.ENABLE_SITEMAP_SOURCES:
            continue
        if src.scope == "global_outside" and not settings.ENABLE_GLOBAL_OUTSIDE_SOURCES:
            continue
        if not source_allowed_by_pack(
            source_id=src.source_id,
            enable_theme_pack=bool(settings.ENABLE_GLOBAL_MARKETS_THEME_PACK),
            enable_extras_pack=bool(settings.ENABLE_GLOBAL_EXTRAS_PACK),
        ):
            continue
        if src.premium and not settings.ENABLE_PREMIUM_GLOBAL_SOURCES:
            continue
        enabled = src.enabled_by_default if not enabled_override else src.source_id in enabled_override
        if enabled:
            out.append(src)
    return out


def get_all_source_configs() -> list[SentimentSourceConfig]:
    return _all_source_configs()


def get_collector(source: SentimentSourceConfig) -> CollectorFn:
    collector = PARSER_REGISTRY.get(source.parser)
    if collector is None:
        raise ValueError(f"No sentiment parser registered for {source.source_id} parser={source.parser}")
    return collector
