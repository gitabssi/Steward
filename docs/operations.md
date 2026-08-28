# Operations — how the fleet fails, and what happens next

Judges asked two questions by name: *how does the system recover if a
worker agent loops or hallucinates?* and *what happens on token runaway?*
This document answers those, and the rest of the failure surface, with
pointers to the code that does it.

## A worker asserts something it cannot support

Everything a worker wants to put in front of the operator passes through
the supervisor ([app/fleet/supervisor.py](../app/fleet/supervisor.py)):

1. **No cited source → compromised.** The claim is withheld, the worker's
   grant is revoked live (`quarantined = True`, which makes the authority
   plugin refuse its every subsequent tool call), and the task is
   re-issued to a freshly resolved replacement.
2. **Source exists → the supervisor reads it itself** and compares. A
   deviation beyond `RELATIVE_TOLERANCE` (15%) is treated identically:
   withheld, quarantined, re-issued.
3. All three steps are attributed ledger rows with trace ids. The
   operator sees one line: *"That number never reached you."*

Test coverage: `tests/unit/test_fleet.py::TestSupervisor`.

## A worker loops, or a task runs away

Every issued task carries a `TaskEnvelope`: a **step budget (24)** and a
**wall-clock ceiling (120 s)**. `enforce_budget()` is charged on every
model/tool step inside the runner loop; exhaustion is a quarantine, not a
retry storm — the worker is stopped, the ledger records how far it got,
and the task is re-issued once to a fresh instance. There is no path
where a looping worker consumes tokens unobserved: the budget is charged
in the same loop that would spend them.

## A model endpoint is unavailable

`ReasoningPool.ask()` ([app/fleet/llm.py](../app/fleet/llm.py)) wraps
every reasoning call. On endpoint failure or contract-parse failure the
worker's **deterministic fallback line** is used — terse, numeric,
computed from the same telemetry — and a SYSTEM ledger row records
`model endpoint unavailable — deterministic fallback used`. The console
renders it like any other utterance; the ledger tells the truth about
where it came from. Nothing is ever silently degraded.

Retry policy at the SDK layer: 3 attempts (`HttpRetryOptions`) before
the fallback fires.

## Partial fleet failure

The shift loop contains every tick in its own try/except: a failing
agent, tool, or subsystem produces a `tick failed and was contained`
ledger row and the loop continues. The console's SSE client reconnects
with backoff and, while disconnected, shows `DEGRADED — last known state
shown` and freezes the breathing animation. **The console degrades; it
never blanks.**

## Firestore / Memory Bank unavailable

Both record their own absence at boot (`firestore unavailable — ledger
is in-memory only`, `Memory Bank unavailable — using local store`) and
continue on in-process fallbacks. The active backend is always stated in
the ledger — a silent fallback is indistinguishable from a lie.

## The chaos harness: a lagging replica, not a scripted failure

`STEWARD_FAULT_INJECTION=stale_lab_context` serves the mounted
specialist telemetry from **forty plant-minutes ago, labelled as
current** — the readings a historian replica behind on replication, a
cached read, or a backed-up queue would still be handing out. Nobody
tells the reader the data is old; that is the whole point.

Mid-surge those numbers are wrong by multiples, not margins. Measured at
the moment the specialist is consulted (plant-minute ~52, briefed from
minute ~12):

| reading | live | stale briefing | off by |
|---|---|---|---|
| `aeration_do_mg_l` | 1.35 | 2.41 | 77.8% |
| `effluent_ammonia_mg_l` | 2.17 | 0.70 | 67.6% |
| `influent_flow_mgd` | 2.85 | 1.62 | 43.0% |
| `effluent_tss_mg_l` | 11.16 | 8.55 | 23.4% |

Three of the four exceed the supervisor's 35% tolerance, so a specialist
reasoning honestly from the briefing will assert at least one figure the
live sensors contradict — and the supervisor, which re-reads every cited
sensor itself, catches it and withholds the claim.

**What is injected is a world fact** (a cache served old data) and a
contaminated document (the poisoned lab report, screened by Model Armor
before any model context sees it). **What is never injected is the
response.** Whether the guard strips the instruction, whether the
specialist cites a stale number, and whether the supervisor quarantines
it are all decided at runtime. That is the chaos-engineering posture:
inject faults, never outcomes — which is also why the beat is not
perfectly deterministic, and why `TSS` alone would slip through.

## Approval tokens

Irreversible tools require a single-use token minted only by the
console's decision route — after readback and confirmation by the
operator. Tokens bind to one action fingerprint, expire in 5 minutes,
and burn on first redemption (`tests/unit/test_fleet.py::TestApprovalVault`).
No agent code path can mint one.
