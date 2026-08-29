import { useMemo } from "react";
import type { LedgerEntry, PendingDecision, RosterGrant } from "./types";

/** The fleet, as a fleet.
 *
 *  Agents were previously readable only as dots on the cross-section and
 *  as names in a log, which made a five-agent system look like one
 *  program with a chatty logger. Each agent now holds a card that states
 *  who it is, what it may do, and what it is doing this second — so the
 *  roster reads as a crew on shift, and a quarantine reads as one of
 *  them being pulled off the floor.
 */

const AUTHORITY_BLURB: Record<string, string> = {
  observe: "reads · cannot act",
  recommend: "drafts · cannot act",
  act: "may act, in scope",
};

interface AgentView {
  key: string;
  name: string;
  authority: string;
  quarantined: boolean;
  external: boolean;
  doing: string;
  activeAgo: number;
}

export function FleetStrip({
  roster,
  entries,
  pending,
  onOpenRequest,
  onOpenAgent,
}: {
  roster: RosterGrant[];
  entries: LedgerEntry[];
  pending: PendingDecision[];
  onOpenRequest: (d: PendingDecision) => void;
  onOpenAgent: (name: string) => void;
}) {
  // A request belongs to whoever raised it. Showing it on their card is
  // the difference between an actor asking for something and a queue
  // that nobody owns.
  const askedBy = new Map<string, PendingDecision>();
  for (const d of pending.filter((x) => !x.resolved)) {
    for (const who of d.asked_by ?? []) askedBy.set(who.split("@")[0], d);
    if (!d.asked_by?.length) askedBy.set("fleet-orchestrator", d);
  }
  const now = Date.now() / 1000;

  const agents = useMemo<AgentView[]>(() => {
    const lastAct: Record<string, { at: number; what: string }> = {};
    for (const entry of entries) {
      const bare = entry.actor.split("@")[0];
      if (entry.kind === "telemetry") continue;
      const what =
        entry.kind === "agent_state" && typeof entry.detail?.say === "string" && entry.detail.say
          ? "speaking"
          : entry.kind === "proposal"
            ? "proposing"
            : entry.kind === "handoff"
              ? "handing off"
              : entry.action.startsWith("read ")
                ? "reading"
                : entry.action.startsWith("claim")
                  ? "checked"
                  : entry.kind === "quarantine"
                    ? "quarantined"
                    : "working";
      lastAct[bare] = { at: entry.ts, what };
    }
    return roster.map((g) => {
      const bare = g.identity.split("@")[0];
      const act = lastAct[bare];
      return {
        key: g.identity,
        name: bare,
        authority: g.authority,
        quarantined: g.quarantined,
        external: !g.identity.endsWith("@cedar-ridge"),
        doing: act?.what ?? "on watch",
        activeAgo: act ? now - act.at : 999,
      };
    });
  }, [roster, entries, now]);

  if (agents.length === 0) {
    return (
      <div className="region fleet">
        <span className="label">Fleet</span>
        <span className="fleet-empty">waiting for the shift to report in…</span>
      </div>
    );
  }

  const onShift = agents.filter((a) => !a.quarantined).length;

  return (
    <div className="region fleet">
      <div className="fleet-head">
        <span className="label">Fleet on shift</span>
        <span className="fleet-count mono">
          {onShift}/{agents.length}
        </span>
        <span className="fleet-note">none of them can touch the outfall</span>
      </div>
      <div className="fleet-cards">
        {agents.map((a) => {
          const active = a.activeAgo < 6;
          const cls = [
            "agent-chip",
            "clickable",
            a.quarantined ? "quarantined" : "",
            active ? "active" : "",
            a.external ? "external" : "",
          ]
            .filter(Boolean)
            .join(" ");
          const request = askedBy.get(a.name);
          return (
            <div
              className={cls + (request ? " asking" : "")}
              key={a.key}
              title={a.key}
              onClick={() => onOpenAgent(a.name)}
            >
              <div className="chip-top">
                <span className="chip-name mono">{a.name}</span>
                <span className={`chip-auth auth-${a.authority}`}>
                  {a.quarantined ? "HELD" : a.authority.toUpperCase()}
                </span>
              </div>
              <div className="chip-doing">
                {a.quarantined ? "pulled off the floor by the supervisor" : a.doing}
              </div>
              {request && (
                <button className="chip-request" onClick={(e) => { e.stopPropagation(); onOpenRequest(request); }}>
                  needs a decision →
                </button>
              )}
              <div className="chip-scope mono">
                {a.external ? "state primacy agency" : AUTHORITY_BLURB[a.authority] ?? ""}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
