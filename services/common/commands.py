from __future__ import annotations

import asyncio
from datetime import date
import os
from typing import Awaitable, Callable
from uuid import uuid4

from apps.agents.analyst.pipeline import run_analyst_pipeline
from apps.agents.announcements.pipeline import run_announcements_pipeline
from apps.agents.archivist.pipeline import run_archivist_pipeline
from apps.agents.briefing.pipeline import run_daily_briefing_pipeline
from apps.agents.sentiment.pipeline import run_sentiment_pipeline
from apps.agents.narrator.pipeline import run_narrator_pipeline
from apps.core.config import get_settings
from apps.core.events import ack_stream_group, iter_stream_group
from apps.core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


Runner = Callable[[dict], Awaitable[dict]]


def _none_like(value: object) -> bool:
    return value is None or (isinstance(value, str) and value.strip().lower() in {"", "none", "null"})


def _parse_optional_date(value: object) -> date | None:
    if _none_like(value):
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"Invalid date value: {value!r}")


def _parse_optional_bool(value: object) -> bool | None:
    if _none_like(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    raise ValueError(f"Invalid bool value: {value!r}")


async def _run_briefing(payload: dict) -> dict:
    return await run_daily_briefing_pipeline(
        run_id=payload.get("run_id"),
        force_send=_parse_optional_bool(payload.get("force_send")),
        email_recipients_override=payload.get("email_recipients_override"),
    )


async def _run_announcements(payload: dict) -> dict:
    return await run_announcements_pipeline(
        run_id=payload.get("run_id"),
        force_send=_parse_optional_bool(payload.get("force_send")),
        email_recipients_override=payload.get("email_recipients_override"),
    )


async def _run_sentiment(payload: dict) -> dict:
    parsed = _parse_optional_date(payload.get("period_key"))
    return await run_sentiment_pipeline(
        run_id=payload.get("run_id"),
        week_start_override=parsed,
        force_send=_parse_optional_bool(payload.get("force_send")),
        email_recipients_override=payload.get("email_recipients_override"),
    )


async def _run_analyst(payload: dict) -> dict:
    parsed = _parse_optional_date(payload.get("period_key"))
    return await run_analyst_pipeline(
        run_id=payload.get("run_id"),
        report_type=payload.get("report_type"),
        period_key=parsed,
        force_send=_parse_optional_bool(payload.get("force_send")),
        email_recipients_override=payload.get("email_recipients_override"),
    )


async def _run_archivist(payload: dict) -> dict:
    parsed = _parse_optional_date(payload.get("period_key"))
    return await run_archivist_pipeline(
        run_id=payload.get("run_id"),
        run_type=payload.get("run_type") or payload.get("report_type"),
        period_key=parsed,
        force_send=_parse_optional_bool(payload.get("force_send")),
        email_recipients_override=payload.get("email_recipients_override"),
    )


async def _run_narrator(payload: dict) -> dict:
    return await run_narrator_pipeline(
        run_id=payload.get("run_id"),
        force_regenerate=_parse_optional_bool(payload.get("force_send")),
    )


RUNNERS: dict[str, Runner] = {
    "briefing": _run_briefing,
    "announcements": _run_announcements,
    "sentiment": _run_sentiment,
    "analyst": _run_analyst,
    "archivist": _run_archivist,
    "narrator": _run_narrator,
}


async def run_agent_direct(agent_name: str, payload: dict) -> dict:
    runner = RUNNERS.get(agent_name)
    if runner is None:
        raise ValueError(f"Unknown agent_name={agent_name}")
    return await runner(payload)


async def command_listener(agent_name: str, stop_event: asyncio.Event):
    stream = settings.REDIS_STREAM_COMMANDS
    group = f"commands:{agent_name}"
    consumer = f"{agent_name}:{os.getpid()}:{uuid4().hex[:8]}"
    logger.info("command_listener_started", agent_name=agent_name, stream=stream, group=group, consumer=consumer)
    backoff = 1.0
    while not stop_event.is_set():
        try:
            async for _stream_name, msg_id, payload in iter_stream_group(stream, group=group, consumer=consumer, block_ms=3000, count=100):
                if stop_event.is_set():
                    return
                backoff = 1.0  # reset on any successful iteration
                if msg_id is None:
                    await asyncio.sleep(0.1)
                    continue
                if payload is None:
                    await ack_stream_group(stream, group=group, message_id=msg_id)
                    await asyncio.sleep(0.1)
                    continue
                if payload.get("schema") != "RunCommandV1":
                    await ack_stream_group(stream, group=group, message_id=msg_id)
                    continue
                if payload.get("agent_name") != agent_name:
                    await ack_stream_group(stream, group=group, message_id=msg_id)
                    continue
                try:
                    await run_agent_direct(agent_name, payload)
                except Exception as e:
                    logger.exception("command_execution_failed", agent_name=agent_name, error=str(e), payload=payload)
                finally:
                    await ack_stream_group(stream, group=group, message_id=msg_id)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("command_listener_reconnecting", agent_name=agent_name, error=str(exc), backoff=backoff)
            await asyncio.sleep(min(backoff, 30.0))
            backoff = min(backoff * 2, 30.0)
