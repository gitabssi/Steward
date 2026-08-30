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

import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.fleet import memory_bank
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
        self.backend = "local-json"
        self.hydrated = False
        self._dirty: set[str] = set()
        self._flush_lock = asyncio.Lock()
        self._write_failures = 0
        self._bank = self._connect_memory_bank()
        self._load()

    def _connect_memory_bank(self):
        """Vertex AI Memory Bank, when an engine can be resolved."""
        target = memory_bank.resolve_engine()
        if target is None:
            self.backend = "local-json"
            BUS.record(
                EventKind.SYSTEM,
                "fleet-memory",
                "no Memory Bank configured — facts persist to the local store",
                Outcome.INFO,
                backend=self.backend,
            )
            return None
        try:
            bank = memory_bank.MemoryBank(target)
            self.backend = "memory-bank"
            BUS.record(
                EventKind.SYSTEM,
                "fleet-memory",
                "backed by Vertex AI Memory Bank",
                Outcome.INFO,
                backend=self.backend,
                agent_engine=target.engine_id,
                location=target.location,
                resolved_from=target.source,
                scope=f"{memory_bank.APP_NAME}/{memory_bank.USER_ID}",
            )
            return bank
        except Exception as exc:
            self.backend = "local-json"
            BUS.record(
                EventKind.SYSTEM,
                "fleet-memory",
                "Memory Bank unavailable — using local store (recorded, not silent)",
                Outcome.INFO,
                backend=self.backend,
                error=str(exc)[:600],
            )
            return None

    # -- learning -----------------------------------------------------------

    def observe(self, subject: str, statement: str, learned_by: str) -> LearnedFact:
        """Record a fact. Deliberately synchronous and network-free.

        This is called from the reasoning path and from sync contexts, so
        it only ever touches memory and the local file; the Memory Bank
        write is queued and drained by the shift loop's own dispatcher.
        """
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
            backend=self.backend,
        )
        self._dirty.add(key)
        self._save()
        return fact

    # -- the managed backend, drained off the heartbeat ---------------------

    def pending(self) -> bool:
        return bool(self._dirty) and self._bank is not None

    async def flush(self) -> None:
        """Write queued facts to Memory Bank. Failures keep the fact in
        the local store and say so once, rather than pretending."""
        if self._bank is None:
            self._dirty.clear()
            return
        async with self._flush_lock:
            queued, self._dirty = self._dirty, set()
            failed: set[str] = set()
            for key in queued:
                fact = self._facts.get(key)
                if fact is None:
                    continue
                try:
                    await self._bank.write(fact)
                except Exception as exc:
                    failed.add(key)
                    self._write_failures += 1
                    if self._write_failures == 1:
                        BUS.record(
                            EventKind.SYSTEM,
                            "fleet-memory",
                            "memory bank write failed — the local store keeps the fact",
                            Outcome.INFO,
                            error=str(exc)[:600],
                        )
            self._dirty |= failed
            if failed and self._write_failures >= 3:
                self.backend = "local-json (degraded)"
            elif not failed:
                self._write_failures = 0

    async def hydrate(self) -> None:
        """Load what previous shifts learned. This is the cross-session
        persistence claim, and it is one ledger row."""
        if self._bank is None:
            return
        remote = await self._bank.read_all()
        local_only = len(self._facts)
        merged = 0
        for row in remote:
            key = f"{row['subject']}::{row['statement']}"
            existing = self._facts.get(key)
            if existing is None:
                self._facts[key] = LearnedFact(
                    subject=row["subject"],
                    statement=row["statement"],
                    observations=row["observations"],
                    first_seen=row["first_seen"] or time.time(),
                    learned_by=row["learned_by"],
                )
                merged += 1
            else:
                # Neither side is authoritative; the higher count is.
                existing.observations = max(
                    existing.observations, row["observations"]
                )
        self.hydrated = True
        self._save()
        BUS.record(
            EventKind.MEMORY,
            "fleet-memory",
            f"hydrated {merged} facts from Vertex AI Memory Bank",
            Outcome.INFO,
            backend=self.backend,
            scope=f"{memory_bank.APP_NAME}/{memory_bank.USER_ID}",
            from_bank=len(remote),
            already_local=local_only,
        )

    async def recall(self, query: str, by: str) -> list[str]:
        """Semantic recall from the bank, cited on the record."""
        if self._bank is None:
            return []
        found = await self._bank.recall(query)
        if found:
            BUS.record(
                EventKind.MEMORY,
                by,
                f"recalled {len(found)} facts from Memory Bank",
                Outcome.INFO,
                query=query[:80],
            )
        return found

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
