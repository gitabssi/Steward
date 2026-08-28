import type { LedgerEntry, ShiftState } from "./types";

/** The Capacity Assessment — the artifact that leaves the system.
 *  Serif, on paper, unlike anything else on screen: the weekly deliverable
 *  is evidence of what the fleet could not do, stated as forward-looking
 *  capacity, and it goes to the board only when the operator sends it. */

export function Capacity({
  entry,
  state,
  onDismiss,
  onSend,
}: {
  entry: LedgerEntry;
  state: ShiftState | null;
  onDismiss: () => void;
  onSend: () => void;
}) {
  const week = state?.week;
  const degraded = (entry.detail?.degraded_tonight as string[]) ?? [];
  const curve = entry.detail?.escalation_curve as
    | { day_1: { sent: number; acted_on: number }; today: { sent: number; acted_on: number } }
    | undefined;

  return (
    <div className="capacity">
      <div className="sheet">
        <div className="mono" style={{ fontSize: 11, color: "var(--ink-soft)", marginBottom: 18 }}>
          CAPACITY ASSESSMENT · WEEK ENDING · CEDAR RIDGE WRF · PREPARED BY THE FLEET,
          APPROVED BY THE OPERATOR OF RECORD
        </div>
        <h1>
          {week?.obligations_degraded ?? 41} obligations degraded to protect{" "}
          {week?.obligations_protected ?? 9}.
        </h1>
        <p>
          The fleet completed {week?.process_check_hours_returned ?? 14} hours of process
          checks this week. Escalations fell from {curve?.day_1?.sent ?? 22} on day one
          ({curve?.day_1?.acted_on ?? 4} acted on) to {curve?.today?.sent ?? 6} today
          ({curve?.today?.acted_on ?? 5} acted on): it is learning what deserves this
          operator's attention.
        </p>
        <p>
          Deprioritized tonight, by his decision, cost recorded:{" "}
          {degraded.length > 0 ? degraded.join("; ") : "—"}.
        </p>
        <p>{String(entry.detail?.note ?? "")}</p>
        <p className="fine">
          This assessment documents the limits of automation at current capacity. It is
          forward-looking; it indicts no budget and no person.
        </p>
        <div style={{ display: "flex", gap: 12, marginTop: 28 }}>
          <button
            onClick={onSend}
            style={{
              fontFamily: "var(--mono)",
              fontSize: 12,
              padding: "8px 18px",
              background: "var(--ink)",
              color: "#fbf8f1",
              border: "none",
              cursor: "pointer",
            }}
          >
            SEND TO THE BOARD
          </button>
          <button
            onClick={onDismiss}
            style={{
              fontFamily: "var(--mono)",
              fontSize: 12,
              padding: "8px 18px",
              background: "none",
              border: "1px solid var(--rule)",
              cursor: "pointer",
            }}
          >
            NOT NOW
          </button>
        </div>
      </div>
    </div>
  );
}
