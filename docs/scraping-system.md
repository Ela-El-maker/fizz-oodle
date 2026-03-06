# Scraping & Collection System

## Collection modes

The platform uses three connector modes across A/B/C:

- `rss`: fast, low-friction feed ingestion
- `html`/`html_listing`: page parsing for sources without RSS
- `sitemap`: sitemap index/urlset discovery (including nested sitemap support)
- `api`: direct JSON API sources where available
- `official`: dedicated parsing path for structured official sites (e.g., NSE)

## Shared scrape core

Located in `apps/scrape_core/`:

- `http_client.py`: resilient HTTP fetch with timeouts/retries
- `retry.py`: exception classification
- `breaker.py`: simple circuit breaker (closed/open/half_open)
- `source_health.py`: source-level health snapshots
- `sitemap.py`: sitemap index + urlset parser with lookback and cap
- `dedupe.py`: canonical URL normalization and content fingerprinting

## Source registries

- Agent A: `config/briefing_sources.yml` + `apps/agents/briefing/registry.py`
- Agent B: `config/sources.yml` + `apps/agents/announcements/registry.py`
- Agent C: `config/sentiment_sources.yml` + `apps/agents/sentiment/registry.py`

Schemas are strict for B/C source files (`additionalProperties: false`):

- `config/schemas/sources.schema.json`
- `config/schemas/sentiment_sources.schema.json`

## Source taxonomy (lane model)

Fields used in source definitions and runtime policy:

- `scope`: `kenya_core | kenya_extended | global_outside`
- `market_region`: `kenya | east_africa | africa | global`
- `signal_class`: `issuer_disclosure | regulator | macro | commodity | global_market | ai_tech | news_signal`
- `theme`: configurable theme key
- `primary_use`: source intent hints
- `kenya_impact_enabled`, `kenya_impact_weight`
- `premium`

## Global source controls

From `apps/core/config.py`:

- `ENABLE_GLOBAL_OUTSIDE_SOURCES`
- `GLOBAL_OUTSIDE_KENYA_IMPACT_THRESHOLD`
- `ENABLE_PREMIUM_GLOBAL_SOURCES`
- `ENABLE_SITEMAP_SOURCES`
- `ENABLE_GLOBAL_MARKETS_THEME_PACK`
- `ENABLE_GLOBAL_EXTRAS_PACK`

Pack membership is defined in `apps/core/global_source_packs.py`.

## Announcement-specific routing (Agent B)

Agent B enriches each normalized row with:

- scope/region/class/theme
- `kenya_impact_score`
- `promoted_to_core_feed`
- affected sectors and transmission channels

Global rows are visible by lane but only promoted into default company feed at configured impact threshold.

## Typical ingestion lifecycle

1. source selected by config + runtime flags
2. request with retry/backoff
3. breaker/health check update
4. normalize and dedupe
5. classify/enrich (where applicable)
6. persist records + emit metrics
