"""Audit ledger and live event bus.

Every consequential act in the fleet — an allowance, a denial, a handoff,
a quarantine — becomes one immutable LedgerEntry, attributed to a named
agent identity (never a shared service account) and stamped with the
OpenTelemetry trace id of the request that caused it. The console renders
the ledger for the full session; the same trace ids are visible in Cloud
Trace, so a reader can hold the product and the platform side by side.

The bus is deliberately simple: an in-process asyncio fan-out with a ring
buffer for replay to late subscribers. Firestore persistence is layered on
top when configured; if it is not, the fleet degrades loudly (a ledger row
records the degradation) and continues — the console must never blank.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

from opentelemetry import trace as otel_trace


class EventKind(StrEnum):
    TELEMETRY = "telemetry"  # a value moved somewhere on the plant
    AGENT_STATE = "agent_state"  # an agent changed state (idle/working/quarantined)
    HANDOFF = "handoff"  # one agent passed a finding to another
    PROPOSAL = "proposal"  # an agent proposed an action, with its cost
    CONTENTION = "contention"  # two or more proposals conflict; arbiter engaged
    ESCALATION = "escalation"  # the fleet asks the operator for a decision
    DECISION = "decision"  # the operator decided; readback + confirmation
    DENIAL = "denial"  # an act was refused by policy
    QUARANTINE = "quarantine"  # supervisor isolated a worker
    GUARD = "guard"  # Model Armor screened an inbound document
    REGISTRY = "registry"  # catalog hit / live resolve, with latency
    MEMORY = "memory"  # a learned fact was written or cited
    PIN = "pin"  # an agent rewrote the operator's screen
    CAPACITY = "capacity"  # the weekly capacity assessment
    SYSTEM = "system"  # lifecycle, degradation, fallback notices


class Outcome(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    INFO = "INFO"


@dataclass(frozen=True)
class LedgerEntry:
    """One immutable, attributed row of the audit ledger."""

    kind: EventKind
    actor: str  # agent identity, e.g. "permit-sentinel@cedar-ridge"
    action: str  # short verb phrase, e.g. "read effluent series"
    outcome: Outcome
    detail: dict[str, Any] = field(default_factory=dict)
    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    trace_id: str = field(default_factory=lambda: _current_trace_id())
    ts: float = field(default_factory=time.time)

    def to_json(self) -> str:
        d = asdict(self)
        d["kind"] = self.kind.value
        d["outcome"] = self.outcome.value
        return json.dumps(d, default=str)


def _current_trace_id() -> str:
    span = otel_trace.get_current_span()
    ctx = span.get_span_context()
    if ctx and ctx.trace_id:
        return format(ctx.trace_id, "032x")
    return "untraced-" + uuid.uuid4().hex[:16]


class EventBus:
    """In-process fan-out with replay. One instance per fleet process."""

    def __init__(self, replay_size: int = 2000) -> None:
        self._subscribers: set[asyncio.Queue[LedgerEntry]] = set()
        self._replay: deque[LedgerEntry] = deque(maxlen=replay_size)
        self._firestore = None
        self._firestore_failed = False
        self._write_failures = 0

    # -- publishing ---------------------------------------------------------

    def publish(self, entry: LedgerEntry) -> LedgerEntry:
        self._replay.append(entry)
        for q in list(self._subscribers):
            q.put_nowait(entry)
        self._persist(entry)
        return entry

    def record(
        self,
        kind: EventKind,
        actor: str,
        action: str,
        outcome: Outcome = Outcome.INFO,
        **detail: Any,
    ) -> LedgerEntry:
        return self.publish(LedgerEntry(kind, actor, action, outcome, detail))

    # -- subscribing --------------------------------------------------------

    async def subscribe(self, replay: int = 200):
        """Async-iterate live entries, preceded by the last `replay` entries."""
        q: asyncio.Queue[LedgerEntry] = asyncio.Queue()
        for entry in list(self._replay)[-replay:]:
            q.put_nowait(entry)
        self._subscribers.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subscribers.discard(q)

    def tail(self, n: int = 200) -> list[LedgerEntry]:
        return list(self._replay)[-n:]

    # -- persistence (best-effort, loud on failure) -------------------------

    # The heartbeat is not an audit record. Telemetry streams to the
    # console and belongs in a historian; what persists here is the
    # attributed, consequential acts an auditor would ask to see.
    _EPHEMERAL: ClassVar[frozenset[EventKind]] = frozenset({EventKind.TELEMETRY})
    WRITE_FAILURE_LIMIT: ClassVar[int] = 5

    def _persist(self, entry: LedgerEntry) -> None:
        if self._firestore_failed or entry.kind in self._EPHEMERAL:
            return
        if self._firestore is None:
            if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
                self._firestore_failed = True
                return
            try:
                from google.cloud import firestore

                self._firestore = firestore.Client()
            except Exception as exc:  # degradation is a recorded fact, not a secret
                self._firestore_failed = True
                self._replay.append(
                    LedgerEntry(
                        EventKind.SYSTEM,
                        "event-bus",
                        "firestore unavailable — ledger is in-memory only",
                        Outcome.INFO,
                        {"error": str(exc)[:200]},
                    )
                )
                return
        try:
            self._firestore.collection("ledger").document(entry.entry_id).set(
                json.loads(entry.to_json())
            )
            self._write_failures = 0
        except Exception as exc:
            # A transient write error is not a reason to stop keeping the
            # record for the rest of the process's life. Give up only after
            # a run of failures, and say so on the way down — an audit
            # ledger that quietly stopped persisting is worse than one that
            # never started.
            self._write_failures += 1
            if self._write_failures >= self.WRITE_FAILURE_LIMIT:
                self._firestore_failed = True
                self._replay.append(
                    LedgerEntry(
                        EventKind.SYSTEM,
                        "event-bus",
                        f"firestore writes failed {self._write_failures} times — "
                        "ledger is in-memory only from here",
                        Outcome.INFO,
                        {"error": str(exc)[:200]},
                    )
                )


BUS = EventBus()
