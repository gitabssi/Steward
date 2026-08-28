import { useEffect, useRef, useState } from "react";
import type { LedgerEntry, ShiftState } from "./types";

/** One SSE subscription to the fleet's ledger, plus state polling.
 *  If the stream drops, the console degrades (banner via `live=false`)
 *  and keeps rendering the last known world — it never blanks. */
export function useFleet() {
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [state, setState] = useState<ShiftState | null>(null);
  const [live, setLive] = useState(false);
  const seen = useRef(new Set<string>());

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

    return () => {
      source?.close();
      window.clearTimeout(retry);
      window.clearInterval(poll);
    };
  }, []);

  return { entries, state, live };
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
