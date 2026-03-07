# System Architecture

## Overview

The Market Intelligence Platform is a microservices system purpose-built for the Nairobi Securities Exchange (NSE). It runs six autonomous data agents, a scheduling engine, an operational ledger, and an operator dashboard — all coordinated through Redis Streams and isolated PostgreSQL databases.

The system operates on an **Africa/Nairobi (EAT, UTC+3)** schedule aligned with NSE trading hours.

## Design Principles

| Principle                     | Implementation                                                                                                                                                      |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Deterministic-first**       | No LLM sits in any critical decision path. Convergence scores, Kenya impact ratings, and sentiment classifications are all rule-based. LLM is optional polish only. |
| **Database isolation**        | Each agent writes to its own Postgres database. No cross-service joins or shared schema migrations.                                                                 |
| **Event-driven coordination** | Agents communicate exclusively through Redis Streams. No synchronous inter-agent calls during pipeline execution.                                                   |
| **Graceful degradation**      | Every pipeline produces `success`, `partial`, or `fail` status. Partial results are always stored and surfaced rather than discarded.                               |
| **Replay safety**             | All stream messages carry idempotent IDs. Consumer groups with acknowledgement ensure at-least-once processing.                                                     |

## Service Topology

```text
                    ┌────────────────────────────────────────────┐
                    │            Frontend (Next.js 14)           │
                    │         /api/* rewrite → Gateway           │
                    │                port 3000                   │
                    └────────────────────┬───────────────────────┘
                                         │
                    ┌────────────────────┴───────────────────────┐
                    │            Gateway Service                 │
                    │   auth · RBAC · reverse proxy · WebSocket  │
                    │                port 8000                   │
                    └───┬──────────┬──────────┬─────────────────┘
                        │          │          │
          ┌─────────────┤          │          ├────────────────────┐
          │             │          │          │                    │
          v             v          v          v                    v
   ┌────────────┐ ┌──────────┐ ┌──────────────────────────────┐ ┌──────────┐
   │ Scheduler  │ │   Run    │ │        Agents A–F            │ │  Legacy  │
   │  Service   │ │  Ledger  │ │  A:8001  B:8002  C:8003      │ │ (Docker  │
   │ port 8010  │ │  Service │ │  D:8004  E:8005  F:8006      │ │ profile) │
   └─────┬──────┘ │ port 8011│ └────────────┬─────────────────┘ └──────────┘
         │        └────┬─────┘              │
         │             │                    │
         └─────────────┼────────────────────┘
                       │
              ┌────────┴────────┐
              │  Redis 7        │
              │  Streams + Cache│
              │  port 6379      │
              └────────┬────────┘
                       │
              ┌────────┴────────┐
              │  PostgreSQL 16  │
              │  7 databases    │
              │  port 5432      │
              └─────────────────┘
```

## Service Inventory

| Service              | Port | Database          | Purpose                                                                                    |
| -------------------- | ---- | ----------------- | ------------------------------------------------------------------------------------------ |
| `gateway-service`    | 8000 | — (reads only)    | Auth, RBAC, reverse proxy to all agents, WebSocket feeds, health aggregation               |
| `scheduler-service`  | 8010 | —                 | Cron evaluation loop (10s tick), dispatches `RunCommandV1` to Redis Streams                |
| `run-ledger-service` | 8011 | `db_platform_ops` | Persists run lifecycle, stale-run reconciliation, scheduler monitor APIs, email validation |
| `agent-a-service`    | 8001 | `db_agent_a`      | Daily briefing — prices, FX, indices, news                                                 |
| `agent-b-service`    | 8002 | `db_agent_b`      | Announcements — scrape, classify, Kenya impact score                                       |
| `agent-c-service`    | 8003 | `db_agent_c`      | Sentiment — weekly ticker/theme analysis                                                   |
| `agent-d-service`    | 8004 | `db_agent_d`      | Analyst synthesis — convergence engine across A+B+C                                        |
| `agent-e-service`    | 8005 | `db_agent_e`      | Archivist — pattern lifecycle and outcome tracking                                         |
| `agent-f-service`    | 8006 | `db_agent_f`      | Narrator — story generation and announcement insights                                      |
| `frontend`           | 3000 | —                 | Next.js 14 operator dashboard                                                              |
| `postgres`           | 5432 | —                 | PostgreSQL 16 Alpine                                                                       |
| `redis`              | 6379 | —                 | Redis 7 Alpine (Streams + caching)                                                         |

## Database Isolation

Each service has its own database, created at startup by `scripts/init-microservice-dbs.sql` and migrated by Alembic:

```text
PostgreSQL Instance
├── db_agent_a      ← Agent A (prices, briefings, FX, indices, news)
├── db_agent_b      ← Agent B (announcements, announcement assets, source health)
├── db_agent_c      ← Agent C (sentiment posts, mentions, weekly, digest)
├── db_agent_d      ← Agent D (analyst reports)
├── db_agent_e      ← Agent E (patterns, occurrences, impacts, accuracy, outcomes)
├── db_agent_f      ← Agent F (insight cards, evidence packs, context fetch jobs)
└── db_platform_ops ← Run Ledger (runs, commands, dispatches, timeline, healing, autonomy)
```

