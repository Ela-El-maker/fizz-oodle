# Deployment

## Overview

The platform runs as a Docker Compose stack with three environment tiers: **development**, **staging**, and **production**. All tiers share the same 10 core services, with staging and production adding infrastructure for TLS termination, monitoring, and alerting.

## Environment Comparison

| Aspect | Development | Staging | Production |
|---|---|---|---|
| Compose file | `docker-compose.yml` | `docker-compose.staging.yml` | `docker-compose.prod.yml` |
| Env file | `.env` | `.env.staging` | `.env.prod` |
| Images | Local `build: .` | Registry (`$APP_IMAGE`, `$FRONTEND_IMAGE`) | Registry (`$APP_IMAGE`, `$FRONTEND_IMAGE`) |
| Uvicorn | `--reload` | No reload | No reload |
| Exposed ports | All (5432, 6379, 8000-8006, 8010-8011, 3000) | 80, 443 only (via Nginx) | 80, 443 only (via Nginx) |
| Restart policy | None | `unless-stopped` | `unless-stopped` |
| Health checks | Postgres + Redis only | All services (20s interval) | All services (20s interval) |
| Monitoring | None (opt-in via `monitoring` profile) | Full stack | Full stack |
| TLS | None | Nginx + Certbot (Let's Encrypt) | Nginx + Certbot |
| Legacy services | Available via `legacy` profile | Not included | Not included |

## Core Services (All Environments)

| Service | Port | Database | Description |
|---|---|---|---|
| `postgres` | 5432 | - | PostgreSQL 16 with 7 databases |
| `redis` | 6379 | - | Redis 7 (streams + cache) |
| `gateway-service` | 8000 | - | API gateway, auth, proxy |
| `scheduler-service` | 8010 | `db_platform_ops` | Schedule evaluation and dispatch |
| `run-ledger-service` | 8011 | `db_platform_ops` | Run tracking and event persistence |
| `agent-a-service` | 8001 | `db_agent_a` | Briefing agent |
| `agent-b-service` | 8002 | `db_agent_b` | Announcements agent |
| `agent-c-service` | 8003 | `db_agent_c` | Sentiment agent |
| `agent-d-service` | 8004 | `db_agent_d` | Analyst agent |
| `agent-e-service` | 8005 | `db_agent_e` | Archivist agent |
| `agent-f-service` | 8006 | `db_agent_f` | Narrator agent |
| `frontend` | 3000 | - | Next.js dashboard |

## Infrastructure Services (Staging/Production)

| Service | Image | Port | Purpose |
|---|---|---|---|
| `nginx` | nginx:1.27-alpine | 80, 443 | TLS termination, rate limiting, reverse proxy |
| `certbot` | certbot/certbot:v2.11.0 | - | Let's Encrypt certificate auto-renewal |
| `prometheus` | prom/prometheus:v2.55.1 | 9090 | Metrics collection |
| `alertmanager` | prom/alertmanager:v0.27.0 | 9093 | Alert routing and notification |
| `grafana` | grafana/grafana:v11.1.4 | 3001 | Dashboards and visualization |
| `postgres-exporter` | prometheuscommunity/postgres-exporter:v0.16.0 | 9187 | PostgreSQL metrics |
| `redis-exporter` | oliver006/redis_exporter:v1.63.0 | 9121 | Redis metrics |

## Service Boot Sequence

Every backend service follows the same startup sequence:

```text
1. ensure_database.py       -- Create database if not exists (asyncpg)
2. reset_alembic_version.py -- Drop alembic_version table for clean migration
3. prune_service_tables.py  -- Drop tables not owned by this service
4. alembic upgrade head     -- Apply all migrations
5. uvicorn                  -- Start the ASGI server
```

This ensures database isolation and clean migration state on every deploy.

## Dockerfile

Single-stage build based on `python:3.11-slim`:

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y gcc libpq-dev curl
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
WORKDIR /app
ENV PYTHONPATH=/app
```

All backend services share the same image with different entrypoint commands via the compose file.

## Database Initialization

The `scripts/init-microservice-dbs.sql` script creates 7 isolated databases:

```sql
CREATE DATABASE db_agent_a;
CREATE DATABASE db_agent_b;
CREATE DATABASE db_agent_c;
CREATE DATABASE db_agent_d;
CREATE DATABASE db_agent_e;
CREATE DATABASE db_agent_f;
CREATE DATABASE db_platform_ops;
```

Each service connects to its own database via `DATABASE_URL` override in the compose file. The `ensure_database.py` script handles creation at runtime if the databases do not exist.

## Nginx Configuration

Located in `deploy/nginx/conf.d/gateway.conf`:

### Rate Limiting

```
limit_req_zone $binary_remote_addr zone=gateway:10m rate=15r/s;
limit_req zone=gateway burst=30 nodelay;
```

### TLS

- Protocols: TLS 1.2 and 1.3 only
- HSTS: `max-age=31536000; includeSubDomains`
- Security headers: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`
- Certificate auto-renewal via Certbot with webroot challenge

### Proxy Rules

| Path | Target | Notes |
|---|---|---|
| `/ui/*` | `frontend:3000/ui/*` | Dashboard UI |
| `/` | `gateway-service:8000` | API gateway (rate limited) |
| `/metrics` | `gateway-service:8000/metrics` | Restricted to private IPs |
| `/.well-known/acme-challenge/` | Certbot webroot | Certificate validation |

HTTP (port 80) redirects to HTTPS (port 443) with 301.

## Monitoring Stack

### Prometheus

- **Scrape interval:** 15 seconds
- **Evaluation interval:** 30 seconds
- **Targets:** All services (gateway, scheduler, run-ledger, agents A-F, postgres-exporter, redis-exporter)
- **Metrics path:** `/metrics` on each service

### Alert Rules

Three alert groups defined in `deploy/prometheus/alerts.yml`:

**Platform Health:**
| Alert | Condition | Duration | Severity |
|---|---|---|---|
| `ServiceDown` | Target unreachable | 2 minutes | critical |
| `DatabaseExporterDown` | Postgres exporter unreachable | 3 minutes | critical |
| `RedisExporterDown` | Redis exporter unreachable | 3 minutes | critical |

**Run Windows:**
| Alert | Condition | Duration |
|---|---|---|
| `BriefingRunMissingWeekday` | No briefing run in 24h (weekday) | 24h |
| `AnnouncementsRunMissing` | No announcements run in 3h | 3h |
| `SentimentRunMissingWeekly` | No sentiment run in 8 days | 8d |
| `AnalystRunMissing` | No analyst run in 30h | 30h |
| `ArchivistRunMissingWeekly` | No archivist run in 8 days | 8d |
| `NarratorRunMissing` | No narrator run in 2h | 2h |

**Quality Signals:**
| Alert | Condition | Duration |
|---|---|---|
| `HighFailureRatio` | >40% failures in 6h window | 15 minutes |

### Alertmanager

- **Routing:** Groups by `alertname`, `job`, `instance`, `agent_name`
- **Notification:** All alerts sent to Telegram via bot API
- **Receivers:** `telegram-critical`, `telegram-warning`, `telegram-info`
- **Group wait:** 30s | **Group interval:** 5m | **Repeat interval:** 2h

### Grafana

- **Datasource:** Prometheus (auto-provisioned)
- **Dashboard:** `stage7-overview.json` (auto-loaded, 30s refresh)
- **Auth:** Admin credentials via env vars, sign-up disabled

## Operational Scripts

| Script | Description |
|---|---|
| `backup_postgres.sh` | Full encrypted PostgreSQL dump with manifest |
| `backup_retention_prune.sh` | Prune backups older than retention period (default 30 days) |
| `backup_upload_s3.sh` | Upload backup to S3 bucket |
| `restore_postgres.sh` | Restore encrypted PostgreSQL backup |
| `restore_verify.sh` | Verify restore by checking API endpoints |
| `check_drift.py` | Validate codebase against canonical documentation |
| `collect_stage2_evidence.py` | Collect Stage 2 deployment evidence |
| `ensure_database.py` | Create PostgreSQL database if not exists |
| `init-microservice-dbs.sql` | SQL script for initial 7-database creation |
| `prune_service_tables.py` | Drop tables not owned by a service |
| `reset_alembic_version.py` | Reset migration tracking for clean redeploy |
| `run_autonomy_soak.py` | Long-running autonomy system soak test |
| `validate_configs.py` | YAML/JSON configuration contract validation |
| `verify_microservice_db_ownership.py` | Verify each database contains only expected tables |
| `stage4_gate.sh` | Stage 4 deployment evidence collection |
| `stage5_gate.sh` | Stage 5 deployment evidence collection |
| `stage6_gate.sh` | Stage 6 deployment evidence collection |
| `stage7_gate.sh` | Stage 7 staging deployment evidence |

## Environment Variables

Key environment variables (see `.env.example`):

| Variable | Purpose |
|---|---|
| `API_KEY` | Public API key for external access |
| `INTERNAL_API_KEY` | Service-to-service authentication |
| `OPERATOR_USERNAME` / `OPERATOR_PASSWORD` | Dashboard login credentials |
| `DATABASE_URL` | Base PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `EMAIL_PROVIDER` | Email provider: `sendgrid`, `smtp`, `none`, `auto` |
| `SENDGRID_API_KEY` | SendGrid API key |
| `EMAIL_RECIPIENTS` | Comma-separated recipient addresses |
| `NVIDIA_API_KEY` | NVIDIA NIM API key (optional) |
| `TELEGRAM_BOT_TOKEN` | Alertmanager Telegram bot token |
| `TELEGRAM_CHAT_ID` | Alertmanager Telegram chat ID |
| `SERVER_NAME` | Nginx server name for TLS certificate |

## Pre-Deploy Checklist

1. Run `python scripts/validate_configs.py` to verify config contracts
2. Run `pytest -q` to execute the test suite (225 tests)
3. Run `cd dashboard && npm run build` to verify frontend compiles
4. Verify `.env.staging` or `.env.prod` has all required variables
5. Verify Docker images are built and tagged
6. Review `docker compose config` for variable interpolation
