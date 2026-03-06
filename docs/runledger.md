# RunLedger

## Purpose

RunLedger (`services/run_ledger/main.py`) is the central run and timeline ledger.

It consumes run commands/events from Redis and stores operational truth for:

- run lifecycle
- scheduler dispatch history
- retry and timeline events
- email validation tracking
- autonomy/healing/self-mod state views

## Streams consumed

- `commands.run.v1` (`RunCommandV1`)
- `runs.events.v1` (`RunEventV1`)

Consumer groups:

- `commands:ledger`
- `runs:ledger`

## Core responsibilities

### 1) Persist run commands

- Upsert `run_commands`
- Create timeline event `run_command_queued`

### 2) Persist run events

- Upsert `agent_runs`
- Link lifecycle back to latest command for run
- Create timeline event `run_{status}`

### 3) Reconcile stale runs

Background loop checks `running` runs older than per-agent TTL and marks them failed with:

- `error_message=stale_run_timeout`
- `metrics.stale_reconciled=true`

Also records healing incidents and emits healing/system events.

### 4) Retry controls

- `POST /scheduler/control/retry/{run_id}`
- Internal retry endpoint for scheduler/automation

Retries publish a new `RunCommandV1` with `trigger_type=retry`.

### 5) Scheduler monitor APIs

Provides data for ops dashboard:

- `/scheduler/monitor/status`
- `/scheduler/monitor/active`
- `/scheduler/monitor/upcoming`
- `/scheduler/monitor/history`
- `/scheduler/monitor/pipeline`
- `/scheduler/monitor/email`
- `/scheduler/monitor/events`
- `/scheduler/monitor/heatmap`
- `/scheduler/monitor/impact`
- `/scheduler/monitor/snapshot`

### 6) Email validation lifecycle

Tracks validation runs and per-agent steps via internal endpoints and exposes latest status for dashboard.

## Key tables

- `agent_runs`
- `run_commands`
- `scheduler_dispatches`
- `scheduler_timeline_events`
- `email_validation_runs`
- `email_validation_steps`
- `healing_incidents`, `autonomy_states`, `learning_summaries`, self-mod tables

## Health endpoint

- `GET /internal/health`
