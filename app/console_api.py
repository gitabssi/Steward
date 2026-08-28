"""The console's API: the fleet, observable and answerable.

Everything the console renders arrives on one Server-Sent-Events stream —
the same ledger the auditors read, because the console IS the audit view.
The operator's few, deliberate write paths are separate and narrow:

    POST /api/decide        resolve an open escalation (mints the approval
                            token; the irreversible tool runs only then)
    POST /api/authority     promote or demote an agent, live
    POST /api/reconfigure   point the fleet at a different permit id (the
                            public-record door: any plant in the country)

Reads:
    GET  /api/events        SSE — ledger entries as they happen (+replay)
    GET  /api/state         current shift state in one document
    GET  /api/roster        every agent: identity, scope, authority, memory
    GET  /api/finding       the aggregate backtest finding from BigQuery
"""

from __future__ import annotations

import asyncio
import json
import os

from fastapi import APIRouter, FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.fleet import shift
from app.fleet.authority import POLICY, Authority
from app.fleet.events import BUS
from app.fleet.identity import describe_scopes
from app.fleet.memory import MEMORY

router = APIRouter(prefix="/api")


@router.get("/events")
async def events() -> StreamingResponse:
    async def stream():
        async for entry in BUS.subscribe(replay=300):
            yield f"data: {entry.to_json()}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/state")
async def state() -> dict:
    loop = shift.LOOP
    if loop is None:
        return {"status": "shift loop not started"}
    s = loop.state
    return {
        "facility": s.facility,
        "telemetry": s.telemetry,
        "permit_limits": s.permit_limits,
        "dilution_pct": s.dilution_pct,
        "pinned_parameter": s.pinned_parameter,
        "pending": [
            {
                "decision_id": d.decision_id,
                "subject": d.subject,
                "options": d.options,
                "window_minutes": d.window_minutes,
                "resolved": d.resolved,
            }
            for d in s.pending.values()
        ],
        "obligations_degraded": s.obligations_degraded,
        "week": s.week,
        "uptime_seconds": __import__("time").time() - s.started_at,
        "minutes_on_shift": round(loop.world.minutes, 1),
    }


@router.get("/roster")
async def roster() -> dict:
    scopes = describe_scopes()
    facts = MEMORY.facts()
    registry = shift.LOOP.registry.roster() if shift.LOOP else []
    return {"grants": scopes, "learned_facts": facts, "registry": registry}


class Decision(BaseModel):
    decision_id: str
    action: str


@router.post("/decide")
async def decide(decision: Decision) -> dict:
    if shift.LOOP is None:
        return {"error": "shift loop not started"}
    return await shift.LOOP.decide(decision.decision_id, decision.action)


class AuthorityChange(BaseModel):
    agent_name: str
    authority: str  # observe | recommend | act


@router.post("/authority")
async def authority(change: AuthorityChange) -> dict:
    level = Authority[change.authority.upper()]
    POLICY.set_authority(change.agent_name, level, by="operator")
    return {"agent_name": change.agent_name, "authority": level.name.lower()}


class Reconfigure(BaseModel):
    permit_id: str


@router.post("/reconfigure")
async def reconfigure(req: Reconfigure) -> dict:
    """The Any Plant door: pull a real facility's parameter set and
    enforceable limits from the public corpus, and say which specialists
    this plant would need."""
    from app.fleet.tools import read_public_record

    record = await asyncio.to_thread(
        read_public_record, req.permit_id, "permit-sentinel"
    )
    return record


@router.get("/finding")
async def finding() -> dict:
    """The aggregate backtest finding — precomputed by data/sql/, read here."""
    from google.cloud import bigquery

    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    dataset = os.environ.get("BQ_DATASET", "steward_npdes")
    try:
        client = bigquery.Client(project=project)
        rows = list(client.query(f"SELECT * FROM `{project}.{dataset}.finding`").result())
        return dict(rows[0]) if rows else {"error": "finding not yet computed"}
    except Exception as exc:
        return {"error": f"finding unavailable: {exc}"[:300]}


def attach_console_routes(app: FastAPI) -> None:
    app.include_router(router)
    seed = os.environ.get("STEWARD_FACILITY_SEED", "fixtures/seeds/cedar-ridge.json")
    if os.environ.get("STEWARD_SHIFT", "1") == "1" and os.path.exists(seed):

        @app.on_event("startup")
        async def _start_shift() -> None:
            shift.boot(seed)
