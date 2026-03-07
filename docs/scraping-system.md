# Scraping & Collection System

## Overview

The platform collects data from external sources using a shared scraping core (`apps/scrape_core/`) that provides resilient HTTP fetching, circuit breaking, rate limiting, deduplication, and source health tracking. Agents A, B, and C each use this core with their own source registries and connectors.

## Collection Modes

Five connector types are supported across the data collection agents:

| Mode | Description | Used By |
|---|---|---|
| `rss` | RSS/Atom feed ingestion | A, B, C |
| `html` / `html_listing` | Page parsing for sources without RSS feeds | A, B, C |
| `sitemap` | Sitemap index/urlset discovery (including nested sitemaps) | A, B, C |
| `api` | Direct JSON API sources (FX, social, market data) | A, C |
| `official` | Dedicated parsers for structured official sites (NSE, CMA) | B |

## Scrape Core Modules

Located in `apps/scrape_core/`:

### `http_client.py` - Resilient HTTP Client

Provides the base HTTP fetch layer with:

- Configurable request timeout (default 30 seconds)
- Per-domain delay (default 2 seconds between requests to same domain)
- Adaptive rate limiting based on response status codes
- User-agent rotation
- Proxy support (when configured)

### `retry.py` - Error Classification & Retry

Classifies exceptions into retry categories:

| Category | Action | Examples |
|---|---|---|
| **Transient** | Retry with exponential backoff | Connection timeout, 503, 429 |
| **Permanent** | No retry, mark source degraded | 404, 403, DNS failure |
| **Rate-limited** | Retry after delay | 429 with Retry-After header |

### `breaker.py` - Circuit Breaker

Per-source circuit breaker with three states:

```text
CLOSED (normal) --[failures >= threshold]--> OPEN (blocking)
                                                |
                                           [cooldown expires]
                                                |
                                                v
                                          HALF_OPEN (testing)
                                                |
                                    [success]   |   [failure]
                                        |       |       |
                                        v       |       v
                                      CLOSED    |     OPEN
                                                |
```

**Configuration**:
- `SOURCE_CIRCUIT_BREAKER_ENABLED` = `True`
- `SOURCE_CIRCUIT_BREAKER_FAIL_THRESHOLD` = `5` (failures before tripping)
- `SOURCE_CIRCUIT_BREAKER_COOLDOWN_MINUTES` = `60` (time before half-open test)

### `source_health.py` - Rolling Health Scoring

Maintains a rolling window of source fetch results:

- Tracks success/failure counts over recent requests
- Computes health percentage per source
- Exposed in API responses and used by pipeline status computation
- Stored in `source_health` table for persistence

### `dedupe.py` - Deduplication

Two-layer deduplication:

1. **URL normalization** - canonical URL stripping (query params, fragments, trailing slashes)
2. **Content fingerprinting** - SHA-256 hash of normalized content body

Prevents duplicate records when:
- Same article appears on multiple source pages
- Source includes previously-seen content in new listings
- Redirects lead to same content

### `sitemap.py` - Sitemap Parser

Handles standard sitemap formats:

- Sitemap index files (references to sub-sitemaps)
- URL set files (individual page entries)
- Nested sitemaps (recursive discovery)
- Lookback filtering (only process URLs newer than configured window)
- Cap enforcement (maximum URLs processed per sitemap)

### `extract_contract.py` - Standardized Output

Defines the standardized extraction output format that all connectors produce:

```text
ExtractResult:
  url: str
  title: str
  content: str
  published_at: datetime | None
  source_id: str
  metadata: dict
```

This contract ensures all downstream pipeline steps receive consistent data regardless of source type.

## Source Registries

Each data collection agent maintains its own source registry:

| Agent | Config File | Registry Code | Schema Validation |
|---|---|---|---|
| A (Briefing) | `config/briefing_sources.yml` | `apps/agents/briefing/registry.py` | No strict schema |
| B (Announcements) | `config/sources.yml` | `apps/agents/announcements/registry.py` | `config/schemas/sources.schema.json` |
| C (Sentiment) | `config/sentiment_sources.yml` | `apps/agents/sentiment/registry.py` | `config/schemas/sentiment_sources.schema.json` |

Agents B and C use strict JSON schema validation (`additionalProperties: false`) to prevent configuration drift.

## Source Taxonomy (Lane Model)

Sources carry metadata that controls routing and scoring:

| Field | Purpose | Example Values |
|---|---|---|
| `scope` | Geographic relevance tier | `kenya_core`, `kenya_extended`, `global_outside` |
| `market_region` | Market region classification | `kenya`, `east_africa`, `africa`, `global` |
| `signal_class` | Signal type classification | `issuer_disclosure`, `regulator`, `macro`, `commodity` |
| `theme` | Topical grouping | user-defined per source |
| `primary_use` | Source intent hint | describes intended use |
| `kenya_impact_enabled` | Enable Kenya impact scoring | `true`/`false` |
| `kenya_impact_weight` | Weight for impact calculation | numeric |
| `premium` | Premium source flag | `true`/`false` |

## Global Source Controls

Master switches in `apps/core/config.py`:

| Setting | Default | Purpose |
|---|---|---|
| `ENABLE_GLOBAL_OUTSIDE_SOURCES` | `True` | Enable collection from global sources |
| `GLOBAL_OUTSIDE_KENYA_IMPACT_THRESHOLD` | `60` | Minimum score for global items to enter core feed |
| `ENABLE_PREMIUM_GLOBAL_SOURCES` | depends | Enable premium-tier sources |
| `ENABLE_SITEMAP_SOURCES` | depends | Enable sitemap-based discovery |
| `ENABLE_GLOBAL_MARKETS_THEME_PACK` | depends | Enable global markets theme sources |
| `ENABLE_GLOBAL_EXTRAS_PACK` | depends | Enable extra global source pack |

Source pack membership is defined in `apps/core/global_source_packs.py`.

## Tracked Universe

The system tracks 67 companies defined in `config/universe.yml`:

- **Primary**: 64 NSE-listed companies across 15+ sectors
- **Cross-listed**: 3 JSE companies (MTN, Naspers, Standard Bank Group)
- **Regional**: 2 NGX companies (Dangote Cement, Zenith Bank)

Each company has a `ticker`, `company_name`, `exchange`, and `aliases` array for mention matching.

### Key Sectors

Agriculture, Banking (17 companies), Commercial/Transport, Media, Hospitality, Services, Retail, Manufacturing/Construction, Energy, Insurance, Investment, Exchange (NSE), Consumer, Telecom (Safaricom), REITs/ETFs.

## Ingestion Lifecycle

```text
1. Source selected by config + runtime feature flags
        |
2. HTTP request with retry/backoff (scrape_core/http_client.py)
        |
3. Circuit breaker check + source health update
        |
4. Normalize raw response to ExtractResult contract
        |
5. Deduplicate via URL normalization + SHA-256 fingerprint
        |
6. Classify/enrich (per-agent: impact scoring, sentiment, themes)
        |
7. Persist records to agent database
        |
8. Update source health metrics
        |
9. Emit run metrics (records_processed, records_new, errors_count)
```

## Configuration Validation

Run `python scripts/validate_configs.py` to verify:

- Source config files parse without schema errors
- No duplicate `source_id` values
- Schedule tasks reference valid agent interfaces
- All required fields present
