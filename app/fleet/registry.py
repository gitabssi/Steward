"""Agent catalog: cached at boot, resolved live on a miss.

The fleet's roster is not hard-coded. Agents are described by A2A agent
cards from more than one publisher — the Steward fleet itself, and
specialists published by other organisations (the state primacy agency's
wet-weather bypass specialist among them). Cross-department use is the
point: the card says who published it, and the console shows both
publishers side by side.

Discovery goes to the **managed Agent Registry** when the project has
one, and falls back to the bundled catalog when it does not — and every
REGISTRY ledger row names which of the two answered. That is the same
mechanism the Model Armor screener uses to report itself, for the same
reason: a fallback nobody can see is indistinguishable from a claim.

Agents deployed to Agent Runtime register themselves; an external
publisher like the state primacy agency is registered as a `Service`
carrying its A2A card. The registry validates those cards on the way in
— it rejected ours until the card advertised a `version`, which is where
the version a consumer pins against comes from.

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
    version: str = "0.0.0"  # as advertised by the publisher's own card
    pinned: str = ""  # the range this consumer will accept
    source: str = "local-catalog"  # "agent-registry" when the API answered

    def satisfies_pin(self) -> bool:
        """Major-version compatibility, the only pin worth enforcing here.

        A specialist that changed its major version has changed its
        reading of the regulation; mounting it silently would be the
        opposite of governance.
        """
        if not self.pinned:
            return True
        want = self.pinned.lstrip("^~>=<! ").split(".")[0]
        return self.version.split(".")[0] == want


class Registry:
    """Boot-time cache over the catalog, live A2A resolve on a miss."""

    def __init__(self) -> None:
        self._cache: dict[str, CatalogEntry] = {}
        self._mounted: dict[str, CatalogEntry] = {}
        self._pins: dict[str, str] = {}
        self.load_catalog()

    def load_catalog(self) -> None:
        raw = json.loads(CATALOG_PATH.read_text())
        self._pins = dict(raw.get("pins", {}))
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
        for entry in self._candidates(role):
            latency_ms = (time.perf_counter() - t0) * 1000
            self._cache[entry.name] = entry
            BUS.record(
                EventKind.REGISTRY,
                "agent-registry",
                f"live resolve: {role} v{entry.version} — published by {entry.publisher}",
                Outcome.ALLOW,
                latency_ms=round(latency_ms, 1),
                department=entry.department,
                cross_department=entry.department != "steward-fleet",
                registry=entry.source,
                version=entry.version,
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

    def _query_agent_registry(self, role: str):
        """Ask the managed Agent Registry what this project knows about.

        Services registered there carry their publisher's A2A card, so a
        role match here is a real cross-organisation discovery rather
        than a lookup in a file we shipped ourselves.
        """
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project or os.environ.get("AGENT_REGISTRY", "on") == "off":
            return
        location = os.environ.get("AGENT_REGISTRY_LOCATION", "us-central1")
        try:
            import google.auth
            import google.auth.transport.requests

            creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            creds.refresh(google.auth.transport.requests.Request())
            url = (
                f"https://agentregistry.googleapis.com/v1/projects/{project}"
                f"/locations/{location}/services"
            )
            request = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {creds.token}",
                    "x-goog-user-project": project,
                },
            )
            with urllib.request.urlopen(request, timeout=8) as response:
                services = json.load(response).get("services", [])
        except Exception as exc:
            BUS.record(
                EventKind.REGISTRY,
                "agent-registry",
                "managed registry unreachable — falling back to the bundled catalog",
                Outcome.INFO,
                error=str(exc)[:160],
            )
            return

        for service in services:
            card = (service.get("agentSpec") or {}).get("content") or {}
            skills = card.get("skills", [])
            if not any(role in (s.get("id"), s.get("name")) for s in skills):
                continue
            provider = card.get("provider", {})
            yield CatalogEntry(
                name=role,
                publisher=provider.get("organization")
                or service.get("displayName", "unknown"),
                department=provider.get("organization", "external"),
                description=next(
                    (s.get("description", "") for s in skills if role in (s.get("id"), s.get("name"))),
                    service.get("description", ""),
                ),
                endpoint=(provider.get("url") or "").rstrip("/"),
                skills=[s.get("id", "") for s in skills],
                version=card.get("version", "0.0.0"),
                pinned=self._pins.get(role, ""),
                source="agent-registry",
            )

    def _candidates(self, role: str):
        """Managed registry first, then the publishers we shipped."""
        yield from self._query_agent_registry(role)
        yield from self._probe_known_publishers(role)

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
                            version=card.get("version", "0.0.0"),
                            pinned=self._pins.get(role, ""),
                            source="publisher-card",
                        )
            except Exception:
                continue  # unreachable publisher; try the next one

    # -- mounting -----------------------------------------------------------

    def mount(self, role: str) -> CatalogEntry | None:
        entry = self.search(role)
        if entry is None:
            return None
        if not entry.satisfies_pin():
            # A major-version change means the published reading of the
            # regulation changed. Mounting it anyway would be the
            # opposite of governance, so this is a refusal on the record.
            BUS.record(
                EventKind.REGISTRY,
                "agent-registry",
                f"refused to mount {role} v{entry.version} — "
                f"this fleet is pinned to {entry.pinned}",
                Outcome.DENY,
                publisher=entry.publisher,
                version=entry.version,
                pinned=entry.pinned,
            )
            return None
        self._mounted[role] = entry
        BUS.record(
            EventKind.REGISTRY,
            "agent-registry",
            f"mounted {role} v{entry.version}"
            + (f", consumer pinned {entry.pinned}" if entry.pinned else ""),
            Outcome.ALLOW,
            publisher=entry.publisher,
            department=entry.department,
            cross_department=entry.department != "steward-fleet",
            version=entry.version,
            pinned=entry.pinned,
            registry=entry.source,
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
                "version": e.version,
                "pinned": e.pinned,
                "source": e.source,
            }
            for e in self._cache.values()
        ]
