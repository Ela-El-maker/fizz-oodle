from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.agents.announcements.types import NormalizedAnnouncement
from apps.core.models import Announcement, SourceHealth


def _roll_24h_counters(
    previous: dict | None,
    *,
    now_utc: datetime,
    success_inc: int = 0,
    failure_inc: int = 0,
    blocked_inc: int = 0,
) -> dict:
    metrics = dict(previous or {})
    window_started_at = metrics.get("window_started_at")
    reset = True
    if isinstance(window_started_at, str):
        try:
            started = datetime.fromisoformat(window_started_at)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            reset = (now_utc - started) >= timedelta(hours=24)
        except Exception:
            reset = True

    if reset:
        metrics["window_started_at"] = now_utc.isoformat()
        metrics["success_count_24h"] = 0
        metrics["failure_count_24h"] = 0
        metrics["blocked_count_24h"] = 0

    metrics["success_count_24h"] = int(metrics.get("success_count_24h") or 0) + max(0, success_inc)
    metrics["failure_count_24h"] = int(metrics.get("failure_count_24h") or 0) + max(0, failure_inc)
    metrics["blocked_count_24h"] = int(metrics.get("blocked_count_24h") or 0) + max(0, blocked_inc)
    return metrics


async def upsert_announcement(session: AsyncSession, item: NormalizedAnnouncement, now_utc: datetime) -> bool:
    existing = (
        await session.execute(select(Announcement).where(Announcement.announcement_id == item.announcement_id))
    ).scalar_one_or_none()

    if existing is None:
        row = Announcement(
            announcement_id=item.announcement_id,
            source_id=item.source_id,
            ticker=item.ticker,
            company_name=item.company,
            headline=item.headline,
            url=item.url,
            canonical_url=item.canonical_url,
            announcement_date=item.announcement_date,
            announcement_type=item.announcement_type,
            type_confidence=item.type_confidence,
            details=item.details,
            content_hash=item.content_hash,
            raw_payload=item.raw_payload,
            first_seen_at=now_utc,
            last_seen_at=now_utc,
            alerted=False,
            classifier_version=item.classifier_version,
            normalizer_version=item.normalizer_version,
            # legacy bridge columns
            legacy_title=item.headline,
            legacy_description=item.details,
            legacy_source_name=item.source_id,
            legacy_source_url=item.url,
            legacy_published_at=item.announcement_date,
            legacy_detected_at=now_utc,
            legacy_raw_data=item.raw_payload,
        )
        session.add(row)
        return True

    existing.last_seen_at = now_utc
    if not existing.details and item.details:
        existing.details = item.details
    if not existing.content_hash and item.content_hash:
        existing.content_hash = item.content_hash
    if not existing.ticker and item.ticker:
        existing.ticker = item.ticker
    if not existing.company_name and item.company:
        existing.company_name = item.company
    if item.announcement_type and existing.announcement_type == "other":
        existing.announcement_type = item.announcement_type
        existing.type_confidence = item.type_confidence
    return False


async def upsert_announcements_batch(
    session: AsyncSession,
    items: list[NormalizedAnnouncement],
    now_utc: datetime,
) -> tuple[int, int, int, list[str]]:
    if not items:
        return 0, 0, 0, []

    announcement_ids = [item.announcement_id for item in items]
    existing_rows = (
        await session.execute(
            select(Announcement).where(Announcement.announcement_id.in_(announcement_ids))
        )
    ).scalars().all()
    existing_by_id = {row.announcement_id: row for row in existing_rows if row.announcement_id}

    inserted_rows: list[Announcement] = []
    inserted_ids: list[str] = []
    duplicates = 0

    for item in items:
        existing = existing_by_id.get(item.announcement_id)
        if existing is None:
            row = Announcement(
                announcement_id=item.announcement_id,
                source_id=item.source_id,
                ticker=item.ticker,
                company_name=item.company,
                headline=item.headline,
                url=item.url,
                canonical_url=item.canonical_url,
                announcement_date=item.announcement_date,
                announcement_type=item.announcement_type,
                type_confidence=item.type_confidence,
                details=item.details,
                content_hash=item.content_hash,
                raw_payload=item.raw_payload,
                first_seen_at=now_utc,
                last_seen_at=now_utc,
                alerted=False,
                classifier_version=item.classifier_version,
                normalizer_version=item.normalizer_version,
                legacy_title=item.headline,
                legacy_description=item.details,
                legacy_source_name=item.source_id,
                legacy_source_url=item.url,
                legacy_published_at=item.announcement_date,
                legacy_detected_at=now_utc,
                legacy_raw_data=item.raw_payload,
            )
            inserted_rows.append(row)
            inserted_ids.append(item.announcement_id)
            continue

        duplicates += 1
        existing.last_seen_at = now_utc
        if not existing.details and item.details:
            existing.details = item.details
        if not existing.content_hash and item.content_hash:
            existing.content_hash = item.content_hash
        if not existing.ticker and item.ticker:
            existing.ticker = item.ticker
        if not existing.company_name and item.company:
            existing.company_name = item.company
        if item.announcement_type and existing.announcement_type == "other":
            existing.announcement_type = item.announcement_type
            existing.type_confidence = item.type_confidence

    if inserted_rows:
        session.add_all(inserted_rows)

    return len(items), len(inserted_rows), duplicates, inserted_ids


