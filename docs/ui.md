# Dashboard UI

## Overview

The dashboard is a **Next.js 14** application using the App Router, TypeScript, and Tailwind CSS. It provides a real-time operational interface for monitoring all six agents, viewing market intelligence, and managing system operations.

## Technology Stack

| Layer | Technology | Version |
|---|---|---|
| Framework | Next.js (App Router) | 14.2.23 |
| Language | TypeScript | ^5.6.3 |
| Styling | Tailwind CSS | ^3.4.15 |
| Server State | React Query (@tanstack/react-query) | ^5.59.0 |
| Client State | Zustand | ^5.0.1 |
| Theming | next-themes | ^0.4.6 |
| Forms | react-hook-form + Zod | ^7.53.2 / ^3.23.8 |
| Icons | lucide-react | ^0.462.0 |
| Utilities | clsx, tailwind-merge | ^2.1.1 / ^2.5.5 |

## Pages

| Route | Page | Agent | Description |
|---|---|---|---|
| `/auth/login` | Login | - | Operator authentication form |
| `/` | Overview | All | Mission overview with ops console tabs |
| `/prices` | Prices | A | Equity prices, FX rates, index data |
| `/news` | News Intel | A | Briefing news intelligence |
| `/announcements` | Announcements | B | Announcement feed with classification |
| `/sentiment` | Sentiment | C | Sentiment dashboard and digest |
| `/analyst` | Analyst | D | Analyst reports and inputs |
| `/patterns` | Patterns | E | Pattern tracking and accuracy |
| `/stories` | Agent F Monitor | F | Story cards and narrator monitor |
| `/system` | System Ops | Ops | Health, healing, self-mod, learning |
| `/email-validation` | Email Validation | Ops | Email delivery validation results |

All pages except `/auth/login` are protected by the `AuthGate` component.

## Authentication Flow

```text
Browser loads protected page
    |
    v
AuthGate calls GET /api/auth/me
    |
    +-- 401 --> Redirect to /auth/login
    |
    +-- 200 --> Render page content
```

**Login process:**

1. User submits `{username, password}` to `POST /api/auth/login`
2. Gateway validates credentials against `OPERATOR_USERNAME` / `OPERATOR_PASSWORD`
3. On success, gateway sets HMAC-signed session cookie (`{sub, role, iat, exp}`)
4. Browser redirects to `/` with cookie set
5. All subsequent API calls include cookie via `credentials: "include"`

## API Communication

### Proxy Layer

The dashboard never calls backend services directly. All API traffic is proxied:

```text
Browser --> /api/* --> Next.js rewrite --> gateway-service:8000/*
```

Configured in `next.config.mjs`:
```javascript
rewrites: [{ source: "/api/:path*", destination: "${GATEWAY_URL}/:path*" }]
```

Gateway URL resolved from: `GATEWAY_INTERNAL_URL` || `NEXT_PUBLIC_GATEWAY_URL` || `http://gateway-service:8000`.

### HTTP Client

The shared HTTP client (`shared/lib/http.ts`) provides:

- Automatic credential inclusion (session cookie)
- JSON content type
- Retry logic: up to 2 retries with 300ms * attempt backoff on retryable status codes
- Exported as `http.get()` and `http.post()`

### React Query Configuration

- **Retry:** 1 attempt
- **Refetch on window focus:** Disabled
- All server state managed through React Query hooks per page/widget

## Layout & Navigation

### AppShell

The application layout consists of:

- **Sidebar** (288px fixed on desktop, drawer on mobile)
- **Topbar** with hamburger menu toggle
- **Content area** with max-width 1320px

### Navigation Items

10 sidebar items with lucide-react icons:

| Label | Icon | Route |
|---|---|---|
| Home | Home | `/` |
| Prices | LineChart | `/prices` |
| News Intel | Globe2 | `/news` |
| Announcements | Newspaper | `/announcements` |
| Sentiment | Bell | `/sentiment` |
| Analyst | Brain | `/analyst` |
| Patterns | BarChart3 | `/patterns` |
| Agent F Monitor | ScrollText | `/stories` |
| System | Activity | `/system` |
| Email Validation | MailCheck | `/email-validation` |

