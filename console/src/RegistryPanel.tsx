import { useState } from "react";

/** Ask the Agent Registry who publishes a capability, and mount them.
 *
 *  The fleet does this by itself when a condition surfaces a role nobody
 *  catalogued. This is the same call, put in the operator's hands: type
 *  a capability, see who publishes it and at what version, and mount it
 *  — or watch the mount refused because the published version is not one
 *  this fleet accepts.
 */

interface Found {
  found: boolean;
  name?: string;
  publisher?: string;
  department?: string;
  description?: string;
  version?: string;
  pinned?: string;
  satisfies_pin?: boolean;
  source?: string;
  skills?: string[];
  mounted?: boolean;
}

export function RegistryPanel() {
  const [role, setRole] = useState("wet-weather-bypass-specialist");
  const [res, setRes] = useState<Found | null>(null);
  const [busy, setBusy] = useState(false);

  const call = async (path: string) => {
    setBusy(true);
    try {
      const r = await fetch(`/api/registry/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
      });
      const b = await r.json();
      if (path === "search") setRes(b);
      else setRes((p) => (p ? { ...p, mounted: !!b.mounted } : p));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="registry-panel">
      <div className="reg-row">
        <span className="label">Agent Registry</span>
        <input
          className="mono"
          value={role}
          onChange={(e) => setRole(e.target.value)}
          placeholder="capability, e.g. wet-weather-bypass-specialist"
          onKeyDown={(e) => e.key === "Enter" && call("search")}
        />
        <button className="ghost" disabled={busy} onClick={() => call("search")}>
          {busy ? "…" : "search"}
        </button>
      </div>
      {res && (
        <div className={`reg-result ${res.found ? "" : "empty"}`}>
          {!res.found ? (
            <span className="reg-none">no publisher in this project offers that capability</span>
          ) : (
            <>
              <div className="reg-line">
                <b>{res.name}</b>
                <span className="reg-ver mono">v{res.version}</span>
                {res.pinned && (
                  <span className={`reg-pin mono ${res.satisfies_pin ? "ok" : "bad"}`}>
                    pinned {res.pinned} {res.satisfies_pin ? "✓" : "✗"}
                  </span>
                )}
                <span className="reg-src mono">via {res.source}</span>
              </div>
              <div className="reg-pub">{res.publisher}</div>
              {res.description && <div className="reg-desc">{res.description}</div>}
              <div className="reg-actions">
                {res.mounted ? (
                  <span className="reg-mounted">mounted · recommend authority, this facility only</span>
                ) : (
                  <button
                    className="ghost"
                    disabled={busy || res.satisfies_pin === false}
                    onClick={() => call("mount")}
                  >
                    {res.satisfies_pin === false ? "refused by version pin" : "mount"}
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
