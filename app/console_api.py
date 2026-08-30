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
from app.fleet.events import BUS, EventKind, Outcome
from app.fleet.identity import describe_scopes
from app.fleet.memory import MEMORY

router = APIRouter(prefix="/api")


def _ensure_shift() -> None:
    """Boot the shift loop on first console contact (idempotent).

    The generated ADK app owns the ASGI lifespan, so the loop starts
    lazily here rather than in a startup hook — same behaviour under
    uvicorn locally, Cloud Run, and Agent Runtime.
    """
    seed = os.environ.get("STEWARD_FACILITY_SEED", "fixtures/seeds/cedar-ridge.json")
    if not os.path.isabs(seed):
        # Anchor to the repo root so the loop boots regardless of the
        # process's working directory (uvicorn, Agent Runtime, tests).
        seed = os.path.join(os.path.dirname(os.path.dirname(__file__)), seed)
    if os.environ.get("STEWARD_SHIFT", "1") == "1" and os.path.exists(seed):
        shift.boot(seed)


@router.get("/events")
async def events() -> StreamingResponse:
    _ensure_shift()

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
    _ensure_shift()
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
                # Which agents raised this. The console lights their cards,
                # so a request reads as coming from someone rather than
                # appearing in a queue nobody owns.
                "asked_by": sorted(
                    {o.get("offered_by", "") for o in d.options if o.get("offered_by")}
                ),
            }
            for d in s.pending.values()
        ],
        "obligations_degraded": s.obligations_degraded,
        "week": s.week,
        # This process's own clock. Deliberately named for what it is:
        # it resets on a cold start, and the Agent Runtime engine's age
        # is a different number entirely (see /api/runtime).
        "shift_seconds": __import__("time").time() - s.started_at,
        "minutes_on_shift": round(loop.world.minutes, 1),
    }


# The engine's age is a property of the platform, not of this process.
# Cached because it never changes between deploys and the console asks
# often.
_RUNTIME_CACHE: dict[str, object] = {}


