import type { LearnedFact, ShiftState } from "./types";
import type { Runtime } from "./useFleet";

function uptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return days > 0 ? `${days}d ${hours}h` : `${hours}h ${minutes}m`;
}

export function TopBar({
  state,
  runtime,
  live,
  facts,
  memoryBackend,
  voice,
  speaking,
  onToggleVoice,
  onOpenControlCentre,
  onReopenCapacity,
}: {
  state: ShiftState | null;
  runtime: Runtime | null;
  live: boolean;
  /** Surfaced here rather than only in the panel below: what the fleet
   *  remembers between shifts is the difference between a crew and a
   *  script, and it should not require scrolling to see. */
  facts: LearnedFact[];
  memoryBackend: string;
  voice: boolean;
  speaking: boolean;
  onToggleVoice: () => void;
  onOpenControlCentre: () => void;
  /** Present only once the fleet has issued one — "not now" must not
   *  mean "never": the assessment is the week's deliverable. */
  onReopenCapacity?: () => void;
}) {
  const facility = state?.facility;
  return (
    <div className="region top">
      <div>
        <div className="name">STEWARD · {facility?.name ?? "—"}</div>
        <div className="cert">
          Certification of record: {facility?.operator_of_record ?? "—"} — every
          irreversible action requires his approval.
        </div>
      </div>
      <div className="stat">
        <div
          title={
            runtime?.deployed_at
              ? `engine ${runtime.engine_id} · deployed ${runtime.deployed_at}`
              : "engine age unavailable"
          }
        >
          <span className="label">Agent Runtime </span>
          <span className="v">
            {runtime?.age_seconds ? uptime(runtime.age_seconds) : "—"}
          </span>
          {runtime?.identity_type === "AGENT_IDENTITY" && (
            <span className="label"> · own identity</span>
          )}
        </div>
        <div title={memoryBackend ? `backend: ${memoryBackend}` : "memory backend unknown"}>
          <span className="label">Memory Bank </span>
          <span className="v">{facts.length}</span>
          <span className="label"> facts carried</span>
        </div>
        <div>
          <span className="label">Time returned this week </span>
          <span className="v">{state?.week?.process_check_hours_returned ?? "—"}h</span>
        </div>
        <div>
          <span
            className="v"
            style={{ color: live ? "var(--teal)" : "var(--red)", fontSize: 12 }}
          >
            {live ? "● LIVE" : "○ DEGRADED — last known state shown"}
          </span>
        </div>
        {onReopenCapacity && (
          <button
            onClick={onReopenCapacity}
            title="The week's capacity assessment, issued by the fleet"
            style={{
              fontFamily: "var(--mono)",
              fontSize: 11,
              background: "none",
              border: "1px solid var(--amber)",
              color: "var(--amber)",
              padding: "6px 12px",
              cursor: "pointer",
            }}
          >
            CAPACITY ASSESSMENT
          </button>
        )}
        <button
          onClick={onToggleVoice}
          title="Chirp 3 HD — the system's voice, spoken in product"
          className={speaking ? "voice-btn speaking" : "voice-btn"}
          style={{
            background: voice ? "var(--ink)" : "none",
            color: voice ? "var(--ground)" : "var(--ink)",
          }}
        >
          {voice ? (speaking ? "CHIRP ● SPEAKING" : "CHIRP 3 HD ON") : "VOICE OFF"}
        </button>
        <button
          onClick={onOpenControlCentre}
          style={{
            fontFamily: "var(--mono)",
            fontSize: 11,
            background: "none",
            border: "1px solid var(--rule)",
            padding: "6px 12px",
            cursor: "pointer",
            color: "var(--ink)",
          }}
        >
          CONTROL CENTRE
        </button>
      </div>
    </div>
  );
}
