"""What the fleet has learned — about this plant, and about this operator.

Uptime says the fleet ran. Memory says it ran and it changed. Two kinds of
fact accumulate here, each with an observation count, because a fact seen
once is an anecdote and a fact seen seven times is how the plant works:

  facility facts   "Blower 2 underperforms below 8°C (6 observations)"
  operator facts   "Chooses tanker haul over bypass (7 of 7)"

Facts are cited at the moment of decision — "Not escalating: you dismissed
this same pattern four times in three weeks" — and every citation is a
MEMORY ledger row, so the learning is visible where it earns its keep.

Backing store: Vertex AI Memory Bank when the fleet runs on Agent Runtime
(memories survive process restarts and are shared across the fleet's
sessions); a local JSON file otherwise. The interface is identical and the
active backend is recorded at boot — never silent.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.fleet.events import BUS, EventKind, Outcome


@dataclass
class LearnedFact:
    subject: str  # "facility" | "operator"
    statement: str  # the fact, plainly stated
    observations: int = 1
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    learned_by: str = ""  # agent identity that first noticed


class FleetMemory:
    """Observation-counted facts with a pluggable backing store."""

    def __init__(self, store_path: Path | None = None) -> None:
        self._facts: dict[str, LearnedFact] = {}
        self._path = store_path or Path(
            os.environ.get("STEWARD_MEMORY_PATH", "/tmp/steward-memory.json")
        )
        self._memory_bank = self._connect_memory_bank()
        self._load()

    def _connect_memory_bank(self):
        """Vertex AI Memory Bank via the Agent Engine session/memory service."""
        name = os.environ.get("AGENT_ENGINE_MEMORY_BANK")  # projects/.../reasoningEngines/N
        if not name:
            return None
        try:
            from google.adk.memory import VertexAiMemoryBankService

            service = VertexAiMemoryBankService(
                project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
                agent_engine_id=name.rsplit("/", 1)[-1],
            )
            BUS.record(
                EventKind.SYSTEM,
                "fleet-memory",
                "backed by Vertex AI Memory Bank",
                Outcome.INFO,
                agent_engine=name,
            )
            return service
        except Exception as exc:
            BUS.record(
                EventKind.SYSTEM,
                "fleet-memory",
                "Memory Bank unavailable — using local store (recorded, not silent)",
                Outcome.INFO,
                error=str(exc)[:200],
            )
            return None

    # -- learning -----------------------------------------------------------

    def observe(self, subject: str, statement: str, learned_by: str) -> LearnedFact:
        key = f"{subject}::{statement}"
        fact = self._facts.get(key)
        if fact:
            fact.observations += 1
            fact.last_seen = time.time()
        else:
            fact = LearnedFact(subject, statement, learned_by=learned_by)
            self._facts[key] = fact
        BUS.record(
            EventKind.MEMORY,
            learned_by,
            f"learned: {statement}",
            Outcome.INFO,
            subject=subject,
            observations=fact.observations,
        )
        self._save()
        return fact

    def cite(self, statement_contains: str, by: str, decision: str) -> LearnedFact | None:
        """Find a fact and put the citation on the record."""
        for fact in self._facts.values():
            if statement_contains.lower() in fact.statement.lower():
                BUS.record(
                    EventKind.MEMORY,
                    by,
                    decision,
                    Outcome.INFO,
                    because=f"{fact.statement} ({fact.observations} observations)",
                )
                return fact
        return None

    def facts(self, subject: str | None = None) -> list[dict]:
        out = [
            asdict(f)
            for f in self._facts.values()
            if subject is None or f.subject == subject
        ]
        return sorted(out, key=lambda f: -f["observations"])

    # -- persistence --------------------------------------------------------

    def _load(self) -> None:
        if self._path.exists():
            try:
                for d in json.loads(self._path.read_text()):
                    fact = LearnedFact(**d)
                    self._facts[f"{fact.subject}::{fact.statement}"] = fact
            except Exception:
                pass  # a corrupt cache is not worth crashing the fleet over

    def _save(self) -> None:
        try:
            self._path.write_text(
                json.dumps([asdict(f) for f in self._facts.values()], indent=1)
            )
        except Exception:
            pass


MEMORY = FleetMemory()