@router.get("/runtime")
async def runtime() -> dict:
    """How long the Agent Runtime engine has actually been deployed.

    The console used to show this process's own uptime under an "Agent
    Runtime" label, which reset on every Cloud Run cold start and was
    therefore both wrong and unflattering. The engine is a platform
    resource with its own lifetime; this reports that, and says plainly
    that the shift loop's own clock is a separate thing.
    """
    import time as _t
    import urllib.request

    now = _t.time()
    if _RUNTIME_CACHE.get("at", 0) and now - float(_RUNTIME_CACHE["at"]) < 600:
        return dict(_RUNTIME_CACHE["value"])  # type: ignore[arg-type]

    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    region = os.environ.get("AGENT_RUNTIME_LOCATION", "us-central1")
    engine = os.environ.get("AGENT_ENGINE_MEMORY_BANK", "").rsplit("/", 1)[-1] or os.environ.get(
        "GOOGLE_CLOUD_AGENT_ENGINE_ID", ""
    )
    out: dict[str, object] = {"engine_id": engine, "region": region}
    if project and engine:
        try:
            import google.auth
            import google.auth.transport.requests

            creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            creds.refresh(google.auth.transport.requests.Request())
            url = (
                f"https://{region}-aiplatform.googleapis.com/v1/projects/{project}"
                f"/locations/{region}/reasoningEngines/{engine}"
            )
            req = urllib.request.Request(
                url, headers={"Authorization": f"Bearer {creds.token}"}
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                d = json.load(r)
            created = d.get("createTime", "")
            import datetime as _dt

            t = _dt.datetime.fromisoformat(created.replace("Z", "+00:00"))
            age = _dt.datetime.now(_dt.UTC) - t
            out.update(
                {
                    "deployed_at": created,
                    "age_seconds": age.total_seconds(),
                    "identity_type": (d.get("spec") or {}).get("identityType"),
                    "display_name": d.get("displayName"),
                    "reachable": True,
                }
            )
        except Exception as exc:
            out.update({"reachable": False, "error": str(exc)[:120]})
    else:
        out.update({"reachable": False, "error": "no engine id configured"})
    _RUNTIME_CACHE["at"] = now
    _RUNTIME_CACHE["value"] = out
    return dict(out)


@router.get("/roster")
async def roster() -> dict:
    _ensure_shift()
    scopes = describe_scopes()
    facts = MEMORY.facts()
    registry = shift.LOOP.registry.roster() if shift.LOOP else []
    return {
        "grants": scopes,
        "learned_facts": facts,
        "registry": registry,
        # Which store is actually behind those facts — the console says
        # so rather than implying Memory Bank is live when it is not.
        "memory_backend": MEMORY.backend,
        "memory_hydrated": MEMORY.hydrated,
    }


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


class RegistrySearch(BaseModel):
    role: str


@router.post("/registry/search")
async def registry_search(req: RegistrySearch) -> dict:
    """Search the Agent Registry for a role, the way the fleet does.

    The operator can do what the fleet does when a condition surfaces a
    role nobody catalogued: ask the registry who publishes it.
    """
    _ensure_shift()
    if shift.LOOP is None:
        return {"error": "shift loop not started"}
    reg = shift.LOOP.registry
    found = await asyncio.to_thread(reg.search, req.role.strip())
    if found is None:
        return {"role": req.role, "found": False}
    return {
        "role": req.role, "found": True, "name": found.name,
        "publisher": found.publisher, "department": found.department,
        "description": found.description, "version": found.version,
        "pinned": found.pinned, "satisfies_pin": found.satisfies_pin(),
        "source": found.source, "skills": found.skills,
        "mounted": found.name in reg._mounted,
    }


@router.get("/registry/list")
async def registry_list() -> dict:
    """Everything this project knows about — the fleet's own catalog and
    whatever the managed registry holds.

    An operator does not know the name of every capability that exists,
    so browsing has to be possible; searching by exact role only helps
    someone who already knows what to type.
    """
    _ensure_shift()
    if shift.LOOP is None:
        return {"agents": []}
    reg = shift.LOOP.registry
    # The standing crew is already on shift. Offering to "mount" an agent
    # the operator can see working two rows below would be a lie about
    # what the button does, so they are marked as the roster they are.
    on_shift = {g["identity"].split("@")[0] for g in describe_scopes()}
    out = {}
    for e in reg.roster():
        standing = e["name"] in on_shift and e["name"] not in reg._mounted
        out[e["name"]] = {
            **e,
            "origin": "fleet catalog",
            "mounted": e["mounted"] or standing,
            "standing": standing,
        }

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project and os.environ.get("AGENT_REGISTRY", "on") != "off":
        try:
            import urllib.request

            import google.auth
            import google.auth.transport.requests

            creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            creds.refresh(google.auth.transport.requests.Request())
            loc = os.environ.get("AGENT_REGISTRY_LOCATION", "us-central1")
            base = f"https://agentregistry.googleapis.com/v1/projects/{project}/locations/{loc}"
            for kind in ("services", "agents"):
                req = urllib.request.Request(
                    f"{base}/{kind}",
                    headers={
                        "Authorization": f"Bearer {creds.token}",
                        "x-goog-user-project": project,
                    },
                )
                with urllib.request.urlopen(req, timeout=8) as r:
                    body = json.load(r)
                for item in body.get(kind, []):
                    card = (item.get("agentSpec") or {}).get("content") or {}
                    skills = card.get("skills") or []
                    name = card.get("name") or item.get("displayName", "")
                    if not name:
                        continue
                    pin = reg._pins.get(name, "")
                    out.setdefault(
                        name,
                        {
                            "name": name,
                            "publisher": (card.get("provider") or {}).get(
                                "organization", item.get("displayName", "")
                            ),
                            "description": card.get("description")
                            or item.get("description", ""),
                            "version": card.get("version", ""),
                            # The pin is the consumer's, not the
                            # publisher's, so it applies to an agent
                            # however it was discovered — a version range
                            # that only shows up on one code path is not a
                            # policy, it is a coincidence.
                            "pinned": pin,
                            "satisfies_pin": (
                                not pin
                                or card.get("version", "0.0.0").split(".")[0]
                                == pin.lstrip("^~>=<! ").split(".")[0]
                            ),
                            "mounted": False,
                            "origin": "Agent Registry",
                            "skills": [x.get("id", "") for x in skills],
                        },
                    )
        except Exception as exc:
            return {"agents": list(out.values()), "registry_error": str(exc)[:140]}
    return {"agents": list(out.values())}


class RegistryMount(BaseModel):
    role: str


@router.post("/registry/mount")
async def registry_mount(req: RegistryMount) -> dict:
    """Mount a discovered specialist. Refused if it fails the pin."""
    _ensure_shift()
    if shift.LOOP is None:
        return {"error": "shift loop not started"}
    entry = await asyncio.to_thread(shift.LOOP.registry.mount, req.role.strip())
    if entry is None:
        return {"mounted": False, "reason": "not found, or refused by the version pin"}
    if shift.LOOP.bypass_specialist is None and "bypass" in entry.name:
        from app.fleet.agents import workers

        shift.LOOP.bypass_specialist = workers.make_bypass_specialist()
        # A specialist nobody briefs is furniture. The shift loop consults
        # one the moment it mounts it; an operator mounting the same agent
        # from the console got an agent that was never asked anything —
        # and so never audited either. Fire-and-forget, because briefing
        # takes a model call and the operator's click must not wait on it.
        brief = asyncio.create_task(shift.LOOP.consult_specialist())
        shift.LOOP._jobs.add(brief)
        brief.add_done_callback(shift.LOOP._jobs.discard)
    return {"mounted": True, "name": entry.name, "version": entry.version,
            "publisher": entry.publisher, "source": entry.source}


@router.post("/registry/unmount")
async def registry_unmount(req: RegistryMount) -> dict:
    """Send a mounted specialist home.

    A visiting expert should not stay on the roster after the event that
    called for it; releasing one is the operator's call and lands on the
    record like any other.
    """
    _ensure_shift()
    if shift.LOOP is None:
        return {"error": "shift loop not started"}
    role = req.role.strip()
    reg = shift.LOOP.registry
    # The roster knows the agent by its identity's local part
    # ("bypass-specialist"); the registry knows it by its published role
    # ("wet-weather-bypass-specialist"). Release has to work from either,
    # because both are on screen.
    if role not in reg._mounted:
        role = next(
            (k for k in reg._mounted if k.endswith(role) or role.endswith(k)),
            role,
        )
    entry = reg._mounted.pop(role, None)
    if entry is None:
        return {"unmounted": False, "reason": "not mounted"}
    name = role.replace("-", "_")
    POLICY.grants.pop(name, None)
    POLICY.grants.pop("bypass_specialist", None)
    if "bypass" in role:
        shift.LOOP.bypass_specialist = None
    BUS.record(
        EventKind.REGISTRY,
        "agent-registry",
        f"released {role} v{entry.version} — the event it was mounted for is over",
        Outcome.INFO,
        publisher=entry.publisher,
        released_by="operator",
    )
    return {"unmounted": True, "name": role}


@router.get("/edge")
async def edge_status() -> dict:
    """The OT boundary: what Gemma is, and where it runs."""
    import urllib.request

    base = os.environ.get("EDGE_ENDPOINT", "https://steward-edge-i64yn4kmyq-uc.a.run.app")
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=8) as r:
            return {"reachable": True, "endpoint": base, **json.load(r)}
    except Exception as exc:
        return {"reachable": False, "endpoint": base, "error": str(exc)[:120]}


