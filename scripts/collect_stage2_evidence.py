from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from apps.agents.announcements import pipeline
from apps.agents.announcements.types import RawAnnouncement, SourceConfig
from apps.api.main import app
from apps.core import database as db
from apps.core.database import Base, get_session


OUT_DIR = Path("docs/evidence/stage2")


async def _db_ready() -> bool:
    try:
        async with db._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _reset_db() -> None:
    async with db._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE TABLE announcement_assets, announcements, source_health, agent_runs, companies RESTART IDENTITY CASCADE"))


async def _seed_scenario() -> None:
    source_ok = SourceConfig(
        source_id="nse_official",
        type="official",
        base_url="https://example.com",
        enabled_by_default=True,
        parser="x",
        timeout_secs=10,
        retries=0,
        backoff_base=2.0,
        rate_limit_rps=1.0,
        ticker_strategy="headline_regex",
    )
    source_bad = SourceConfig(
        source_id="cma_notices",
        type="regulator",
        base_url="https://bad.example",
        enabled_by_default=True,
        parser="y",
        timeout_secs=10,
        retries=0,
        backoff_base=2.0,
        rate_limit_rps=1.0,
        ticker_strategy="headline_regex",
    )

    raw_ok = RawAnnouncement(
        source_id="nse_official",
        headline="Safaricom interim dividend declared",
        url="https://example.com/a1?utm_source=x",
        published_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        ticker_hint="SCOM",
        extra={"k": "v"},
    )
    raw_new = RawAnnouncement(
        source_id="nse_official",
        headline="KCB board change notice",
        url="https://example.com/a2",
        published_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        ticker_hint="KCB",
        extra={"k": "v2"},
    )

    async def fake_seed_companies():
        return None

    async def collector_ok(_source):
        return [raw_ok]

    async def collector_bad(_source):
        raise RuntimeError("source unavailable")

    async def collector_new(_source):
        return [raw_new]

    def get_collector_single(_source):
        return collector_ok

    def get_collector_mixed(source):
        return collector_bad if source.source_id == "cma_notices" else collector_ok

    def get_collector_failure(_source):
        return collector_new

    async def fake_extract_details(_url: str):
        return "details"

    pipeline.seed_companies = fake_seed_companies
    pipeline.extract_details = fake_extract_details
    pipeline.settings.SOURCE_FAIL_THRESHOLD = 2
    pipeline.settings.SOURCE_COOLDOWN_MINUTES = 30

    # 1) happy path
    pipeline.get_source_configs = lambda: [source_ok]
    pipeline.get_collector = get_collector_single
    pipeline.send_announcements_email = lambda _items, run_id: (True, None)  # noqa: ARG005
    await pipeline.run_announcements_pipeline()

    # 2) idempotent rerun
    await pipeline.run_announcements_pipeline()

    # 3) partial run with one broken source
    pipeline.get_source_configs = lambda: [source_ok, source_bad]
    pipeline.get_collector = get_collector_mixed
    await pipeline.run_announcements_pipeline()

    # 4) email failure keeps unalerted
    pipeline.get_source_configs = lambda: [source_ok]
    pipeline.get_collector = get_collector_failure
    pipeline.send_announcements_email = lambda _items, run_id: (False, "smtp_down")  # noqa: ARG005
    await pipeline.run_announcements_pipeline()

    # 5) repeated source failure -> breaker open
    pipeline.get_source_configs = lambda: [source_bad]
    pipeline.get_collector = lambda _s: collector_bad
    await pipeline.run_announcements_pipeline()
    await pipeline.run_announcements_pipeline()


async def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not await _db_ready():
        print("Postgres not available; skipping evidence collection.")
        return 1

    await _reset_db()
    await _seed_scenario()

    client = TestClient(app)
    headers = {"x-api-key": "change-me"}

    runs_resp = client.get("/runs?agent_name=announcements&limit=10", headers=headers)
    health_resp = client.get("/sources/health", headers=headers)
    admin_resp = client.get("/admin/announcements?limit=50", headers=headers)

    (OUT_DIR / "runs_sample.json").write_text(
        json.dumps(runs_resp.json(), indent=2),
        encoding="utf-8",
    )
    (OUT_DIR / "sources_health_sample.json").write_text(
        json.dumps(health_resp.json(), indent=2),
        encoding="utf-8",
    )
    (OUT_DIR / "admin_announcements_snapshot.html").write_text(
        admin_resp.text,
        encoding="utf-8",
    )

    async with get_session() as session:
        unalerted = (
            await session.execute(text("SELECT COUNT(*) FROM announcements WHERE alerted=false"))
        ).scalar_one()
    (OUT_DIR / "unalerted_after_email_failure.json").write_text(
        json.dumps({"unalerted_count": int(unalerted)}, indent=2),
        encoding="utf-8",
    )

    print(f"Wrote evidence to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
