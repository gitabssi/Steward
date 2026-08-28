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
  onOpenControlCentre,
}: {
  state: ShiftState | null;
  live: boolean;
  onOpenControlCentre: () => void;
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
