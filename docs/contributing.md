# Contributing

## Workflow

1. Create a focused branch.
2. Make incremental changes with tests.
3. Validate config contracts.
4. Run test suite and relevant local checks.
5. Open PR with:
   - behavior change summary
   - risk/rollback notes
   - evidence (logs/screenshots/test output)

## Quality gates

```bash
python scripts/validate_configs.py
pytest -q
```

For frontend updates:

```bash
cd dashboard
npm run lint
npm run build
```

## Coding conventions

- Keep schema changes additive unless migration is planned.
- Preserve backward-compatible API fields where possible.
- Prefer deterministic fallbacks for LLM-dependent paths.
- Keep run status semantics consistent (`success`, `partial`, `fail`).

## Documentation expectations

Update docs whenever changing:

- schedules or run orchestration
- source taxonomy/config fields
- public/internal API contracts
- email delivery behavior
- dashboard operator workflows
