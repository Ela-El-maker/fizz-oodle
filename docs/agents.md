# Agents (A-F)

The platform runs six autonomous agents that form a directed acyclic graph (DAG) of market intelligence processing. Agents A, B, and C are independent data collectors; Agent D synthesizes their outputs; Agent E tracks long-horizon patterns from D; Agent F generates human-readable narratives from all five.

```text
A (Briefing)  -------+
                     +---->  D (Analyst)  --->  E (Archivist)  --->  F (Narrator)
B (Announcements) --+                                           /
                     |                                          /
C (Sentiment)  -----+         (F also reads A-E APIs)  -------+
```

**Critical design rule**: No LLM sits in any critical decision path. Convergence scores, impact ratings, and sentiment classifications are all deterministic. LLM is used only for optional text polish and enrichment.

---

## Agent A - Daily Briefing

**Pipeline**: `apps/agents/briefing/pipeline.py`
**Service**: `services/agent_a/main.py` (port 8001)
**Database**: `db_agent_a`
**Schedule**: Weekdays 08:00 EAT (`0 5 * * 1-5` UTC)

### Purpose

Build a daily market snapshot for the tracked NSE universe. Produces price coverage, FX rates, market indices, news headlines, and an executive briefing used by downstream agents and email delivery.

### Pipeline Steps

1. **Load tracked universe** - reads `config/universe.yml` (67 companies across NSE, JSE, NGX)
2. **Collect news channels** - dispatches to source-type connectors (`rss`, `html`, `sitemap`, `api`, `official`) defined in `config/briefing_sources.yml`
3. **Fetch FX with fallback** - retrieves forex rates; uses stale tolerance (`AGENT_A_FX_STALE_TTL_HOURS=24`, hard limit 72h)
4. **Load market indices** - validates against bounds (`INDEX_VALUE_MIN=100`, `INDEX_VALUE_MAX=20000`, max daily move 25%)
5. **Compute market breadth** - advancers vs decliners, net breadth, top movers with chart generation
6. **NASI alignment** - NSE All Share Index correlation check
7. **Market regime** - determines current market conditions for downstream context
8. **Compose summary** - deterministic template; optional LLM polish when `LLM_MODE != "off"`
9. **Email delivery** - generates executive digest + legacy briefing email based on feature flags

### Configuration Flags

| Setting | Default | Purpose |
|---|---|---|
| `AGENT_A_MIN_PRICE_COVERAGE_PCT` | `60` | Minimum % of universe with price data before degraded status |
| `AGENT_A_MAX_CONCURRENT_PRICE_FETCHES` | `4` | Parallel price collection limit |
| `AGENT_A_FX_STALE_TTL_HOURS` | `24` | FX data freshness tolerance |
| `AGENT_A_FX_STALE_HARD_LIMIT_HOURS` | `72` | Maximum FX data age before marking unavailable |
| `BRIEFING_SOURCE_PACK` | - | Source pack gating (global markets / extras / premium) |
| `AGENT_A_MAX_NEWS_ITEMS_PER_SOURCE` | `25` | News collection cap per individual source |
| `AGENT_A_CHART_VOLUME_OVERLAY` | `True` | Include volume data in movers chart |

### Models

| Model | Table | Purpose |
|---|---|---|
| `DailyBriefing` | `daily_briefings` | Briefing artifacts and metadata |
| `PriceDaily` | `prices_daily` | Daily price snapshots per ticker |
| `FxDaily` | `fx_daily` | Foreign exchange rates |
| `IndexDaily` | `index_daily` | Market index values |
| `NewsHeadlineDaily` | `news_headlines_daily` | Collected news headlines |
| `NewsArticle` | `news_articles` | Full article records |

### Outputs

- **Database**: Daily briefing record, price/FX/index snapshots, news headlines
- **Email**: Executive digest (with Agent F stories, glossary) + legacy briefing
- **Metrics**: `global_news_collected`, `global_themes`, `source_health_by_source_id`, `executive_digest_*`

### Status Semantics

| Status | Condition |
|---|---|
| `success` | All core channels healthy, coverage above threshold |
| `partial` | Core channel degradation or low coverage |
| `fail` | Pipeline error or email delivery failure |

---

## Agent B - Announcements & Signals

