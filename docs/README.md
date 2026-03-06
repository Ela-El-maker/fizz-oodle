# Documentation Index

This directory documents the production behavior of the Market Intel Platform.

- [architecture.md](architecture.md): service topology, runtime boundaries, data ownership
- [agents.md](agents.md): A–F agent responsibilities, workflows, failure modes
- [scheduler.md](scheduler.md): schedule loading, dispatch loop, overlap/jitter, ops tasks
- [runledger.md](runledger.md): run/event persistence, reconciliation, monitor APIs
- [scraping-system.md](scraping-system.md): connectors, breaker/retry, source taxonomy
- [data-flow.md](data-flow.md): end-to-end movement from sources to dashboard/emails
- [api.md](api.md): gateway and service API surfaces used by operators/UI
- [ui.md](ui.md): Next.js app structure, pages, auth, data integration
- [deployment.md](deployment.md): local/container deployment and ops conventions
- [troubleshooting.md](troubleshooting.md): common failures and fix runbooks
- [contributing.md](contributing.md): contribution workflow and quality checks
- [canonical/INTERFACE_CONTRACT.md](canonical/INTERFACE_CONTRACT.md): schedule task contract registry
