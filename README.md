# Market Intel Platform

**Autonomous multi-agent market intelligence system for the Nairobi Securities Exchange (NSE).**

Collects prices, corporate disclosures, sentiment, and global macro context from 25+ sources. Six cooperating agents process raw data into scored signals, synthesized analyst reports, tracked market patterns, and human-readable narrative explainers — all served through a real-time operator dashboard and executive email digests.

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Agents](#agents)
- [Scheduler](#scheduler)
- [RunLedger](#runledger)
- [Data Flow](#data-flow)
- [Installation](#installation)
- [Running the System](#running-the-system)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [Monitoring and Observability](#monitoring-and-observability)
- [Security](#security)
- [Contributing](#contributing)
- [Future Improvements](#future-improvements)
- [Documentation](#documentation)

---

## Overview

The Market Intel Platform solves a core operations problem: NSE market intelligence is fragmented across official exchange filings, regulator notices, company IR pages, business media, social feeds, and global macro sources. Manual monitoring is slow, incomplete, and not auditable.

This system automates the full pipeline:

1. **Collect** — Agents A, B, and C scrape and normalize data from 25+ configured sources
2. **Synthesize** — Agent D merges price, announcement, and sentiment signals into per-ticker analyst decisions with full traceability
3. **Learn** — Agent E tracks market patterns over time, promoting confirmed patterns and retiring failed ones
4. **Explain** — Agent F generates human-readable narrative cards backed by evidence references
5. **Deliver** — A Next.js dashboard provides real-time views; executive email digests deliver daily/weekly summaries

All signal computation (convergence scoring, Kenya impact scoring, sentiment classification) is **deterministic** — no LLM in critical decision paths. LLMs are used only for optional narrative polishing and enrichment.

### Who Uses This

| Role                 | How They Use It                                                                     |
| -------------------- | ----------------------------------------------------------------------------------- |
| **Market operators** | Monitor the dashboard for daily briefings, high-impact alerts, and sentiment shifts |
| **Analysts**         | Review per-ticker decision traces with full signal provenance                       |
| **Product managers** | Read narrative explainers and weekly digests for market context                     |
| **Developers**       | Extend agents, add sources, build new UI views, tune scoring parameters             |
| **DevOps**           | Monitor agent health, run retries, review healing incidents, manage deployments     |

---

## Key Features

- **Six autonomous agents** (A–F) with a defined dependency DAG: A/B/C → D → E → F
- **Dual-lane intelligence**: `kenya_core` (truth-first domestic signals) and `global_outside` (context-first international events scored by Kenya impact)
- **Deterministic convergence engine** — multi-signal alignment with auditable decision traces per ticker
- **Kenya impact scoring** — 5–100 point scoring system for global events with sector-aware transmission mapping
- **Pattern lifecycle management** — candidate → confirmed → retired with regime-aware thresholds
- **Self-healing pipeline** — incident detection, automated remediation, learning engine, and self-modification proposals
- **25+ scraping connectors** with adaptive rate limiting, circuit breakers, conditional GET, and content deduplication
- **Redis Streams event bus** — `RunCommandV1` / `RunEventV1` for decoupled scheduling and execution tracking
- **RunLedger** — complete execution ledger with stale-run reconciliation and timeline events
- **Operator dashboard** — Next.js 14 with real-time WebSocket feeds, 10 pages, light/dark theming
- **Email delivery** — daily executive digests, high-impact alerts, weekly summaries, and validation flows
- **Prometheus + Grafana** — per-service metrics, alerting rules, and pre-built dashboards
- **RBAC** — viewer / operator / admin roles with session-based and API key authentication

---

## System Architecture

```
                         ┌──────────────────────────────────┐
                         │           Scheduler              │
                         │  cron loop (10s tick) → dispatch  │
                         └───────────────┬──────────────────┘
                                         │ RunCommandV1
                                         ▼
                              Redis Streams (Event Bus)
                          ┌──────────────────────────────┐
                          │  runs.commands.v1             │
                          │  runs.events.v1               │
                          │  analyst.report.generated.v1  │
                          │  archivist.patterns.updated.v1│
                          └──────────┬───────────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              ▼                      ▼                      ▼
     ┌────────────────┐   ┌────────────────┐   ┌────────────────┐
     │ Agent A :8001  │   │ Agent B :8002  │   │ Agent C :8003  │
     │ Briefing       │   │ Announcements  │   │ Sentiment      │
     │ prices/fx/news │   │ filings/alerts │   │ social/themes  │
     └───────┬────────┘   └───────┬────────┘   └───────┬────────┘
             │                    │                    │
             └────────────────────┼────────────────────┘
                                  ▼
                       ┌────────────────────┐
                       │ Agent D :8004      │
                       │ Analyst Synthesis  │
                       │ convergence engine │
                       └─────────┬──────────┘
                                 ▼
                       ┌────────────────────┐
                       │ Agent E :8005      │
                       │ Archivist          │
                       │ pattern lifecycle  │
                       └─────────┬──────────┘
                                 ▼
                       ┌────────────────────┐
                       │ Agent F :8006      │
                       │ Narrator           │
                       │ story generation   │
                       └─────────┬──────────┘
                                 │
    ┌────────────────────────────┼────────────────────────────┐
    ▼                            ▼                            ▼
┌──────────┐          ┌──────────────────┐         ┌──────────────┐
│RunLedger │          │ Gateway :8000    │         │ Email        │
│  :8011   │◄────────►│ auth + proxy +   │         │ SendGrid/SMTP│
│ ledger + │          │ orchestration    │         └──────────────┘
│ healing  │          └────────┬─────────┘
└──────────┘                   │
                               ▼
                    ┌─────────────────────┐
                    │ Dashboard :3000     │
                    │ Next.js 14          │
                    │ 10 pages + widgets  │
                    └─────────────────────┘
```

**Infrastructure**: PostgreSQL 16 (7 isolated databases per service), Redis 7 (streams + caching), Nginx (TLS termination + rate limiting), Prometheus + Grafana + Alertmanager.

See [Architecture](docs/architecture.md) for the complete breakdown.

---

## Agents

| Agent | Name          | Schedule                   | Purpose                                                                                                                                                                                             | Key Output                                                                                     |
| ----- | ------------- | -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| **A** | Briefing      | Daily 06:00 EAT (weekdays) | Collects NSE prices, FX rates, index data, and news headlines. Computes market breadth, regime classification, and movers.                                                                          | `daily_briefings`, `price_daily`, `fx_daily`, `index_daily`, executive digest email            |
| **B** | Announcements | Every 3 hours              | Scrapes corporate disclosures from NSE, CMA, company IR pages, and business media. Classifies by type, scores severity, and detects Kenya impact for global events.                                 | `announcements` with classification + severity + Kenya impact scores, high-impact alert emails |
| **C** | Sentiment     | Weekly (Monday 07:00 EAT)  | Analyzes social media and news RSS for per-ticker sentiment. Computes bullish/bearish/neutral distributions with week-over-week momentum.                                                           | `sentiment_weekly` aggregates, raw posts, theme summaries, sentiment digest email              |
| **D** | Analyst       | Daily 09:00 EAT            | Synthesizes A+B+C outputs into per-ticker trading signals via the convergence engine. Produces decision traces with confidence scores and anomaly detection. Incorporates Agent E pattern feedback. | `analyst_reports` with `decision_trace[]`, signal intelligence, global context                 |
| **E** | Archivist     | Weekly (Monday 08:00 EAT)  | Manages market pattern lifecycle. Discovers patterns from analyst history, tracks occurrences, promotes confirmed patterns, retires failed ones. Adjusts thresholds by market regime.               | `patterns`, `impact_stats`, `archive_runs`, `accuracy_scores`                                  |
| **F** | Narrator      | Every 2 hours              | Generates human-readable story cards from all upstream agents. Fetches context via HTTP from A–E services. Falls back to rule-based narratives if LLM is unavailable.                               | `insight_cards`, `evidence_packs`, announcement-level narratives                               |

**Dependency DAG**: A, B, C run independently → D depends on A+B+C → E depends on D → F depends on D+E

See [Agents](docs/agents.md) for deep documentation including pipeline steps, models, config flags, and failure modes.

---

## Scheduler

The scheduler service runs a continuous loop (10-second tick) evaluating cron schedules defined in `config/schedules.yml`.

- Parses both EAT (display) and UTC (execution) cron expressions
- Dispatches agent runs as `RunCommandV1` messages to Redis Streams
- Dispatches ops tasks (email validation) via internal HTTP endpoints
- Applies an **overlap guard** (15-minute window per agent) to prevent duplicate concurrent runs
- Adds **random jitter** (0–30 seconds) to prevent thundering herd
- Logs every dispatch (success or failure) to the RunLedger timeline

See [Scheduler](docs/scheduler.md) for schedule definitions, dispatch flow, and manual trigger instructions.

---

## RunLedger

The RunLedger service is the **execution system of record**. It provides:

- **Command tracking** — persists every `RunCommandV1` with lifecycle status (queued → running → success/partial/fail)
- **Event sourcing** — consumes `RunEventV1` from Redis Streams and persists to PostgreSQL
- **Stale-run reconciliation** — periodic sweep marks stuck runs as failed after configurable TTLs per agent
- **Scheduler timeline** — unified event log of dispatches, completions, retries, and failures
- **Email validation orchestration** — tracks per-agent validation steps for daily/weekly email verification flows
- **Self-modification integration** — background loop generates and auto-applies improvement proposals
- **Prometheus metrics** — run counts, stale reconciliation counts, email validation tracking

See [RunLedger](docs/runledger.md) for the complete reference.

---

## Data Flow

```
External Sources (25+)
  ├── NSE official, CMA filings, company IR pages
  ├── Business Daily, The Star, Standard, Reuters Africa
  ├── Reddit RSS, Google News KE, BBC Business
  ├── Alpha Vantage, mystocks, ERAPI (FX)
  └── Global macro feeds (oil, tech, commodities)
         │
         ▼
┌─────────────────────────────────────────────────┐
│ Collection Layer (Agents A, B, C)               │
│  scrape → normalize → classify → score → store  │
│  Source health tracking + circuit breakers       │
└─────────────────────┬───────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────┐
│ Synthesis Layer (Agent D)                       │
│  per-ticker: price signal + announcement signal │
│  + sentiment signal → convergence engine        │
│  → decision trace with confidence + anomalies   │
└─────────────────────┬───────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────┐
│ Learning Layer (Agent E)                        │
│  extract patterns from report history           │
│  track occurrences → promote or retire          │
│  feed back pattern success rates to Agent D     │
└─────────────────────┬───────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────┐
│ Explanation Layer (Agent F)                     │
│  fetch context from all agents via HTTP         │
│  generate narrative cards + evidence packs      │
│  LLM generation with rule-based fallback        │
└─────────────────────┬───────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────┐
│ Delivery Layer                                  │
│  Gateway API (REST + WebSocket)                 │
│  Next.js Dashboard (10 pages, real-time)        │
│  Email digests (daily/weekly/alert)             │
└─────────────────────────────────────────────────┘
```

See [Data Flow](docs/data-flow.md) for per-agent data schemas and inter-agent contracts.

---

## Installation

### Prerequisites

| Requirement             | Version | Purpose                          |
| ----------------------- | ------- | -------------------------------- |
| Docker + Docker Compose | v2+     | Container orchestration          |
| Python                  | 3.11    | Local scripts and tests          |
| Node.js                 | 20+     | Dashboard development (optional) |

### Quick Start

```bash
# 1. Clone the repository
git clone <repository-url>
cd fizz-oodle

# 2. Create environment file
cp .env.example .env

# 3. Edit .env — set at minimum:
#    OPERATOR_USERNAME, OPERATOR_PASSWORD
#    API_KEY, INTERNAL_API_KEY
#    EMAIL_PROVIDER (sendgrid or smtp) + credentials
#    Source API keys (ALPHA_VANTAGE_API_KEY, etc.)

# 4. Initialize databases and start all services
docker compose up -d --build
```

This starts 12 services: PostgreSQL, Redis, Gateway, Scheduler, RunLedger, Agents A–F, and the Dashboard.

### Database Initialization

Each agent service runs the following on startup (defined in docker-compose):

```bash
python scripts/ensure_database.py      # Create DB if not exists
python scripts/reset_alembic_version.py # Clean migration state
python scripts/prune_service_tables.py  # Enforce table isolation
alembic upgrade head                    # Apply migrations
```

Seven isolated databases are created: `db_agent_a` through `db_agent_f` plus `db_platform_ops`.

### Validate Configuration

```bash
python scripts/validate_configs.py
```

This validates all YAML configs against their JSON schemas in `config/schemas/`.

---

## Running the System

### Access Points

| Service     | URL                     | Auth                                 |
| ----------- | ----------------------- | ------------------------------------ |
| Dashboard   | `http://localhost:3000` | Session login                        |
| Gateway API | `http://localhost:8000` | `X-API-Key` header or session cookie |
| Prometheus  | `http://localhost:9090` | None (staging/prod only)             |
| Grafana     | `http://localhost:3001` | admin/admin (staging/prod only)      |

### Trigger an Agent Run

```bash
# Via API (requires operator role or API key)
curl -X POST -H "X-API-Key: $API_KEY" http://localhost:8000/run/briefing

# Agent names: briefing, announcements, sentiment, analyst, archivist, narrator
```

### Health Check

```bash
# System-wide health (aggregates all 8 services)
curl http://localhost:8000/health

# Scheduler state
curl -H "X-API-Key: $API_KEY" http://localhost:8000/scheduler/monitor/snapshot
```

### View Logs

```bash
docker compose logs -f gateway-service
docker compose logs -f scheduler-service
docker compose logs -f run-ledger-service
docker compose logs -f agent-a-service    # through agent-f-service
```

---

## Configuration

### YAML Config Files

| File                            | Purpose                                                               |
| ------------------------------- | --------------------------------------------------------------------- |
| `config/universe.yml`           | 50+ NSE-listed companies with ticker symbols and aliases              |
| `config/sources.yml`            | Agent B announcement sources with tier, timeout, retries, rate limits |
| `config/briefing_sources.yml`   | Agent A price/FX/index/news channels (~25 news sources)               |
| `config/sentiment_sources.yml`  | Agent C social/news sources with weights and auth requirements        |
| `config/announcement_types.yml` | 10 announcement categories with classifier keywords                   |
| `config/company_ir.yml`         | 20 company investor relations page URLs                               |
| `config/schedules.yml`          | Cron schedules (EAT and UTC) for all agents and ops tasks             |
| `config/agent_dependencies.yml` | Agent dependency DAG definition                                       |

### Runtime Settings

All runtime configuration is defined in `apps/core/config.py` as Pydantic settings, overridable via environment variables. Key groups:

- **Agent toggles**: `ENABLE_AGENT_A` through `ENABLE_AGENT_E`
- **LLM**: `LLM_MODE` (off/openai-compatible/ollama), model selection, API keys
- **Scraping**: timeouts, retries, circuit breaker thresholds, rate limits
- **Email**: provider selection, dry-run mode, recipient overrides
- **Per-agent**: dozens of agent-specific thresholds, budgets, and toggles

See `.env.example` for the complete variable reference (197 variables).

---

## Project Structure

```
fizz-oodle/
├── apps/
│   ├── agents/                      # Agent pipelines (A–F)
│   │   ├── briefing/                #   Agent A — prices, FX, news, market breadth
│   │   ├── announcements/           #   Agent B — disclosure classification + alerting
│   │   ├── sentiment/               #   Agent C — social/news sentiment scoring
│   │   ├── analyst/                 #   Agent D — convergence engine + synthesis
│   │   ├── archivist/               #   Agent E — pattern lifecycle management
│   │   └── narrator/                #   Agent F — narrative generation
│   ├── core/                        # Shared infrastructure
│   │   ├── config.py                #   Pydantic settings (all env vars)
│   │   ├── database.py              #   SQLAlchemy async engine + session
│   │   ├── events.py                #   Redis Streams pub/sub
│   │   ├── models/                  #   40+ SQLAlchemy ORM models
│   │   ├── run_service.py           #   start_run / finish_run / fail_run lifecycle
│   │   ├── data_quality.py          #   Cross-agent quality checks
│   │   ├── healing.py               #   Self-healing engine
│   │   ├── learning.py              #   Incident pattern analysis
│   │   ├── autonomy.py              #   Auto-apply policy gates
│   │   └── self_mod.py              #   Self-modification proposal engine
│   ├── api/routers/                 # 17 FastAPI router modules
│   ├── reporting/                   # Email digest builder + HTML renderers
│   └── scrape_core/                 # HTTP client, rate limiter, circuit breaker,
│                                    #   source health, dedup, retry classification
├── services/
│   ├── gateway/                     # API gateway — auth, proxy, WebSocket, orchestration
│   ├── scheduler/                   # Cron dispatcher — 10s tick loop
│   ├── run_ledger/                  # Execution ledger — event sourcing + reconciliation
│   ├── agent_a/ .. agent_f/        # Per-agent FastAPI service wrappers
│   └── common/                      # Shared: command listener, internal router, security, metrics
├── config/
│   ├── *.yml                        # Source, schedule, universe, dependency definitions
│   └── schemas/                     # JSON Schema validation for YAML configs
├── dashboard/                       # Next.js 14 operator console
│   └── src/
│       ├── app/(protected)/         #   10 authenticated pages
│       ├── widgets/                 #   9 dashboard widgets
│       ├── entities/                #   API fetcher modules per domain
│       ├── shared/                  #   UI components, layout, theming, utilities
│       └── features/                #   Auth, filters, monitoring, triggers
├── templates/                       # Jinja2 HTML email templates
├── tests/                           # ~60 test files (pytest + pytest-asyncio)
├── scripts/                         # DB init, config validation, backup, gate scripts
├── deploy/                          # Nginx, Prometheus, Grafana, Alertmanager configs
├── alembic/                         # 7 sequential database migrations
├── docker-compose.yml               # Development (12 services)
├── docker-compose.staging.yml       # Staging (+ Prometheus, Grafana, Nginx, certbot)
└── docker-compose.prod.yml          # Production
```

---

## Monitoring and Observability

### Prometheus Metrics

Every service exposes a `/metrics` endpoint scraped at 15-second intervals:

- `http_requests_total` — request count by service, method, path, status
- `http_request_duration_seconds` — latency histogram
- `run_events_total` — agent run completions by agent and status
- `stale_runs_reconciled_total` — stuck runs detected and failed
- `scheduler_dispatch_total` — schedule dispatches by key and status
- `email_validation_runs_total` — email validation tracking

### Alert Rules

Three alert groups fire to Telegram via Alertmanager:

| Group               | Alerts                                                                                                                                 |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| **Platform Health** | `ServiceDown` (2m), `DatabaseExporterDown` (3m), `RedisExporterDown` (3m)                                                              |
| **Run Windows**     | Per-agent expected frequency: Briefing (24h weekday), Announcements (3h), Sentiment (8d), Analyst (30h), Archivist (8d), Narrator (2h) |
| **Quality Signals** | `HighFailureRatio` (>40% over 6h), `HighPartialRatio` (>60% over 6h)                                                                   |

### Dashboard Monitoring

The Next.js dashboard provides real-time monitoring through:

- **Overview page** — system health, agent chain status, mission control
- **System ops page** — autonomy state, healing incidents, learning summary, swhats the best stack for this system. assume we are looking at the project and not the builders interest.lets say we are building this system. what technology stack is best for what part of the system

Great question. Let's be completely objective — best tool for each job, not familiarity.elf-mod proposals
- **Scheduler mission control** — dispatch heatmap, upcoming runs, timeline, impact metrics
- **Per-agent pages** — source health, data freshness, run history

### Structured Logging

All services emit structured JSON logs via `structlog` to stdout, collected by Docker's logging driver.

See [Troubleshooting](docs/troubleshooting.md) for debugging runbooks.

---

## Security

### Authentication

| Layer             | Method           | Details                                                         |
| ----------------- | ---------------- | --------------------------------------------------------------- |
| **Public API**    | API Key          | `X-API-Key` header, validated via `hmac.compare_digest`         |
| **Dashboard**     | Session cookie   | HMAC-signed token with expiry and role claims via `/auth/login` |
| **Inter-service** | Internal API Key | `X-Internal-Api-Key` header for service-to-service calls        |
| **WebSocket**     | Multi-method     | `X-API-Key` header, `api_key` query param, or session cookie    |

### Authorization (RBAC)

| Role       | Capabilities                                                                 |
| ---------- | ---------------------------------------------------------------------------- |
| `viewer`   | Read-only access to all dashboards and API data                              |
| `operator` | Viewer + trigger agent runs, retry failed runs                               |
| `admin`    | Operator + access admin endpoints, trigger self-mod, manage email validation |

### Network Security

- **Nginx** terminates TLS (1.2/1.3) with HSTS, X-Frame-Options DENY, nosniff headers
- **Rate limiting**: 15 req/s per IP with burst of 30
- `/metrics` endpoints restricted to internal networks only (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
- All internal service communication uses private Docker network

---

## Contributing

### Development Workflow

1. Create a feature branch: `feature/your-feature-name`
2. Validate configuration: `python scripts/validate_configs.py`
3. Run tests:
   ```bash
   pytest -q                          # Backend (219 tests)
   cd dashboard && npm run build      # Frontend type-check + build
   ```
4. Open a PR with:
   - Behavior summary and motivation
   - Risk assessment and rollback plan
   - Evidence (test output, logs, or screenshots)

### Branch Conventions

| Branch      | Purpose               |
| ----------- | --------------------- |
| `main`      | Production-ready      |
| `dev`       | Integration / staging |
| `feature/*` | New features          |
| `fix/*`     | Bug fixes             |
| `docs/*`    | Documentation changes |

### Commit Style

Use conventional, intent-first prefixes:

```
feat: add sitemap connector health scoring
fix: prevent duplicate announcement alert dispatch
docs: update deployment and scheduler runbook
chore: tighten .gitignore and cleanup build artifacts
```

See [Contributing](docs/contributing.md) for coding standards and testing guidance.

---

## Future Improvements

- **Source expansion** — add paid-tier market APIs with feature-flagged access
- **Lineage tracing** — end-to-end provenance from source item → alert → story paragraph
- **IR archive parsing** — improved deduplication and recency weighting for long company IR pages
- **Runbook automation** — richer self-healing actions beyond retry/breaker-reset/cache-clear
- **ML-based classification** — supplement rule-based announcement classification with trained models
- **Multi-exchange support** — extend universe beyond NSE to regional African exchanges
- **Real-time streaming** — WebSocket push for price updates and high-impact alerts to dashboard

---

## Documentation

| Document                                   | Description                                                                                       |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| [Architecture](docs/architecture.md)       | System design, service topology, database layout, event bus                                       |
| [Agents](docs/agents.md)                   | Deep documentation for all six agents including pipeline steps, models, config, and failure modes |
| [Scheduler](docs/scheduler.md)             | Schedule definitions, dispatch flow, overlap guards, manual triggers                              |
| [RunLedger](docs/runledger.md)             | Event sourcing, stale reconciliation, email validation, self-mod integration                      |
| [Scraping System](docs/scraping-system.md) | HTTP client, rate limiting, circuit breakers, source health, deduplication                        |
| [Data Flow](docs/data-flow.md)             | Inter-agent data contracts, per-agent schemas, signal flow                                        |
| [API Reference](docs/api.md)               | Complete REST and WebSocket endpoint catalog                                                      |
| [Dashboard UI](docs/ui.md)                 | Pages, widgets, theming, auth flow, entity fetchers                                               |
| [Deployment](docs/deployment.md)           | Docker Compose environments, Nginx, TLS, backups, staging/production                              |
| [Troubleshooting](docs/troubleshooting.md) | Debugging runbooks, common failures, log analysis                                                 |
| [Contributing](docs/contributing.md)       | Coding standards, testing process, PR expectations                                                |