**Pipeline**: `apps/agents/announcements/pipeline.py`
**Service**: `services/agent_b/main.py` (port 8002)
**Database**: `db_agent_b`
**Schedule**: Every 2 hours on weekdays (`0 */2 * * 1-5` UTC)

### Purpose

Scrape, normalize, classify, and score corporate announcements from NSE, CMA, company IR pages, and media sources. Produces structured announcements with Kenya impact scores for downstream consumption.

### Pipeline Steps

1. **Source collection** - iterates all sources from `config/sources.yml` with circuit breaker and health checks
2. **Deduplication** - URL normalization + SHA-256 content fingerprinting via `apps/scrape_core/dedupe.py`
3. **Classification** - assigns scope, signal class, theme, and affected sectors (deterministic rules; LLM optional with budget/breaker controls)
4. **Kenya impact scoring** - deterministic 5-100 point scale based on scope, signal class, and transmission channel analysis
5. **Promotion gate** - `global_outside` items promoted to core feed only when `kenya_impact_score >= 60`
6. **Alert evaluation** - high-impact items trigger email alerts based on gating rules

### Configuration Flags

| Setting | Default | Purpose |
|---|---|---|
| `ANNOUNCEMENT_LOOKBACK_DAYS` | `30` | How far back to look for announcements |
| `ANNOUNCEMENT_MAX_ITEMS_PER_SOURCE` | `500` | Collection cap per source |
| `ANNOUNCEMENT_ALERT_CANDIDATES_MAX` | `40` | Maximum items evaluated for alerting |
| `ANNOUNCEMENT_DETAIL_ENRICHMENTS_MAX` | `8` | Max items receiving LLM detail enrichment |
| `ANNOUNCEMENT_COLLECTION_MAX_SECONDS` | `45` | Source collection timeout |
| `GLOBAL_OUTSIDE_KENYA_IMPACT_THRESHOLD` | `60` | Minimum impact score for core feed promotion |
| `EMAIL_ALERTS_HIGH_IMPACT_ONLY` | `True` | Only alert on high-impact announcements |
| `ANNOUNCEMENT_LLM_CONFIDENCE_THRESHOLD` | `0.70` | Minimum LLM confidence for classification acceptance |
| `ANNOUNCEMENT_LLM_MAX_CALLS_PER_RUN` | `25` | LLM call budget per pipeline run |
| `ANNOUNCEMENT_LLM_CONCURRENCY` | `5` | Parallel LLM classification limit |
| `ANNOUNCEMENT_LLM_CIRCUIT_BREAKER_THRESHOLD` | `3` | Failures before LLM circuit trips |

### Source Taxonomy (Lane Model)

Each source and announcement carries lane metadata:

| Field | Values | Purpose |
|---|---|---|
| `scope` | `kenya_core`, `kenya_extended`, `global_outside` | Geographic relevance tier |
| `market_region` | `kenya`, `east_africa`, `africa`, `global` | Market region classification |
| `signal_class` | `issuer_disclosure`, `regulator`, `macro`, `commodity`, `global_market`, `ai_tech`, `news_signal` | Signal type |
| `theme` | configurable per source | Topical grouping |
| `kenya_impact_score` | 5-100 | Deterministic Kenya relevance rating |
| `promoted_to_core_feed` | boolean | Whether global item passed promotion gate |
| `affected_sectors` | list | Kenyan sectors impacted |
| `transmission_channels` | list | How the event affects Kenya markets |

Announcement types are defined in `config/announcement_types.yml` (10 types).

### Models

| Model | Table | Purpose |
|---|---|---|
| `Announcement` | `announcements` | Normalized announcement records with lane metadata |
| `AnnouncementAsset` | `announcement_assets` | Associated files/documents |
| `SourceHealth` | `source_health` | Per-source health snapshots |

### Status Semantics

| Status | Condition |
|---|---|
| `success` | All core sources passed |
| `partial` | Core source or email degradation |
| `fail` | Critical source failure or email error |

### Common Failure Modes

- **Source blocked/timeout**: Source health degrades, circuit breaker may trip. Run continues as `partial`.
- **Deep IR archives**: Company IR pages expose old content. Mitigated by dedupe and lookback window, but parser tuning may be needed.
- **LLM unavailable**: Classification falls back to deterministic rules. No impact on critical scoring.

