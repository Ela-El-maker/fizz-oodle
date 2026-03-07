# Data Flow

## Overview

Data moves through the platform in three planes: **collection** (external sources into agents A/B/C), **synthesis** (agents D/E/F reading upstream outputs), and **delivery** (email reports + dashboard APIs + WebSocket streams).

## End-to-End Pipeline

```text
External Sources
      |
      v
[A] Briefing ----+
[B] Announcements +----> [D] Analyst -----> [E] Archivist
[C] Sentiment ----+          |                    |
                             |  feedback loop <---+
                             |
                             +----> [F] Narrator ---> Dashboard
                                                       + Email
```

**Dependency rules:**
- A, B, C are **independent** — they run on their own schedules and have no upstream agent dependencies.
- D reads from A, B, and C databases plus archivist feedback (E).
- E reads from D reports, B announcements, and A prices.
- F reads latest outputs from A, B, C, and D via their APIs.

## Trigger Mechanism

All agent runs are triggered through the **Redis Streams command bus**:

```text
Scheduler tick (10s)
    |
    v
Evaluate cron expressions (Celery crontab parser)
    |
    v
Publish RunCommandV1 to "commands.run.v1" stream
    |
    v
Agent service consumes command from stream
    |
    v
Execute pipeline → publish RunEventV1 to "runs.events.v1"
    |
    v
Run Ledger consumes event → persists to DB
```

Manual triggers follow the same path: `POST /run/{agent}` publishes a `RunCommandV1` with `trigger_type: manual`.

## Redis Streams

Five streams form the event backbone:

| Stream | Publisher | Consumer | Purpose |
|---|---|---|---|
| `commands.run.v1` | Scheduler, Gateway (manual) | Agent services | Dispatch run commands |
| `runs.events.v1` | All agents | Run Ledger | Lifecycle events (running/success/partial/fail) |
| `analyst.report.generated.v1` | Agent D | Run Ledger, downstream | Report ready notification |
| `archivist.patterns.updated.v1` | Agent E | Run Ledger, downstream | Patterns updated notification |
| `system.events.v1` | Platform ops | Run Ledger | Self-healing actions |

All streams are capped at **maxlen 10,000** entries.

## Event Schemas

### RunCommandV1

Published to `commands.run.v1` when a run is dispatched:

| Field | Type | Description |
|---|---|---|
| `schema` | str | Schema version identifier |
| `command_id` | str | Unique command identifier |
| `run_id` | str | Run identifier (UUID) |
| `agent_name` | str | Target agent (briefing/announcements/sentiment/analyst/archivist/narrator) |
| `trigger_type` | str | `scheduled` or `manual` |
| `schedule_key` | str | Schedule key from `schedules.yml` |
| `requested_by` | str | Username or `scheduler` |
| `scheduled_for` | datetime | When the run was scheduled |
| `report_type` | str | `daily` or `weekly` (where applicable) |
| `run_type` | str | Run type qualifier |
| `period_key` | str | Date key (YYYY-MM-DD) |
| `force_send` | bool | Override email send conditions |
| `email_recipients_override` | str | Override default recipients |
| `requested_at` | datetime | Timestamp of command creation |

### RunEventV1

Published to `runs.events.v1` by agents during and after execution:

| Field | Type | Description |
|---|---|---|
| `schema` | str | Schema version |
| `run_id` | str | Matching run identifier |
| `agent_name` | str | Reporting agent |
| `status` | str | `running`, `success`, `partial`, `fail` |
| `started_at` | datetime | Pipeline start time |
| `finished_at` | datetime | Pipeline end time (null while running) |
| `metrics` | dict | Agent-specific metrics |
| `error_message` | str | Error details (on failure) |
| `records_processed` | int | Total records handled |
| `records_new` | int | New records persisted |
| `errors_count` | int | Non-fatal errors encountered |
| `event_at` | datetime | Event timestamp |

### AnalystReportGeneratedV1

Published to `analyst.report.generated.v1` when Agent D completes a report:

| Field | Type | Description |
|---|---|---|
| `report_id` | str | Report identifier |
| `report_type` | str | `daily` or `weekly` |
| `period_key` | str | Report date |
| `degraded` | bool | Whether report was generated with partial data |
| `generated_at` | datetime | Generation timestamp |

### ArchivistPatternsUpdatedV1

Published to `archivist.patterns.updated.v1` when Agent E updates patterns:

| Field | Type | Description |
|---|---|---|
| `run_type` | str | `weekly` or `monthly` |
| `period_key` | str | Period date |
| `patterns_upserted` | int | Count of patterns inserted/updated |
| `impacts_upserted` | int | Impact records updated |
| `accuracy_rows_upserted` | int | Accuracy tracking rows updated |
| `generated_at` | datetime | Timestamp |
| `degraded` | bool | Generated with partial inputs |

### OpsHealingAppliedV1

Published to `system.events.v1` when the self-healing engine acts:

