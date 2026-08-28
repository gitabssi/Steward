"""The supervisor — the fleet's answer to a worker that loops or lies.

Workers do not talk to the operator. Everything a worker asserts passes
through the supervisor, which enforces three rules:

1. **Every numeric claim cites a source.** A claim with no source is
   treated as compromised, whatever it says.
2. **A cited claim is checked against its source.** The supervisor reads
   the same sensor series the worker cites; a contradiction beyond
   tolerance is treated as compromised.
3. **A compromised claim never reaches the operator.** The worker is
   quarantined (its grant is revoked live), the claim is withheld, and
   the task is re-issued to a freshly resolved replacement. All three
   steps are attributed ledger rows.

Loops and runaways are bounded the same way: every worker task carries a
step budget and a wall-clock ceiling; exceeding either is a quarantine,
not a retry storm. Model endpoint failures follow a documented fallback
chain (docs/operations.md) and are recorded — never silent.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.fleet.authority import POLICY
from app.fleet.events import BUS, EventKind, Outcome

# A worker may be wrong by measurement noise; it may not be wrong by 16 mg/L.
RELATIVE_TOLERANCE = 0.15

STEP_BUDGET = 24  # tool/model steps per issued task
WALL_CLOCK_CEILING_S = 120.0  # per issued task


@dataclass(frozen=True)
class Claim:
    """One assertion a worker wants to put in front of the operator."""

    agent_name: str
    parameter: str  # e.g. "ammonia_mg_l"
    value: float
    source: str | None  # e.g. "sensor:aeration.do", "dmr:2025-06", None
    narrative: str = ""


@dataclass
class TaskEnvelope:
    """Budgeted execution context for one issued worker task."""

    agent_name: str
    task: str
    steps_used: int = 0
    started_at: float = field(default_factory=time.time)

    def spend_step(self) -> bool:
        """True while within budget; False once exhausted."""
        self.steps_used += 1
        if self.steps_used > STEP_BUDGET:
            return False
        return (time.time() - self.started_at) <= WALL_CLOCK_CEILING_S


class Supervisor:
    """Audits claims against sources; quarantines what cannot be trusted."""

    def __init__(self, read_source: Callable[[str], float | None]) -> None:
        # read_source resolves a citation like "sensor:aeration.do" to the
        # current authoritative value, or None if the source doesn't exist.
        self.read_source = read_source
        self.reissue_hooks: list[Callable[[str, str], None]] = []

    # -- claim auditing -----------------------------------------------------

    def audit(self, claim: Claim) -> bool:
        """True if the claim may reach the operator. False means quarantined."""
        identity = self._identity(claim.agent_name)

        if not claim.source:
            self._quarantine(
                claim,
                reason="asserted a number with no cited source",
                comparison=None,
            )
            return False

        authoritative = self.read_source(claim.source)
        if authoritative is None:
            # A citation the supervisor cannot independently resolve (a lab
            # report line, a forecast) is not a lie — it is an unverified
            # citation. It passes, and the ledger says exactly that. Only
            # the two compromising cases quarantine: no source at all, or a
            # contradiction with a source the supervisor CAN read.
            BUS.record(
                EventKind.AGENT_STATE,
                self._identity(claim.agent_name),
                f"claim cites {claim.source} — not independently verifiable, recorded as such",
                Outcome.INFO,
                parameter=claim.parameter,
                value=claim.value,
            )
            return True

        deviation = abs(claim.value - authoritative) / max(abs(authoritative), 1e-9)
        if deviation > RELATIVE_TOLERANCE:
            self._quarantine(
                claim,
                reason=(
                    f"claimed {claim.parameter} = {claim.value:g}; "
                    f"{claim.source} reads {authoritative:g}"
                ),
                comparison={"claimed": claim.value, "source": authoritative},
            )
            return False

        BUS.record(
            EventKind.AGENT_STATE,
            identity,
            f"claim verified against {claim.source}",
            Outcome.ALLOW,
            parameter=claim.parameter,
            value=claim.value,
        )
        return True

    # -- budget enforcement -------------------------------------------------

    def enforce_budget(self, envelope: TaskEnvelope) -> bool:
        """Call on every step. False → the worker was stopped and re-issued."""
        if envelope.spend_step():
            return True
        self._quarantine_name(
            envelope.agent_name,
            reason=(
                f"exceeded task budget ({envelope.steps_used} steps, "
                f"{time.time() - envelope.started_at:.0f}s) — stopped, not retried"
            ),
        )
        self._reissue(envelope.agent_name, envelope.task)
        return False

    # -- quarantine mechanics -----------------------------------------------

    def _identity(self, agent_name: str) -> str:
        grant = POLICY.grants.get(agent_name)
        return grant.identity if grant else agent_name

    def _quarantine(self, claim: Claim, reason: str, comparison) -> None:
        self._quarantine_name(claim.agent_name, reason, comparison=comparison)
        self._reissue(claim.agent_name, f"re-verify {claim.parameter}")

    def _quarantine_name(self, agent_name: str, reason: str, **detail: Any) -> None:
        grant = POLICY.grants.get(agent_name)
        if grant:
            grant.quarantined = True  # authority checks now refuse every call
        BUS.record(
            EventKind.QUARANTINE,
            self._identity(agent_name),
            "quarantined by supervisor — claim withheld from operator",
            Outcome.DENY,
            reason=reason,
            **{k: v for k, v in detail.items() if v is not None},
        )

    def _reissue(self, agent_name: str, task: str) -> None:
        for hook in self.reissue_hooks:
            hook(agent_name, task)
        BUS.record(
            EventKind.AGENT_STATE,
            "fleet-supervisor",
            f"task re-issued to a fresh replacement for {agent_name}",
            Outcome.INFO,
            task=task,
        )
