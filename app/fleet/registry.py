"""Agent catalog: cached at boot, resolved live on a miss.

The fleet's roster is not hard-coded. Agents are described by A2A agent
cards from more than one publisher — the Steward fleet itself, and
specialists published by other organisations (the state primacy agency's
wet-weather bypass specialist among them). Cross-department use is the
point: the card says who published it, and the console shows both
publishers side by side.

Deviation from the platform guidance, on purpose: Google's docs recommend
resolving agents once at startup for latency. Steward caches the catalog
at boot **and** resolves live on a miss, because an emerging condition at
a plant can surface a role nobody catalogued for it — a permitted
wet-weather bypass is exactly such a role. The resolution latency is
measured and shown, not hidden: it is evidence the registry is doing real
work at the moment it matters.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from app.fleet.events import BUS, EventKind, Outcome

CATALOG_PATH = Path(__file__).parent / "catalog.json"


@dataclass(frozen=True)
class CatalogEntry:
    """One agent card the fleet knows how to reach."""

    name: str  # role name, e.g. "wet-weather-bypass-specialist"
    publisher: str  # organisation that published the card
    department: str  # "steward-fleet" or an external department
    description: str
    endpoint: str  # A2A base URL ("" for in-process fleet members)
    skills: list[str] = field(default_factory=list)


class Registry:
    """Boot-time cache over the catalog, live A2A resolve on a miss."""

    def __init__(self) -> None:
        self._cache: dict[str, CatalogEntry] = {}
        self._mounted: dict[str, CatalogEntry] = {}
        self.load_catalog()

    def load_catalog(self) -> None:
        raw = json.loads(CATALOG_PATH.read_text())
        for item in raw["agents"]:
            entry = CatalogEntry(**item)
            self._cache[entry.name] = entry
        BUS.record(
            EventKind.REGISTRY,
            "agent-registry",
            f"catalog cached at boot — {len(self._cache)} agents, "
            f"{len({e.publisher for e in self._cache.values()})} publishers",
            Outcome.INFO,
        )

    # -- lookup -------------------------------------------------------------

    def search(self, role: str) -> CatalogEntry | None:
        """Cache first; on a miss, resolve live and time it."""
        entry = self._cache.get(role)
        if entry is not None:
            BUS.record(
                EventKind.REGISTRY,
                "agent-registry",
                f"catalog hit: {role}",
                Outcome.ALLOW,
                publisher=entry.publisher,
            )
            return entry
        return self._resolve_live(role)

    def _resolve_live(self, role: str) -> CatalogEntry | None:
        """A miss is not a failure — it is the reason the registry exists."""
        t0 = time.perf_counter()
        for entry in self._probe_known_publishers(role):
            latency_ms = (time.perf_counter() - t0) * 1000
            self._cache[entry.name] = entry
            BUS.record(
                EventKind.REGISTRY,
                "agent-registry",
                f"live resolve: {role} — found, published by {entry.publisher}",
                Outcome.ALLOW,
                latency_ms=round(latency_ms, 1),
                department=entry.department,
                cross_department=entry.department != "steward-fleet",
            )
            return entry
        BUS.record(
            EventKind.REGISTRY,
            "agent-registry",
            f"live resolve: {role} — no publisher offers this role",
            Outcome.DENY,
            latency_ms=round((time.perf_counter() - t0) * 1000, 1),
        )
        return None

    def _probe_known_publishers(self, role: str):
        """Fetch A2A agent cards from every known publisher endpoint."""
        raw = json.loads(CATALOG_PATH.read_text())
        endpoints = list(raw.get("publisher_endpoints", []))
        if os.environ.get("PRIMACY_AGENCY_ENDPOINT"):
            endpoints.append(os.environ["PRIMACY_AGENCY_ENDPOINT"])
        for base in endpoints:
            try:
                url = f"{base.rstrip('/')}/.well-known/agent-card.json"
                with urllib.request.urlopen(url, timeout=5) as r:
                    card = json.load(r)
                for skill in card.get("skills", []):
                    if role in (skill.get("id", ""), skill.get("name", "")):
                        yield CatalogEntry(
                            name=role,
                            publisher=card.get("provider", {}).get(
                                "organization", "unknown"
                            ),
                            department=card.get("provider", {}).get(
                                "organization", "external"
                            ),
                            description=skill.get("description", ""),
                            endpoint=base,
                            skills=[s.get("id", "") for s in card.get("skills", [])],
                        )
            except Exception:
                continue  # unreachable publisher; try the next one

    # -- mounting -----------------------------------------------------------

    def mount(self, role: str) -> CatalogEntry | None:
        entry = self.search(role)
        if entry is None:
            return None
        self._mounted[role] = entry
        BUS.record(
            EventKind.REGISTRY,
            "agent-registry",
            f"mounted {role}",
            Outcome.ALLOW,
            publisher=entry.publisher,
            department=entry.department,
            cross_department=entry.department != "steward-fleet",
        )
        return entry

    def roster(self) -> list[dict]:
        return [
            {
                "name": e.name,
                "publisher": e.publisher,
                "department": e.department,
                "description": e.description,
                "mounted": e.name in self._mounted,
            }
            for e in self._cache.values()
        ]
