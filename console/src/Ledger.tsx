import type { LedgerEntry } from "./types";

/** The audit ledger — on screen for the whole session, denials alongside
 *  allowances, every row attributed to an agent identity with the real
 *  trace id that Cloud Trace holds on the other side of the split screen. */

const HIDDEN = new Set(["telemetry"]); // telemetry lives on the plant, not here

function verbFor(entry: LedgerEntry): string {
  if (entry.outcome === "DENY") return "DENIED";
  switch (entry.kind) {
    case "quarantine":
      return "QUARANTINED";
    case "guard":
      return "SCREENED";
    case "registry":
      return "REGISTRY";
    case "handoff":
      return "HANDOFF";
    case "decision":
      return "DECIDED";
    case "escalation":
      return "ESCALATED";
    case "contention":
      return "CONTENTION";
    case "proposal":
      return "PROPOSED";
    case "memory":
      return "LEARNED";
    case "pin":
      return "PINNED";
    case "capacity":
      return "ISSUED";
    default:
      return entry.outcome === "ALLOW" ? "ALLOWED" : "—";
  }
}

export function Ledger({ entries }: { entries: LedgerEntry[] }) {
  const rows = entries.filter((entry) => !HIDDEN.has(entry.kind)).slice(-26);
  return (
    <div className="ledger">
      <div style={{ padding: "12px 14px 6px", borderBottom: "1px solid var(--rule)" }}>
        <span className="label">Audit ledger</span>
        <span className="label" style={{ float: "right", color: "var(--ink-soft)" }}>
          denials recorded alongside allowances
        </span>
      </div>
      <div className="rows">
        {[...rows].reverse().map((entry) => (
          <div key={entry.entry_id} className={`lrow ${entry.outcome === "DENY" ? "deny" : ""}`}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
              <span className="who">{entry.actor}</span>
              <span className="verdict">{verbFor(entry)}</span>
            </div>
            <div>{entry.action}</div>
            {typeof entry.detail?.reason === "string" && (
              <div style={{ color: "var(--ink-soft)", fontSize: 11 }}>{entry.detail.reason}</div>
            )}
            {typeof entry.detail?.latency_ms === "number" && (
              <div style={{ color: "var(--ink-soft)", fontSize: 11 }}>
                resolved in {(entry.detail.latency_ms as number).toFixed(0)} ms
              </div>
            )}
            <div className="trace">trace {entry.trace_id.slice(0, 20)}…</div>
          </div>
        ))}
      </div>
    </div>
  );
}
