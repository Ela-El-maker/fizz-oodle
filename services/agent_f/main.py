from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.api.routers.narrator import router as narrator_router
from apps.core.logger import configure_logging
from services.common.commands import command_listener
from services.common.internal_router import build_internal_router
from services.common.metrics import setup_metrics

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop_event = asyncio.Event()
    task = asyncio.create_task(command_listener("narrator", stop_event))
    try:
        yield
    finally:
        stop_event.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Agent F Service", lifespan=lifespan)
setup_metrics(app, "agent_f")
app.include_router(build_internal_router("narrator"))
app.include_router(narrator_router)
