"""The authority model: observe / recommend / act — enforced, not declared.

Every agent in the fleet holds exactly one authority level. The level is
not a description in a prompt; it is a policy checked on every tool call
by an ADK plugin before the call executes. A denial is not an error path —
it is a first-class, attributed ledger entry, because fortification is
proved by refusal.

Above all three levels sits the operator. Tools marked `irreversible`
cannot be executed by any agent at any level without a single-use approval
token minted only when the operator confirms — by click or by voice — in
the console. The certification of record is his; the fleet cannot carry
the consequence of an action, so it is not permitted to take one.
"""

from __future__ import annotations

import inspect
import secrets
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from google.adk.plugins.base_plugin import BasePlugin

from app.fleet.events import BUS, EventKind, Outcome


class Authority(IntEnum):
    OBSERVE = 1  # read only
    RECOMMEND = 2  # may draft, may not act
    ACT = 3  # may execute, within scope


@dataclass(frozen=True)
class ToolPolicy:
    """What a tool requires before it may run."""

    required: Authority = Authority.OBSERVE
    irreversible: bool = False  # requires an operator approval token
    scope_checked: bool = True  # facility scope is verified (identity.py)


@dataclass
class AgentGrant:
    """One agent's standing: who it is, where it may look, what it may do."""

    agent_name: str  # ADK agent name, e.g. "aeration_keeper" — the grant key
    identity: str  # attributed identity, e.g. "aeration-keeper@cedar-ridge"
    facility: str  # NPDES permit id the agent is scoped to
    authority: Authority
    description: str = ""
    quarantined: bool = False
    granted_at: float = field(default_factory=time.time)

    def display(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "facility": self.facility,
            "authority": self.authority.name.lower(),
            "description": self.description,
            "quarantined": self.quarantined,
        }


class ApprovalVault:
    """Single-use tokens minted by the console when the operator confirms.

    A token binds to one action fingerprint; it cannot be replayed and it
    expires. No agent code path can mint one — only the console route that
    the operator drives.
    """

    TTL_SECONDS = 300

    def __init__(self) -> None:
        self._tokens: dict[str, tuple[str, float]] = {}

    def mint(self, action_fingerprint: str) -> str:
        token = secrets.token_urlsafe(24)
        self._tokens[token] = (action_fingerprint, time.time())
        return token

    def redeem(self, token: str, action_fingerprint: str) -> bool:
        entry = self._tokens.pop(token, None)
        if entry is None:
            return False
        fingerprint, minted_at = entry
        if time.time() - minted_at > self.TTL_SECONDS:
            return False
        return fingerprint == action_fingerprint


class FleetPolicy:
    """The single authority: grants per agent, policies per tool."""

    def __init__(self) -> None:
        self.grants: dict[str, AgentGrant] = {}
        self.tools: dict[str, ToolPolicy] = {}
        self.approvals = ApprovalVault()

    # -- configuration ------------------------------------------------------

    def grant(self, grant: AgentGrant) -> None:
        self.grants[grant.agent_name] = grant

    def register_tool(self, tool_name: str, policy: ToolPolicy) -> None:
        self.tools[tool_name] = policy

    def set_authority(self, agent_name: str, authority: Authority, by: str) -> None:
        """Operator promotes or demotes an agent, live."""
        grant = self.grants[agent_name]
        previous = grant.authority
        grant.authority = authority
        BUS.record(
            EventKind.AGENT_STATE,
            grant.identity,
            f"authority {previous.name.lower()} → {authority.name.lower()}",
            Outcome.ALLOW,
            changed_by=by,
        )

    # -- enforcement --------------------------------------------------------

    def check(
        self, agent_name: str, tool_name: str, args: dict[str, Any]
    ) -> tuple[bool, str]:
        grant = self.grants.get(agent_name)
        if grant is None:
            return False, f"no grant exists for agent '{agent_name}'"
        if grant.quarantined:
            return False, "agent is quarantined"

        policy = self.tools.get(tool_name, ToolPolicy())
        if policy.irreversible:
            token = args.get("approval_token", "")
            fingerprint = f"{tool_name}:{args.get('action_id', '')}"
            if not self.approvals.redeem(str(token), fingerprint):
                return False, (
                    "irreversible action requires operator approval — "
                    "no agent at any authority level may execute it alone"
                )
        if grant.authority < policy.required:
            return False, (
                f"{grant.authority.name.lower()} authority cannot call "
                f"{tool_name} (requires {policy.required.name.lower()})"
            )
        return True, "within authority"


POLICY = FleetPolicy()


class AuthorityPlugin(BasePlugin):
    """ADK plugin: the checkpoint every tool call passes through.

    Runs before each tool call, resolves the calling agent's grant, and
    either lets the call proceed or replaces the result with a structured
    denial the model can read. Both outcomes are ledger entries; a denial
    is evidence the fence held, so it is never silent.
    """

    def __init__(self, policy: FleetPolicy | None = None) -> None:
        super().__init__(name="authority")
        self.policy = policy or POLICY

    async def before_tool_callback(self, *, tool, tool_args, tool_context, **_):
        agent_name = getattr(tool_context, "agent_name", "unknown")
        grant = self.policy.grants.get(agent_name)
        identity = grant.identity if grant else agent_name
        allowed, reason = self.policy.check(agent_name, tool.name, tool_args or {})
        if allowed:
            # The caller's identity is established here, from the execution
            # context — a model does not get to name itself into a scope.
            func = getattr(tool, "func", None)
            if isinstance(tool_args, dict) and func is not None:
                try:
                    if "agent_name" in inspect.signature(func).parameters:
                        tool_args["agent_name"] = agent_name
                except (TypeError, ValueError):
                    pass
            BUS.record(
                EventKind.AGENT_STATE,
                identity,
                f"tool {tool.name}",
                Outcome.ALLOW,
                reason=reason,
            )
            return None  # proceed with the real tool call
        BUS.record(
            EventKind.DENIAL,
            identity,
            f"tool {tool.name}",
            Outcome.DENY,
            reason=reason,
        )
        return {
            "denied": True,
            "reason": reason,
            "note": "This denial is recorded in the audit ledger.",
        }
