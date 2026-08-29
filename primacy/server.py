"""The state primacy agency's agent publisher — the other department.

A deliberately separate service, deployed under its own identity,
representing the state agency that holds primacy for NPDES enforcement.
It publishes one specialist as an A2A agent card: the wet-weather bypass
specialist. The Steward fleet does not ship this expertise; when an
emerging condition surfaces the role, the fleet's registry resolves it
live from this publisher and mounts it cross-department, with recommend
authority and single-facility scope.

Two organisations, two publishers, one registry — cataloged for
cross-department use, as the track asks, with the seam visible.
"""

from __future__ import annotations

import os

from fastapi import FastAPI

AGENCY = "State Primacy Agency — Water Compliance Division"

app = FastAPI(title="primacy-agency-publisher", description=__doc__)


# The version a consumer pins against. Bumping this is how the agency
# would ship a revised reading of the regulation; the fleet records
# which version it mounted and whether that satisfied its pin.
AGENT_VERSION = os.environ.get("AGENT_VERSION", "1.2.0")


@app.get("/.well-known/agent-card.json")
def agent_card() -> dict:
    # Without PUBLIC_URL the card advertises localhost, which no registry
    # and no other fleet can reach. Deploy sets it (see `make deploy-all`).
    base = os.environ.get("PUBLIC_URL", "http://localhost:8091")
    return {
        # An A2A v1 card declares its protocol per interface, not at the
        # top level — a top-level protocolVersion is the v0.3 shape, and
        # the managed Agent Registry rejects the mixture outright.
        "version": AGENT_VERSION,
        "name": "wet-weather-bypass-specialist",
        "description": (
            "Specialist in 40 CFR 122.41(m): when a wet-weather bypass is "
            "lawful, what evidence the determination needs, and what the "
            "facility owes afterward. Recommend-only by publication policy."
        ),
        # No top-level "url": that is the v0.3 shape, and a card carrying
        # both it and supportedInterfaces is ambiguous. The registry
        # rejects the mixture, which is how we found this.
        "provider": {"organization": AGENCY, "url": base},
        "supportedInterfaces": [
            {
                "url": f"{base}/a2a",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "capabilities": {"streaming": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "wet-weather-bypass-specialist",
                "name": "wet-weather-bypass-specialist",
                "description": (
                    "Assess bypass lawfulness under 40 CFR 122.41(m); cite "
                    "which conditions are met and what is obligated after."
                ),
                "tags": ["npdes", "bypass", "compliance", "cross-department"],
            },
            {
                "id": "bypass-reporting",
                "name": "bypass-reporting",
                "description": "24-hour oral notice and 5-day written report requirements.",
                "tags": ["npdes", "reporting"],
            },
        ],
    }


@app.get("/healthz")
def healthz() -> dict:
    return {"service": "primacy-agency-publisher", "publisher": AGENCY}
