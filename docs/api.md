# API Reference

## Overview

All external access goes through the **gateway service** (port 8000), which proxies requests to internal microservices. The gateway handles authentication, rate limiting, and route multiplexing.

## Authentication

Three authentication mechanisms are supported:

### 1. API Key (Header)

Send `X-API-Key` header with every request. Validated via `hmac.compare_digest`. API key holders receive **admin** role access.

```bash
curl -H "X-API-Key: $API_KEY" https://host/briefings/latest
```

### 2. Session Cookie

Created via `POST /auth/login`. Returns an HMAC-signed JSON cookie containing `{sub, role, iat, exp}`. The cookie is sent automatically by browsers.

### 3. Internal API Key

For service-to-service calls only. Sent as `X-Internal-Api-Key` header. Separate from the public API key.

### Role Hierarchy

| Role | Level | Access |
|---|---|---|
| `admin` | 3 | Full access including system control |
| `operator` | 2 | Run triggers, rebuilds |
| `viewer` | 1 | Read-only data access |

API key holders automatically receive `admin` level. Session tokens carry a `role` claim set at login.

---

## Auth Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/auth/login` | None | Login with `{username, password}` returns session cookie |
| `POST` | `/auth/logout` | Session | Clear session cookie |
| `GET` | `/auth/me` | Session | Return current user info and role |

---

## Health

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | None | Aggregated health check across all services |

---

## Run Management

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/runs` | API key / session | List runs. Filters: `agent_name`, `status`, `limit` |
| `POST` | `/run/{agent}` | `operator` | Trigger an agent run (returns 202 Accepted) |

---

## Briefing (Agent A)

| Method | Path | Description |
|---|---|---|
| `GET` | `/briefings/latest` | Latest briefing summary |
| `GET` | `/briefings/daily` | Daily briefing data |
| `GET` | `/briefing/sources/health` | Source health for briefing feeds |
| `GET` | `/prices/daily` | Daily price data for all tracked tickers |
| `GET` | `/prices/{ticker}` | Price history for a specific ticker |
| `GET` | `/fx/daily` | Daily foreign exchange rates |
| `GET` | `/index/daily` | Daily market index data |
| `GET` | `/universe/summary` | Tracked company universe overview |
| `GET` | `/v1/prices/latest` | Legacy v1 price endpoint |

All briefing endpoints require API key or session authentication.

---

## Announcements (Agent B)

| Method | Path | Description |
|---|---|---|
| `GET` | `/announcements` | List announcements. Filters: type, ticker, date range |
| `GET` | `/announcements/stats` | Announcement counts and classification statistics |
| `GET` | `/announcements/{id}` | Single announcement detail |
| `GET` | `/announcements/{id}/insight` | AI-generated insight for an announcement |
| `POST` | `/announcements/{id}/context/refresh` | Re-generate context for an announcement |
| `GET` | `/sources/health` | Source health across all announcement sources |
| `GET` | `/v1/announcements/recent` | Legacy v1 recent announcements |

---

## Sentiment (Agent C)

| Method | Path | Description |
|---|---|---|
| `GET` | `/sentiment/weekly` | Weekly aggregated sentiment scores |
| `GET` | `/sentiment/weekly/{ticker}` | Weekly sentiment for a specific ticker |
| `GET` | `/sentiment/themes/weekly` | Weekly theme-level sentiment |
| `GET` | `/sentiment/raw` | Raw sentiment data points |
| `GET` | `/sentiment/sources/health` | Sentiment source health |
| `GET` | `/sentiment/digest/latest` | Latest sentiment digest summary |
| `GET` | `/sentiment/digest` | Sentiment digest list |
| `GET` | `/v1/sentiment/latest` | Legacy v1 sentiment endpoint |

---

## Analyst Reports (Agent D)

| Method | Path | Description |
|---|---|---|
| `GET` | `/reports/latest` | Latest analyst report |
| `GET` | `/reports` | List analyst reports |
| `GET` | `/reports/{report_id}` | Single report detail |
| `GET` | `/reports/{report_id}/inputs` | Input data used to generate a report |

---

## Patterns (Agent E)

| Method | Path | Description |
|---|---|---|
| `GET` | `/patterns` | List all tracked patterns |
| `GET` | `/patterns/active` | Currently active patterns |
| `GET` | `/patterns/summary` | Pattern summary statistics |
| `GET` | `/patterns/ticker/{ticker}` | Patterns for a specific ticker |
| `GET` | `/impacts/{announcement_type}` | Historical impact data by announcement type |
| `GET` | `/archive/latest` | Latest archivist archive |

---

## Stories (Agent F)

### Data Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/stories/latest` | API key | Latest story cards |
| `GET` | `/stories` | API key | List story cards |
| `GET` | `/stories/{card_id}` | API key | Single story card |
| `POST` | `/stories/rebuild` | `operator` | Force rebuild all story cards |

### Monitor Endpoints

Agent F exposes 8 monitor endpoints for operational visibility:

| Method | Path | Description |
|---|---|---|
| `GET` | `/stories/monitor/status` | Current narrator status and health |
| `GET` | `/stories/monitor/pipeline` | Pipeline execution state |
| `GET` | `/stories/monitor/requests` | Recent HTTP request log |
| `GET` | `/stories/monitor/scrapers` | Scraper status per source |
| `GET` | `/stories/monitor/events` | Recent event log |
| `GET` | `/stories/monitor/cycles` | Cycle history and timing |
| `GET` | `/stories/monitor/health` | Health check detail |
| `GET` | `/stories/monitor/snapshot` | Full monitor state snapshot |

---

## Scheduler Monitor & Control

### Monitor (read-only)

| Method | Path | Description |
|---|---|---|
| `GET` | `/scheduler/monitor/status` | Scheduler daemon status |
| `GET` | `/scheduler/monitor/active` | Currently executing runs |
| `GET` | `/scheduler/monitor/upcoming` | Next scheduled runs |
| `GET` | `/scheduler/monitor/history` | Recent run history |
| `GET` | `/scheduler/monitor/pipeline` | Pipeline state overview |
| `GET` | `/scheduler/monitor/email` | Email delivery status |
| `GET` | `/scheduler/monitor/events` | Recent scheduler events |
| `GET` | `/scheduler/monitor/heatmap` | Run timing heatmap data |
| `GET` | `/scheduler/monitor/impact` | Impact metrics |
| `GET` | `/scheduler/monitor/snapshot` | Full scheduler state snapshot |

### Control (write)

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/scheduler/control/dispatch/{schedule_key}` | `admin` | Force dispatch a schedule |
| `POST` | `/scheduler/control/retry/{run_id}` | `operator` | Retry a failed run |
| `POST` | `/scheduler/control/rebuild-narrator` | `admin` | Trigger narrator rebuild |

---

## Insights (Cross-Agent)

| Method | Path | Description |
|---|---|---|
| `GET` | `/insights/overview/latest` | Aggregated overview across all agents |
| `GET` | `/insights/ticker/{ticker}` | All intelligence for a specific ticker |
| `GET` | `/insights/quality/latest` | Data quality metrics |

---

## Admin

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/admin/reports` | `admin` | Reports management page (HTML) |
| `POST` | `/admin/reports/trigger` | `admin` | Trigger report generation |
| `POST` | `/admin/reports/resend` | `admin` | Resend a report email |
| `GET` | `/admin/ui` | `admin` | Admin UI page (HTML) |
| `GET` | `/admin/data-quality` | `admin` | Data quality dashboard |
| `POST` | `/admin/email-validation/run` | `admin` | Run email validation check |

---

## System Ops

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/email-validation/latest` | API key | Latest email validation results |
| `GET` | `/system/autonomy/state` | API key | Autonomy system state |
| `GET` | `/system/healing/incidents` | API key | Self-healing incident log |
| `GET` | `/system/learning/summary` | API key | Learning engine summary |
| `GET` | `/system/self-mod/state` | API key | Self-modification engine state |
| `GET` | `/system/self-mod/proposals` | API key | Pending self-mod proposals |
| `POST` | `/system/self-mod/generate` | `admin` | Generate new self-mod proposal |
| `POST` | `/system/self-mod/apply/{proposal_id}` | `admin` | Apply a self-mod proposal |

---

## Internal Endpoints

These are used for service-to-service communication and require the internal API key:

| Method | Path | Description |
|---|---|---|
| `POST` | `/internal/ops/email-validation/run` | Trigger email validation from scheduler |
| `GET` | `/internal/email/executive/latest` | Latest executive digest data |

---

## WebSocket Endpoints

### Narrator Monitor (`/stories/monitor/ws`)

Real-time monitor stream for the narrator service.

- **Auth:** API key (header or `api_key` query param) or session cookie
- **Protocol:** Sends JSON snapshots every 2 seconds
- **Heartbeat:** Ping every 15 seconds
- **Data:** Full narrator monitor state (pipeline, scrapers, events, cycles)

### Scheduler Monitor (`/scheduler/monitor/ws`)

Real-time monitor stream for the scheduler.

- **Auth:** Same as narrator WebSocket
- **Protocol:** Sends JSON snapshots every 2 seconds
- **Heartbeat:** Ping every 15 seconds
- **Data:** Active runs, upcoming schedule, recent events

### Connection Example

```javascript
const ws = new WebSocket("wss://host/stories/monitor/ws?api_key=KEY");
ws.onmessage = (event) => {
  const snapshot = JSON.parse(event.data);
  // Update UI with snapshot data
};
```

---

## Legacy Routers

The monolith-era router implementations remain at `apps/api/routers/` (17 files) but are superseded by the microservice gateway proxy. They are preserved for reference and backward compatibility under the `legacy` Docker Compose profile.

---

## Common Response Patterns

### Pagination

List endpoints accept `limit` and `offset` query parameters:

```
GET /announcements?limit=50&offset=100
```

### Error Responses

| Status | Meaning |
|---|---|
| `401` | Missing or invalid authentication |
| `403` | Insufficient role for the endpoint |
| `404` | Resource not found |
| `429` | Rate limited (via Nginx, 15 req/s per IP) |
| `502` | Upstream service unavailable |

### Rate Limiting

Nginx enforces 15 requests/second per IP with burst of 30 (nodelay). The `/metrics` path is restricted to private IP ranges only.
