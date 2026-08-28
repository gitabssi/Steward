import { useEffect, useState } from "react";
import { setAuthority } from "./useFleet";
import type { LearnedFact, RegistryRow, RosterGrant } from "./types";

/** The drawer over the console: every agent individually inspectable —
 *  identity, scope, authority, what it has learned — and the operator can
 *  promote or demote authority live. The registry panel shows both
 *  publishers side by side: cross-department is a fact here, not a word. */

const LEVELS = ["observe", "recommend", "act"] as const;

export function ControlCentre({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [grants, setGrants] = useState<RosterGrant[]>([]);
  const [facts, setFacts] = useState<LearnedFact[]>([]);
  const [registry, setRegistry] = useState<RegistryRow[]>([]);

  useEffect(() => {
    if (!open) return;
    const load = async () => {
      const body = await (await fetch("/api/roster")).json();
      setGrants(body.grants ?? []);
      setFacts(body.learned_facts ?? []);
      setRegistry(body.registry ?? []);
    };
    void load();
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [open]);

  return (
    <div className={`drawer ${open ? "open" : ""}`}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
        <span className="label" style={{ fontSize: 13 }}>
          Control Centre
        </span>
        <button
          onClick={onClose}
          style={{ background: "none", border: "none", cursor: "pointer", fontSize: 16 }}
        >
          ×
        </button>
      </div>

      <span className="label">Agents · authority is enforced per tool call</span>
      {grants.map((grant) => (
        <div key={grant.identity} className={`agent-card ${grant.quarantined ? "quarantined" : ""}`}>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span className="id">{grant.identity}</span>
            <span className="mono" style={{ fontSize: 10, color: "var(--ink-soft)" }}>
              scope {grant.facility}
            </span>
          </div>
          <div style={{ fontSize: 12, margin: "4px 0 6px" }}>{grant.description}</div>
          <div style={{ display: "flex", gap: 6 }}>
            {LEVELS.map((level) => (
              <span
                key={level}
                className={`authority-pill ${grant.authority === level ? "active" : ""}`}
                onClick={() =>
                  void setAuthority(grant.identity.split("@")[0].replace(/-/g, "_"), level)
                }
              >
                {level.toUpperCase()}
              </span>
            ))}
            {grant.quarantined && (
              <span className="mono" style={{ fontSize: 10, color: "var(--red)", marginLeft: "auto" }}>
                QUARANTINED
              </span>
            )}
          </div>
        </div>
      ))}

      <span className="label" style={{ marginTop: 18 }}>
        Registry · cross-department — two publishers
      </span>
      {registry.map((row) => (
        <div key={row.name} className="agent-card">
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span className="id">{row.name}</span>
            <span className="mono" style={{ fontSize: 10, color: row.department === "steward-fleet" ? "var(--ink-soft)" : "var(--amber)" }}>
              {row.publisher}
            </span>
          </div>
          <div style={{ fontSize: 11.5, marginTop: 3, color: "var(--ink-soft)" }}>
            {row.description} {row.mounted ? " · mounted" : ""}
          </div>
        </div>
      ))}

      <span className="label" style={{ marginTop: 18 }}>
        Learned facts · none of this existed on day one
      </span>
      {facts.slice(0, 8).map((fact) => (
        <div key={fact.statement} className="agent-card" style={{ padding: "7px 12px" }}>
          <div style={{ fontSize: 12.5 }}>{fact.statement}</div>
          <div className="mono" style={{ fontSize: 10, color: "var(--ink-soft)", marginTop: 2 }}>
            {fact.observations} observation{fact.observations === 1 ? "" : "s"} · {fact.subject} ·
            by {fact.learned_by}
          </div>
        </div>
      ))}
    </div>
  );
}