### Responsive Design

- **Desktop (>=1024px):** Fixed sidebar, full content area
- **Tablet/Mobile (<1024px):** Sidebar becomes a slide-in drawer, hamburger menu in topbar
- Sidebar state managed via Zustand store (`sidebarOpen`)

## Theming

### Color System

The dashboard uses CSS custom properties mapped to Tailwind tokens, supporting light and dark modes via `next-themes` (attribute-based class toggling, default: `dark`).

**19 semantic color tokens:**

| Token | Light | Dark |
|---|---|---|
| `surface` | White base | `#020817` (slate-950) |
| `elevated` | Slightly raised | `#0a1628` |
| `inset` | Recessed area | `#020817` |
| `ink` | Primary text | `#f8fafc` |
| `ink-soft` | Secondary text | Slate-300 |
| `muted` | Tertiary text | Slate-400 |
| `ink-faint` | Quaternary text | Slate-500 |
| `line` | Borders/dividers | Slate-700 |
| `panel` | Card backgrounds | `#061226` |
| `panel-border` | Card borders | Slate-700 |
| `panel-soft` | Subtle panels | `#0a1628` |
| `hover` | Hover states | Slate-800 |
| `sidebar-bg` | Navigation background | `#020817` |
| `topbar-bg` | Top bar background | `#020817` |
| `brand` | Primary brand color | `#00d084` (green) |
| `accent` | Accent highlights | `#34d399` (emerald) |
| `success` | Success states | `#22c55e` |
| `warning` | Warning states | `#f59e0b` |
| `danger` | Error/danger states | `#ef4444` |

### Tailwind Configuration

Extended `borderRadius`: `lg` = 12px, `xl` = 16px.
All semantic tokens available as `bg-[var(--surface)]`, `text-[var(--ink)]`, etc.

## Widgets

9 reusable widget components in `dashboard/src/widgets/`:

| Widget | Description |
|---|---|
| `announcements-feed` | Recent announcement stream with classification badges |
| `chain-health` | Agent pipeline chain health visualization |
| `health-overview` | System-wide health dashboard |
| `ops-console` | Operational console with tabs for runs, events, logs |
| `pattern-summary` | Pattern tracking summary cards |
| `report-status` | Report generation status indicators |
| `runs-table` | Run history table with status, duration, metrics |
| `scheduler-mission-control` | Schedule overview with heatmap and upcoming |
| `sentiment-snapshot` | Sentiment score snapshot with ticker breakdown |

## Features

9 feature modules in `dashboard/src/features/`:

| Feature | Description |
|---|---|
| `auth` | AuthGate, login form, session management |
| `email-validation` | Email validation results display |
| `filters` | Shared filter components (date range, ticker, type) |
| `health` | Health check display and status indicators |
| `market-story` | Story card rendering and display |
| `monitor` | Real-time monitor panels (WebSocket-driven) |
| `run-monitor` | Run lifecycle monitoring |
| `scheduler` | Schedule visualization and control |
| `trigger-agent` | Manual agent run trigger UI |

## Shared Components

Common components in `dashboard/src/shared/`:

- **`ui/`** - Base components: Panel, StatCard, Badge, Button, Tabs, Modal
- **`layout/`** - AppShell, Sidebar, Topbar, ContentWrapper
- **`lib/`** - HTTP client, UI store, utilities
- **`config/`** - Navigation configuration

## WebSocket Integration

Two pages use WebSocket connections for real-time data:

### Stories Page (`/stories`)

Connects to `/api/stories/monitor/ws` for live narrator monitoring:
- Pipeline state updates every 2 seconds
- Scraper status, event log, cycle history
- Auto-reconnect on connection loss

### Overview Page (`/`)

The ops console connects to `/api/scheduler/monitor/ws` for:
- Active run tracking
- Schedule state updates
- Real-time event stream

## Development

```bash
cd dashboard
npm install
npm run dev       # Start dev server on :3000
npm run build     # Production build
npm run lint      # ESLint check
```

The dev server connects to the gateway via the proxy rewrite. Set `NEXT_PUBLIC_GATEWAY_URL` for custom gateway URLs during development.