---

## Agent C - Sentiment & Theme Momentum

**Pipeline**: `apps/agents/sentiment/pipeline.py`
**Service**: `services/agent_c/main.py` (port 8003)
**Database**: `db_agent_c`
**Schedule**: Mondays 07:00 EAT (`0 4 * * 1` UTC)

### Purpose

Produce weekly ticker sentiment and theme momentum summaries from social media, news RSS, and forum sources. Tracks bullish/bearish/neutral signals with week-over-week momentum per ticker, plus global theme inference even when ticker mapping is absent.

### Pipeline Steps

1. **Source collection** - collects posts from `config/sentiment_sources.yml` via RSS/HTML/forum/API/sitemap connectors
2. **Mention extraction** - maps posts to tickers via company name/alias matching from `config/universe.yml`
3. **Sentiment scoring** - rule-based bullish/bearish/neutral classification; optional LLM refinement
4. **Theme inference** - tags posts with themes: `oil`, `usd_strength`, `ai_platforms`, `bonds_yields`, `earnings_cycle`, etc.
5. **Unmapped theme pipeline** - posts without ticker matches still enter theme analysis when relevance is sufficient
6. **Weekly aggregation** - computes per-ticker weekly sentiment and week-over-week momentum
7. **Digest generation** - builds sentiment digest report for email delivery

### Configuration Flags

| Setting | Default | Purpose |
|---|---|---|
| `SENTIMENT_WINDOW_DAYS` | `7` | Lookback window for weekly sentiment |
| `SENTIMENT_BULL_THRESHOLD` | `0.20` | Score threshold for bullish classification |
| `SENTIMENT_BEAR_THRESHOLD` | `-0.20` | Score threshold for bearish classification |
| `SENTIMENT_MIN_MENTIONS_PER_TICKER` | `3` | Minimum mentions before ticker sentiment is reported |
| `SENTIMENT_LLM_MAX_CALLS` | `25` | LLM call budget for alpha enrichment |
| `SENTIMENT_ALPHA_ENRICHMENT_ENABLED` | `True` | Enable LLM-based enrichment on raw posts |

### Models

| Model | Table | Purpose |
|---|---|---|
| `SentimentRawPost` | `sentiment_raw_posts` | Raw collected posts |
| `SentimentTickerMention` | `sentiment_ticker_mentions` | Ticker-to-post mappings |
| `SentimentWeekly` | `sentiment_weekly` | Weekly per-ticker sentiment scores |
| `SentimentDigestReport` | `sentiment_digest_reports` | Digest summaries for email |
| `SentimentSnapshot` | `sentiment_snapshots` | Point-in-time sentiment state |
| `SentimentMention` | `sentiment_mentions` | Legacy mention records |

### Outputs

- **Database**: Raw posts, ticker mentions, weekly aggregations, digest reports
- **API**: `/sentiment/themes/weekly` provides theme aggregates used by Agent D and F
- **Email**: Legacy weekly sentiment email (during digest parallel window)

### Status Semantics

| Status | Condition |
|---|---|
| `success` | All core sources passed |
| `partial` | Core source or digest degradation |
| `fail` | Critical source or digest failure |

---

## Agent D - Analyst Synthesis

**Pipeline**: `apps/agents/analyst/pipeline.py`
**Service**: `services/agent_d/main.py` (port 8004)
**Database**: `db_agent_d`
**Schedules**: Daily weekdays 09:00 EAT (`0 6 * * 1-5` UTC), Weekly Mondays 07:30 EAT (`30 4 * * 1` UTC)

### Purpose

Synthesize outputs from Agents A, B, and C into interpretable analyst reports. The convergence engine is the system's core analytical mechanism - it overlays price signals, announcement signals, and sentiment signals to compute multi-factor convergence scores with full decision traces.

### Pipeline Steps

