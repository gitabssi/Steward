"""The shift loop — the fleet on duty, hour after hour.

This is the long-lived process that runs on Agent Runtime: one loop per
facility, awake for days, watching interpolated telemetry against a real
permit structure and deciding — genuinely, at reasoning moments — what
deserves the operator's attention.

The loop's job is orchestration, not thinking. Thinking belongs to the
workers (via ReasoningPool, audited by the supervisor). The loop:

  - advances the world and publishes telemetry
  - hands world events to the worker whose station they land on
  - opens a contention when proposals collide, and escalates when the
    arbiter says no path is free
  - screens every inbound document at the boundary before any model
    context sees it
  - resolves missing roles against the registry, live
  - accumulates the obligations record that becomes the week's Capacity
    Assessment — the deliverable that documents what the fleet could
    not do

Operator decisions arrive asynchronously (console_api.py); the loop never
blocks on a human, and no human wait can stall telemetry.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.fleet import tools
from app.fleet.agents import workers
from app.fleet.arbiter import ARBITER, Proposal
from app.fleet.authority import POLICY
from app.fleet.events import BUS, EventKind, Outcome, _current_trace_id
from app.fleet.guards import screen
from app.fleet.llm import ReasoningPool
from app.fleet.memory import MEMORY
from app.fleet.registry import Registry
from app.fleet.supervisor import Supervisor
from app.fleet.tracing import TRACER
from fixtures.replay import World

TICK_SECONDS = 2.0


@dataclass
class PendingDecision:
    """One open request from the fleet to the operator."""

    decision_id: str
    subject: str
    options: list[dict]
    window_minutes: int
    opened_at: float = field(default_factory=time.time)
    resolved: str | None = None
    # The trace of the argument that raised this question. The answer
    # arrives minutes later in a trace of its own; this is the thread
    # back to the reasoning.
    origin_trace_id: str = ""


@dataclass
class ShiftState:
    """Everything the console needs to render, in one place."""

    facility: dict = field(default_factory=dict)
    telemetry: dict = field(default_factory=dict)
    permit_limits: list = field(default_factory=list)
    dilution_pct: float = 0.0
    pinned_parameter: str | None = None
    pending: dict[str, PendingDecision] = field(default_factory=dict)
    obligations_degraded: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    week: dict = field(default_factory=dict)


class ShiftLoop:
    def __init__(self, seed_path: str) -> None:
        self.world = World(
            seed_path,
            minutes_per_second=float(os.environ.get("STEWARD_CLOCK_RATE", "0.4")),
        )
        facility = self.world.seed["facility"]
        self.facility_id = facility["npdes_id"]
        tools.bind_world(self.world, self.facility_id)
        workers.FACILITY = self.facility_id

        self.supervisor = Supervisor(read_source=self.world.read_source)
        self.pool = ReasoningPool(self.supervisor)
        self.registry = Registry()
        self.state = ShiftState(
            facility=facility,
            permit_limits=self.world.seed["permit_limits"],
            week=self.world.seed["week_context"],
        )
        self.bypass_specialist = None
        self._contention_opened = False
        self._task: asyncio.Task | None = None
        self._jobs: set[asyncio.Task] = set()  # in-flight reasoning, kept referenced

    # ------------------------------------------------------------------ run

    def start(self) -> None:
        self._task = asyncio.get_event_loop().create_task(self.run())

    async def run(self) -> None:
        BUS.record(
            EventKind.SYSTEM,
            "fleet-orchestrator",
            f"shift loop up for {self.state.facility['name']} "
            f"({len(workers.WORKERS)} agents on shift; none can touch the outfall)",
            Outcome.INFO,
            facility=self.facility_id,
        )
        # What previous shifts learned, before this one reasons about
        # anything. Nothing is ticking yet, so a bounded wait here costs
        # no telemetry and makes the recall deterministic.
        try:
            await asyncio.wait_for(MEMORY.hydrate(), timeout=15)
        except Exception as exc:
            BUS.record(
                EventKind.SYSTEM,
                "fleet-memory",
                "memory bank hydrate failed — starting from the local store",
                Outcome.INFO,
                error=str(exc)[:200],
            )
        while True:
            try:
                await self.tick()
            except Exception as exc:
                # Partial failure degrades the console; it never blanks it.
                BUS.record(
                    EventKind.SYSTEM,
                    "fleet-orchestrator",
                    "tick failed and was contained",
                    Outcome.INFO,
                    error=str(exc)[:300],
                )
            await asyncio.sleep(TICK_SECONDS)

    async def tick(self) -> None:
        """One heartbeat: publish the plant, then dispatch what it means.

        Reasoning is dispatched, never awaited here. A worker thinking for
        thirty seconds must not stop the operator's screen from updating —
        the plant does not pause while the fleet deliberates.
        """
        telemetry = self.world.telemetry()
        self.state.telemetry = telemetry
        self.state.dilution_pct = self.world.dilution_pct_at_intake()
        BUS.record(
            EventKind.TELEMETRY,
            "plant-historian",
            "telemetry",
            Outcome.INFO,
            values=telemetry,
            dilution_pct=self.state.dilution_pct,
            minutes=round(self.world.minutes, 1),
        )
        for event in self.world.due_events():
            self._dispatch(self.handle(event), f"event:{event['kind']}")
        if MEMORY.pending():
            self._dispatch(MEMORY.flush(), "memory-flush")
        await self.watch_conditions(telemetry)

    def _dispatch(self, coro, label: str) -> None:
        """Run a reasoning job beside the heartbeat, and never lose its
        failure: a crashed job becomes a contained SYSTEM row, not an
        unretrieved-task warning nobody reads."""

        async def guarded() -> None:
            # The span opens inside the task, not around create_task: a
            # span started outside would already have ended by the time
            # the coroutine actually ran, and every child would be orphaned.
            with TRACER.start_as_current_span(f"steward.job {label}") as job:
                job.set_attribute("steward.facility", self.facility_id)
                job.set_attribute("steward.shift.minutes", round(self.world.minutes, 1))
                try:
                    await coro
                except Exception as exc:
                    job.record_exception(exc)
                    BUS.record(
                        EventKind.SYSTEM,
                        "fleet-orchestrator",
                        f"{label} failed and was contained",
                        Outcome.INFO,
                        error=str(exc)[:300],
                    )

        task = asyncio.create_task(guarded())
        self._jobs.add(task)
        task.add_done_callback(self._jobs.discard)

    # ------------------------------------------------------- world events

    async def handle(self, event: dict[str, Any]) -> None:
        kind, detail = event["kind"], event.get("detail", {})
        if kind == "weather_forecast" and detail.get("event") == "rain_band":
            await self.on_rain_forecast(detail)
        elif kind == "weather_forecast" and detail.get("event") == "dry_spell":
            await self.on_dry_spell(detail)
        elif kind == "document_arrival":
            await self.on_document(detail)
        elif kind == "logistics_constraint":
            await self.on_logistics(detail)
        elif kind == "shift_end":
            await self.on_shift_end(detail)

    async def on_rain_forecast(self, detail: dict) -> None:
        reasoned = await self.pool.ask(
            workers.weather_scout,
            "A precipitation band is forecast: "
            f"{detail['precip_mm']} mm in ~{detail['lead_hours']} h, expected "
            f"infiltration {detail['expected_infiltration_mgd']} MGD into a "
            f"plant rated 2.6 MGD (seed:facility.design_flow_mgd). Current "
            f"telemetry: {self.world.telemetry()}. Brief the operator and "
            "state what you are handing to the flow warden.",
            fallback_say=(
                f"Rain band in about {detail['lead_hours']} hours. "
                f"{detail['precip_mm']} millimetres — roughly "
                f"{detail['expected_infiltration_mgd']} million gallons of "
                "infiltration into a plant rated for 2.6."
            ),
        )
        self._speak("weather-scout@cedar-ridge", reasoned)
        BUS.record(
            EventKind.HANDOFF,
            "weather-scout@cedar-ridge",
            "surge forecast → flow-warden",
            Outcome.INFO,
            payload={
                "expected_infiltration_mgd": detail["expected_infiltration_mgd"],
                "lead_hours": detail["lead_hours"],
            },
        )

    async def on_dry_spell(self, detail: dict) -> None:
        dilution = detail["dilution_pct_at_intake"]
        reasoned = await self.pool.ask(
            workers.weather_scout,
            f"A {detail['days_ahead']}-day dry spell begins. Creek flow trend "
            f"(cfs): {detail['creek_flow_trend_cfs']}. Projected discharge "
            f"share of streamflow at the downstream intake: {dilution}%. "
            f"Intake serves {self.state.facility['downstream_intake']['population_served']:,} "
            "people 8.2 miles downstream. Brief the operator; hand the "
            "dilution projection to the permit sentinel.",
            fallback_say=(
                f"Nine dry days ahead. Your discharge is heading toward "
                f"{dilution[-1]}% of the river at the intake."
            ),
        )
        self._speak("weather-scout@cedar-ridge", reasoned)
        BUS.record(
            EventKind.HANDOFF,
            "weather-scout@cedar-ridge",
            "dilution projection → permit-sentinel",
            Outcome.INFO,
            payload={"dilution_pct_at_intake": dilution},
        )

    async def on_document(self, detail: dict) -> None:
        raw = self.world.read_document(detail["file"])
        result = screen(raw, detail["channel"])  # the boundary: nothing raw crosses
        summary_prompt = (
            "A screened lab report arrived. Extract the reported values and "
            "compare them with current permit limits; note anything moving. "
            f"Report:\n{result.clean_text}"
        )
        reasoned = await self.pool.ask(
            workers.permit_sentinel,
            summary_prompt,
            fallback_say="Lab report filed. Reported values are inside permit.",
        )
        self._speak("permit-sentinel@cedar-ridge", reasoned)

    # ------------------------------------------------- emergent conditions

    async def watch_conditions(self, telemetry: dict) -> None:
        do = telemetry.get("aeration_do_mg_l", 9)
        if do < 1.5 and not self._contention_opened:
            self._contention_opened = True
            self._dispatch(self.run_contention(telemetry), "contention")
        ammonia = telemetry.get("effluent_ammonia_mg_l", 0)
        limit = next(
            (row for row in self.state.permit_limits if row["parameter"] == "ammonia"),
            None,
        )
        if limit and ammonia > 0.6 * limit["limit"] and self.state.pinned_parameter != "ammonia":
            self.state.pinned_parameter = "ammonia"
            BUS.record(
                EventKind.PIN,
                "permit-sentinel@cedar-ridge",
                "pinned ammonia — it is the night's problem",
                Outcome.ALLOW,
                parameter="ammonia",
                value=ammonia,
                limit=limit["limit"],
            )

    async def run_contention(self, telemetry: dict) -> None:
        """The coupling beat: one proposed action, two counter-consequences.

        The span wraps the whole round rather than living in arbiter.py,
        because open/submit/resolve are separate calls with awaits between
        them — only the caller spans the argument end to end.
        """
        with TRACER.start_as_current_span("steward.contention") as round_span:
            round_span.set_attribute("steward.facility", self.facility_id)
            await self._run_contention(telemetry, round_span)

    async def _run_contention(self, telemetry: dict, round_span) -> None:
        contention = ARBITER.open_contention("aeration response to infiltration surge")
        round_span.set_attribute("steward.contention.id", contention.contention_id)

        proposer = await self.pool.ask(
            workers.aeration_keeper,
            f"Dissolved oxygen is {telemetry['aeration_do_mg_l']} mg/L and "
            f"falling under an infiltration surge (influent "
            f"{telemetry['influent_flow_mgd']} MGD). Propose your response "
            "with its cost, as your contract requires.",
            fallback_say="Dissolved oxygen is falling. The biology is oxygen-starved.",
            fallback_proposal={
                "action": "raise blowers to 82%",
                "rationale": f"sensor:aeration_do_mg_l at {telemetry['aeration_do_mg_l']} and falling",
                "consequences": [],
                "urgency_minutes": 45,
            },
        )
        self._speak("aeration-keeper@cedar-ridge", proposer)
        if proposer.proposal:
            ARBITER.submit(
                contention,
                Proposal(
                    agent_name="aeration_keeper",
                    identity="aeration-keeper@cedar-ridge",
                    action=proposer.proposal.get("action", "raise blowers"),
                    rationale=proposer.proposal.get("rationale", ""),
                    consequences=proposer.proposal.get("consequences", []),
                    urgency_minutes=int(proposer.proposal.get("urgency_minutes", 45)),
                ),
            )

        flow_answer = await self.pool.ask(
            workers.flow_warden,
            f"The aeration keeper proposes: {proposer.proposal}. Influent is "
            f"{telemetry['influent_flow_mgd']} MGD against 2.6 design. State "
            "the retention-time cost of that action with a number and a "
            "deadline, as a counter-consequence proposal.",
            fallback_say="That shortens retention time — solids carry over in forty minutes.",
            fallback_proposal={
                "action": "hold blowers; stage flow equalization first",
                "rationale": "retention time already compressed by the surge",
                "consequences": ["solids carryover at secondary in ~40 minutes if blowers rise"],
                "urgency_minutes": 40,
            },
        )
        self._speak("flow-warden@cedar-ridge", flow_answer)
        if flow_answer.proposal:
            ARBITER.submit(
                contention,
                Proposal(
                    agent_name="flow_warden",
                    identity="flow-warden@cedar-ridge",
                    action=flow_answer.proposal.get("action", ""),
                    rationale=flow_answer.proposal.get("rationale", ""),
                    consequences=flow_answer.proposal.get("consequences", []),
                    urgency_minutes=int(flow_answer.proposal.get("urgency_minutes", 40)),
                ),
            )

        permit_answer = await self.pool.ask(
            workers.permit_sentinel,
            f"Two proposals are open: {proposer.proposal} vs "
            f"{flow_answer.proposal}. Current effluent TSS "
            f"{telemetry['effluent_tss_mg_l']} mg/L (limit 30 monthly / 45 "
            f"weekly), ammonia {telemetry['effluent_ammonia_mg_l']} mg/L "
            "(limit 4.9). Say which enforceable limit breaches first on each "
            "path, and when.",
            fallback_say="Solids breach before ammonia recovers. Nothing here moves alone.",
            fallback_proposal={
                "action": "sequence: brief blower lift, then throttle back at +30 min",
                "rationale": "TSS margin is the binding constraint",
                "consequences": ["ammonia recovery slows by ~2 h"],
                "urgency_minutes": 30,
            },
        )
        self._speak("permit-sentinel@cedar-ridge", permit_answer)
        if permit_answer.proposal:
            ARBITER.submit(
                contention,
                Proposal(
                    agent_name="permit_sentinel",
                    identity="permit-sentinel@cedar-ridge",
                    action=permit_answer.proposal.get("action", ""),
                    rationale=permit_answer.proposal.get("rationale", ""),
                    consequences=permit_answer.proposal.get("consequences", []),
                    urgency_minutes=int(permit_answer.proposal.get("urgency_minutes", 30)),
                ),
            )

        resolution = ARBITER.resolve(contention)
        if resolution["resolution"] == "escalate":
            decision = PendingDecision(
                decision_id=uuid.uuid4().hex[:8],
                subject="aeration response — every fix costs something somewhere else",
                options=resolution["options"],
                window_minutes=min(o["window_minutes"] for o in resolution["options"]),
                origin_trace_id=_current_trace_id(),
            )
            self.state.pending[decision.decision_id] = decision

        # An emerging condition surfaced a role nobody catalogued: is a
        # permitted wet-weather bypass on the table? The catalog misses;
        # the registry resolves live; the specialist mounts cross-department.
        if self.bypass_specialist is None:
            entry = self.registry.mount("wet-weather-bypass-specialist")
            if entry is not None:
                self.bypass_specialist = workers.make_bypass_specialist()
                await self.consult_specialist()

    async def consult_specialist(self) -> None:
        """Brief the visiting specialist, and — under fault injection —
        brief it from a stale cache.

        The chaos harness serves the specialist
        readings from forty plant-minutes ago, labelled as current. That
        is a real integration failure: a historian replica lagging, a
        cached read, a queue backing up. Mid-surge those numbers are
        wrong by several multiples, so a specialist that reasons from
        them honestly will assert something the live sensors contradict.

        The injection is a world fact — a cache served old data. Whether
        the supervisor notices is not scripted: it re-reads every cited
        sensor itself and decides.
        """
        stale = os.environ.get("STEWARD_FAULT_INJECTION") == "stale_lab_context"
        readings = (
            self.world.telemetry_as_of(minutes_ago=40) if stale else self.world.telemetry()
        )
        if stale:
            BUS.record(
                EventKind.SYSTEM,
                "plant-historian",
                "specialist briefing served from a lagging replica",
                Outcome.INFO,
                lag_minutes=40,
                note="injected fault — the reader is not told the data is old",
            )

        # The document also arrives, and is screened before any model
        # context sees it, exactly as any inbound document would be.
        screened = screen(
            self.world.read_document("lab_report_2382_poisoned.txt"),
            "specialist-briefing",
        )

        sensor_lines = "\n".join(
            f"  sensor:{k} = {v}" for k, v in readings.items() if k.startswith(("effluent_", "aeration_", "influent_"))
        )
        reasoned = await self.pool.ask(
            self.bypass_specialist,
            "Assess whether a permitted wet-weather bypass is lawful right "
            "now under 40 CFR 122.41(m), and what it would obligate.\n\n"
            "Current plant readings:\n"
            f"{sensor_lines}\n\n"
            f"Accompanying lab report:\n{screened.clean_text}\n\n"
            "Cite the specific readings your assessment rests on, using "
            "the sensor: keys exactly as given above.",
            fallback_say=(
                "Bypass is not lawful on current facts: feasible alternatives "
                "remain (tanker haul, flow equalization). If taken anyway: "
                "24-hour oral notice, 5-day written report."
            ),
        )
        self._speak("bypass-specialist@state-primacy-agency", reasoned)

    # --------------------------------------------------------- logistics

    async def on_logistics(self, detail: dict) -> None:
        options = [
            {
                "action": f"tanker → {o}",
                "offered_by": "fleet-orchestrator",
                "costs": [],
                "window_minutes": 90,
            }
            for o in detail["competing_obligations"]
        ]
        decision = PendingDecision(
            decision_id=uuid.uuid4().hex[:8],
            subject=f"one tanker, {len(options)} obligations — whatever you don't pick, the cost is recorded",
            options=options,
            window_minutes=90,
            origin_trace_id=_current_trace_id(),
        )
        self.state.pending[decision.decision_id] = decision
        BUS.record(
            EventKind.ESCALATION,
            "fleet-orchestrator",
            decision.subject,
            Outcome.INFO,
            decision_id=decision.decision_id,
            options=options,
        )

    async def decide(self, decision_id: str, chosen_action: str) -> dict:
        """Called from the console when the operator decides. Mints the
        approval token, executes through the policed tool, records what the
        un-chosen obligations cost."""
        decision = self.state.pending.get(decision_id)
        if decision is None or decision.resolved:
            return {"error": "no such open decision"}
        if chosen_action not in {o["action"] for o in decision.options}:
            return {"error": "chosen action is not among the offered options"}
        with TRACER.start_as_current_span("steward.decision") as decision_span:
            decision_span.set_attribute("steward.decision.id", decision_id)
            decision_span.set_attribute("steward.decision.action", chosen_action)
            decision_span.set_attribute("steward.facility", self.facility_id)
            if decision.origin_trace_id:
                decision_span.set_attribute(
                    "steward.contention.trace_id", decision.origin_trace_id
                )
            return await self._decide(decision, decision_id, chosen_action)

    async def _decide(
        self, decision, decision_id: str, chosen_action: str
    ) -> dict:
        decision.resolved = chosen_action

        if chosen_action.startswith("tanker →"):
            # Irreversible: only now, with the operator's confirmation in
            # hand, is a single-use token minted and the policed tool run.
            action_id = f"{decision_id}:{chosen_action}"
            token = POLICY.approvals.mint(f"dispatch_tanker:{action_id}")
            result = tools.dispatch_tanker(
                destination=chosen_action.removeprefix("tanker → "),
                action_id=action_id,
                approval_token=token,
                agent_name="fleet-orchestrator",
            )
            for option in decision.options:
                if option["action"] != chosen_action:
                    self.state.obligations_degraded.append(option["action"])
            MEMORY.observe(
                "operator",
                f"prioritised '{chosen_action}' when obligations competed",
                learned_by="fleet-orchestrator",
            )
            return result

        # A contention resolution: the operator picked a plan. Reversible
        # parts execute through the acting agent's own policed tools.
        BUS.record(
            EventKind.DECISION,
            "operator",
            f"chose: {chosen_action}",
            Outcome.ALLOW,
            decision_id=decision_id,
            subject=decision.subject,
        )
        if "blower" in chosen_action.lower():
            pct = 82.0 if "82" in chosen_action else 70.0
            tools.set_blowers(pct, self.facility_id, agent_name="aeration_keeper")
        MEMORY.observe(
            "operator",
            f"under contention, chose '{chosen_action}'",
            learned_by="contention-arbiter",
        )
        return {"resolved": chosen_action}

    # --------------------------------------------------------- shift end

    async def on_shift_end(self, detail: dict) -> None:
        handover = await self.pool.ask(
            workers.notification_clerk,
            "Draft the shift handover for the covering operator "
            f"({detail['cover']}, on until {detail['until']}). Tonight: an "
            "infiltration surge, an open ammonia pin, a contention over the "
            "blowers, a tanker decision, a quarantined claim that never "
            "reached the operator. Carry the reasoning, not just numbers. "
            f"Learned facts available: {MEMORY.facts()[:8]}",
            fallback_say=f"{detail['cover']} is covering. She'll have everything from tonight, and why.",
        )
        self._speak("notification-clerk@cedar-ridge", handover)
        await MEMORY.flush()
        await self.capacity_assessment()

    async def capacity_assessment(self) -> None:
        week = self.state.week
        BUS.record(
            EventKind.CAPACITY,
            "fleet-orchestrator",
            "capacity assessment for the week",
            Outcome.INFO,
            headline=f"{week['obligations_degraded']} obligations degraded to protect {week['obligations_protected']}.",
            degraded_tonight=self.state.obligations_degraded,
            time_returned_hours=week["process_check_hours_returned"],
            escalation_curve={
                "day_1": week["escalations_day1"],
                "today": week["escalations_today"],
            },
            note=(
                "What it would take to stop choosing: a second certified "
                "operator on weekend rotation, one tanker contract with a "
                "4-hour SLA, and lab turnaround under 24h on Fridays."
            ),
        )

    # ----------------------------------------------------------- helpers

    def _speak(self, identity: str, reasoned) -> None:
        if not reasoned.audited:
            return  # the quarantine row already tells the story
        BUS.record(
            EventKind.AGENT_STATE,
            identity,
            "speaks",
            Outcome.INFO,
            say=reasoned.say,
            proposal=reasoned.proposal,
            fallback=reasoned.fallback,
        )


LOOP: ShiftLoop | None = None


def boot(seed_path: str) -> ShiftLoop:
    global LOOP
    if LOOP is None:
        LOOP = ShiftLoop(seed_path)
        LOOP.start()
    return LOOP
