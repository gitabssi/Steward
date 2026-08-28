"""Steward fleet — long-lived agents beside a part-time watershed steward.

The fleet is organised around one rule: an agent may see much, say some,
and do almost nothing. Every module here enforces a piece of that rule.

    events.py      append-only audit ledger + live event bus (SSE to console)
    authority.py   observe / recommend / act — enforced, not declared
    identity.py    per-facility scoping; cross-facility reads are denied
    guards.py      Model Armor screening of every inbound document
    supervisor.py  audits worker claims against cited sources; quarantines
    arbiter.py     resolves contention between agents that disagree
    registry.py    catalog cache at boot + live A2A resolve on a miss
    memory.py      learned facts about this plant and this operator
    agents/        the workers, each anchored to a station of the plant
"""
