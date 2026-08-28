import type { ShiftState } from "./types";

/** Four parameters against one idea: the permit line. Everything below it
 *  is a quiet night. When the permit-sentinel pins a parameter, that
 *  parameter grows and the others step back — the agent rearranged the
 *  operator's screen, and the attribution is in the ledger. */

const SHOWN: { parameter: string; telemetryKey: string }[] = [
  { parameter: "tss", telemetryKey: "effluent_tss_mg_l" },
  { parameter: "cbod5", telemetryKey: "effluent_cbod5_mg_l" },
  { parameter: "ammonia", telemetryKey: "effluent_ammonia_mg_l" },
  { parameter: "flow", telemetryKey: "influent_flow_mgd" },
];

export function PermitLines({ state }: { state: ShiftState | null }) {
  if (!state) return <div className="region permit" />;
  const pinned = state.pinned_parameter;
  return (
    <div className="region permit">
      {SHOWN.map(({ parameter, telemetryKey }) => {
        const limit = state.permit_limits.find((l) => l.parameter === parameter);
        const value = state.telemetry[telemetryKey] ?? 0;
        const cap = limit?.limit ?? 1;
        const ratio = Math.min(value / cap, 1.15);
        const color =
          ratio >= 1 ? "var(--red)" : ratio > 0.72 ? "var(--amber)" : "var(--effluent)";
        const cls =
          pinned === parameter ? "param pinned" : pinned ? "param demoted" : "param";
        return (
          <div key={parameter} className={cls}>
            <div className="head">
              <span className="label">{limit?.label ?? parameter}</span>
              <span className="lim">
                limit {cap} {limit?.unit}
              </span>
            </div>
            <div className="bar">
              <div className="line" style={{ top: "18%" }} />
              <div
                className="fill"
                style={{
                  height: `${Math.min(ratio * 82, 100)}%`,
                  background: color,
                  opacity: 0.65,
                }}
              />
            </div>
            <div className="head">
              <span className="val" style={{ color: ratio > 0.72 ? color : "var(--ink)" }}>
                {value.toFixed(value >= 10 ? 1 : 2)}
              </span>
              <span className="lim">{limit?.unit}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