class EdgeNote(BaseModel):
    text: str


@router.post("/edge/transcribe")
async def edge_transcribe(note: EdgeNote) -> dict:
    """Send a round note through the boundary and show what comes back.

    The data-sovereignty claim, made touchable: raw text goes in, and
    only the de-identified form comes out.
    """
    import urllib.request

    base = os.environ.get("EDGE_ENDPOINT", "https://steward-edge-i64yn4kmyq-uc.a.run.app")
    body = json.dumps({"text": note.text}).encode()
    try:
        request = urllib.request.Request(
            f"{base}/transcribe", data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as r:
            out = json.load(r)
        BUS.record(
            EventKind.GUARD, "gemma-edge@ot-boundary",
            "round note de-identified on-plant — only this left the segment",
            Outcome.ALLOW, model=out.get("model"), path=out.get("path"))
        return {"raw": note.text, **out}
    except Exception as exc:
        return {"error": str(exc)[:160], "raw": note.text}


class Speak(BaseModel):
    text: str


@router.post("/speak")
async def speak(req: Speak):
    """The system's voice — Chirp 3 HD, a product surface, not a voice-over.

    The console captions every utterance it plays; if synthesis is
    unavailable the caption still carries the line (burned-in captions
    are the primary channel, voice is the secondary one).
    """
    from fastapi.responses import Response

    try:
        from google.cloud import texttospeech

        client = texttospeech.TextToSpeechClient()
        audio = client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=req.text[:500]),
            voice=texttospeech.VoiceSelectionParams(
                language_code="en-US", name="en-US-Chirp3-HD-Charon"
            ),
            audio_config=texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3, speaking_rate=1.04
            ),
        )
        return Response(content=audio.audio_content, media_type="audio/mpeg")
    except Exception as exc:
        return {"error": f"voice unavailable — captions carry the line: {exc}"[:200]}


@router.get("/finding/by-parameter")
async def finding_by_parameter() -> dict:
    """Where the TimesFM forecast earns its keep, per pollutant.

    The permit sentinel's exceedance outlook comes from this model; this
    is its measured record on the national corpus.
    """
    from google.cloud import bigquery

    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    dataset = os.environ.get("BQ_DATASET", "steward_npdes")
    try:
        client = bigquery.Client(project=project)
        rows = list(client.query(
            f"SELECT parameter_desc, facilities, exceedance_months, recall_pct, "
            f"median_lead_days FROM `{project}.{dataset}.finding_by_parameter` "
            f"ORDER BY exceedance_months DESC LIMIT 6").result())
        return {"parameters": [dict(r) for r in rows]}
    except Exception as exc:
        return {"error": f"unavailable: {exc}"[:200]}


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
    # The built console (console/dist) is served by the same service, so
    # one Cloud Run URL is the whole product: /console for the operator,
    # /api for the data, /a2a for other fleets, ADK's dev UI for judges.
    dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "console", "dist")
    if os.path.isdir(dist):
        from fastapi.staticfiles import StaticFiles

        app.mount("/console", StaticFiles(directory=dist, html=True), name="console")