This isolation ensures:

- No cross-service migration coupling
- Independent backup and restore per agent
- Safe schema evolution without coordination
- Clean data ownership boundaries

## Event Bus (Redis Streams)

All inter-service coordination flows through five Redis Streams:

| Stream                          | Producer             | Consumer(s)                | Purpose                                               |
| ------------------------------- | -------------------- | -------------------------- | ----------------------------------------------------- |
| `commands.run.v1`               | Scheduler, Gateway   | Agent services, Run Ledger | Dispatch pipeline execution commands                  |
| `runs.events.v1`                | Agent services       | Run Ledger                 | Report run lifecycle (running → success/partial/fail) |
| `analyst.report.generated.v1`   | Agent D              | Agent E, Agent F           | Notify downstream of new analyst report               |
| `archivist.patterns.updated.v1` | Agent E              | Agent F                    | Notify narrator of pattern updates                    |
| `system.events.v1`              | Run Ledger (healing) | Ops monitoring             | Healing and operational events                        |

All streams are capped at 10,000 messages (approximate trimming). Consumer groups use the pattern `commands:{agent_name}` with unique consumer names per process instance.

### Event Schemas

```text
RunCommandV1
├── command_id, run_id, agent_name
├── trigger_type (schedule | manual | retry)
├── schedule_key, report_type, run_type
├── requested_by, requested_at, scheduled_for
└── email_recipients_override, force_send

RunEventV1
├── run_id, agent_name
├── status (running | success | partial | fail)
├── started_at, finished_at
├── metrics (dict), error_message
└── records_processed, records_new, errors_count

AnalystReportGeneratedV1
├── report_id, report_type (daily | weekly)
├── period_key, degraded, generated_at

ArchivistPatternsUpdatedV1
├── run_type (weekly | monthly), period_key
├── patterns_upserted, impacts_upserted
├── accuracy_rows_upserted, degraded, generated_at

OpsHealingAppliedV1
├── incident_id, component, failure_type
├── action, result, auto_applied
└── escalated, occurred_at
```

## Request Planes

The system operates on two distinct communication planes:

### External Plane (Operators / Dashboard)

- **Auth methods**: `X-API-Key` header OR session cookie from `/auth/login`
- **RBAC roles**: `viewer`, `operator`, `admin`
- **Entry point**: Gateway service only (all external traffic proxied through gateway)

### Internal Plane (Service-to-Service)

- **Auth**: `X-Internal-Api-Key` header validated via HMAC comparison
- **Endpoints**: `/internal/*` routes on each agent and run-ledger
- **Usage**: Health checks, trigger runs, scheduler dispatch logging

## Resilience Model

| Layer                 | Mechanism                                             | Location                            |
| --------------------- | ----------------------------------------------------- | ----------------------------------- |
| **Network**           | Retry with exponential backoff + error classification | `apps/scrape_core/retry.py`         |
| **Source**            | Circuit breaker (closed → open → half-open)           | `apps/scrape_core/breaker.py`       |
| **Source**            | Rolling-window health scoring                         | `apps/scrape_core/source_health.py` |
| **Deduplication**     | SHA-256 content fingerprinting + URL normalization    | `apps/scrape_core/dedupe.py`        |
| **Run lifecycle**     | Stale-run reconciler (per-agent TTL, marks fail)      | `services/run_ledger/`              |
| **Self-healing**      | Autonomy state tracking + healing incidents           | `apps/core/models/`                 |
| **Self-modification** | Proposal-based config changes (auto or manual apply)  | `apps/agent_system/`                |
| **Observability**     | Prometheus metrics per service + Grafana dashboards   | `services/common/metrics.py`        |

## Agent Dependency Graph

```text
         ┌───────┐    ┌───────┐    ┌───────┐
         │   A   │    │   B   │    │   C   │
         │Briefng│    │Announce│    │Sentmnt│
         └───┬───┘    └───┬───┘    └───┬───┘
             │            │            │
             └────────────┼────────────┘
                          │
                     ┌────┴────┐
                     │    D    │
                     │ Analyst │
                     └────┬────┘
                          │
                     ┌────┴────┐
                     │    E    │
                     │Archivist│
                     └────┬────┘
                          │
                     ┌────┴────┐
                     │    F    │
                     │Narrator │
                     └─────────┘

 A, B, C  →  independent (can run in parallel)
 D        →  depends on A + B + C outputs
 E        →  depends on D output
 F        →  depends on D + E outputs (reads A–E APIs)
```

## Data Model Summary

The system manages 39 SQLAlchemy models across 7 databases. Key model groups:

| Domain            | Models                                                                                                                            | Tables                                                                                                                                          |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| **Market Data**   | `Company`, `PriceDaily`, `PriceSnapshot`, `FxDaily`, `ForexRate`, `IndexDaily`                                                    | `companies`, `prices_daily`, `price_snapshots`, `fx_daily`, `forex_rates`, `index_daily`                                                        |
| **News**          | `NewsArticle`, `NewsHeadlineDaily`, `DailyBriefing`                                                                               | `news_articles`, `news_headlines_daily`, `daily_briefings`                                                                                      |
| **Announcements** | `Announcement`, `AnnouncementAsset`, `SourceHealth`                                                                               | `announcements`, `announcement_assets`, `source_health`                                                                                         |
| **Sentiment**     | `SentimentRawPost`, `SentimentTickerMention`, `SentimentWeekly`, `SentimentDigestReport`, `SentimentSnapshot`, `SentimentMention` | `sentiment_raw_posts`, `sentiment_ticker_mentions`, `sentiment_weekly`, `sentiment_digest_reports`, `sentiment_snapshots`, `sentiment_mentions` |
| **Analysis**      | `AnalystReport`                                                                                                                   | `analyst_reports`                                                                                                                               |
| **Patterns**      | `Pattern`, `PatternOccurrence`, `ImpactStat`, `AccuracyScore`, `OutcomeTracking`, `ArchiveRun`                                    | `pattern`, `pattern_occurrence`, `impact_stat`, `accuracy_score`, `outcome_tracking`, `archive_run`                                             |
| **Narratives**    | `InsightCard`, `EvidencePack`, `ContextFetchJob`                                                                                  | `insight_cards`, `evidence_packs`, `context_fetch_jobs`                                                                                         |
| **Operations**    | `AgentRun`, `RunCommand`, `SchedulerDispatch`, `SchedulerTimelineEvent`                                                           | `agent_runs`, `run_commands`, `scheduler_dispatches`, `scheduler_timeline_events`                                                               |
| **Ops/Healing**   | `HealingIncident`, `AutonomyState`, `LearningSummary`, `SelfModificationProposal`, `SelfModificationAction`                       | `healing_incidents`, `autonomy_state`, `learning_summaries`, `self_mod_proposals`, `self_mod_actions`                                           |
| **Email**         | `EmailValidationRun`, `EmailValidationStep`                                                                                       | `email_validation_runs`, `email_validation_steps`                                                                                               |

## Migration History

| Stage | Migration                         | Description                                           |
| ----- | --------------------------------- | ----------------------------------------------------- |
| 1     | `0001_init.py`                    | Initial schema (companies, prices, runs, core tables) |
| 2     | `0002_agent_runs_uuid_stage1.py`  | UUID primary keys for agent runs                      |
| 3     | `0003_announcements_stage2.py`    | Announcements and source health tables                |
| 4     | `0004_stage3_daily_briefing.py`   | Briefing, FX, index, and news tables                  |
| 5     | `0005_stage4_sentiment_full.py`   | Full sentiment tracking tables                        |
| 6     | `0006_stage5_analyst_reports.py`  | Analyst report tables                                 |
| 7     | `0007_stage6_archivist_tables.py` | Pattern, impact, accuracy, and outcome tables         |

## Shared Libraries

### `apps/` — Application Library

All business logic lives in `apps/`, shared across all services via a single Docker image:

```text
apps/
├── core/              # Settings, events, models, data quality, self-healing
├── scrape_core/       # HTTP client, retry, circuit breaker, dedupe, source health
├── agents/            # Agent-specific pipelines and registries
│   ├── briefing/      # Agent A pipeline
│   ├── announcements/ # Agent B pipeline
│   ├── sentiment/     # Agent C pipeline
│   ├── analyst/       # Agent D pipeline
│   ├── archivist/     # Agent E pipeline
│   └── narrator/      # Agent F pipeline
├── reporting/         # Email templates and digest generation
├── api/               # API router definitions
└── agent_system/      # Self-modification and ops modules
```

### `services/common/` — Service Utilities

| Module               | Purpose                                                                                                               |
| -------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `commands.py`        | Command dispatcher — maps agent names to pipeline runners, Redis stream consumer with backoff reconnection            |
| `internal_router.py` | Factory for `/internal/health`, `/internal/runs/trigger`, `/internal/resend` routes                                   |
| `metrics.py`         | Prometheus middleware — `http_requests_total` counter, `http_request_duration_seconds` histogram, `/metrics` endpoint |
| `security.py`        | HMAC-based internal API key validation dependency                                                                     |

## Deployment Topology

See [deployment.md](deployment.md) for full details. Summary:

| Environment     | Compose File                             | Additional Services                                                                      |
| --------------- | ---------------------------------------- | ---------------------------------------------------------------------------------------- |
| **Development** | `docker-compose.yml`                     | 12 core services (postgres, redis, gateway, scheduler, run-ledger, agents A–F, frontend) |
| **Staging**     | `docker-compose.staging.yml`             | + Nginx, Prometheus, Alertmanager, Grafana, certbot, node-exporter                       |
| **Production**  | `docker-compose.prod.yml`                | Same as staging with production secrets and TLS                                          |
| **Legacy**      | `docker-compose.yml` (profile: `legacy`) | Monolith API + Celery worker + beat + Flower                                             |