| Field | Type | Description |
|---|---|---|
| `incident_id` | str | Incident identifier |
| `component` | str | Affected component |
| `failure_type` | str | Classified failure type |
| `action` | str | Remediation action taken |
| `result` | str | Action outcome |
| `auto_applied` | bool | Whether auto-applied or escalated |
| `escalated` | bool | Whether human intervention was requested |
| `occurred_at` | datetime | Timestamp |

## Collection Flows (Agents A, B, C)

### Agent A — Briefing Collection

```text
briefing_sources.yml → source registry
    |
    v
Per-source: fetch RSS/HTML/API → parse → normalize
    |
    v
Briefing items + prices + FX + index data → db_agent_a
    |
    v
Render briefing.html template → send email
```

### Agent B — Announcement Collection

```text
sources.yml → source registry (schema-validated)
    |
    v
Per-source: fetch by mode (rss/html/sitemap/official/api)
    |
    v
Classify announcement type → score Kenya impact
    |
    v
Lane assignment: kenya_core / kenya_extended / global_outside
    |
    v
Deduplicate (URL + SHA-256) → persist to db_agent_b
    |
    v
Render announcements.html template → send email
```

### Agent C — Sentiment Collection

```text
sentiment_sources.yml → source registry (schema-validated)
    |
    v
Per-source: fetch RSS/HTML/API (including social)
    |
    v
Extract ticker/company mentions → score sentiment
    |
    v
Aggregate weekly per-ticker scores → persist to db_agent_c
    |
    v
Weekly: render sentiment.html digest → send email
```

## Synthesis Flow (Agent D)

```text
Read from upstream agent databases:
  - Agent A: latest briefing data
  - Agent B: recent announcements
  - Agent C: sentiment scores
  - Agent E: archivist feedback (patterns, accuracy)
    |
    v
Convergence engine (deterministic, no LLM in critical path)
    |
    v
Optional LLM enhancement (NVIDIA API, off by default)
    |
    v
Generate analyst report → persist to db_agent_d
    |
    v
Publish AnalystReportGeneratedV1 event
    |
    v
Render analyst_report.html → send email
```

## Archival Flow (Agent E)

```text
Read from upstream:
  - Agent D: analyst reports
  - Agent B: announcements (for impact tracking)
  - Agent A: prices (for accuracy verification)
    |
    v
Extract patterns from reports → upsert pattern records
    |
    v
Track announcement impacts over time
    |
    v
Verify prediction accuracy against actual price movements
    |
    v
Persist to db_agent_e → publish ArchivistPatternsUpdatedV1
    |
    v
Render archivist_report.html → send email
```

## Narration Flow (Agent F)

```text
Read latest outputs via internal APIs:
  - Agent A: briefing data
  - Agent B: announcements
  - Agent C: sentiment
  - Agent D: analyst report
    |
    v
Generate story cards (HTML fragments) for dashboard
    |
    v
Cache with TTL → persist to db_agent_f
    |
    v
Serve via REST API + WebSocket stream to dashboard
```

Runs every 30 minutes. Cache prevents redundant regeneration.

## Lane Promotion Model

Announcements are assigned to geographic scope lanes:

```text
kenya_core          <-- Direct Kenya market (NSE, CMA, company IR)
    ^
    | promoted if kenya_impact_score >= 60
    |
kenya_extended      <-- Regional/contextual Kenya relevance
    ^
    | promoted if kenya_impact_score >= 60
    |
global_outside      <-- International events
```

**Score threshold:** `GLOBAL_OUTSIDE_KENYA_IMPACT_THRESHOLD` = `60` (configurable).
**Master switch:** `ENABLE_GLOBAL_OUTSIDE_SOURCES` = `True`.

Kenya impact scoring factors: ticker presence, company name match, Kenya keywords, theme relevance, content confidence, details length. Scores range 5–100.

## Email Delivery

Each agent that produces reports sends email via the shared email service (`apps/core/email_service.py`):

| Agent | Template | Frequency |
|---|---|---|
| A (Briefing) | `templates/briefing.html` | Weekdays |
| B (Announcements) | `templates/announcements.html` | Every 2 hours |
| C (Sentiment) | `templates/sentiment.html` | Weekly (Saturday) |
| D (Analyst) | `templates/analyst_report.html` | Weekdays |
| E (Archivist) | `templates/archivist_report.html` | Weekly/Monthly |
| Executive | `templates/executive_digest.html` | On demand |

**Provider selection:** SendGrid (if API key set) → SMTP (if host set) → `none`.
**Dry run mode:** `EMAIL_DRY_RUN=true` logs output without sending.
**Recipients:** Comma-separated `EMAIL_RECIPIENTS`, overridable per-run via `email_recipients_override`.

## Dashboard Delivery

The Next.js dashboard consumes data through two channels:

1. **REST API** — React Query polls endpoints via `/api/` proxy → gateway → agent services.
2. **WebSocket** — Real-time streams for narrator monitor (`/stories/monitor/ws`) and scheduler monitor (`/scheduler/monitor/ws`), pushing snapshots every 2 seconds with 15-second heartbeat.