async def load_known_announcement_keys(session: AsyncSession) -> tuple[set[str], set[str]]:
    id_rows = (await session.execute(select(Announcement.announcement_id))).scalars().all()
    hash_rows = (await session.execute(select(Announcement.content_hash))).scalars().all()
    known_ids = {row for row in id_rows if row}
    known_hashes = {row for row in hash_rows if row}
    return known_ids, known_hashes


async def content_hash_exists(session: AsyncSession, content_hash: str, *, exclude_announcement_id: str | None = None) -> bool:
    if not content_hash:
        return False
    with session.no_autoflush:
        stmt = select(Announcement.announcement_id).where(Announcement.content_hash == content_hash)
        rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        return False
    if exclude_announcement_id is None:
        return True
    return any(row != exclude_announcement_id for row in rows if row)


async def list_alert_candidates(
    session: AsyncSession,
    run_started_at: datetime,
    inserted_ids: list[str],
    *,
    limit: int | None = None,
) -> list[Announcement]:
    if run_started_at.tzinfo is None:
        run_started_at = run_started_at.replace(tzinfo=timezone.utc)

    stmt = (
        select(Announcement)
        .where(Announcement.alerted.is_(False))
        .where(
            (Announcement.announcement_id.in_(inserted_ids))
            | (Announcement.first_seen_at >= run_started_at)
        )
        .order_by(Announcement.announcement_date.desc().nullslast(), Announcement.first_seen_at.desc())
    )
    if limit is not None:
        stmt = stmt.limit(max(1, int(limit)))
    return list((await session.execute(stmt)).scalars().all())


async def list_recent_announcements_for_validation(
    session: AsyncSession,
    *,
    limit: int = 25,
) -> list[Announcement]:
    stmt = (
        select(Announcement)
        .order_by(Announcement.first_seen_at.desc())
        .limit(max(1, min(limit, 200)))
    )
    return list((await session.execute(stmt)).scalars().all())


async def mark_alerted(session: AsyncSession, announcement_ids: list[str], now_utc: datetime) -> None:
    if not announcement_ids:
        return
    await session.execute(
        update(Announcement)
        .where(Announcement.announcement_id.in_(announcement_ids))
        .values(alerted=True, alerted_at=now_utc)
    )


async def get_source_health(session: AsyncSession, source_id: str) -> SourceHealth | None:
    return (
        await session.execute(select(SourceHealth).where(SourceHealth.source_id == source_id))
    ).scalar_one_or_none()


async def source_can_run(
    session: AsyncSession,
    source_id: str,
    breaker_enabled: bool,
    now_utc: datetime,
) -> bool:
    if not breaker_enabled:
        return True
    row = await get_source_health(session, source_id)
    if row is None:
        return True
    if row.breaker_state != "open":
        return True
    if row.cooldown_until is None:
        return False
    if row.cooldown_until.tzinfo is None:
        cooldown = row.cooldown_until.replace(tzinfo=timezone.utc)
    else:
        cooldown = row.cooldown_until.astimezone(timezone.utc)
    return cooldown <= now_utc


async def mark_source_success(
    session: AsyncSession,
    source_id: str,
    metrics: dict,
    now_utc: datetime,
) -> None:
    row = await get_source_health(session, source_id)
    if row is None:
        row = SourceHealth(source_id=source_id)
        session.add(row)

    row.last_success_at = now_utc
    row.consecutive_failures = 0
    row.breaker_state = "closed"
    row.cooldown_until = None
    merged = _roll_24h_counters(
        row.last_metrics if isinstance(row.last_metrics, dict) else {},
        now_utc=now_utc,
        success_inc=1,
    )
    merged.update(metrics or {})
    merged["last_error_type"] = None
    row.last_metrics = merged


async def mark_source_failure(
    session: AsyncSession,
    source_id: str,
    error: str,
    error_type: str | None,
    now_utc: datetime,
    fail_threshold: int,
    cooldown_minutes: int,
) -> None:
    row = await get_source_health(session, source_id)
    if row is None:
        row = SourceHealth(source_id=source_id)
        session.add(row)

    row.last_failure_at = now_utc
    row.consecutive_failures = int(row.consecutive_failures or 0) + 1
    merged = _roll_24h_counters(
        row.last_metrics if isinstance(row.last_metrics, dict) else {},
        now_utc=now_utc,
        failure_inc=1,
        blocked_inc=1 if (error_type or "") == "blocked" else 0,
    )
    merged.update({"error": error, "error_type": error_type or "unknown_error", "last_error_type": error_type or "unknown_error"})
    row.last_metrics = merged

    if row.consecutive_failures >= fail_threshold:
        row.breaker_state = "open"
        row.cooldown_until = now_utc + timedelta(minutes=cooldown_minutes)
    else:
        row.breaker_state = "closed"
