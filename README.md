# Market Intel Platform (fizz-oodle)

Production-style multi-agent market intelligence platform for **Kenya-first operations** with **global early-warning context**.

The system runs autonomous agents (A–F), schedules and tracks every run, ingests multi-source market data, computes derived intelligence, and serves an operator dashboard plus executive/alert emails.

## 1) Project Title

**Market Intel Platform (fizz-oodle)**

## 2) Project Overview

This project provides a full intelligence pipeline for operators who monitor:

- NSE prices and market breadth
- Company/regulatory disclosures
- Sentiment and theme momentum
- Analyst synthesis and pattern memory
- Narrative explainers (Agent F)

It exists to solve a practical operations problem: consolidate fragmented signals (official disclosures, Kenya business media, global macro/AI/oil feeds) into one consistent, explainable system with quality controls and run telemetry.

Primary users:

- Developers building ingestion, scoring, and UI features
- Operators running day-to-day market monitoring
- Product/stakeholder teams reviewing market narratives and alerts

## 3) Key Features

- Autonomous **A–F** agent chain with scheduled and manual runs
- Dual-lane intelligence model:
  - `kenya_core` (truth-first)
  - `global_outside` (context-first)
- Kenya-impact scoring and promotion gates (`>= 60` by default)
- Multi-source scraping/connectors (official, RSS, HTML listing, sitemap, API)
- Source health + circuit breakers + retries
- Run command/event bus via Redis Streams
- RunLedger service for lifecycle tracking, scheduler monitoring, retry control
- Operator dashboard (Next.js) with lane/theme/system views
- Email system:
  - Daily executive digest (A+B+C+F context)
  - High-impact alerts
  - Validation flows
- Ops/autonomy primitives (stale-run reconciler, healing incidents, self-mod proposal cycle)

## 4) System Architecture

```text
                 ┌─────────────────────────────┐
                 │         Scheduler           │
                 │   cron -> RunCommandV1     │
                 └──────────────┬──────────────┘
                                │ Redis Stream: commands.run.v1
                                v
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ Agent A      │   │ Agent B      │   │ Agent C      │   │ Agent D      │
│ Prices/Brief │   │ Announcements│   │ Sentiment    │   │ Analyst       │
└──────┬───────┘   └──────┬───────┘   └──────┬───────┘   └──────┬───────┘
       │                  │                  │                  │
       └──────────────────┴──────────────────┴──────────┬───────┘
                                                          v
                                                   ┌──────────────┐
                                                   │ Agent E      │
                                                   │ Patterns     │
                                                   └──────┬───────┘
                                                          v
                                                   ┌──────────────┐
                                                   │ Agent F      │
                                                   │ Narrator     │
                                                   └──────┬───────┘
                                                          │
                         ┌────────────────────────────────┴────────────────────────────────┐
                         │                             Gateway                             │
                         │ Auth, role checks, API proxy, monitor websockets, run trigger │
                         └────────────────────────────────┬────────────────────────────────┘
                                                          │
                                               ┌──────────┴──────────┐
                                               │ Next.js Dashboard   │
                                               │ + Email delivery    │
                                               └─────────────────────┘

Redis Streams:
- commands.run.v1         (RunCommandV1)
- runs.events.v1          (RunEventV1)
- analyst.report.generated.v1
- archivist.patterns.updated.v1

RunLedger service consumes command/event streams and persists run/scheduler/email-validation timelines.
```

See [Architecture](docs/architecture.md) for details.

## 5) Agents Overview

| Agent | Purpose | Inputs | Outputs |
|---|---|---|---|
| A (briefing) | Daily market state, coverage, movers, context headlines | prices/index/fx/news sources + universe | `daily_briefings`, `price_daily`, `index_daily`, `fx_daily`, `news_headline_daily`, executive digest |
| B (announcements) | Disclosure + news-signal normalization and alerting | NSE/IR/regulator/news/global sources | `announcements`, source health, high-impact alerts |
| C (sentiment) | Weekly ticker + theme sentiment | social/news/theme sources | `sentiment_raw_posts`, mentions, weekly aggregates, theme summary |
| D (analyst) | Synthesis of A+B+C + feedback | latest A/B/C + archivist feedback | `analyst_reports`, analyst event |
| E (archivist) | Pattern lifecycle and outcomes memory | D reports (or hybrid fallback) + A/B/C context | `patterns`, `impact_stats`, `archive_runs`, `accuracy_scores`, archivist event |
| F (narrator) | Human-readable explainers + monitor telemetry | A/B/C/D/E APIs + context fetch jobs | `insight_cards`, `evidence_packs`, story/announcement narratives |

Deep agent docs: [Agents](docs/agents.md)

## 6) Scheduler

- Scheduler service loads `config/schedules.yml`.
- Runs cron loop (~10s tick), computes due schedules in UTC.
- Dispatches:
  - Agent tasks as `RunCommandV1`
  - Ops tasks (email validation) via internal gateway endpoint
- Applies overlap guard per agent and jitter to avoid thundering herd.
- Logs every dispatch to RunLedger timeline.

See [Scheduler](docs/scheduler.md).

## 7) RunLedger

RunLedger is the execution system of record.

It tracks:

- queued commands
- run lifecycle events (`running/success/partial/fail`)
- scheduler dispatches/timeline
- retry actions
- email validation runs/steps
- autonomy/healing/learning/self-mod state

It also performs stale-run reconciliation and can emit healing events.

See [RunLedger](docs/runledger.md).

## 8) Data Flow

```text
Sources -> (A/B/C collectors + normalization + scoring)
       -> DB tables per service
       -> D synthesis -> E pattern memory -> F narratives
       -> Gateway APIs/WebSockets
       -> Dashboard + Email artifacts
```