1. **Load input bundle** - fetches latest A, B, C artifacts; evaluates upstream quality and degraded reasons
2. **Signal extraction** - builds `PriceSignal`, `AnnouncementSignal`, `SentimentSignal` from upstream data
3. **Convergence computation** - deterministic multi-factor scoring (confidence 0-95%), no LLM involvement
4. **Decision trace** - records exactly which signals contributed to each convergence score for auditability
5. **Archivist feedback integration** - when `ANALYST_USE_ARCHIVIST_FEEDBACK=True` and Agent E has >=3 active patterns, incorporates pattern context (weight capped at 60%)
6. **Global context** - captures global market drivers for downstream E/F consumption
7. **Optional LLM polish** - narrative overview text only (not scores or decisions)
8. **Email delivery** - report distribution based on send policy

### Configuration Flags

| Setting | Default | Purpose |
|---|---|---|
| `ANALYST_DAILY_TARGET_HOUR_EAT` | `9` | Target hour for daily report |
| `ANALYST_WEEKLY_TARGET_HOUR_EAT` | `8` | Target hour for weekly report |
| `ANALYST_LOOKBACK_DAYS` | `7` | Data window for report generation |
| `ANALYST_MAX_EVENTS` | `30` | Maximum events processed per report |
| `ANALYST_USE_ARCHIVIST_FEEDBACK` | `True` | Enable pattern feedback from Agent E |
| `ANALYST_ARCHIVIST_FEEDBACK_MIN_PATTERNS` | `3` | Minimum active patterns before feedback is applied |
| `ANALYST_ARCHIVIST_FEEDBACK_WEIGHT_CAP` | `0.60` | Maximum influence of pattern feedback on convergence |

### Convergence Engine

The convergence engine is entirely deterministic:

```text
Inputs:
  PriceSignal        <- Agent A (daily prices, movers, breadth)
  AnnouncementSignal <- Agent B (classified events, impact scores)
  SentimentSignal    <- Agent C (weekly ticker/theme sentiment)

Processing:
  compute_convergence(signals) -> {
    convergence_score: 0-95%,
    decision_trace: [...signal contributions...],
    confidence_level: low|medium|high,
    degraded_reasons: [...]
  }
```

### Models

| Model | Table | Purpose |
|---|---|---|
| `AnalystReport` | `analyst_reports` | Full report payload with convergence data, signals, and global context |

### Events Emitted

- `AnalystReportGeneratedV1` - consumed by Agent E and Agent F

### Status Semantics

| Status | Condition |
|---|---|
| `success` | Upstream quality acceptable |
| `partial` | Degraded upstream inputs (still produces report with caveat) |
| `fail` | Report generation or email failure |

---

## Agent E - Archivist / Pattern Memory

**Pipeline**: `apps/agents/archivist/pipeline.py`
**Service**: `services/agent_e/main.py` (port 8005)
**Database**: `db_agent_e`
**Schedules**: Weekly Mondays 06:00 EAT (`0 3 * * 1` UTC), Monthly 1st 07:00 EAT (`0 4 1 * *` UTC)

### Purpose

Maintain long-horizon pattern memory with lifecycle management. Tracks patterns from candidate to confirmed to retired, with regime-aware thresholds and outcome tracking. Feeds pattern context back to Agent D for convergence adjustment.

### Pipeline Steps

1. **Input loading** - reads from Agent D reports (`input_mode="analyst_only"` by default); optional hybrid from B/C
2. **Upstream quality gate** - evaluates market regime and applies regime-specific thresholds
3. **Lifecycle management**:
   - **Candidate to Confirmed**: promotion at 65% occurrence threshold, minimum 5 occurrences
   - **Confirmed to Retired**: retirement at 45% threshold, minimum 8 occurrences
   - Regime adjustments enabled (thresholds shift based on market conditions)
4. **Pattern upsert** - creates/updates patterns with occurrence records, impact statistics, and accuracy scores
5. **Global pattern context** - builds additive context from themes + high-impact global events
6. **Outcome tracking** - records whether pattern predictions materialized

### Configuration Flags

| Setting | Default | Purpose |
|---|---|---|
| `ARCHIVIST_PROMOTION_THRESHOLD` | `0.65` | Occurrence % threshold for candidate to confirmed |
| `ARCHIVIST_RETIREMENT_THRESHOLD` | `0.45` | Threshold for confirmed to retired |
| `ARCHIVIST_MIN_OCCURRENCES_CONFIRM` | `5` | Minimum observations before confirmation |
| `ARCHIVIST_MIN_OCCURRENCES_RETIRE` | `8` | Minimum observations before retirement |
| `ARCHIVIST_REGIME_ADJUSTMENTS_ENABLED` | `True` | Adjust thresholds by market regime |
| `ARCHIVIST_MONTHLY_LOOKBACK_WEEKS` | `12` | Monthly run lookback window |
| `ARCHIVIST_INPUT_MODE` | `"analyst_only"` | Input source (`analyst_only` or `hybrid`) |

