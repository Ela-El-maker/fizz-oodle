# Troubleshooting

## 1. Service Won't Start / Proxy DNS Errors

**Symptom:** Gateway logs show `httpx.ConnectError` or DNS resolution failures when proxying to agent services.

**Causes & Fixes:**

| Cause | Fix |
|---|---|
| Service container not running | `docker compose ps` to check, `docker compose up -d agent-x-service` to start |
| Database not created | Check `ensure_database.py` output in logs. Run `docker compose exec postgres psql -U postgres -c "\l"` to verify databases exist |
| Migration failure | Check `alembic upgrade` output. Run `docker compose exec agent-x-service alembic upgrade head` manually |
| Port conflict | Verify no other process on ports 8000-8006, 8010-8011 |

**Debug commands:**
```bash
docker compose logs agent-a-service --tail=50
docker compose exec gateway-service curl http://agent-a-service:8001/health
```

## 2. Login Fails / 401 on Protected Endpoints

**Symptom:** Dashboard shows login error or API calls return 401.

**Causes & Fixes:**

| Cause | Fix |
|---|---|
| Wrong credentials | Verify `OPERATOR_USERNAME` and `OPERATOR_PASSWORD` in `.env` |
| Session cookie expired | Log out and log in again. Session expiry is controlled by `SESSION_EXPIRY_HOURS` |
| API key mismatch | Verify `API_KEY` in `.env` matches the header value |
| Cookie domain mismatch | Ensure `SESSION_COOKIE_DOMAIN` matches request origin |
| HTTPS/HTTP mismatch | If using HTTPS, ensure `SESSION_COOKIE_SECURE=true` |

**Debug:**
```bash
# Test API key auth
curl -H "X-API-Key: $API_KEY" http://localhost:8000/health

# Test session auth
curl -c cookies.txt -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"operator","password":"password"}'
curl -b cookies.txt http://localhost:8000/auth/me
```

## 3. Dashboard Shows Blank Cards / No Data

**Symptom:** Page loads but widgets show empty state or "No data available."

**Causes & Fixes:**

| Cause | Fix |
|---|---|
| Agent hasn't run yet | Trigger a manual run: `POST /run/{agent}` or use the dashboard trigger button |
| Gateway proxy down | Check `docker compose logs gateway-service` for upstream errors |
| Frontend proxy misconfigured | Verify `NEXT_PUBLIC_GATEWAY_URL` or `GATEWAY_INTERNAL_URL` is set correctly |
| Database empty | Agent ran but collected no data. Check run logs for errors |
| React Query stale | Hard refresh the browser (Ctrl+Shift+R) |

**Debug:**
```bash
# Check if data exists
curl -H "X-API-Key: $API_KEY" http://localhost:8000/briefings/latest
curl -H "X-API-Key: $API_KEY" http://localhost:8000/runs?limit=5
```

## 4. Noisy IR / Duplicate Announcements

**Symptom:** Announcement feed shows too many low-quality or duplicate items.

**Causes & Fixes:**

| Cause | Fix |
|---|---|
| Deduplication not catching all variants | Check content fingerprinting in scrape_core logs |
| Source misconfigured | Review `config/sources.yml` for the noisy source |
| Global sources too broad | Raise `GLOBAL_OUTSIDE_KENYA_IMPACT_THRESHOLD` (default 60) or disable `ENABLE_GLOBAL_OUTSIDE_SOURCES` |
| Source health degraded | Check `/sources/health` endpoint for failing sources |

**Tune:**
```yaml
# In .env or docker compose environment
GLOBAL_OUTSIDE_KENYA_IMPACT_THRESHOLD=70  # Raise threshold
ENABLE_GLOBAL_EXTRAS_PACK=false           # Disable extra sources
```

## 5. Narrator / Agent F Shows Partial or Stale Stories

**Symptom:** Story cards are outdated, missing, or show incomplete data.

**Causes & Fixes:**

| Cause | Fix |
|---|---|
| Upstream agents haven't run | Check `/runs` for recent A/B/C/D completions |
| Cache TTL not expired | Force rebuild: `POST /stories/rebuild` |
| Narrator run failed | Check `/stories/monitor/status` and container logs |
| Internal API unreachable | Verify agent services are healthy: `GET /health` |

**Monitor endpoints:**
```bash
curl -H "X-API-Key: $API_KEY" http://localhost:8000/stories/monitor/status
curl -H "X-API-Key: $API_KEY" http://localhost:8000/stories/monitor/pipeline
```

## 6. Schedule Misfire / Agent Didn't Run on Time

**Symptom:** Expected scheduled run did not execute.

**Causes & Fixes:**

| Cause | Fix |
|---|---|
| Scheduler service down | `docker compose ps scheduler-service` |
| Overlap guard blocked the run | Previous run still within 15-minute TTL. Check `/scheduler/monitor/active` |
| Cron expression wrong | Review `config/schedules.yml`. All times are UTC (EAT = UTC+3) |
| Redis connection lost | Check Redis connectivity: `docker compose exec redis redis-cli ping` |
| Schedule disabled | Verify the schedule key is present in `schedules.yml` |

