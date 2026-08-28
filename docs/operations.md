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

## The poisoned document path (chaos harness)

`STEWARD_FAULT_INJECTION=stale_lab_context` briefs the mounted
specialist with an hours-old lab report instead of live reads — a
stale-context failure a real integration can produce. The injection is a
**world fact** (a contaminated input arrived); whether Model Armor
strips the embedded instruction and whether the supervisor quarantines
the resulting claim are the fleet's genuine responses. This is the same
posture as chaos engineering: we inject faults, never outcomes.

## Approval tokens

Irreversible tools require a single-use token minted only by the
console's decision route — after readback and confirmation by the
operator. Tokens bind to one action fingerprint, expire in 5 minutes,
and burn on first redemption (`tests/unit/test_fleet.py::TestApprovalVault`).
No agent code path can mint one.
