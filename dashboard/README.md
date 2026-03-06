# Market Intel Dashboard (`dashboard/`)

Operator UI for the Market Intel Platform, built with **Next.js 14** and wired to the **gateway service**.

## What this app does

- Presents live operations views for Agents **A–F**
- Displays Kenya Core + Global Outside intelligence lanes
- Provides run monitoring, scheduler visibility, and email validation pages
- Uses gateway session auth for protected routes

## Runtime architecture

- Frontend routes are served from `/`
- API calls use `/api/*` and are rewritten to gateway in [`next.config.mjs`](./next.config.mjs)
- Auth endpoints proxied through gateway:
  - `/api/auth/login`
  - `/api/auth/me`
  - `/api/auth/logout`

Gateway target resolution order:
1. `GATEWAY_INTERNAL_URL`
2. `NEXT_PUBLIC_GATEWAY_URL`
3. fallback: `http://gateway-service:8000`

## Prerequisites

- Node.js 20+ (recommended)
- Running gateway service (`services/gateway`) reachable from frontend runtime

## Environment setup

Use template:

```bash
cp .env.example .env.local
```

### Host-based frontend dev (outside Docker)

Set gateway to localhost:

```bash
NEXT_PUBLIC_GATEWAY_URL=http://localhost:8000
```

### Dockerized frontend (inside Compose network)

Set gateway to service DNS:

```bash
GATEWAY_INTERNAL_URL=http://gateway-service:8000
```

## Local development

```bash
cd dashboard
npm install
npm run dev
```

Open: `http://localhost:3000`

## Build and run

```bash
npm run lint
npm run build
npm run start
```

## NPM scripts

- `npm run dev` -> start Next.js dev server
- `npm run build` -> production build
- `npm run start` -> run production build
- `npm run lint` -> lint checks

## Routes (current)

Public:
- `/auth/login`

Protected:
- `/` (Overview / Mission Control)
- `/prices` (Agent A)
- `/news` (News Intel feed)
- `/announcements` (Agent B)
- `/sentiment` (Agent C)
- `/analyst` (Agent D)
- `/patterns` (Agent E)
- `/stories` (Agent F monitor)
- `/system` (System Ops + scheduler monitor)
- `/email-validation`

## Common issue

If you see `ENOTFOUND gateway-service` while running `npm run dev` on host:

- you are using Docker DNS outside Docker.
- set `NEXT_PUBLIC_GATEWAY_URL=http://localhost:8000` in `.env.local`.