### Pattern Lifecycle

```text
                    +------------+
      new signal -> | Candidate  |
                    +------+-----+
                           | occurrences >= 5
                           | threshold >= 65%
                           v
                    +------------+
                    | Confirmed  | <-- feeds back to Agent D
                    +------+-----+
                           | occurrences >= 8
                           | threshold <= 45%
                           v
                    +------------+
                    |  Retired   |
                    +------------+
```

### Models

| Model | Table | Purpose |
|---|---|---|
| `Pattern` | `pattern` | Pattern records with lifecycle state |
| `PatternOccurrence` | `pattern_occurrence` | Individual occurrence observations |
| `ImpactStat` | `impact_stat` | Statistical impact measurements |
| `AccuracyScore` | `accuracy_score` | Historical accuracy tracking |
| `OutcomeTracking` | `outcome_tracking` | Did the pattern prediction materialize? |
| `ArchiveRun` | `archive_run` | Archive pipeline run records |

### Events Emitted

- `ArchivistPatternsUpdatedV1` - consumed by Agent F

### Status Semantics

| Status | Condition |
|---|---|
| `success` | Upstream quality acceptable, patterns processed |
| `partial` | Upstream degradation or low quality data |
| `fail` | Archive pipeline or email failure |

---

## Agent F - Narrator (Deep Focus)

**Pipeline**: `apps/agents/narrator/pipeline.py`, `apps/agents/narrator/monitor.py`
**Service**: `services/agent_f/main.py` (port 8006)
**Database**: `db_agent_f`
**Schedule**: Every 30 minutes (`*/30 * * * *` UTC)

### Purpose

Generate operator-readable stories and announcement insight cards with evidence references. Agent F is the system's primary interface for turning raw intelligence into actionable narrative content. It also exposes rich monitor telemetry for narrative pipeline health.

### Architecture

Unlike Agents A-E which write to their own databases during pipeline execution, Agent F makes **HTTP calls to all other agent services** to assemble context. It is the only agent that reads cross-service during its own pipeline run.

```text
                +--- Agent A API (/briefings/latest)
                +--- Agent B API (/announcements)
 Agent F <----- +--- Agent C API (/sentiment/weekly)
 (Narrator)     +--- Agent D API (/reports/latest)
                +--- Agent E API (/patterns/active)
                          |
                          v
               LLM generation (optional)
               OR deterministic fallback
                          |
                          v
               InsightCards + EvidencePacks
```

### Pipeline Steps

1. **Parallel context fetch** - HTTP calls to A-E service APIs simultaneously
2. **Story scope assembly** - builds four story scopes:
   - `market` - today's market state from Agent A data
   - `analyst` - convergence highlights from Agent D
   - `pattern` - active pattern context from Agent E
   - `announcement` - key corporate events from Agent B with Kenya impact context
3. **Announcement insight card seeding** - creates insight cards for latest feed rows with evidence
4. **LLM narrative generation** - when enabled, uses JSON mode for structured output; deterministic fallback when unavailable
5. **Global drivers** - computes "global-to-Kenya" transmission narrative showing how international events affect local markets
6. **Card caching** - stores insight cards with expiry and refresh rules

### Configuration Flags

