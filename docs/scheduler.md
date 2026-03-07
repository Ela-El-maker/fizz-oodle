# Scheduler

## Overview

The scheduler service (`services/scheduler/main.py`, port 8010) is the cron orchestrator for all agent and operational tasks. It evaluates a schedule table on a 10-second tick, dispatches commands to Redis Streams, and logs dispatch events to the RunLedger service.

The scheduler does **not** execute any agent logic. It only dispatches `RunCommandV1` messages that agent services consume independently.

## Schedule Source of Truth

All schedules are defined in `config/schedules.yml`:

```yaml
version: 1
timezone: Africa/Nairobi
schedules:
  - schedule_key: agent_a_daily_briefing
    task_name: agent_briefing.run
    eat_cron: "0 8 * * 1-5"
    utc_cron: "0 5 * * 1-5"
    # ...
```

### Active Schedules

| Schedule Key | Task Name | UTC Cron | EAT Cron | Description |
|---|---|---|---|---|
| `agent_a_daily_briefing` | `agent_briefing.run` | `0 5 * * 1-5` | `0 8 * * 1-5` | Weekday daily briefing 08:00 EAT |
| `agent_b_announcements_2h` | `agent_announcements.run` | `0 */2 * * 1-5` | `0 */2 * * 1-5` | Every 2 hours on weekdays |
| `agent_c_weekly_sentiment` | `agent_sentiment.run` | `0 4 * * 1` | `0 7 * * 1` | Monday 07:00 EAT |
| `agent_d_daily_analyst` | `agent_analyst.run` | `0 6 * * 1-5` | `0 9 * * 1-5` | Weekday daily analyst 09:00 EAT |
| `agent_d_weekly_analyst` | `agent_analyst.run` | `30 4 * * 1` | `30 7 * * 1` | Monday weekly analyst 07:30 EAT |
| `agent_e_weekly_archivist` | `agent_archivist.run` | `0 3 * * 1` | `0 6 * * 1` | Monday archivist 06:00 EAT |
| `agent_e_monthly_archivist` | `agent_archivist.run` | `0 4 1 * *` | `0 7 1 * *` | Monthly 1st 07:00 EAT |
| `agent_f_narrator_30m` | `agent_narrator.run` | `*/30 * * * *` | `*/30 * * * *` | Every 30 minutes |
| `agent_system_ping` | `agent_system.ping` | `* * * * *` | `* * * * *` | System heartbeat (every minute) |
| `ops_email_validation_daily` | `ops.email_validation.run` | `0 7 * * 1-5` | `0 10 * * 1-5` | Daily SMTP validation |
| `ops_email_validation_weekly` | `ops.email_validation.run` | `30 6 * * 1` | `30 9 * * 1` | Weekly SMTP validation |

### Schedule Fields

| Field | Required | Description |
|---|---|---|
| `schedule_key` | Yes | Unique identifier for the schedule |
| `task_name` | Yes | Dotted task name (`agent_briefing.run`, `ops.email_validation.run`) |
| `utc_cron` | Yes | Cron expression in UTC |
| `eat_cron` | No | Display-only EAT equivalent (documentation purpose) |
| `timezone` | No | Override timezone (defaults to `Africa/Nairobi`) |
| `task_kwargs` | No | Additional arguments passed to the command (e.g., `report_type: daily`) |
| `enabled` | No | Explicit enable/disable flag |

## Dispatch Loop

The scheduler runs an async loop (`_scheduler_loop`) inside the FastAPI lifespan:

```text
Every 10 seconds:
  1. Load schedules from config/schedules.yml
  2. For each schedule:
     a. Parse UTC cron expression (Celery crontab format, but Celery is NOT used)
     b. Check if schedule is due (current minute matches cron)
     c. Check overlap guard (is this agent already running?)
     d. If due and no overlap:
        - Apply random jitter (0 to DISPATCH_JITTER_MAX_SECONDS, default 30s)
        - Publish RunCommandV1 to Redis stream commands.run.v1
        - Log dispatch to RunLedger via /internal/scheduler/dispatch-log
```

### Cron Parsing

The scheduler uses Celery's `crontab` class for expression parsing, but does **not** use Celery for task execution. This is parse-only - the actual dispatch goes through Redis Streams.

### Overlap Guard

Each agent has an in-flight map tracked by the scheduler:

- When a command is dispatched, the agent is marked as in-flight
- In-flight status has a 15-minute TTL
- If the agent is still marked in-flight when the next tick evaluates, dispatch is skipped
- This prevents cascading duplicate runs when pipelines take longer than the schedule interval

### Jitter

Random jitter (0 to `DISPATCH_JITTER_MAX_SECONDS`, default 30 seconds) is applied before each dispatch. This prevents all agents from starting simultaneously when multiple schedules fire on the same minute.

## Ops Tasks

The scheduler also dispatches operational tasks:

| Task | Purpose | Dispatch Method |
|---|---|---|
| `ops.email_validation.run` | SMTP provider health check | HTTP POST to gateway internal endpoint |

Ops tasks are routed through the gateway's internal API rather than Redis Streams.

## Timezone Handling

- All cron expressions are evaluated in **UTC**
- The `eat_cron` field is provided for human readability (Africa/Nairobi = UTC+3)
- The system does **not** handle DST (East Africa Time does not observe daylight saving)

## Internal Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/internal/health` | GET | Scheduler health status |
| `/internal/state` | GET | Current scheduler state (in-flight agents, last tick) |
| `/internal/schedules` | GET | All loaded schedule definitions |
| `/internal/dispatch/{schedule_key}` | POST | Manual dispatch trigger (requires internal API key) |

## Manual Dispatch

Operators can trigger agent runs outside the schedule:

1. **Via Gateway** (recommended): `POST /scheduler/control/dispatch/{schedule_key}` (requires admin role)
2. **Via Gateway manual**: `POST /run/{agent}` (requires operator role, publishes RunCommandV1 directly)
3. **Via Scheduler internal**: `POST /internal/dispatch/{schedule_key}` (requires internal API key)

## Reliability Notes

- The scheduler is stateless between restarts. It re-evaluates all schedules on every tick.
- It does not persist dispatch history itself - that is the RunLedger's responsibility.
- If the scheduler crashes, no agent runs are affected (already-dispatched commands continue processing).
- The overlap guard resets on restart, which may cause a one-time duplicate dispatch. The RunLedger's stale reconciler handles this case.
