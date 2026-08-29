"""One door to the models, with the supervisor standing in it.

Every autonomous reasoning moment in the shift loop goes through
`ReasoningPool.ask()`: a real ADK Runner per worker, the strict JSON
contract from workers.py, and then — before anything reaches the operator
— the supervisor's audit of every numeric claim against its cited source.

Model endpoints fail; the fleet does not get to fail with them. On an
unreachable or misbehaving endpoint the pool returns the worker's
deterministic fallback line and records a SYSTEM row saying exactly that.
The fallback chain is documented in docs/operations.md. Nothing here is
ever silent.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types

from app.fleet.authority import POLICY, AuthorityPlugin
from app.fleet.events import BUS, EventKind, Outcome
from app.fleet.supervisor import (
    WALL_CLOCK_CEILING_S,
    Claim,
    Supervisor,
    TaskEnvelope,
)
from app.fleet.tracing import TRACER, mark_failed


@dataclass
class Reasoned:
    """A worker's audited utterance."""

    agent_name: str
    say: str
    proposal: dict | None
    claims: list[dict]
    audited: bool  # False → withheld: the operator never sees `say`
    fallback: bool = False
    raw: dict = field(default_factory=dict)


class ReasoningPool:
    def __init__(self, supervisor: Supervisor) -> None:
        self.supervisor = supervisor
        self._runners: dict[str, InMemoryRunner] = {}

    def _runner(self, agent: Agent) -> InMemoryRunner:
        if agent.name not in self._runners:
            self._runners[agent.name] = InMemoryRunner(
                app=App(
                    root_agent=agent,
                    name=f"steward-{agent.name.replace('_', '-')}",
                    plugins=[AuthorityPlugin()],
                )
            )
        return self._runners[agent.name]

    async def ask(
        self,
        agent: Agent,
        prompt: str,
        fallback_say: str,
        fallback_proposal: dict | None = None,
    ) -> Reasoned:
        envelope = TaskEnvelope(agent_name=agent.name, task=prompt[:80])
        grant = POLICY.grants.get(agent.name)
        with TRACER.start_as_current_span(f"steward.task {agent.name}") as task_span:
            task_span.set_attribute("steward.agent.name", agent.name)
            if grant is not None:
                task_span.set_attribute("steward.agent.identity", grant.identity)
                task_span.set_attribute("steward.agent.authority", grant.authority.name)
                task_span.set_attribute("steward.facility", grant.facility)
            task_span.set_attribute("steward.task", prompt[:80])
            return await self._ask_traced(
                agent, prompt, fallback_say, fallback_proposal, envelope, task_span
            )

    async def _ask_traced(
        self,
        agent: Agent,
        prompt: str,
        fallback_say: str,
        fallback_proposal: dict | None,
        envelope: TaskEnvelope,
        task_span,
    ) -> Reasoned:
        try:
            try:
                raw_text = await self._budgeted(agent, prompt, envelope)
            except Exception as exc:
                if "429" not in str(exc) and "RESOURCE_EXHAUSTED" not in str(exc):
                    raise
                # Shared-quota throttling deserves one paced retry before
                # the deterministic fallback takes over.
                await asyncio.sleep(12)
                raw_text = await self._budgeted(agent, prompt, envelope)
            parsed = _parse_contract(raw_text)
        except Exception as exc:
            BUS.record(
                EventKind.SYSTEM,
                agent.name.replace("_", "-"),
                "model endpoint unavailable — deterministic fallback used",
                Outcome.INFO,
                error=str(exc)[:200],
            )
            task_span.set_attribute("steward.fallback", True)
            mark_failed(task_span, "model unavailable — deterministic fallback")
            return Reasoned(
                agent_name=agent.name,
                say=fallback_say,
                proposal=fallback_proposal,
                claims=[],
                audited=True,
                fallback=True,
            )

        audited = True
        with TRACER.start_as_current_span("steward.audit") as audit_span:
            audit_span.set_attribute(
                "steward.claims.count", len(parsed.get("claims", []))
            )
            audited = self._audit_claims(agent, parsed, audit_span)
        task_span.set_attribute("steward.audited", audited)

        return Reasoned(
            agent_name=agent.name,
            say=parsed.get("say", fallback_say) if audited else "",
            proposal=parsed.get("proposal") if audited else None,
            claims=parsed.get("claims", []),
            audited=audited,
            raw=parsed,
        )

    def _audit_claims(self, agent: Agent, parsed: dict, audit_span) -> bool:
        """Every numeric claim, checked against the source it cited."""
        for claim in parsed.get("claims", []):
            ok = self.supervisor.audit(
                Claim(
                    agent_name=agent.name,
                    parameter=str(claim.get("parameter", "")),
                    value=float(claim.get("value", 0.0)),
                    source=claim.get("source") or None,
                )
            )
            if not ok:
                # A quarantine is a decision, not a crash — but it should
                # be findable by filtering errored spans.
                mark_failed(audit_span, f"claim withheld: {claim.get('parameter')}")
                return False
        return True

    async def _budgeted(self, agent: Agent, prompt: str, envelope: TaskEnvelope) -> str:
        """The wall-clock ceiling, actually enforced.

        The step budget is charged per event the runner yields — which
        cannot help if the call hangs *before* yielding anything. So the
        whole invocation sits inside a hard timeout: a worker that stops
        responding is stopped, quarantined, and re-issued, exactly like
        one that loops. Without this the ceiling in docs/operations.md
        would be a claim rather than a mechanism.
        """
        remaining = WALL_CLOCK_CEILING_S - (time.time() - envelope.started_at)
        try:
            return await asyncio.wait_for(
                self._invoke(agent, prompt, envelope), timeout=max(5.0, remaining)
            )
        except TimeoutError as exc:
            self.supervisor.stop_unresponsive(envelope)
            raise RuntimeError("wall-clock ceiling exceeded — worker stopped") from exc

    async def _invoke(self, agent: Agent, prompt: str, envelope: TaskEnvelope) -> str:
        runner = self._runner(agent)
        session_id = f"shift-{uuid.uuid4().hex[:8]}"
        await runner.session_service.create_session(
            app_name=runner.app_name, user_id="shift-loop", session_id=session_id
        )
        message = types.Content(role="user", parts=[types.Part(text=prompt)])
        final = ""
        async for event in runner.run_async(
            user_id="shift-loop", session_id=session_id, new_message=message
        ):
            if not self.supervisor.enforce_budget(envelope):
                raise RuntimeError("task budget exceeded — stopped by supervisor")
            if event.is_final_response() and event.content and event.content.parts:
                final = "".join(p.text or "" for p in event.content.parts)
        if not final:
            raise RuntimeError("empty final response")
        return final


def _parse_contract(text: str) -> dict[str, Any]:
    """Extract the JSON contract from a model response, tolerantly."""
    candidate = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    else:
        brace = re.search(r"\{.*\}", candidate, re.DOTALL)
        if brace:
            candidate = brace.group(0)
    parsed = json.loads(candidate)
    if not isinstance(parsed, dict):
        raise ValueError("contract is not an object")
    parsed.setdefault("claims", [])
    parsed.setdefault("proposal", None)
    parsed.setdefault("say", "")
    return parsed
