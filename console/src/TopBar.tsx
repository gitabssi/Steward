import type { ShiftState } from "./types";

function uptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return days > 0 ? `${days}d ${hours}h` : `${hours}h ${minutes}m`;
}

export function TopBar({
  state,
  live,
  voice,
  onToggleVoice,
  onOpenControlCentre,
  onReopenCapacity,
}: {
  state: ShiftState | null;
  live: boolean;
  voice: boolean;
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
        <div>
          <span className="label">Fleet uptime </span>
          <span className="v">{state ? uptime(state.uptime_seconds) : "—"}</span>
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
          title="Chirp 3 HD — system voice, in product"
          style={{
            fontFamily: "var(--mono)",
            fontSize: 11,
            background: voice ? "var(--ink)" : "none",
            color: voice ? "var(--ground)" : "var(--ink)",
            border: "1px solid var(--rule)",
            padding: "6px 12px",
            cursor: "pointer",
          }}
        >
          VOICE {voice ? "ON" : "OFF"}
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
