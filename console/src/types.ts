// Mirrors app/fleet/events.py — one ledger entry per consequential act.
export type EventKind =
  | "telemetry"
  | "agent_state"
  | "handoff"
  | "proposal"
  | "contention"
  | "escalation"
  | "decision"
  | "denial"
  | "quarantine"
  | "guard"
  | "registry"
  | "memory"
  | "pin"
  | "capacity"
  | "system";

export interface LedgerEntry {
  entry_id: string;
  kind: EventKind;
  actor: string;
  action: string;
  outcome: "ALLOW" | "DENY" | "INFO";
  detail: Record<string, unknown>;
  trace_id: string;
  ts: number;
}

export interface PermitLimit {
  parameter: string;
  label: string;
  unit: string;
  limit?: number;
  limit_low?: number;
  limit_high?: number;
  direction?: string;
}

export interface PendingDecision {
  decision_id: string;
  subject: string;
  options: { action: string; offered_by: string; costs: string[]; window_minutes: number }[];
  window_minutes: number;
  resolved: string | null;
  asked_by?: string[];
}

export interface ShiftState {
  facility: {
    name: string;
    npdes_id: string;
    operator_of_record: string;
    certification: string;
    downstream_intake: { name: string; distance_miles: number; population_served: number };
  };
  telemetry: Record<string, number>;
  permit_limits: PermitLimit[];
  dilution_pct: number;
  pinned_parameter: string | null;
  pending: PendingDecision[];
  obligations_degraded: string[];
  week: {
    process_check_hours_returned: number;
    escalations_day1: { sent: number; acted_on: number };
    escalations_today: { sent: number; acted_on: number };
    obligations_protected: number;
    obligations_degraded: number;
  };
  shift_seconds: number;
  minutes_on_shift: number;
}

export interface RosterGrant {
  identity: string;
  facility: string;
  authority: "observe" | "recommend" | "act";
  description: string;
  quarantined: boolean;
}

export interface LearnedFact {
  subject: string;
  statement: string;
  observations: number;
  learned_by: string;
}

export interface RegistryRow {
  name: string;
  publisher: string;
  department: string;
  description: string;
  mounted: boolean;
}
