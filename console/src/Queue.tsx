import { useState } from "react";
import { decide } from "./useFleet";
import type { PendingDecision } from "./types";

/** A request queue, not a notification feed. Actors want something from
 *  the operator, and irreversible actions run only after readback and
 *  confirmation — the approval token is minted on Confirm, nowhere else. */

export function Queue({ pending }: { pending: PendingDecision[] }) {
  const open = pending.filter((decision) => !decision.resolved).slice(0, 2);
  const [confirming, setConfirming] = useState<{ id: string; action: string } | null>(null);

  if (open.length === 0)
    return (
      <div className="region queue">
        <div style={{ alignSelf: "center", color: "var(--ink-soft)", fontSize: 12 }}>
          No open requests. The fleet is watching.
        </div>
      </div>
    );

  return (
    <div className="region queue">
      {open.map((request) => (
        <div className="request" key={request.decision_id}>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span className="subject">{request.subject}</span>
            <span className="mono" style={{ fontSize: 11, color: "var(--amber)" }}>
              {request.window_minutes}h window
            </span>
          </div>
          {confirming?.id === request.decision_id ? (
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ fontSize: 12 }}>
                Readback: <b>{confirming.action}</b>. Confirm?
              </span>
              <button
                onClick={() => {
                  void decide(request.decision_id, confirming.action);
                  setConfirming(null);
                }}
              >
                CONFIRM
              </button>
              <button onClick={() => setConfirming(null)}>BACK</button>
            </div>
          ) : (
            <div className="options">
              {request.options.map((option) => (
                <button
                  key={option.action}
                  title={option.costs.join(" · ")}
                  onClick={() => setConfirming({ id: request.decision_id, action: option.action })}
                >
                  {option.action}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
