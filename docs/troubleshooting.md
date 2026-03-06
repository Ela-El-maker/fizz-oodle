# Troubleshooting

## 1) Frontend shows proxy DNS errors (`ENOTFOUND gateway-service`)

### Symptom

Frontend started locally with `npm run dev`, logs show:

- `Failed to proxy http://gateway-service:8000/...`
- `getaddrinfo ENOTFOUND gateway-service`

### Cause

`gateway-service` is Docker network DNS and not resolvable from host Node process.

### Fix

Run dashboard in containers, or set local gateway URL for host dev:

```bash
cd dashboard
echo "GATEWAY_INTERNAL_URL=http://localhost:8000" > .env.local
```

## 2) Login fails with `Invalid credentials`

### Checks

- Confirm `.env` values:
  - `OPERATOR_USERNAME`
  - `OPERATOR_PASSWORD`
- Restart gateway after changing `.env`.
- Verify API call reaches gateway container you expect.

## 3) Dashboard cards show blanks (`-`)

### Common causes

- No recent runs for that agent
- Upstream services unavailable
- Source failures leading to partial data
- Query filters exclude current rows

### Actions

- Check `GET /health`
- Check latest runs: `GET /runs?limit=20`
- Trigger manual run for missing agent: `POST /run/{agent}`

## 4) Announcements noisy / too many old IR records

### Cause

Company IR pages can expose deep archives and generic headings.

### Actions

- Keep lane filter on `kenya_core` for operator default
- Tighten parser keywords/recency filters in source connectors
- Review dedupe rules and UI archive toggle behavior

## 5) Narrator frequently `partial`

### Cause

Agent F depends on multiple upstream APIs and optional LLM context.

### Actions

- Verify A–E recent runs are healthy
- Check `/stories/monitor/snapshot` for failing stage
- If LLM unavailable, ensure deterministic fallback still returns useful output

## 6) Scheduled jobs not firing

### Checks

- `GET /scheduler/monitor/status`
- `GET /scheduler/monitor/upcoming`
- verify `config/schedules.yml` syntax and enable flags
- ensure scheduler service healthy

## 7) Stale `running` runs in UI

RunLedger reconciler should mark stale runs failed by TTL.

- Check `STALE_RUN_RECONCILER_ENABLED=true`
- Check run-ledger logs
- Inspect latest run row metrics for `stale_reconciled=true`

## 8) Email not delivered

### Checks

- `EMAIL_PROVIDER` and credentials
- `EMAIL_DRY_RUN` not forcing no-send
- validation runs in `/email-validation/latest`
- daily/weekly validation schedules in `config/schedules.yml`

## 9) Config validation failures

Run:

```bash
python scripts/validate_configs.py
```

Typical failures:

- unknown fields in strict schemas
- duplicate `source_id`
- schedule task not present in interface contract

## 10) Debug sequence for production incidents

1. `GET /health`
2. `GET /scheduler/monitor/snapshot`
3. `GET /runs?limit=50`
4. source health endpoints for A/B/C
5. specific agent logs (`docker compose logs -f agent-*-service`)
