import { useMemo } from "react";
import { setAuthority } from "./useFleet";
import type { LearnedFact, LedgerEntry, RosterGrant } from "./types";

/** Everything about one agent, in the operator's language.
 *
 *  The roster answers "who is on shift". This answers the questions that
 *  follow: what does this one actually do, what has it done in the last
 *  few minutes, what has it learned about my plant — and, when it has
 *  been pulled off the floor, *why*, and what I can do about it.
 *
 *  The quarantine case matters most. A supervisor that isolates a worker
 *  without saying why is just an outage; the reason and the remedy are
 *  what make it governance.
 */

const BRINGS: Record<string, { governs: string; brings: string }> = {
  "flow-warden": {
    governs: "the headworks — influent, infiltration, retention time",
    brings:
      "Prices every proposal in retention time. When someone wants more air, this is the agent that says what it costs the clarifier, in minutes.",
  },
  "aeration-keeper": {
    governs: "the aeration basin — dissolved oxygen, mixed liquor, nitrification",
    brings:
      "The only agent holding a lever. Below about 1.5 mg/L the nitrifiers starve and ammonia climbs within hours; it may move the blowers, in scope.",
  },
  "permit-sentinel": {
    governs: "outfall 001 — every enforceable limit and its margin",
    brings:
      "Knows which limit breaches first and when. Pins the parameter that has become the night's problem and rewrites the screen around it.",
  },
  "weather-scout": {
    governs: "the sky and the creek — precipitation, drought, dilution",
    brings:
      "Turns weather into plant consequences: infiltration on a delay, and what share of the river at the intake is your own discharge.",
  },
  "notification-clerk": {
    governs: "the front office — handovers and outward notifications",
    brings:
      "Writes what leaves the room, and never sends it. A handover carries the reasoning, not just the numbers.",
  },
  "bypass-specialist": {
    governs: "40 CFR 122.41(m) — when a wet-weather bypass is lawful",
    brings:
      "Published by the state primacy agency, not by this fleet. Mounted for one event, scoped to this facility, recommend-only by publication policy.",
  },
};

export function AgentDetail({
  agent,
  roster,
  entries,
  facts,
  memoryBackend,
  onClose,
}: {
  agent: string | null;
  roster: RosterGrant[];
  entries: LedgerEntry[];
  facts: LearnedFact[];
  memoryBackend: string;
  onClose: () => void;
}) {
  const grant = roster.find((g) => g.identity.split("@")[0] === agent);

  const acts = useMemo(
    () =>
      entries
        .filter((e) => e.actor.split("@")[0] === agent && e.kind !== "telemetry")
        .slice(-9)
        .reverse(),
    [entries, agent],
  );

  const quarantine = useMemo(
    () =>
      [...entries]
        .reverse()
        .find((e) => e.kind === "quarantine" && e.actor.split("@")[0] === agent),
    [entries, agent],
  );

  const mine = facts.filter((f) => f.learned_by.split("@")[0] === agent);

  if (!agent || !grant) return null;
  const meta = BRINGS[agent] ?? { governs: "", brings: "" };

  return (
    <div className="agent-detail">
      <div className="ad-head">
        <div>
          <div className="ad-name mono">{grant.identity}</div>
          <div className="ad-governs">{meta.governs}</div>
        </div>
        <button className="ghost" onClick={onClose}>close</button>
      </div>

      {grant.quarantined && (
        <div className="ad-quarantine">
          <div className="ad-q-title">Pulled off the floor by the supervisor</div>
          <div className="ad-q-why">
            {String(quarantine?.detail?.reason ?? "reason not in this session's ledger")}
          </div>
          <div className="ad-q-what">
            Its claim was withheld from you and the task was re-issued to a fresh
            replacement, so nothing is waiting on it. Reinstate only if you have
            reason to believe the source it cited was right and the sensor wrong.
          </div>
          <button
            className="confirm"
            onClick={() => {
              void setAuthority(agent.replace(/-/g, "_"), grant.authority);
              onClose();
            }}
          >
            REINSTATE — I ACCEPT THE CLAIM
          </button>
        </div>
      )}

      <div className="ad-section">
        <span className="label">What it brings</span>
        <p className="ad-brings">{meta.brings}</p>
      </div>

      <div className="ad-section">
        <span className="label">Authority</span>
        <div className="ad-auth">
          <b className="mono">{grant.authority}</b> · scope {grant.facility}
          <div className="ad-fine">{grant.description}</div>
        </div>
      </div>

      <div className="ad-section">
        <span className="label">
          What it has learned {memoryBackend && <em className="mono">· {memoryBackend}</em>}
        </span>
        {mine.length === 0 ? (
          <div className="ad-fine">nothing attributed to this agent yet</div>
        ) : (
          mine.slice(0, 4).map((f) => (
            <div className="ad-fact" key={f.statement}>
              {f.statement}
              <span className="mono ad-obs"> · {f.observations}×</span>
            </div>
          ))
        )}
      </div>

      <div className="ad-section ad-acts">
        <span className="label">Last acts</span>
        {acts.length === 0 ? (
          <div className="ad-fine">quiet so far this shift</div>
        ) : (
          acts.map((e) => (
            <div className={`ad-act ${e.outcome === "DENY" ? "deny" : ""}`} key={e.entry_id}>
              <span className="ad-act-kind mono">{e.kind}</span>
              <span>{e.action}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