**Debug:**
```bash
curl -H "X-API-Key: $API_KEY" http://localhost:8000/scheduler/monitor/status
curl -H "X-API-Key: $API_KEY" http://localhost:8000/scheduler/monitor/upcoming

# Force dispatch a schedule
curl -X POST -H "X-API-Key: $API_KEY" \
  http://localhost:8000/scheduler/control/dispatch/briefing_daily
```

## 7. Stale Runs Stuck in "running" Status

**Symptom:** Runs appear permanently in `running` status in the run history.

**Causes & Fixes:**

| Cause | Fix |
|---|---|
| Agent crashed mid-run | The stale reconciler in run-ledger will auto-mark runs older than the agent TTL as `stale` |
| Reconciler not running | Check run-ledger logs for `reconcile_stale_runs` task execution |
| TTL too long | Review per-agent stale TTLs (Briefing: 30m, Announcements: 45m, etc.) |

**Agent Stale TTLs:**

| Agent | Default TTL |
|---|---|
| Briefing (A) | 30 minutes |
| Announcements (B) | 45 minutes |
| Sentiment (C) | 60 minutes |
| Analyst (D) | 90 minutes |
| Archivist (E) | 120 minutes |
| Narrator (F) | 30 minutes |

The reconciler runs every 5 minutes in the run-ledger background tasks.

## 8. Email Not Delivered

**Symptom:** Agents report success but no email arrives.

**Causes & Fixes:**

| Cause | Fix |
|---|---|
| `EMAIL_DRY_RUN=true` | Set `EMAIL_DRY_RUN=false` in `.env` |
| `EMAIL_PROVIDER=none` | Set to `sendgrid`, `smtp`, or `auto` |
| SendGrid API key invalid | Verify `SENDGRID_API_KEY` |
| SMTP credentials wrong | Verify `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` |
| No recipients configured | Set `EMAIL_RECIPIENTS` in `.env` |
| Email send after run turned off | Check agent-specific `*_SEND_EMAIL` flags |

**Debug:**
```bash
# Check email validation results
curl -H "X-API-Key: $API_KEY" http://localhost:8000/email-validation/latest

# Trigger email validation
curl -X POST -H "X-API-Key: $API_KEY" http://localhost:8000/admin/email-validation/run
```

## 9. Config Validation Errors

**Symptom:** `validate_configs.py` reports schema errors or missing fields.

**Causes & Fixes:**

| Cause | Fix |
|---|---|
| Missing required field | Add the field to the YAML config per schema requirements |
| Unknown field in strict schema | Sources with `additionalProperties: false` reject extra fields. Remove the field or update the schema |
| Invalid source_id format | Ensure `source_id` is unique and follows naming conventions |
| Duplicate source_id | Each source must have a unique identifier |

**Run validation:**
```bash
python scripts/validate_configs.py
```

This checks: `config/sources.yml`, `config/briefing_sources.yml`, `config/sentiment_sources.yml`, `config/schedules.yml`, `config/universe.yml`, `config/announcement_types.yml`.

## 10. Production Incident Debug Sequence

When something goes wrong in production, follow this diagnostic flow:

```text
1. Check service health
   GET /health --> aggregated status of all services

2. Check Prometheus alerts
   Grafana dashboard or Alertmanager UI

3. Check recent runs
   GET /runs?limit=20 --> look for failures

4. Check specific agent
   GET /stories/monitor/status (for Agent F)
   GET /scheduler/monitor/status (for scheduler)
   docker compose logs {service} --tail=100

5. Check infrastructure
   docker compose exec postgres pg_isready
   docker compose exec redis redis-cli ping

6. Check self-healing
   GET /system/healing/incidents --> auto-remediation log

7. Check source health
   GET /sources/health
   GET /briefing/sources/health
   GET /sentiment/sources/health

8. Review metrics
   Prometheus: rate(http_requests_total[5m])
   Prometheus: run_duration_seconds{agent="..."}
```

## 11. Circuit Breaker Tripped

**Symptom:** Source consistently returns no data, source health shows 0%.

**Fix:**

1. Check source health: `GET /sources/health`
2. Wait for cooldown (`SOURCE_CIRCUIT_BREAKER_COOLDOWN_MINUTES`, default 60 minutes)
3. If urgent, restart the agent service to reset circuit breaker state
4. Investigate the root cause (DNS change, site redesign, auth change)

## 12. Database Migration Conflicts

**Symptom:** Alembic reports version conflicts or "target database is not up to date."

**Fix:**

```bash
# Check current alembic version
docker compose exec agent-x-service alembic current

# Reset and reapply (service startup does this automatically)
docker compose exec agent-x-service python scripts/reset_alembic_version.py
docker compose exec agent-x-service alembic upgrade head

# Verify table ownership
python scripts/verify_microservice_db_ownership.py
```

## Common Log Locations

| Service | How to Access |
|---|---|
| Any service | `docker compose logs {service-name} --tail=100 -f` |
| All services | `docker compose logs --tail=50 -f` |
| Nginx access | `docker compose logs nginx --tail=100` |
| Prometheus alerts | Grafana UI or `http://host:9090/alerts` |
| Alertmanager | `http://host:9093/#/alerts` |
