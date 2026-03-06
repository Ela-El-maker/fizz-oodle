# Scheduler

## What it does

The scheduler service (`services/scheduler/main.py`) is a cron orchestrator for agent and ops tasks.

- Loads schedules from `config/schedules.yml`
- Evaluates due jobs in a loop (default every 10s)
- Dispatches commands to Redis stream (`RunCommandV1`) or ops tasks via internal gateway endpoint
- Logs dispatch metadata to RunLedger

## Schedule source of truth

`config/schedules.yml` includes:

- `schedule_key`
- `task_name` (e.g., `agent_briefing.run`, `ops.email_validation.run`)
- `eat_cron`, `utc_cron`, `timezone`
- optional `task_kwargs`
- optional `enabled`

## Dispatch behavior

1. Compute `due` from UTC crontab expression.
2. For due schedules:
   - apply overlap guard per agent (`inflight` map, 15m TTL)
   - apply random jitter (`DISPATCH_JITTER_MAX_SECONDS`, default 30s)
   - dispatch task
3. Log dispatch outcome to RunLedger (`/internal/scheduler/dispatch-log`).

## Ops tasks

Supported ops task currently:

- `ops.email_validation.run`

Executed through gateway internal endpoint with internal API key.

## Internal endpoints

- `GET /internal/health`
- `GET /internal/state`
- `GET /internal/schedules`
- `POST /internal/dispatch/{schedule_key}`

## Reliability notes

- Scheduler itself does not run task logic; it only dispatches commands.
- Run status/timeout reconciliation is handled by RunLedger.
