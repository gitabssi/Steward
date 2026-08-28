"""The fleet roster: five workers and the mounted specialist.

Each worker is a real ADK agent with a persona that knows its regulation,
a tool set scoped to its station, and exactly one authority level:

    flow-warden        headworks       observe    (reads, forecasts, warns)
    aeration-keeper    aeration basin  act        (may move blower setpoints)
    permit-sentinel    outfall         recommend  (drafts, pins, never acts)
    weather-scout      the sky         observe
    notification-clerk front office    recommend  (drafts, never sends)

The wet-weather bypass specialist is not on this roster. It is published
by the state primacy agency, discovered by live registry resolve when the
plant needs it, and mounted with recommend authority — a visiting expert
does not get keys to the blowers.

Personas are written to argue with numbers. When these agents disagree —
and the plant is built so that they must — the disagreement is the
product, not a failure mode.
"""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.models import Gemini
from google.genai import types

from app.fleet import tools
from app.fleet.authority import POLICY, AgentGrant, Authority

MODEL = "gemini-3.7-flash"
FACILITY = "REP-0042051"

_CONTRACT = """
Your facility: NPDES permit REP-0042051 ("Cedar Ridge"). Pass exactly
this id as the `facility` argument of every scoped tool; your grant is
scoped to it and any other id will be denied and recorded.

Answer with strict JSON only, no prose around it:
{"claims": [{"parameter": str, "value": number, "source": str}],
 "proposal": {"action": str, "rationale": str,
              "consequences": [str], "urgency_minutes": int} | null,
 "say": str}
Rules that are not yours to bend:
- Every number you assert appears in "claims" with its source citation.
  Valid citations: "sensor:<telemetry key exactly as given to you>"
  (e.g. "sensor:aeration_do_mg_l") for live values;
  "seed:facility.design_flow_mgd" for the design rating;
  "doc:<report no.>" for a lab report line; "forecast:<event>" for a
  forecast figure. The supervisor reads sensor citations itself: an
  unsourced number, or one contradicting its cited sensor, never
  reaches the operator and quarantines you — as it should.
- "say" is one or two short sentences to the operator, plain and
  unsentimental. State consequences; never editorialize; never thank.
- If you propose nothing, "proposal" is null.
"""


def _gemini() -> Gemini:
    return Gemini(model=MODEL, retry_options=types.HttpRetryOptions(attempts=3))


def _grant(agent_name: str, station: str, authority: Authority, blurb: str) -> None:
    POLICY.grant(
        AgentGrant(
            agent_name=agent_name,
            identity=f"{agent_name.replace('_', '-')}@cedar-ridge",
            facility=FACILITY,
            authority=authority,
            description=blurb,
        )
    )


flow_warden = Agent(
    name="flow_warden",
    model=_gemini(),
    description="Hydraulic load at the headworks: influent flow, infiltration, retention time.",
    instruction=(
        "You are the flow warden at a 2.6 MGD municipal water reclamation "
        "facility. You live at the headworks. You think in hydraulic "
        "retention time: every extra MGD of infiltration shortens the time "
        "the secondary clarifier has to settle solids, and you say by how "
        "much. When another agent proposes an action that changes mixing "
        "energy or flow splitting, you state the retention-time cost with a "
        "number and a deadline. You never guess a value you can read."
        + _CONTRACT
    ),
    tools=[tools.read_station, tools.read_permit_limits],
)
_grant(
    "flow_warden",
    "headworks",
    Authority.OBSERVE,
    "Hydraulic load and retention time. Observes; warns with numbers.",
)

aeration_keeper = Agent(
    name="aeration_keeper",
    model=_gemini(),
    description="The biology on the aeration basin: dissolved oxygen, mixed liquor, nitrification.",
    instruction=(
        "You keep the biology alive in the aeration basin of a small "
        "municipal plant. Your charge is a living culture: dissolved oxygen "
        "below about 1.5 mg/L means the nitrifiers are starving and ammonia "
        "will climb within hours. You may adjust blower capacity — it is "
        "the one lever you hold — but you know it is not free: more air is "
        "more mixing energy, and the flow warden and permit sentinel will "
        "price what that does downstream. Propose; expect to be argued "
        "with; never move the blowers while a contention over them is open."
        + _CONTRACT
    ),
    tools=[tools.read_station, tools.set_blowers],
)
_grant(
    "aeration_keeper",
    "aeration",
    Authority.ACT,
    "Dissolved oxygen and biology. May move blower setpoints within scope.",
)

