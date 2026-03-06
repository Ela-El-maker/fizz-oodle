# System Architecture

## Overview

The platform is a microservice system with shared libraries under `apps/` and service wrappers under `services/`.

Core runtime components:

- `gateway-service` (port 8000): auth, API proxy, operator control plane
- `scheduler-service` (port 8010): cron dispatcher
- `run-ledger-service` (port 8011): run/event ledger and scheduler monitor
- `agent-a-service`..`agent-f-service` (ports 8001..8006)
- `frontend` (Next.js, port 3000)
- `postgres`, `redis`

Legacy monolith (`api`, `worker`, `beat`) is retained behind Docker profile `legacy` for parity/fallback.

## Service Topology

```text
                 ┌──────────────────────────────────────────┐
                 │               Frontend (Next.js)         │
                 │  /api/* rewrite -> Gateway               │
                 └─────────────────────┬────────────────────┘
                                       │
                                       v
                        ┌────────────────────────────────┐
                        │          Gateway Service       │
                        │ auth + RBAC + route proxy     │
                        └───────────────┬────────────────┘
                                        │
                ┌───────────────────────┼─────────────────────────┐
                v                       v                         v
        ┌───────────────┐      ┌────────────────┐        ┌────────────────┐
        │ Scheduler     │      │ Run Ledger     │        │ Agents A..F    │
        │ cron dispatch │      │ runs + monitor │        │ data pipelines │
        └──────┬────────┘      └────────┬───────┘        └──────┬─────────┘
               │                        │                       │
               └────── Redis Streams ───┴──────── Redis Streams ┘

                              Postgres (service-scoped DBs)
```

## Data Ownership

Each service container uses its own DB (created by `scripts/init-microservice-dbs.sql` and migrated at boot):

- `db_agent_a`, `db_agent_b`, `db_agent_c`, `db_agent_d`, `db_agent_e`, `db_agent_f`
- `db_platform_ops` for run-ledger/scheduler timelines and ops records

This isolates agent writes and reduces cross-service migration coupling.

## Event Contracts

Event schemas are defined in `apps/core/event_schemas.py`:

- `RunCommandV1`
- `RunEventV1`
- `AnalystReportGeneratedV1`
- `ArchivistPatternsUpdatedV1`
- `OpsHealingAppliedV1`

Redis stream helpers are in `apps/core/events.py`.

## Request Planes

- **External/operator plane**: Gateway public routes, session/API-key auth.
- **Internal plane**: service-to-service `X-Internal-Api-Key` protected endpoints.

## Resilience Model

- Source-level circuit breaker and cooldown (`apps/scrape_core/breaker.py` + source health logic)
- Retry/backoff classification (`apps/scrape_core/retry.py`)
- Run reconciliation for stale `running` rows in RunLedger
- Partial/fail status propagation to UI and monitor endpoints
