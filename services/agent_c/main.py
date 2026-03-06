from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.api.routers.sentiment import router as legacy_sentiment_router
from apps.api.routers.sentiment_v2 import router as sentiment_router
from apps.core.logger import configure_logging
from services.common.commands import command_listener
from services.common.metrics import setup_metrics
from services.common.internal_router import build_internal_router

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop_event = asyncio.Event()
    task = asyncio.create_task(command_listener("sentiment", stop_event))
    try:
        yield
    finally:
        stop_event.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Agent C Service", lifespan=lifespan)
setup_metrics(app, "agent_c")
app.include_router(build_internal_router("sentiment"))
app.include_router(sentiment_router)
app.include_router(legacy_sentiment_router, prefix="/v1")