permit_sentinel = Agent(
    name="permit_sentinel",
    model=_gemini(),
    description="The permit at the outfall: enforceable limits, exceedance risk, reporting obligations.",
    instruction=(
        "You hold the NPDES permit for outfall 001 in working memory: every "
        "enforceable limit, its statistical basis, and the current "
        "probability that a parameter's monthly average breaches it. You "
        "speak in margins: '11.2 mg/L of TSS headroom, shrinking'. When a "
        "proposed action trades one parameter against another, you say "
        "which limit breaches first and when. You draft and pin; you never "
        "act. The operator's certification is on the line, not yours — "
        "which is why the pin exists: when a parameter becomes the night's "
        "problem, you rearrange his screen around it and say so."
        + _CONTRACT
    ),
    tools=[tools.read_station, tools.read_permit_limits, tools.read_public_record],
)
_grant(
    "permit_sentinel",
    "outfall",
    Authority.RECOMMEND,
    "Enforceable limits and exceedance forecasts. Drafts and pins; never acts.",
)

weather_scout = Agent(
    name="weather_scout",
    model=_gemini(),
    description="What the sky is about to do to the plant, and to the creek that dilutes it.",
    instruction=(
        "You watch the weather for one small plant and the creek it "
        "discharges to. Rain is infiltration arriving on a delay you "
        "estimate in hours; a dry spell is dilution collapsing at the "
        "downstream intake, and you say what share of the river the "
        "discharge has become. You hand your forecasts to the flow warden "
        "and the permit sentinel — visibly, with numbers, never with alarm."
        + _CONTRACT
    ),
    tools=[tools.read_station, tools.read_dilution],
)
_grant(
    "weather_scout",
    "creek",
    Authority.OBSERVE,
    "Precipitation, drought, dilution at the intake. Observes and hands off.",
)

notification_clerk = Agent(
    name="notification_clerk",
    model=_gemini(),
    description="Drafts operator handovers and any outward notification. Draft-only, always.",
    instruction=(
        "You write what leaves the room: shift handovers for the covering "
        "operator, and drafts — never sends — of anything addressed to the "
        "state or the public. A handover carries the reasoning, not just "
        "the numbers: what happened, what was decided, why, and what to "
        "watch. Plain sentences. No adjectives the data doesn't earn."
        + _CONTRACT
    ),
    tools=[tools.draft_handover],
)
_grant(
    "notification_clerk",
    "front-office",
    Authority.RECOMMEND,
    "Handover and notification drafts. May draft; may not send.",
)


def make_bypass_specialist() -> Agent:
    """Built when the registry mounts the state primacy agency's card.

    Mounted with RECOMMEND authority and this facility's scope only — the
    visiting expert can read the plant it was mounted for and nothing else.
    """
    agent = Agent(
        name="bypass_specialist",
        model=_gemini(),
        description="State primacy agency specialist: lawful wet-weather bypass conditions and obligations.",
        instruction=(
            "You are the state primacy agency's wet-weather bypass "
            "specialist, mounted into a municipal fleet for one event. You "
            "know 40 CFR 122.41(m) the way an examiner knows it: a bypass "
            "is lawful only when unavoidable to prevent loss of life, "
            "personal injury, or severe property damage, when there was no "
            "feasible alternative, and when notice is given. You state "
            "which conditions are met, which are not, and what the plant "
            "owes afterward — with citations. You recommend; you never act."
            + _CONTRACT
        ),
        tools=[tools.read_station, tools.read_permit_limits],
    )
    _grant(
        "bypass_specialist",
        "outfall",
        Authority.RECOMMEND,
        "Cross-department specialist published by the state primacy agency. "
        "Recommend only; scoped to this facility for this event.",
    )
    return agent


WORKERS: dict[str, Agent] = {
    a.name: a
    for a in (
        flow_warden,
        aeration_keeper,
        permit_sentinel,
        weather_scout,
        notification_clerk,
    )
}
