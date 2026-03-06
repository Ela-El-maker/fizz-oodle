# Deployment Guide

## Local container deployment (recommended)

```bash
cp .env.example .env
docker compose up -d --build
```

Services expose:

- Frontend: `:3000`
- Gateway: `:8000`
- Scheduler: `:8010`
- RunLedger: `:8011`
- Agents A..F: `:8001..8006`
- Postgres: `:5432`
- Redis: `:6379`

## Service boot behavior

Agent and ledger containers run:

1. ensure database exists
2. reset/prune service tables where configured
3. run alembic migrations
4. start uvicorn service

See service `command` chains in `docker-compose.yml`.

## Production/staging assets

- `docker-compose.staging.yml`
- `docker-compose.prod.yml`
- `deploy/prometheus/*`
- `deploy/alertmanager/*`
- `deploy/grafana/*`
- `deploy/nginx/*`

## Legacy profile

Legacy monolith stack remains for fallback:

```bash
docker compose --profile legacy up -d api worker beat
```

## Environment management

Primary runtime config lives in `.env` and `apps/core/config.py`.

Key groups to set correctly:

- auth and API keys
- email provider credentials
- LLM and external APIs
- source/lane flags
- internal service URLs

## Pre-deploy checks

```bash
python scripts/validate_configs.py
pytest -q
```

## Operational checks

```bash
curl http://localhost:8000/health
curl -H "X-API-Key: <API_KEY>" http://localhost:8000/scheduler/monitor/snapshot
```