Detailed flow: [Data Flow](docs/data-flow.md)

## 9) Installation Guide

### Prerequisites

- Docker + Docker Compose
- (Optional local UI dev) Node.js 20+
- Python 3.11 (for local scripts/tests)

### Setup

```bash
cp .env.example .env
```

Review at minimum:

- `OPERATOR_USERNAME`, `OPERATOR_PASSWORD`
- `API_KEY`, `INTERNAL_API_KEY`
- email provider settings (`EMAIL_PROVIDER`, SMTP/SendGrid)
- source flags (`ENABLE_GLOBAL_OUTSIDE_SOURCES`, etc.)

### Start full stack (containers)

```bash
docker compose up -d --build
```

This starts postgres, redis, gateway, scheduler, run-ledger, agents A–F, and frontend.

## 10) Running the System

### Access

- Dashboard: `http://localhost:3000`
- Gateway API: `http://localhost:8000`

### Manual run trigger

```bash
curl -X POST \
  -H "X-API-Key: ${API_KEY}" \
  http://localhost:8000/run/briefing
```

Agent names: `briefing`, `announcements`, `sentiment`, `analyst`, `archivist`, `narrator`.

### Health checks

```bash
curl http://localhost:8000/health
curl -H "X-API-Key: ${API_KEY}" http://localhost:8000/scheduler/monitor/snapshot
```

### Logs

```bash
docker compose logs -f gateway-service
docker compose logs -f scheduler-service
docker compose logs -f run-ledger-service
docker compose logs -f agent-b-service
```

## 11) Configuration

Primary config files:

- `config/sources.yml` (Agent B sources)
- `config/sentiment_sources.yml` (Agent C sources)
- `config/briefing_sources.yml` (Agent A channels/sources)
- `config/universe.yml` (tracked companies/tickers)
- `config/company_ir.yml` (company IR links)
- `config/schedules.yml` (cron schedules)
- `config/agent_dependencies.yml` (A→F dependency map)

Runtime settings live in `apps/core/config.py` and `.env`.

Validation:

```bash
python scripts/validate_configs.py
```

## 12) Project Structure

```text
apps/
  agents/                 # A–F pipelines, registries, connectors
  api/routers/            # shared FastAPI routers used by services
  core/                   # config, DB, events, models, run_service, ops engines
  reporting/              # digest builder/composer
  scrape_core/            # retry, breaker, sitemap, source health, dedupe
services/
  gateway/                # auth + proxy + orchestration endpoints
  scheduler/              # cron dispatcher
  run_ledger/             # run/event ledger + monitor APIs
  agent_a..agent_f/       # service wrappers per agent
config/
  *.yml + schemas/        # source/schedule/universe definitions + strict schemas
dashboard/                # Next.js operator console
templates/                # email/report HTML templates
tests/                    # unit + integration tests
scripts/                  # config validation, db init, gates, ops utilities
deploy/                   # prometheus/grafana/alertmanager/nginx manifests
```

## 13) Monitoring & Logs

- Application logs: structured JSON to stdout (container logs)
- Metrics: Prometheus endpoint on each service (`/metrics`)
- Scheduler monitor APIs: timeline, impact, upcoming, heatmap
- Narrator monitor APIs: status/pipeline/requests/scrapers/events/cycles/snapshot
- Source health tables + endpoints for A/B/C

Ops docs: [Troubleshooting](docs/troubleshooting.md)

## 14) Security

- Public gateway routes require either:
  - `X-API-Key`, or
  - signed session cookie from `/auth/login`
- Role-based route guard:
  - `viewer`, `operator`, `admin`
- Internal service routes require `X-Internal-Api-Key`.
- Session token is HMAC-signed (`apps/core/session_auth.py`) with exp/role claims.

## 15) Contributing Guide

1. Create branch and implement small, testable changes.
2. Validate configs: `python scripts/validate_configs.py`.
3. Run tests:
   ```bash
   pytest -q
   ```
4. For frontend changes:
   ```bash
   cd dashboard
   npm test
   npm run build
   ```
5. Open PR with behavior summary, risks, and rollback notes.

Additional guidance: [Contributing](docs/contributing.md)

## 16) Future Improvements

- Expand deterministic relevance filtering to further reduce `UNMAPPED` Kenya noise.
- Add more first-party market APIs with paid-source feature flags.
- Improve source-specific parsers for long IR archives (dedupe/recency weighting).
- Add stronger lineage tracing from source item -> alert -> story paragraph.
- Add richer runbook automation for self-healing actions.

## 17) Repository Standards

### Git workflow

- `main`: production-ready branch
- `dev`: integration/staging branch
- `feature/*`: scoped feature work
- `fix/*`: hotfix or bugfix work
- `docs/*`: documentation-only changes

### Commit guidelines

Use conventional, intent-first commit prefixes:

- `feat: add sitemap connector health scoring`
- `fix: prevent duplicate announcement alert dispatch`
- `docs: update deployment and scheduler runbook`
- `chore: tighten .gitignore and cleanup build artifacts`

### Pull request expectations

- Include summary, risk, and rollback notes.
- Include evidence for behavior changes (test output/logs/screenshots).
- Keep infra/config changes explicit and reviewed with security impact in mind.

---

## Full Documentation

- [Documentation Index](docs/README.md)
- [Architecture](docs/architecture.md)
- [Agents](docs/agents.md)
- [Scheduler](docs/scheduler.md)
- [RunLedger](docs/runledger.md)
- [Scraping System](docs/scraping-system.md)
- [Data Flow](docs/data-flow.md)
- [API Guide](docs/api.md)
- [UI Guide](docs/ui.md)
- [Deployment Guide](docs/deployment.md)
- [Troubleshooting](docs/troubleshooting.md)
