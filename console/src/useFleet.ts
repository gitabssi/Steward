import { useEffect, useRef, useState } from "react";
import type { LedgerEntry, RosterGrant, ShiftState } from "./types";

/** One SSE subscription to the fleet's ledger, plus state polling.
 *  If the stream drops, the console degrades (banner via `live=false`)
 *  and keeps rendering the last known world — it never blanks. */
export interface Finding {
  facilities: number;
  reported_values: number;
  exceedance_months: number;
  recall_pct: number;
  precision_pct: number;
  median_lead_days: number;
  corpus: string;
}

export function useFleet() {
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [state, setState] = useState<ShiftState | null>(null);
  const [roster, setRoster] = useState<RosterGrant[]>([]);
  const [finding, setFinding] = useState<Finding | null>(null);
  const [live, setLive] = useState(false);
  const seen = useRef(new Set<string>());

  // The backtest is computed in BigQuery and never changes during a
  // shift, so it is fetched once and then simply stated on screen.
  useEffect(() => {
    void (async () => {
      try {
        const body = await (await fetch("/api/finding")).json();
        if (!("error" in body)) setFinding(body);
      } catch {
        /* the strip renders its own absence */
      }
    })();
  }, []);

  useEffect(() => {
    let source: EventSource | null = null;
    let retry: number | undefined;

    const connect = () => {
      source = new EventSource("/api/events");
      source.onopen = () => setLive(true);
      source.onmessage = (message) => {
        const entry: LedgerEntry = JSON.parse(message.data);
        if (seen.current.has(entry.entry_id)) return;
        seen.current.add(entry.entry_id);
        setEntries((prior) => [...prior.slice(-800), entry]);
      };
      source.onerror = () => {
        setLive(false);
        source?.close();
        retry = window.setTimeout(connect, 2000);
      };
    };
    connect();

    const poll = window.setInterval(async () => {
      try {
        const response = await fetch("/api/state");
        const body = await response.json();
        if (!("status" in body) && !("error" in body)) setState(body);
      } catch {
        /* degraded, not blank */
      }
    }, 1500);

    // The roster changes rarely (a mount, a promotion, a quarantine),
    // so it is polled slowly and kept even when a fetch fails.
    const rosterPoll = window.setInterval(async () => {
      try {
        const body = await (await fetch("/api/roster")).json();
        if (body.grants) setRoster(body.grants);
      } catch {
        /* keep the last known roster */
      }
    }, 4000);

    return () => {
      source?.close();
      window.clearTimeout(retry);
      window.clearInterval(poll);
      window.clearInterval(rosterPoll);
    };
  }, []);

  return { entries, state, roster, finding, live };
}

export async function decide(decision_id: string, action: string) {
  await fetch("/api/decide", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision_id, action }),
  });
}

export async function setAuthority(agent_name: string, authority: string) {
  await fetch("/api/authority", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent_name, authority }),
  });
}
