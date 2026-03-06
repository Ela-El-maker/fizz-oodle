from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.api.routers.briefings import router as briefings_router
from apps.api.routers.fx import router as fx_router
from apps.api.routers.indexes import router as indexes_router
from apps.api.routers.prices import router as prices_router
from apps.core.logger import configure_logging
from services.common.commands import command_listener
from services.common.metrics import setup_metrics
from services.common.internal_router import build_internal_router

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop_event = asyncio.Event()
    task = asyncio.create_task(command_listener("briefing", stop_event))
    try:
        yield
    finally:
        stop_event.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

app = FastAPI(title="Agent A Service", lifespan=lifespan)
setup_metrics(app, "agent_a")
app.include_router(build_internal_router("briefing"))
app.include_router(briefings_router)
app.include_router(fx_router)
app.include_router(indexes_router)
app.include_router(prices_router)
