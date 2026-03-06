# Agents (A–F)

## Agent A — Prices & Daily Briefing

**Code**: `apps/agents/briefing/pipeline.py`  
**Service**: `services/agent_a/main.py`

### Purpose

Build a daily market snapshot for tracked NSE universe and publish briefing artifacts used downstream by D/F and email digest.

### Inputs

- Price/index/fx/news channel definitions from `config/briefing_sources.yml`
- Universe aliases from `config/universe.yml`
- Source flags from env (`ENABLED_*_SOURCES`, global/source toggles)

### Processing

- Collects channel data via source-type dispatch (`rss`, `html`, `sitemap`, `api`, `official`)
- Applies source pack gating (`global markets` / `extras` / premium off)
- Computes:
  - price coverage vs tracked NSE universe
  - advancers/decliners/net breadth
  - top movers and chart
  - global theme counts and source health
- Generates market brief with LLM when enabled; deterministic fallback otherwise.
- Builds executive digest payload (`apps/reporting/email_digest/*`) and sends based on feature flags.

### Outputs

- DB: `daily_briefings`, `price_daily`, `index_daily`, `fx_daily`, `news_headline_daily`
- Email: legacy briefing + executive digest (flag controlled)
- Metrics fields include `global_news_collected`, `global_themes`, `source_health_by_source_id`, `executive_digest_*`

### Status behavior

- `success`: all core channels healthy
- `partial`: core channel degradation
- `fail`: email or pipeline failure

---

## Agent B — Announcements & Signals

**Code**: `apps/agents/announcements/pipeline.py`  
**Service**: `services/agent_b/main.py`

### Purpose

Normalize disclosures/news into structured announcement records and produce high-value alert candidates.

### Inputs

- `config/sources.yml` (strict schema)
- parser registry (official, IR, RSS, HTML listing, sitemap)
- ticker aliases from universe

### Processing

- Source collection with breaker/health checks and retries.
- Dedupes via URL/content hashes.
- Classification + severity (LLM optional with budget/breaker controls).
- Computes lane metadata for each item:
  - `scope`, `signal_class`, `theme`
  - `kenya_impact_score`
  - `affected_sectors`, `transmission_channels`
  - `promoted_to_core_feed`
- Promotion gate:
  - `global_outside` only promoted to default feed when impact threshold is met (default `>= 60`).

### Outputs

- DB: `announcements`, `source_health`
- Alert emails: gated by `EMAIL_ALERTS_HIGH_IMPACT_ONLY` and per-scope logic
- API fields consumed by UI/F include lane/impact metadata

### Status behavior

- `success`: all core sources passed
- `partial`: core/email degradation
- `fail`: critical source or email failure

### Common failure modes

- Source blocked/timeout -> source health degraded, run may still be partial.
- Aggressive IR archives causing noisy old rows -> mitigated by dedupe and UI filtering, but parser tuning may be required.

---

## Agent C — Sentiment & Theme Momentum

**Code**: `apps/agents/sentiment/pipeline.py`  
**Service**: `services/agent_c/main.py`

### Purpose

Produce weekly ticker sentiment and theme sentiment summaries, including global themes even when ticker mapping is absent.

### Inputs

- `config/sentiment_sources.yml`
- mention extraction from ticker/company alias map
- optional social/news API credentials

### Processing

- Collects posts from RSS/html/forum/api/sitemap connectors.
- Scores sentiment via rules + optional LLM refinement.
- Performs theme inference (`oil`, `usd_strength`, `ai_platforms`, `bonds_yields`, `earnings_cycle`, etc.).
- Keeps unmapped ticker posts in theme pipeline when relevance is sufficient.

### Outputs

- DB: `sentiment_raw_posts`, `sentiment_ticker_mentions`, `sentiment_weekly`, `sentiment_digest_reports`
- API: `/sentiment/themes/weekly` returns theme aggregates used by D/F
- Legacy weekly sentiment email (during digest parallel window)

### Status behavior

- `success`: all core sources passed
- `partial`: core or digest degradation
- `fail`: critical source/digest failure

---

## Agent D — Analyst Synthesis

**Code**: `apps/agents/analyst/pipeline.py`  
**Service**: `services/agent_d/main.py`

### Purpose

Convert A/B/C outputs into interpretable daily/weekly report payloads with quality and feedback context.

### Inputs

- Latest A/B/C artifacts
- Optional archivist feedback (config-controlled)

### Processing

- Loads input bundle + computes upstream quality/degraded reasons.
- Builds deterministic feature set and rules-based payload.
- Optional LLM polish for narrative overview.
- Captures `global_context` for downstream E/F.

### Outputs

- DB: `analyst_reports`
- Event: `AnalystReportGeneratedV1`
- Email report (unless suppressed by send policy)

### Status behavior

- `success`: upstream quality ok
- `partial`: degraded upstream inputs
- `fail`: report/email failure

---

## Agent E — Archivist / Patterns

**Code**: `apps/agents/archivist/pipeline.py`  
**Service**: `services/agent_e/main.py`

### Purpose

Maintain long-horizon pattern memory and outcome tracking from analyst intelligence.

### Inputs

- Primarily D reports (`ANALYST_ONLY` mode default)
- Optional hybrid context from B/C
- Market regime and upstream quality

### Processing

- Computes lifecycle thresholds (promotion/retire) by market regime.
- Applies upstream quality gates and replacement-pressure rules.
- Upserts patterns, impacts, accuracy, outcomes.
- Builds additive `global_pattern_context` from themes + high-impact global events.

### Outputs

- DB: `patterns`, `impact_stats`, `archive_runs`, `accuracy_scores`, `outcome_tracking`, occurrences
- Event: `ArchivistPatternsUpdatedV1`

### Status behavior

- `success`: upstream quality ok
- `partial`: upstream degradation / low quality
- `fail`: archive email or pipeline failure

---

## Agent F — Narrator (Special Focus)

**Code**: `apps/agents/narrator/pipeline.py`, `apps/agents/narrator/monitor.py`  
**Service**: `services/agent_f/main.py`

### Purpose

Generate operator-readable stories and announcement insight cards with evidence references, while exposing monitor telemetry for narrative pipeline health.

### Inputs

- A/B/C/D/E service APIs (parallel fetched)
- Announcement context fetch jobs (source article corroboration)
- Existing cached cards and quality metadata

### Processing

- Builds scope stories: `market`, `analyst`, `pattern`, `announcement`.
- Seeds announcement insight cards for latest feed rows.
- Uses LLM JSON mode when enabled; deterministic fallback when unavailable.
- Computes `global_drivers` for “global-to-Kenya” transmission narrative.
- Caches cards with expiry and refresh rules (`NARRATOR_*` settings).

### Outputs

- DB: `insight_cards`, `evidence_packs`, `context_fetch_jobs`
- APIs:
  - `/stories/latest`, `/stories`, `/stories/{id}`
  - `/announcements/{id}/insight`
  - `/stories/monitor/*` rich telemetry endpoints

### Status behavior

- `success`: narrator completed
- `partial`: narrator partial errors (common when some context fetches fail)
- `fail`: narrator pipeline failure

### Failure cases and handling

- Upstream API gaps: falls back to deterministic sections + lower confidence.
- LLM errors/timeouts: fallback mode persists in card quality/status.
- Weak evidence: returns `needs_more_data` style status instead of overconfident narrative.

### Improvement opportunities

- Better source-level relevance pruning before context-fetch to reduce noise.
- Stronger citation formatting per paragraph.
- Rank global drivers by actual local market response (not only metadata/impact score).
