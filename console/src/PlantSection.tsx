import { useEffect, useMemo, useState } from "react";
import type { LedgerEntry, ShiftState } from "./types";

/** The console is a cross-section of the plant, not a dashboard.
 *  Headworks → primary → aeration → secondary → UV → outfall → creek →
 *  the downstream intake. Agents live at their stations; when one acts,
 *  its anchor comes alive; when one hands a finding to another, the
 *  trace is drawn between their stations. The aeration basin breathes on
 *  a slow cycle that quickens under load — and stops if the process does. */

const STATIONS: Record<string, { x: number; label: string }> = {
  headworks: { x: 60, label: "HEADWORKS" },
  primary: { x: 195, label: "PRIMARY" },
  aeration: { x: 345, label: "AERATION" },
  secondary: { x: 505, label: "SECONDARY" },
  disinfection: { x: 630, label: "UV" },
  outfall: { x: 725, label: "OUTFALL 001" },
  creek: { x: 830, label: "CEDAR CREEK" },
  intake: { x: 950, label: "INTAKE" },
};

const AGENT_STATION: Record<string, string> = {
  "flow-warden": "headworks",
  "aeration-keeper": "aeration",
  "permit-sentinel": "outfall",
  "weather-scout": "creek",
  "bypass-specialist": "secondary",
  "notification-clerk": "disinfection",
};

// Staggered label rows so neighbouring identities never collide.
const LABEL_ROW: Record<string, number> = {
  "notification-clerk": 56,
  "bypass-specialist": 56,
};

function agentOf(actor: string): string | null {
  const bare = actor.split("@")[0];
  return bare in AGENT_STATION ? bare : null;
}

interface Trace {
  id: string;
  from: string;
  to: string;
  born: number;
}

