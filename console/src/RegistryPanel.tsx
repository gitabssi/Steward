import { useEffect, useState } from "react";

/** Who is available, and who is on the roster.
 *
 *  Searching by exact role only helps someone who already knows what to
 *  type, and an operator does not. So this lists everything the project
 *  knows about — the fleet's own catalog and whatever the managed Agent
 *  Registry holds — and lets him mount or release from the same place.
 */

interface Row {
  name: string;
  publisher?: string;
  description?: string;
  version?: string;
  pinned?: string;
  satisfies_pin?: boolean;
  mounted?: boolean;
  standing?: boolean;
  origin?: string;
  source?: string;
  department?: string;
}

export function RegistryPanel() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);

  const list = async (reveal = true) => {
    setBusy(true);
    try {
      const b = await (await fetch("/api/registry/list")).json();
      setRows(b.agents ?? []);
      setNote(b.registry_error ? `managed registry unreachable — showing the bundled catalog` : "");
      if (reveal) setOpen(true);
    } finally {
      setBusy(false);
    }
  };

  // Loaded at boot so the count is honest before anything is clicked, but
  // left closed: the roster is what the operator reads every day, and the
  // catalogue only matters on the day he needs someone new.
  useEffect(() => { void list(false); }, []);

  const act = async (role: string, what: "mount" | "unmount") => {
    setBusy(true);
    try {
      const r = await fetch(`/api/registry/${what}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
      });
      const b = await r.json();
      if (what === "mount" && b.mounted === false) setNote(b.reason ?? "");
      await list();
    } finally {
      setBusy(false);
    }
  };

  const shown = q.trim()
    ? rows.filter((r) =>
        `${r.name} ${r.publisher ?? ""} ${r.description ?? ""}`
          .toLowerCase()
          .includes(q.trim().toLowerCase()),
      )
    : rows;

  return (
    <div className="registry-panel">
      <div className="reg-row">
        <span className="label">Agent Registry</span>
        <input
          className="mono"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="search every agent this project can reach — or click to see all of them"
          onFocus={() => setOpen(true)}
        />
        <button className="ghost" disabled={busy} onClick={() => void list()}>
          {busy ? "…" : "refresh"}
        </button>
        <button className="ghost" onClick={() => setOpen((o) => !o)}>
          {open ? "hide" : `show all (${rows.length})`}
        </button>
        {note && <span className="reg-note">{note}</span>}
      </div>

      {open && (
        <div className="reg-list">
          {shown.map((r) => (
            <div className={`reg-item ${r.mounted ? "on" : ""}`} key={r.name}>
              <div className="reg-item-main">
                <span className="reg-item-name mono">{r.name}</span>
                {r.version && <span className="reg-ver mono">v{r.version}</span>}
                {r.pinned && (
                  <span className={`reg-pin mono ${r.satisfies_pin ? "ok" : "bad"}`}>
                    pinned {r.pinned} {r.satisfies_pin ? "✓" : "✗"}
                  </span>
                )}
                <span className="reg-origin mono">{r.origin ?? r.source}</span>
              </div>
              <div className="reg-item-pub">
                {r.publisher && r.publisher !== r.name ? r.publisher : (r.description ?? "")}
              </div>
              <div className="reg-item-act">
                {r.mounted ? (
                  <>
                    <span className="reg-on">on the roster</span>
                    {/* A visiting specialist can be sent home; the standing
                        crew is the plant's own, and is not dismissed from
                        a search box. */}
                    {!r.standing && (
                      <button className="ghost" disabled={busy} onClick={() => act(r.name, "unmount")}>
                        release
                      </button>
                    )}
                    {r.standing && <span className="reg-standing">standing crew</span>}
                  </>
                ) : (
                  <button
                    className="ghost"
                    disabled={busy || r.satisfies_pin === false}
                    onClick={() => act(r.name, "mount")}
                  >
                    {r.satisfies_pin === false ? "refused by version pin" : "mount"}
                  </button>
                )}
              </div>
            </div>
          ))}
          {shown.length === 0 && <div className="reg-none">no match in this list</div>}
        </div>
      )}
    </div>
  );
}
