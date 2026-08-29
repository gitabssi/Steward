import { useEffect, useState } from "react";
import type { LearnedFact, PendingDecision } from "./types";
import { decide } from "./useFleet";

/** The bottom band does one of two jobs.
 *
 *  When the fleet wants something, it shows that request in full — the
 *  agents who raised it, what each option costs, and the readback the
 *  operator has to confirm before anything irreversible can run. That is
 *  the most important thing on the screen whenever it exists.
 *
 *  When nothing is pending, the band shows the two pieces of the system
 *  that are otherwise invisible: the OT boundary Gemma enforces, and the
 *  forecast the permit sentinel reasons with. Both are live, and both can
 *  be exercised from here rather than taken on faith.
 */

interface Edge {
  reachable: boolean;
  endpoint: string;
  model?: string;
  boundary?: string;
}
interface ParamRow {
  parameter_desc: string;
  facilities: number;
  exceedance_months: number;
  recall_pct: number;
  median_lead_days: number;
}

const SAMPLE = "Dale Whitmore checked blower two at 341 Cedar Road, call him on 555-201-8899.";

export function Instruments({
  pending,
  selected,
  onClear,
  mode,
  facts = [],
  memoryBackend = "",
}: {
  pending: PendingDecision[];
  selected: PendingDecision | null;
  onClear: () => void;
  /** "requests" sits above the plant; "instruments" below it. Splitting
   *  them means the fleet's question is never competing for the same
   *  band as the telemetry it is asking about. */
  mode: "requests" | "instruments";
  facts?: LearnedFact[];
  memoryBackend?: string;
}) {
  const [edge, setEdge] = useState<Edge | null>(null);
  const [params, setParams] = useState<ParamRow[]>([]);
  const [note, setNote] = useState<{ raw: string; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try { setEdge(await (await fetch("/api/edge")).json()); } catch { /* shown as unreachable */ }
      try {
        const b = await (await fetch("/api/finding/by-parameter")).json();
        if (b.parameters) setParams(b.parameters);
      } catch { /* panel renders its own absence */ }
    })();
  }, []);

  const open = selected ?? pending.find((d) => !d.resolved) ?? null;
  if (mode === "requests" && !open) return null;

  if (open) {
    return (
      <div className="region instruments request-open">
        <div className="inst-head">
          <span className="label">The fleet is asking</span>
          <span className="asked-by mono">
            {open.asked_by?.length ? open.asked_by.join(" · ") : "fleet-orchestrator"}
          </span>
          <span className="window mono">
            {open.window_minutes < 90
              ? `${Math.round(open.window_minutes)} min`
              : `${(open.window_minutes / 60).toFixed(1)} h`}{" "}
            window
          </span>
          {selected && (
            <button className="ghost" onClick={onClear}>dismiss</button>
          )}
        </div>
        <div className="req-subject">{open.subject}</div>
        {confirming ? (
          <div className="readback">
            <span>
              Readback: <b>{confirming}</b>. Nothing irreversible has run yet.
            </span>
            <button
              className="confirm"
              onClick={() => { void decide(open.decision_id, confirming); setConfirming(null); onClear(); }}
            >
              CONFIRM
            </button>
            <button className="ghost" onClick={() => setConfirming(null)}>back</button>
          </div>
        ) : (
          <div className="req-options">
            {open.options.map((o) => (
              <button key={o.action} className="req-option" onClick={() => setConfirming(o.action)}>
                <span className="opt-action">{o.action}</span>
                {o.costs?.length > 0 && <span className="opt-cost">{o.costs.join(" · ")}</span>}
                {o.offered_by && <span className="opt-by mono">{o.offered_by}</span>}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="region instruments">
      <div className="inst">
        <div className="inst-title">
          <span className="label">Memory Bank · Vertex AI</span>
          <span className={`dot ${memoryBackend.startsWith("memory-bank") ? "up" : "down"}`} />
          <span className="inst-sub mono">{memoryBackend || "…"}</span>
        </div>
        <div className="inst-body">
          <span className="inst-sub">
            {facts.length} fact{facts.length === 1 ? "" : "s"} written by the fleet and
            reloaded at boot — none of this existed on day one
          </span>
          {facts.slice(0, 3).map((f) => (
            <div className="mb-fact" key={f.statement}>
              {f.statement}
              <span className="mono mb-obs"> · {f.observations}×</span>
            </div>
          ))}
          {facts.length === 0 && (
            <span className="inst-sub">nothing learned yet this shift</span>
          )}
        </div>
      </div>

      <div className="inst">
        <div className="inst-title">
          <span className="label">OT boundary · Gemma 4</span>
          <span className={`dot ${edge?.reachable ? "up" : "down"}`} />
          <span className="inst-sub mono">
            {edge?.model ?? "…"} · self-hosted, never an API call
          </span>
        </div>
        <div className="inst-body">
          <button
            className="ghost"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                const r = await fetch("/api/edge/transcribe", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ text: SAMPLE }),
                });
                const b = await r.json();
                if (b.text) setNote({ raw: b.raw, text: b.text });
              } finally { setBusy(false); }
            }}
          >
            {busy ? "sending…" : "send a round note through the boundary"}
          </button>
          {note && (
            <div className="deident">
              <div className="raw">in&nbsp; {note.raw}</div>
              <div className="out">out {note.text}</div>
            </div>
          )}
        </div>
      </div>

      <div className="inst">
        <div className="inst-title">
          <span className="label">Forecast · TimesFM via BigQuery ML</span>
          <span className="inst-sub mono">measured on the public record</span>
        </div>
        <div className="inst-body forecast">
          {params.length === 0 ? (
            <span className="inst-sub">loading the backtest…</span>
          ) : (
            params.slice(0, 4).map((r) => (
              <div className="fc-row" key={r.parameter_desc}>
                <span className="fc-name">{r.parameter_desc}</span>
                <span className="fc-num mono">{r.recall_pct}%</span>
                <span className="fc-lead mono">{r.median_lead_days}d early</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
