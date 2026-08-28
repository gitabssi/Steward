"""Per-facility identity scoping — real multi-tenancy over a real dataset.

The fleet's data plane holds records for many permitted facilities (the
public EPA NPDES corpus in BigQuery, and per-facility live state in
Firestore). An agent's grant names exactly one facility. Every read goes
through `ScopedReader`, which compares the facility on the request with
the facility on the grant. A mismatch is not an exception — it is a DENY
row in the ledger, attributed to the requesting agent, with the trace id
of the request that tried.

This is the track's data-sovereignty requirement made concrete: the fence
sits in front of real data about real facilities, so a denied cross-
facility read is a genuine authorization decision, not a mock.
"""

from __future__ import annotations

from typing import Any

from app.fleet.authority import POLICY, FleetPolicy
from app.fleet.events import BUS, EventKind, Outcome


class ScopeDenied(Exception):
    """Raised to the caller; already recorded in the ledger by then."""


class ScopedReader:
    """The only door to per-facility data. Checks scope on every read."""

    def __init__(self, policy: FleetPolicy | None = None) -> None:
        self.policy = policy or POLICY

    def authorize(self, agent_name: str, facility: str, resource: str) -> None:
        grant = self.policy.grants.get(agent_name)
        identity = grant.identity if grant else agent_name
        if grant is None or grant.facility != facility:
            BUS.record(
                EventKind.DENIAL,
                identity,
                f"read {resource} of {facility}",
                Outcome.DENY,
                reason=(
                    f"identity is scoped to {grant.facility}" if grant else "no grant"
                ),
            )
            raise ScopeDenied(
                f"{identity} is not scoped to facility {facility}; "
                "this attempt is recorded in the audit ledger"
            )
        BUS.record(
            EventKind.AGENT_STATE,
            identity,
            f"read {resource} of {facility}",
            Outcome.ALLOW,
        )

    def guarded(self, agent_name: str, facility: str, resource: str, fetch):
        """Authorize, then fetch. `fetch` runs only after the scope check."""
        self.authorize(agent_name, facility, resource)
        return fetch()


READER = ScopedReader()


def facility_state_key(facility: str, *parts: str) -> str:
    """Canonical Firestore document path for one facility's live state."""
    safe = [p.replace("/", "_") for p in (facility, *parts)]
    return "facilities/" + "/".join(safe)


def describe_scopes() -> list[dict[str, Any]]:
    """For the Control Centre: every grant, its scope, its authority."""
    return [g.display() for g in POLICY.grants.values()]
