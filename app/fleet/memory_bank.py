"""Vertex AI Memory Bank, behind one small door.

Every call into the managed service lives here so that memory.py can stay
about facts. Three things in this file are load-bearing and each of them
is a trap someone will otherwise hit:

**The region.** Memory Bank is regional. `GOOGLE_CLOUD_LOCATION` is
`global` on every deploy path in this project, because that is where
Gemini 3.x serves from — reusing it here would 404 on every call. The
bank carries its own `STEWARD_MEMORY_BANK_LOCATION`, exactly as the
Model Armor screener carries its own.

**The scope.** `{app_name, user_id}` is the partition key of the whole
bank. It must be identical on Agent Runtime and on Cloud Run or the two
surfaces keep separate memories and nothing appears to persist. It is
therefore a fixed, env-overridable constant and never derived from a
session id.

**Reading back.** ADK's `search_memory` requires a query and drops
`memory.metadata` on the way out, so observation counts cannot survive
it. Hydration goes through the raw client's `memories.retrieve`, which
returns the metadata; `search_memory` is kept for what it is genuinely
good at, semantic recall at the moment of decision.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any

APP_NAME = os.environ.get("STEWARD_MEMORY_APP", "steward-fleet")
USER_ID = os.environ.get("STEWARD_MEMORY_SCOPE", "cedar-ridge-operator")


@dataclass(frozen=True)
class BankTarget:
    engine_id: str
    location: str
    source: str  # how we found it — reported in the ledger


def resolve_engine() -> BankTarget | None:
    """Find the reasoning engine whose Memory Bank we should use.

    On Agent Runtime the platform injects the engine id, so nothing needs
    wiring. On Cloud Run it must be passed in, which is what
    `make memory-bank` does.
    """
    location = os.environ.get("STEWARD_MEMORY_BANK_LOCATION", "us-central1")

    explicit = os.environ.get("AGENT_ENGINE_MEMORY_BANK", "").strip()
    if explicit:
        if "/" in explicit:
            # A full resource path carries its own project and region;
            # ADK wants the bare id and warns if handed the path.
            parts = explicit.split("/")
            try:
                location = parts[parts.index("locations") + 1]
            except (ValueError, IndexError):
                pass
            return BankTarget(parts[-1], location, "AGENT_ENGINE_MEMORY_BANK")
        return BankTarget(explicit, location, "AGENT_ENGINE_MEMORY_BANK")

    injected = os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID", "").strip()
    if injected:
        return BankTarget(
            injected,
            os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_LOCATION", location),
            "GOOGLE_CLOUD_AGENT_ENGINE_ID",
        )
    return None


def _fact_id(subject: str, statement: str) -> str:
    """A deterministic id, so the same fact learned twice is the same
    memory rather than a duplicate."""
    digest = hashlib.sha256(f"{subject}::{statement}".encode()).hexdigest()
    return f"steward-{digest[:32]}"


class MemoryBank:
    """Writes facts to Memory Bank; reads them back with their counts."""

    def __init__(self, target: BankTarget) -> None:
        from google.adk.memory import VertexAiMemoryBankService

        self.target = target
        self.project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        self._service = VertexAiMemoryBankService(
            project=self.project,
            location=target.location,
            agent_engine_id=target.engine_id,
        )

    # -- writing ------------------------------------------------------------

    async def write(self, fact: Any) -> None:
        """Persist one fact. Re-observing replaces it, because the
        observation count is the point and there is no update verb."""
        from google.adk.memory.memory_entry import MemoryEntry
        from google.genai import types

        memory_id = _fact_id(fact.subject, fact.statement)
        entry = MemoryEntry(
            content=types.Content(
                role="user", parts=[types.Part(text=fact.statement)]
            ),
            # author and timestamp are deliberately left unset: ADK turns
            # them into Vertex revision *labels*, whose charset rejects
            # both our agent identities ("weather-scout@cedar-ridge") and
            # ISO timestamps. Both travel in metadata instead.
            custom_metadata={
                "memory_id": memory_id,
                "steward_subject": fact.subject,
                "steward_observations": float(fact.observations),
                "steward_learned_by": fact.learned_by,
                "steward_first_seen": float(fact.first_seen),
            },
        )
        try:
            await self._service.add_memory(
                app_name=APP_NAME, user_id=USER_ID, memories=[entry]
            )
        except Exception as exc:
            if not _already_exists(exc):
                raise
            # create-with-id is AIP-133; there is no update. Replace.
            await self._delete(memory_id)
            try:
                await self._service.add_memory(
                    app_name=APP_NAME, user_id=USER_ID, memories=[entry]
                )
            except Exception as retry:
                if not _already_exists(retry):
                    raise
                # The delete did not take before the write raced it back.
                # The statement is already stored under this id — only the
                # observation count is now behind. That is a worse record,
                # not a broken one, and it is not worth declaring the whole
                # store degraded and falling back to a local file.
                return

    async def _delete(self, memory_id: str) -> None:
        """Remove one memory so it can be written again with a new count.

        A partial name is resolved by the client against the project *id*,
        while creates land under the project *number* — so the delete
        looked for the memory somewhere it had never been, got a 404, and
        that 404 took down the whole write. A memory that is not there is
        already deleted; the only thing lost is the observation count.
        """
        client = self._service._get_api_client()
        try:
            await client.agent_engines.memories.delete(
                name=f"reasoningEngines/{self.target.engine_id}/memories/{memory_id}"
            )
        except Exception as exc:
            if "not_found" not in str(exc).lower() and "404" not in str(exc):
                raise

    # -- reading ------------------------------------------------------------

    async def read_all(self) -> list[dict[str, Any]]:
        """Every fact in scope, with its observation count intact.

        Uses the raw client rather than ADK's search_memory, which needs
        a query and discards metadata.
        """
        client = self._service._get_api_client()
        pager = await client.agent_engines.memories.retrieve(
            name=f"reasoningEngines/{self.target.engine_id}",
            scope={"app_name": APP_NAME, "user_id": USER_ID},
            simple_retrieval_params={"page_size": 100},
        )
        out: list[dict[str, Any]] = []
        async for retrieved in pager:
            memory = getattr(retrieved, "memory", retrieved)
            meta = getattr(memory, "metadata", None) or {}
            out.append(
                {
                    "statement": getattr(memory, "fact", "") or "",
                    "subject": _string(meta.get("steward_subject")) or "facility",
                    "observations": int(_number(meta.get("steward_observations")) or 1),
                    "learned_by": _string(meta.get("steward_learned_by")) or "",
                    "first_seen": _number(meta.get("steward_first_seen")) or 0.0,
                }
            )
        return out

    async def recall(self, query: str) -> list[str]:
        """Semantic recall — what ADK's search_memory is actually for."""
        response = await self._service.search_memory(
            app_name=APP_NAME, user_id=USER_ID, query=query
        )
        found = []
        for memory in getattr(response, "memories", []) or []:
            for part in getattr(memory.content, "parts", []) or []:
                if getattr(part, "text", None):
                    found.append(part.text)
        return found


def _already_exists(exc: Exception) -> bool:
    """Whether this failure means "that id is taken".

    Matching only on ALREADY_EXISTS/409 was wrong: Vertex rejects a
    duplicate memory id with 400 INVALID_ARGUMENT and says so in the
    message. Since a fact's id is derived from its text, every
    *re-observation* took that path — and re-observation is the normal
    case, because the observation count is what the fleet is recording.
    So the first write of any fact succeeded and every one after it
    failed, until three failures degraded the whole store to local JSON.
    Read the message, not just the code.
    """
    text = str(exc).lower()
    return (
        "already exists" in text
        or "already_exists" in text
        or "409" in text
    )


def _string(value: Any) -> str:
    return getattr(value, "string_value", "") if value is not None else ""


def _number(value: Any) -> float:
    return getattr(value, "double_value", 0.0) if value is not None else 0.0
