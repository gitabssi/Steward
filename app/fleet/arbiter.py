"""The contention arbiter — agents that disagree, resolved in the open.

Nothing in a treatment plant moves alone. Raising the blowers rescues the
biology and shortens retention time; shortening retention time carries
solids over the weirs; carried-over solids breach the permit before the
ammonia recovers. Three agents each own one of those truths, and each one
is right.

The arbiter's job is not to pick a winner quietly. It is to surface the
disagreement as a first-class object: every proposal, every counter-
consequence, the quantified cost of each path, and — when no path is free
— an escalation that puts the choice where it belongs, in front of the
person whose certification is on the line.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.fleet.events import BUS, EventKind, Outcome


@dataclass(frozen=True)
class Proposal:
    """One agent's proposed action, with what it costs elsewhere."""

    agent_name: str
    identity: str
    action: str  # "raise blowers to 82%"
    rationale: str  # "dissolved oxygen 1.1 mg/L and falling"
    consequences: list[str]  # quantified costs, in other agents' domains
    urgency_minutes: int  # how long before the option expires


@dataclass
class Contention:
    """A set of proposals that cannot all be taken."""

    subject: str  # "aeration response to infiltration surge"
    proposals: list[Proposal] = field(default_factory=list)
    contention_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])


class Arbiter:
    """Runs a contention round and produces either a plan or an escalation."""

    def open_contention(self, subject: str) -> Contention:
        return Contention(subject=subject)

    def submit(self, contention: Contention, proposal: Proposal) -> None:
        contention.proposals.append(proposal)
        BUS.record(
            EventKind.PROPOSAL,
            proposal.identity,
            proposal.action,
            Outcome.INFO,
            contention_id=contention.contention_id,
            rationale=proposal.rationale,
            consequences=proposal.consequences,
            urgency_minutes=proposal.urgency_minutes,
        )

    def resolve(self, contention: Contention) -> dict:
        """Emit the contention and decide whether it needs the operator.

        A single proposal with no counter-consequences resolves in place.
        Anything else — proposals whose consequences land in another
        agent's domain — escalates with the full costed option set. The
        arbiter never silently discards an agent's objection.
        """
        conflicted = len(contention.proposals) > 1 or any(
            p.consequences for p in contention.proposals
        )
        BUS.record(
            EventKind.CONTENTION,
            "contention-arbiter",
            contention.subject,
            Outcome.INFO,
            contention_id=contention.contention_id,
            proposals=[
                {
                    "by": p.identity,
                    "action": p.action,
                    "rationale": p.rationale,
                    "consequences": p.consequences,
                }
                for p in contention.proposals
            ],
            conflicted=conflicted,
        )
        if not conflicted:
            only = contention.proposals[0]
            return {"resolution": "proceed", "action": only.action}

        options = [
            {
                "action": p.action,
                "offered_by": p.identity,
                "costs": p.consequences,
                "window_minutes": p.urgency_minutes,
            }
            for p in contention.proposals
        ]
        BUS.record(
            EventKind.ESCALATION,
            "contention-arbiter",
            f"decision needed: {contention.subject}",
            Outcome.INFO,
            contention_id=contention.contention_id,
            options=options,
            note="every fix costs something somewhere else — the choice is the operator's",
        )
        return {"resolution": "escalate", "options": options}


ARBITER = Arbiter()