export function PlantSection({
  state,
  entries,
  live,
}: {
  state: ShiftState | null;
  entries: LedgerEntry[];
  live: boolean;
}) {
  const t = state?.telemetry ?? {};
  const influent = t.influent_flow_mgd ?? 1.6;
  const doLevel = t.aeration_do_mg_l ?? 2.4;
  const design = 2.6;
  const loadRatio = Math.min(influent / design, 1.4);

  // Breathing: 4s at rest, down toward 1.6s under stress. Stopped if dead.
  const breath = Math.max(1.6, 4 - 2.4 * Math.max(0, loadRatio - 0.62));
  const stressed = doLevel < 1.5;

  // Recent activity per agent: the anchor comes alive for 4s after it
  // acts. Quarantine is different — it is a standing state, not a blip,
  // so it is tracked across the whole session and cleared only when the
  // operator reinstates the agent. A fence that stops being visible
  // because the ledger scrolled is a fence nobody can audit.
  const now = Date.now() / 1000;
  const activity = useMemo(() => {
    const map: Record<string, { at: number; deny: boolean }> = {};
    const quarantined = new Set<string>();
    const recentFrom = Math.max(0, entries.length - 160);
    entries.forEach((entry, i) => {
      const agent = agentOf(entry.actor);
      if (!agent) return;
      if (entry.kind === "quarantine") quarantined.add(agent);
      if (entry.action.includes("reinstated from quarantine")) quarantined.delete(agent);
      if (i >= recentFrom) map[agent] = { at: entry.ts, deny: entry.outcome === "DENY" };
    });
    return { map, quarantined };
  }, [entries]);

  // Handoff traces render for ~3.5 s.
  const [traces, setTraces] = useState<Trace[]>([]);
  useEffect(() => {
    const latest = entries[entries.length - 1];
    if (!latest || latest.kind !== "handoff") return;
    const from = agentOf(latest.actor);
    const target = String(latest.action.split("→")[1] ?? "").trim();
    const to = agentOf(target);
    if (!from || !to) return;
    setTraces((prior) => [
      ...prior.filter((trace) => now - trace.born < 4),
      { id: latest.entry_id, from, to, born: now },
    ]);
    const timer = setTimeout(
      () => setTraces((prior) => prior.filter((trace) => trace.id !== latest.entry_id)),
      3500,
    );
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entries.length]);

  const intake = state?.facility?.downstream_intake;
  const dilution = state?.dilution_pct ?? 0;
  const waterY = 195;

  return (
    <svg viewBox="0 0 1000 330" style={{ width: "100%", height: "100%" }}>
      <style>{`
        .st-label { font: 500 9.5px "IBM Plex Sans Condensed"; letter-spacing: .09em; fill: var(--ink-soft); }
        .st-value { font: 600 13px "IBM Plex Mono"; fill: var(--ink); }
        .st-sub { font: 400 9px "IBM Plex Mono"; fill: var(--ink-soft); }
        .anchor-id { font: 500 9.5px "IBM Plex Mono"; }
        @keyframes breathe { 0%,100% { transform: scaleY(1); } 50% { transform: scaleY(1.055); } }
        @keyframes flowdash { to { stroke-dashoffset: -26; } }
        @keyframes tracein { from { stroke-dashoffset: 320; } to { stroke-dashoffset: 0; } }
        .basin-breath { transform-origin: center 205px; animation: breathe ${breath}s ease-in-out infinite; ${live ? "" : "animation-play-state: paused;"} }
        .trace-path { stroke-dasharray: 320; animation: tracein 1.4s ease forwards; }
      `}</style>

      {/* The OT boundary. Everything left of this line is the plant's
          own network; nothing raw crosses it. Gemma reads the raw
          telemetry here and emits a de-identified summary — which is
          why the operator's name and the sensor stream never appear
          anywhere else on this screen. */}
      <g>
        <line
          x1="14" y1="60" x2="14" y2="292"
          stroke="var(--liquor)" strokeWidth="2" strokeDasharray="6 5"
        />
        {/* Set along the boundary itself, so the label cannot collide
            with the headworks readings that sit just inside it. */}
        <text
          x="14" y="176" className="st-label" fill="var(--liquor)"
          transform="rotate(-90 14 176)" textAnchor="middle"
        >
          OT BOUNDARY · GEMMA 4 ON-PLANT · NOTHING RAW CROSSES
        </text>
      </g>

      {/* ground line */}
      <line x1="12" y1="238" x2="988" y2="238" stroke="var(--rule)" strokeWidth="1.5" />

      {/* process water: one continuous ribbon through the train */}
      <path
        d={`M 20 ${waterY} H 770`}
        stroke="var(--effluent)"
        strokeWidth={10 + 8 * loadRatio}
        strokeLinecap="round"
        opacity="0.5"
        strokeDasharray="14 12"
        style={{ animation: `flowdash ${Math.max(0.7, 2.2 - loadRatio)}s linear infinite` }}
      />

      {/* headworks */}
      <rect x="35" y="160" width="52" height="78" fill="none" stroke="var(--ink)" strokeWidth="1.4" />
      <text x="61" y="152" textAnchor="middle" className="st-label">HEADWORKS</text>
      <text x="61" y="262" textAnchor="middle" className="st-value">{influent.toFixed(2)}</text>
      <text x="61" y="275" textAnchor="middle" className="st-sub">MGD · rated {design.toFixed(1)}</text>

      {/* primary clarifier */}
      <path d="M 160 178 H 230 L 218 238 H 172 Z" fill="none" stroke="var(--ink)" strokeWidth="1.4" />
      <text x="195" y="170" textAnchor="middle" className="st-label">PRIMARY</text>

      {/* aeration basin — the breathing element */}
      <g className="basin-breath">
        <rect x="280" y="172" width="130" height="66" fill="var(--green)" opacity="0.13" />
        <rect x="280" y="172" width="130" height="66" fill="none" stroke="var(--green)" strokeWidth="1.6" />
        {[0, 1, 2, 3, 4].map((i) => (
          <circle
            key={i}
            cx={298 + i * 24}
            cy={228 - (i % 3) * 14}
            r={2 + (i % 2)}
            fill="var(--green)"
            opacity="0.55"
          />
        ))}
      </g>
      <text x="345" y="164" textAnchor="middle" className="st-label">AERATION</text>
      <text x="345" y="262" textAnchor="middle" className="st-value" fill={stressed ? "var(--amber)" : "var(--ink)"}>
        DO {doLevel.toFixed(1)}
      </text>
      <text x="345" y="275" textAnchor="middle" className="st-sub">mg/L · blowers {(t.blower_capacity_pct ?? 58).toFixed(0)}%</text>

      {/* secondary clarifier */}
      <path d="M 470 178 H 540 L 528 238 H 482 Z" fill="none" stroke="var(--ink)" strokeWidth="1.4" />
      <text x="505" y="170" textAnchor="middle" className="st-label">SECONDARY</text>
      <text x="505" y="262" textAnchor="middle" className="st-value">TSS {(t.effluent_tss_mg_l ?? 8.5).toFixed(1)}</text>
      <text x="505" y="275" textAnchor="middle" className="st-sub">mg/L at weir</text>

      {/* UV disinfection */}
      <rect x="612" y="184" width="36" height="54" fill="none" stroke="var(--ink)" strokeWidth="1.4" />
      {[0, 1, 2].map((i) => (
        <line key={i} x1={620 + i * 10} y1="188" x2={620 + i * 10} y2="234" stroke="var(--teal)" strokeWidth="1" opacity="0.6" />
      ))}
      <text x="630" y="176" textAnchor="middle" className="st-label">UV</text>

      {/* outfall */}
      <path d="M 700 195 Q 740 195 752 225" fill="none" stroke="var(--effluent)" strokeWidth="7" strokeLinecap="round" opacity="0.8" />
      <text x="725" y="168" textAnchor="middle" className="st-label">OUTFALL 001</text>
      <text x="725" y="262" textAnchor="middle" className="st-value">
        NH₃ {(t.effluent_ammonia_mg_l ?? 0.7).toFixed(1)}
      </text>
      <text x="725" y="275" textAnchor="middle" className="st-sub">mg/L as N</text>

      {/* the creek, and who drinks it */}
      <path d="M 752 228 Q 800 240 988 232" fill="none" stroke="var(--effluent)" strokeWidth="12" strokeLinecap="round" opacity="0.45" />
      <text x="830" y="216" textAnchor="middle" className="st-label">CEDAR CREEK</text>
      <text x="830" y="262" textAnchor="middle" className="st-value" fill={dilution > 45 ? "var(--amber)" : "var(--ink)"}>
        {dilution.toFixed(0)}%
      </text>
      <text x="830" y="275" textAnchor="middle" className="st-sub">of streamflow is discharge</text>

      {/* downstream intake — on screen from the first frame */}
      <g>
        <line x1="950" y1="238" x2="950" y2="176" stroke="var(--ink)" strokeWidth="1.4" />
        <circle cx="950" cy="170" r="5" fill="none" stroke="var(--ink)" strokeWidth="1.4" />
        <text x="950" y="120" textAnchor="middle" className="st-label" fill="var(--ink)">
          MUNICIPAL INTAKE
        </text>
        <text x="950" y="134" textAnchor="middle" className="st-sub">
          {(intake?.population_served ?? 12400).toLocaleString()} SERVED
        </text>
        <text x="950" y="146" textAnchor="middle" className="st-sub">
          {(intake?.distance_miles ?? 8.2).toFixed(1)} MI DOWNSTREAM
        </text>
      </g>

      {/* handoff traces between agent anchors */}
      {traces.map((trace) => {
        const a = STATIONS[AGENT_STATION[trace.from]];
        const b = STATIONS[AGENT_STATION[trace.to]];
        if (!a || !b) return null;
        return (
          <path
            key={trace.id}
            className="trace-path"
            d={`M ${a.x} 92 C ${a.x} 56, ${b.x} 56, ${b.x} 92`}
            fill="none"
            stroke="var(--teal)"
            strokeWidth="1.6"
          />
        );
      })}

      {/* agent anchors */}
      {Object.entries(AGENT_STATION).map(([agent, stationId]) => {
        const station = STATIONS[stationId];
        const act = activity.map[agent];
        const isActive = act && now - act.at < 4;
        const isQuarantined = activity.quarantined.has(agent);
        const color = isQuarantined ? "var(--red)" : isActive ? "var(--teal)" : "var(--ink-soft)";
        if (agent === "bypass-specialist" && !act && !isQuarantined) return null; // not mounted yet
        return (
          <g key={agent}>
            <circle
              cx={station.x}
              cy="92"
              r={isActive ? 5 : 3.5}
              fill={isActive || isQuarantined ? color : "var(--ground)"}
              stroke={color}
              strokeWidth="1.4"
            />
            <line x1={station.x} y1="97" x2={station.x} y2="150" stroke={color} strokeWidth="0.8" strokeDasharray="2 3" opacity="0.7" />
            <text
              x={station.x}
              y={LABEL_ROW[agent] ?? 80}
              textAnchor="middle"
              className="anchor-id"
              fill={color}
            >
              {agent}
            </text>
            {isQuarantined && (
              <text x={station.x} y={(LABEL_ROW[agent] ?? 80) - 12} textAnchor="middle" className="anchor-id" fill="var(--red)">
                QUARANTINED
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
