# API Guide

## Gateway as primary API surface

The dashboard and operator tooling primarily call `gateway-service` (`services/gateway/main.py`).

Authentication methods:

- `X-API-Key` header
- session cookie from `/auth/login`

Internal service routes use `X-Internal-Api-Key` and are not for browser clients.

## Core endpoint groups

### Auth

- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/me`

### Run control

- `GET /runs`
- `POST /run/{agent}`

### Agent A (prices/briefing)

- `GET /briefings/latest`
- `GET /briefings/daily`
- `GET /briefing/sources/health`
- `GET /prices/daily`
- `GET /prices/{ticker}`
- `GET /universe/summary`
- `GET /fx/daily`
- `GET /index/daily`

### Agent B (announcements)

- `GET /announcements`
- `GET /announcements/stats`
- `GET /announcements/{announcement_id}`
- `GET /sources/health`

Filter highlights for `/announcements`:

- `scope`
- `theme`
- `kenya_impact_min`
- `global_only`

### Agent C (sentiment)

- `GET /sentiment/weekly`
- `GET /sentiment/weekly/{ticker}`
- `GET /sentiment/raw`
- `GET /sentiment/sources/health`
- `GET /sentiment/digest/latest`
- `GET /sentiment/themes/weekly`

### Agent D (analyst)

- `GET /reports/latest`
- `GET /reports`
- `GET /reports/{report_id}`
- `GET /reports/{report_id}/inputs`

### Agent E (patterns/archive)

- `GET /patterns`
- `GET /patterns/active`
- `GET /patterns/summary`
- `GET /patterns/ticker/{ticker}`
- `GET /impacts/{announcement_type}`
- `GET /archive/latest`

### Agent F (stories/insights)

- `GET /stories/latest`
- `GET /stories`
- `GET /stories/{card_id}`
- `POST /stories/rebuild`
- `GET /announcements/{announcement_id}/insight`
- `POST /announcements/{announcement_id}/context/refresh`

Monitor endpoints:

- `/stories/monitor/status|pipeline|requests|scrapers|events|cycles|health|snapshot`

### Scheduler monitor and control

- `GET /scheduler/monitor/*`
- `POST /scheduler/control/dispatch/{schedule_key}` (admin)
- `POST /scheduler/control/retry/{run_id}`

### System and quality

- `GET /health`
- `GET /insights/overview/latest`
- `GET /insights/ticker/{ticker}`
- `GET /insights/quality/latest`
- `GET /email-validation/latest`

## Compatibility endpoints

Legacy paths are preserved for compatibility:

- `/v1/prices/latest`
- `/v1/announcements/recent`
- `/v1/sentiment/latest`
