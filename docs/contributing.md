# Contributing

## Development Setup

### Prerequisites

- Python 3.11+
- Node.js 18+ and npm
- Docker and Docker Compose
- PostgreSQL 16 client tools (optional, for direct DB access)

### Getting Started

```bash
# Clone and start all services
git clone <repo-url>
cd fizz-oodle
cp .env.example .env          # Configure environment variables
docker compose up -d           # Start all 12 dev services

# Frontend development (hot reload)
cd dashboard
npm install
npm run dev                    # Starts on http://localhost:3000
```

### Makefile Shortcuts

| Target | Command | Purpose |
|---|---|---|
| `make up` | `docker compose up -d` | Start all services |
| `make down` | `docker compose down` | Stop all services |
| `make build` | `docker compose up -d --build` | Rebuild and start |
| `make logs` | `docker compose logs -f gateway-service` | Gateway logs |
| `make validate` | `python scripts/validate_configs.py` | Config validation |
| `make test` | `pytest -q` | Run test suite |
| `make frontend-install` | `cd dashboard && npm install` | Install frontend deps |
| `make frontend-dev` | `cd dashboard && npm run dev` | Frontend dev server |
| `make frontend-build` | `cd dashboard && npm run build` | Frontend production build |

## Quality Gates

All changes must pass these checks before merge:

### 1. Python Tests

```bash
pytest -q
```

- 225 tests across 63 test files
- Async test support via `pytest-asyncio` (auto mode)
- Covers: gateway routes, all 6 agents, email service, event contracts, healing engine, learning engine, self-mod engine, run reconciler, scrape core, sentiment pipeline, schedule loader, session auth, admin endpoints, source policy

### 2. Configuration Validation

```bash
python scripts/validate_configs.py
```

Validates all YAML/JSON config files against their schemas:
- `config/sources.yml` (strict JSON schema)
- `config/briefing_sources.yml`
- `config/sentiment_sources.yml` (strict JSON schema)
- `config/schedules.yml`
- `config/universe.yml`
- `config/announcement_types.yml`

### 3. Frontend Build

```bash
cd dashboard
npm run lint     # ESLint
npm run build    # TypeScript compilation + Next.js build
```

Both must pass with zero errors.

## Code Structure

### Backend

```
apps/
  core/           # Shared: config, models, events, email, scoring
  agents/         # Agent business logic (one subpackage per agent)
  api/            # Legacy monolith routers (preserved for reference)
  scrape_core/    # Shared HTTP client, circuit breaker, dedup, sitemap
services/
  gateway/        # API gateway service (port 8000)
  scheduler/      # Schedule evaluation and dispatch (port 8010)
  run_ledger/     # Run tracking and event persistence (port 8011)
  agent_a/ - f/   # Per-agent microservice entrypoints
  common/         # Shared service utilities (commands, metrics, security)
config/           # YAML/JSON configuration files
scripts/          # Operational and deployment scripts
templates/        # Jinja2 email templates
tests/            # Test suite
```

### Frontend

```
dashboard/
  src/
    app/           # Next.js App Router pages
      (protected)/ # Auth-gated route group
      auth/        # Login page
    features/      # Feature modules (auth, monitor, scheduler, etc.)
    widgets/       # Reusable dashboard widgets
    shared/        # Layout, UI components, HTTP client, config
```

## Coding Conventions

### Python

- **Framework:** FastAPI with async handlers
- **ORM:** SQLAlchemy 2.0 async with asyncpg
- **Settings:** Pydantic `BaseSettings` from environment variables
- **Logging:** `structlog` for structured JSON logging
- **Type hints:** Required on all public function signatures
- **Async:** Prefer `async def` for I/O-bound operations

### TypeScript

- **Framework:** Next.js 14 App Router
- **State:** React Query for server state, Zustand for client state
- **Styling:** Tailwind CSS with semantic CSS custom properties
- **Forms:** react-hook-form + Zod validation
- **Imports:** Prefer path aliases (`@/shared/`, `@/features/`, `@/widgets/`)

### Configuration

- Source configs use strict JSON schemas (`additionalProperties: false`) where applicable
- All schedule times are in UTC (EAT = UTC+3)
- Feature flags follow the `ENABLE_*` naming convention
- Agent-specific settings use `AGENT_NAME_*` prefix pattern

## Database Conventions

- Each agent owns its own database (`db_agent_a` through `db_agent_f`)
- Platform services share `db_platform_ops`
- Migrations via Alembic with sequential numbering (`0001_init`, `0002_stage2`, etc.)
- Tables not owned by a service are pruned at startup (enforced isolation)

## Adding a New Source

1. Add the source entry to the appropriate config file (`sources.yml`, `briefing_sources.yml`, or `sentiment_sources.yml`)
2. Include all required fields per the JSON schema
3. Ensure `source_id` is unique across all sources
4. Set appropriate `scope`, `market_region`, and `signal_class` metadata
5. Run `python scripts/validate_configs.py` to verify
6. Test collection with a manual agent run

## Adding a New Company

1. Add the company to `config/universe.yml` with `ticker`, `company_name`, `exchange`, and `aliases`
2. Run config validation
3. The company will be picked up by sentiment extraction and mention matching on next runs

## Documentation

- Documentation lives in `docs/` as Markdown files
- Update documentation when changing behavior, APIs, or configuration
- Keep the docs index (`docs/README.md`) current
