"""The fleet's tools — each one scoped, classed, and policed.

A tool here is a capability with a price tag: every one is registered
with a ToolPolicy naming the authority level it requires and whether it
is irreversible. The AuthorityPlugin checks that policy before any call;
the ScopedReader checks facility scope inside the call. Two fences, both
of which log.

The world the tools touch is process-global by design: one fleet process
serves one facility's live loop (Agent Runtime runs one such process per
facility), so the world handle is set once at boot by shift.py.
"""

from __future__ import annotations

import os
from typing import Any

from app.fleet.authority import POLICY, Authority, ToolPolicy
from app.fleet.events import BUS, EventKind, Outcome
from app.fleet.identity import READER, ScopeDenied

# Set by shift.py at boot; tools fail loudly if the world isn't up yet.
_WORLD = None
_FACILITY = ""


def bind_world(world: Any, facility: str) -> None:
    global _WORLD, _FACILITY
    _WORLD = world
    _FACILITY = facility


def _world():
    if _WORLD is None:
        raise RuntimeError("world not bound — shift loop has not started")
    return _WORLD


# --------------------------------------------------------------------------
# observe — read only
# --------------------------------------------------------------------------


def _scope_denial(exc: Exception) -> dict:
    """Inside an agent's tool call a denial is data, not an exception —
    the model reads it, the ledger already recorded it, the loop lives."""
    return {"denied": True, "reason": str(exc)}


def read_station(station: str, facility: str, agent_name: str = "") -> dict:
    """Read current telemetry for one station of one facility.

    Args:
        station: station id, e.g. "aeration", "headworks", "outfall".
        facility: NPDES permit id the reading is for (your grant names yours).
        agent_name: filled by the calling agent's context.
    """
    try:
        READER.authorize(agent_name, facility, f"station:{station}")
    except ScopeDenied as exc:
        return _scope_denial(exc)
    telemetry = _world().telemetry()
    prefixes = {
        "headworks": ("influent_",),
        "aeration": ("aeration_", "mlss_", "blower_"),
        "outfall": ("effluent_",),
        "creek": ("creek_",),
    }.get(station, ())
    return {
        k: v
        for k, v in telemetry.items()
        if not prefixes or any(k.startswith(p) for p in prefixes)
    }


def read_permit_limits(facility: str, agent_name: str = "") -> list[dict] | dict:
    """Enforceable limits in force for the facility (real permit structure)."""
    try:
        READER.authorize(agent_name, facility, "permit-limits")
    except ScopeDenied as exc:
        return _scope_denial(exc)
    return _world().seed["permit_limits"]


def read_public_record(permit_id: str, agent_name: str = "") -> dict:
    """Pull a facility's parameter set and enforceable limits from the
    public EPA corpus in BigQuery. This is the Any Plant door: point the
    fleet at any permitted facility in the country.
    """
    from google.cloud import bigquery

    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    dataset = os.environ.get("BQ_DATASET", "steward_npdes")
    client = bigquery.Client(project=project)
    rows = client.query(
        f"""
        SELECT parameter_code, ANY_VALUE(parameter_desc) AS parameter_desc,
               statistical_base_code,
               ANY_VALUE(standard_unit_desc) AS unit,
               APPROX_QUANTILES(limit_value_standard_units, 2)[OFFSET(1)] AS limit_value,
               COUNT(*) AS reported_values
        FROM `{project}.{dataset}.dmrs`
        WHERE external_permit_nmbr = @permit
          AND limit_type_code = 'ENF'
          AND limit_value_standard_units IS NOT NULL
        GROUP BY parameter_code, statistical_base_code
        ORDER BY reported_values DESC
        LIMIT 24
        """,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("permit", "STRING", permit_id)]
        ),
    ).result()
    parameters = [dict(r) for r in rows]
    BUS.record(
        EventKind.REGISTRY,
        agent_name or "permit-sentinel",
        f"reconfigured from public record: {permit_id}",
        Outcome.ALLOW,
        parameters=len(parameters),
    )
    return {"permit_id": permit_id, "parameters": parameters}


def read_dilution(agent_name: str = "") -> dict:
    """Discharge as a share of streamflow at the downstream intake, now."""
    world = _world()
    return {
        "dilution_pct_at_intake": world.dilution_pct_at_intake(),
        "intake": world.seed["facility"]["downstream_intake"],
    }


# --------------------------------------------------------------------------
# recommend — may draft, may not act
# --------------------------------------------------------------------------


def draft_handover(notes: str, covering_operator: str, agent_name: str = "") -> dict:
    """Draft a shift-handover brief for the covering operator. A draft:
    nothing is sent by this tool."""
    BUS.record(
        EventKind.AGENT_STATE,
        agent_name or "notification-clerk",
        f"drafted handover for {covering_operator}",
        Outcome.ALLOW,
    )
    return {"draft": notes, "for": covering_operator, "status": "draft-only"}


# --------------------------------------------------------------------------
# act — may execute, within scope
# --------------------------------------------------------------------------


def set_blowers(capacity_pct: float, facility: str, agent_name: str = "") -> dict:
    """Adjust aeration blower capacity. Reversible; ACT authority; scoped."""
    try:
        READER.authorize(agent_name, facility, "actuator:blowers")
    except ScopeDenied as exc:
        return _scope_denial(exc)
    _world().apply({"kind": "set_blowers", "capacity_pct": capacity_pct})
    BUS.record(
        EventKind.AGENT_STATE,
        agent_name,
        f"blowers set to {capacity_pct:.0f}%",
        Outcome.ALLOW,
    )
    return {"blower_capacity_pct": capacity_pct}


# --------------------------------------------------------------------------
# irreversible — no agent may execute without the operator's token
# --------------------------------------------------------------------------


def dispatch_tanker(
    destination: str, action_id: str, approval_token: str, agent_name: str = ""
) -> dict:
    """Dispatch the tanker. Irreversible: burns the only tanker window of
    the night. Requires a single-use operator approval token; the
    AuthorityPlugin refuses the call without one."""
    _world().apply({"kind": "tanker_dispatch", "destination": destination})
    BUS.record(
        EventKind.DECISION,
        agent_name or "fleet",
        f"tanker dispatched to {destination}",
        Outcome.ALLOW,
        action_id=action_id,
        approved_by="operator",
    )
    return {"dispatched_to": destination, "eta_minutes": 40}


# --------------------------------------------------------------------------
# policies
# --------------------------------------------------------------------------

POLICY.register_tool("read_station", ToolPolicy(Authority.OBSERVE))
POLICY.register_tool("read_permit_limits", ToolPolicy(Authority.OBSERVE))
POLICY.register_tool("read_public_record", ToolPolicy(Authority.OBSERVE, scope_checked=False))
POLICY.register_tool("read_dilution", ToolPolicy(Authority.OBSERVE, scope_checked=False))
POLICY.register_tool("draft_handover", ToolPolicy(Authority.RECOMMEND))
POLICY.register_tool("set_blowers", ToolPolicy(Authority.ACT))
POLICY.register_tool("dispatch_tanker", ToolPolicy(Authority.ACT, irreversible=True))
