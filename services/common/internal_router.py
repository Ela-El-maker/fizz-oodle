from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends

from services.common.commands import run_agent_direct
from services.common.security import require_internal_api_key


def build_internal_router(agent_name: str) -> APIRouter:
    router = APIRouter(tags=["internal"])

    @router.get("/internal/health", dependencies=[Depends(require_internal_api_key)])
    async def internal_health():
        return {"status": "ok", "service_agent": agent_name}

    @router.post("/internal/runs/trigger", dependencies=[Depends(require_internal_api_key)])
    async def internal_trigger(
        run_id: str | None = None,
        report_type: str | None = None,
        period_key: str | None = None,
        force_send: bool | None = None,
        run_type: str | None = None,
        email_recipients_override: str | None = None,
    ):
        payload = {
            "run_id": run_id,
            "report_type": report_type,
            "period_key": period_key,
            "force_send": force_send,
            "run_type": run_type,
            "email_recipients_override": email_recipients_override,
        }
        result = await run_agent_direct(agent_name, payload)
        return {"accepted": True, "agent_name": agent_name, "result": result}

    @router.post("/internal/resend", dependencies=[Depends(require_internal_api_key)])
    async def internal_resend(
        period_key: str | None = None,
        report_type: str | None = None,
    ):
        payload = {
            "period_key": period_key,
            "report_type": report_type,
            "force_send": True,
            "run_type": report_type,
        }
        result = await run_agent_direct(agent_name, payload)
        return {"accepted": True, "agent_name": agent_name, "result": result}

    return router
