from __future__ import annotations

from fastapi import FastAPI

from apps.core.logger import configure_logging
from apps.api.routers.health import router as health_router
from apps.api.routers.runs import router as runs_router
from apps.api.routers.prices import router as prices_router
from apps.api.routers.announcements import router as announcements_router
from apps.api.routers.sentiment import router as sentiment_router
from apps.api.routers.sentiment_v2 import router as sentiment_v2_router
from apps.api.routers.admin import router as admin_router
from apps.api.routers.admin_sentiment import router as admin_sentiment_router
from apps.api.routers.admin_reports import router as admin_reports_router
from apps.api.routers.briefings import router as briefings_router
from apps.api.routers.fx import router as fx_router
from apps.api.routers.indexes import router as indexes_router
from apps.api.routers.reports import router as reports_router
from apps.api.routers.patterns import router as patterns_router
from apps.api.routers.narrator import router as narrator_router

configure_logging()

app = FastAPI(title="Market Intelligence API")

app.include_router(health_router)
app.include_router(runs_router)
app.include_router(announcements_router)
app.include_router(admin_router)
app.include_router(admin_sentiment_router)
app.include_router(admin_reports_router)
app.include_router(briefings_router)
app.include_router(fx_router)
app.include_router(indexes_router)
app.include_router(prices_router)
app.include_router(sentiment_v2_router)
app.include_router(reports_router)
app.include_router(patterns_router)
app.include_router(narrator_router)
app.include_router(prices_router, prefix="/v1")
app.include_router(announcements_router, prefix="/v1")
app.include_router(sentiment_router, prefix="/v1")
