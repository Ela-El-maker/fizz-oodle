# Documentation Index

Comprehensive documentation for the Market Intelligence Platform — a six-agent autonomous system tracking 67 companies across African equity markets.

## System Design

- **[Architecture](architecture.md)** — Service topology, database isolation, event bus, resilience model, data ownership
- **[Agents](agents.md)** — Deep documentation for all six agents (A–F): pipelines, config flags, models, failure modes
- **[Data Flow](data-flow.md)** — End-to-end data movement from external sources through synthesis to delivery

## Core Services

- **[Scheduler](scheduler.md)** — Schedule loading, dispatch loop, overlap guard, jitter, timezone handling
- **[Run Ledger](runledger.md)** — Run/event persistence, stale reconciliation, monitor APIs

## Data Collection

- **[Scraping System](scraping-system.md)** — Collection modes, HTTP client, circuit breaker, source taxonomy, deduplication

## Interfaces

- **[API Reference](api.md)** — Complete REST and WebSocket API surface (80+ endpoints), authentication, rate limiting
- **[Dashboard UI](ui.md)** — Next.js application: pages, widgets, theming, auth flow, WebSocket integration

## Operations

- **[Deployment](deployment.md)** — Docker Compose environments, Nginx/TLS, monitoring stack, operational scripts
- **[Troubleshooting](troubleshooting.md)** — 12 common failure scenarios with diagnostic commands and fixes
- **[Contributing](contributing.md)** — Development setup, quality gates (225 tests), coding conventions

## Reference

- **[canonical/INTERFACE_CONTRACT.md](canonical/INTERFACE_CONTRACT.md)** — Schedule task contract registry