| Setting | Default | Purpose |
|---|---|---|
| `NARRATOR_ENABLED` | `True` | Master enable/disable |
| `NARRATOR_REFRESH_CYCLE_MINUTES` | `30` | Refresh interval |
| `NARRATOR_LLM_CACHE_MINUTES` | `360` | LLM response cache TTL |
| `NARRATOR_LLM_TIMEOUT_SECONDS` | `20` | LLM call timeout |
| `NARRATOR_LLM_MAX_TOKENS` | `500` | Maximum tokens per LLM response |
| `NARRATOR_MAX_CONTEXT_SOURCES` | `5` | Maximum sources used for context assembly |
| `NARRATOR_MIN_COVERAGE` | `0.6` | Minimum source coverage before degraded status |
| `NARRATOR_LLM_RETRIES` | `3` | LLM retry attempts |
| `NARRATOR_READ_TIMEOUT` | `90` | HTTP read timeout for upstream APIs |
| `ANNOUNCEMENT_INSIGHT_CACHE_MINUTES` | `360` | Insight card cache duration |
| `ANNOUNCEMENT_INSIGHT_MAX_TOKENS` | `350` | Max tokens for announcement insights |
| `ANNOUNCEMENT_INSIGHT_TIMEOUT` | `10` | Insight generation timeout |
| `ANNOUNCEMENT_INSIGHT_MIN_CONTEXT_LENGTH` | `240` | Minimum context chars before insight generation |

### Models

| Model | Table | Purpose |
|---|---|---|
| `InsightCard` | `insight_cards` | Generated narrative cards with evidence references |
| `EvidencePack` | `evidence_packs` | Source evidence supporting insight cards |
| `ContextFetchJob` | `context_fetch_jobs` | Tracks HTTP calls to upstream services |

### Monitor Telemetry

Agent F exposes rich monitoring via `apps/agents/narrator/monitor.py`:

| Endpoint | Data |
|---|---|
| `/stories/monitor/status` | Current narrator pipeline status |
| `/stories/monitor/pipeline` | Pipeline stage timing and success rates |
| `/stories/monitor/requests` | HTTP request metrics to upstream services |
| `/stories/monitor/scrapers` | Context scraper health |
| `/stories/monitor/events` | Recent narrator events |
| `/stories/monitor/cycles` | Refresh cycle history |
| `/stories/monitor/health` | Overall narrator health assessment |
| `/stories/monitor/snapshot` | Complete state snapshot for dashboards |

Gateway also provides WebSocket streaming at `/stories/monitor/ws` (2-second refresh, 15-second heartbeat).

### API Surface

| Endpoint | Method | Purpose |
|---|---|---|
| `/stories/latest` | GET | Most recent stories |
| `/stories` | GET | Paginated story listing |
| `/stories/{card_id}` | GET | Specific story card |
| `/stories/rebuild` | POST | Force narrative rebuild |
| `/announcements/{id}/insight` | GET | Insight card for specific announcement |
| `/announcements/{id}/context/refresh` | POST | Trigger context re-fetch |

### Failure Handling

Agent F is the most failure-prone agent because it depends on all upstream services:

| Failure Mode | Behavior |
|---|---|
| **Upstream API unavailable** | Falls back to deterministic sections with lower confidence |
| **LLM timeout** | Deterministic fallback mode persists in card quality/status fields |
| **Weak evidence** | Returns `needs_more_data` status rather than overconfident narrative |
| **Partial upstream data** | Generates stories from available data, marks as degraded |
| **Context fetch failure** | Individual card marked as degraded, pipeline continues |

### Status Semantics

| Status | Condition |
|---|---|
| `success` | Narrator completed with sufficient coverage |
| `partial` | Some context fetches failed or LLM unavailable (common in normal operation) |
| `fail` | Narrator pipeline failure |

---

## Agent Comparison Matrix

| Property | A (Briefing) | B (Announcements) | C (Sentiment) | D (Analyst) | E (Archivist) | F (Narrator) |
|---|---|---|---|---|---|---|
| **Frequency** | Daily weekdays | Every 2h weekdays | Weekly Monday | Daily+Weekly | Weekly+Monthly | Every 30min |
| **Data Sources** | External APIs/RSS | NSE/CMA/IR/Media | Social/News/Forums | Agents A+B+C | Agent D reports | Agents A-E APIs |
| **LLM Usage** | Optional polish | Optional classify | Optional refine | Optional polish | None | Optional narrate |
| **Critical Path LLM** | No | No | No | No | N/A | No |
| **Key Output** | Market briefing | Scored announcements | Sentiment scores | Convergence report | Pattern lifecycle | Story cards |
| **Downstream** | D, F, Email | D, F, Email | D, F, Email | E, F, Email | D (feedback), F | Dashboard, Email |
| **Stale TTL** | 30 min | 20 min | 45 min | 30 min | 45 min | 30 min |
