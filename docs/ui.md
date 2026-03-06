# UI (Next.js Dashboard)

## Stack

- Next.js 14 app router (`dashboard/`)
- React Query for data polling/caching
- API proxy rewrite in `dashboard/next.config.mjs` from `/api/*` to gateway

## Layout

Shared shell:

- `AppShell` + `Sidebar` + `Topbar`
- auth gate for protected routes

Navigation (`dashboard/src/shared/config/nav.ts`):

- Overview
- Prices (A)
- News Intel
- Announcements (B)
- Sentiment (C)
- Analyst (D)
- Patterns (E)
- Agent F Monitor
- System Ops
- Email Validation

## Important pages

- `/(protected)/overview`: mission-control summary
- `/(protected)/prices`: Agent A metrics, coverage, movers
- `/(protected)/news`: blog/feed-style inside+outside feed with source links and Agent F brief
- `/(protected)/announcements`: lane-aware company signal table + insight panel
- `/(protected)/sentiment`: ticker/theme sentiment summaries
- `/(protected)/analyst`: report view from Agent D
- `/(protected)/patterns`: pattern lifecycle from Agent E
- `/(protected)/stories`: Agent F monitor telemetry
- `/(protected)/system`: scheduler/run/system ops views
- `/(protected)/email-validation`: validation outcomes

## Auth flow

- Login page posts credentials to `/api/auth/login`
- Gateway sets signed session cookie
- Protected pages query `/api/auth/me`

## Polling model

Pages use periodic refresh (e.g., 15s/30s intervals) to keep operations view live.

## Local dev note

If running dashboard outside Docker, set gateway URL to localhost; otherwise DNS name `gateway-service` will not resolve on host shell.
