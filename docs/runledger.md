# RunLedger

## Overview

The RunLedger service (`services/run_ledger/main.py`, port 8011, database `db_platform_ops`) is the central operational ledger for the platform. It consumes events from Redis Streams, persists the complete run lifecycle timeline, reconciles stale runs, tracks email validation, and exposes the scheduler monitor API surface.

RunLedger is the **single source of truth** for whether an agent run happened, when it happened, and what its outcome was.

## Core Responsibilities

### 1. Run Command Persistence

Consumes `RunCommandV1` messages from `commands.run.v1` stream:

- Upserts into `run_commands` table
- Creates timeline event: `run_command_queued`
- Links command to schedule key and trigger type

### 2. Run Event Persistence

Consumes `RunEventV1` messages from `runs.events.v1` stream:

- Upserts into `agent_runs` table
- Links lifecycle back to latest command for the run
- Creates timeline events: `run_running`, `run_success`, `run_partial`, `run_fail`
- Records metrics payload (records processed, errors, custom agent metrics)

### 3. Stale Run Reconciliation

A background loop checks for runs stuck in `running` status beyond per-agent TTLs:

| Agent | Stale TTL |
|---|---|
| Announcements (B) | 20 minutes |
| Briefing (A) | 30 minutes |
| Analyst (D) | 30 minutes |
| Narrator (F) | 30 minutes |
| Sentiment (C) | 45 minutes |
| Archivist (E) | 45 minutes |

When a stale run is detected:

1. Marks run as `fail` with `error_message=stale_run_timeout`
2. Sets `metrics.stale_reconciled=true`
3. Records a healing incident
4. Emits an `OpsHealingAppliedV1` system event
5. Creates timeline event: `run_stale_reconciled`

**Configuration**: `STALE_RUN_RECONCILER_ENABLED=True`, interval 60 seconds.

### 4. Email Validation Tracking

Tracks SMTP provider health through validation runs:

- `email_validation_runs` table: validation run records
- `email_validation_steps` table: per-step results within each validation
- Exposed via `GET /email-validation/latest` for dashboard display

### 5. Self-Modification Integration

Persists operational intelligence tables:

- `autonomy_state`: Current autonomy level and state
- `healing_incidents`: Recorded healing actions
- `learning_summaries`: Aggregated operational learnings
- `self_mod_proposals`: Proposed configuration changes
- `self_mod_actions`: Applied modification actions

## Streams Consumed

| Stream | Consumer Group | Purpose |
|---|---|---|
| `commands.run.v1` | `commands:ledger` | Run commands from scheduler/gateway |
| `runs.events.v1` | `runs:ledger` | Run lifecycle events from agent services |

## Background Tasks

RunLedger runs four background tasks during its FastAPI lifespan:

1. **Command consumer** - reads `commands.run.v1` stream, persists run commands
2. **Event consumer** - reads `runs.events.v1` stream, persists run events and timeline
3. **Stale reconciler** - checks for and resolves stuck runs (60-second interval)
4. **Self-mod loop** - background self-modification recomputation (900-second interval, when enabled)

## Database Tables

| Table | Purpose |
|---|---|
| `agent_runs` | Run execution records (status, timing, metrics) |
| `run_commands` | Dispatched command records (trigger type, schedule key) |
| `scheduler_dispatches` | Scheduler dispatch log entries |
| `scheduler_timeline_events` | Timeline of all scheduler/run events |
| `email_validation_runs` | Email validation run records |
| `email_validation_steps` | Per-step validation results |
| `healing_incidents` | Recorded healing actions (stale reconciliation, etc.) |
| `autonomy_state` | Current operational autonomy state |
| `learning_summaries` | Aggregated operational learnings |
| `self_mod_proposals` | Proposed configuration changes |
| `self_mod_actions` | Applied modification actions |

## Scheduler Monitor APIs

The RunLedger exposes the scheduler monitoring surface (proxied through gateway at `/scheduler/monitor/*`):

| Endpoint | Purpose |
|---|---|
| `/scheduler/monitor/status` | Current scheduler and run statuses |
| `/scheduler/monitor/active` | Currently running agents |
| `/scheduler/monitor/upcoming` | Next scheduled dispatches |
| `/scheduler/monitor/history` | Recent run history |
| `/scheduler/monitor/pipeline` | Pipeline health across all agents |
| `/scheduler/monitor/email` | Email delivery tracking |
| `/scheduler/monitor/events` | Recent timeline events |
| `/scheduler/monitor/heatmap` | Run frequency heatmap data |
| `/scheduler/monitor/impact` | Impact analysis of recent runs |
| `/scheduler/monitor/snapshot` | Complete operational snapshot (used by dashboard and WebSocket) |

## Retry Controls

Operators can retry failed runs:

- `POST /scheduler/control/retry/{run_id}` - publishes a new `RunCommandV1` with `trigger_type=retry`
- Retry commands are consumed by the original agent service and re-execute the pipeline

## Prometheus Metrics

RunLedger exposes standard HTTP metrics via `services/common/metrics.py`:

- `http_requests_total` - counter by service, method, path, status code
- `http_request_duration_seconds` - histogram of request latencies
- Available at `GET /metrics`

## Health Endpoint

- `GET /internal/health` - returns service health status (requires internal API key)

## Reliability Notes

- RunLedger uses SQLAlchemy async with `asyncpg` for non-blocking database operations
- Stream consumers use `XREADGROUP` with acknowledgement for at-least-once processing
- Consumer reconnection uses exponential backoff on Redis failures
- The stale reconciler is idempotent - marking an already-failed run as failed is a no-op
