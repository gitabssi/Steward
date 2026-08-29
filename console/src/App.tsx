import { useMemo, useState } from "react";
import { Capacity } from "./Capacity";
import { ControlCentre } from "./ControlCentre";
import { Defences } from "./Defences";
import { AgentDetail } from "./AgentDetail";
import { FleetStrip } from "./FleetStrip";
import { Ledger } from "./Ledger";
import { PermitLines } from "./PermitLines";
import { PlantSection } from "./PlantSection";
import { Instruments } from "./Instruments";
import { RegistryPanel } from "./RegistryPanel";
import { SystemLine } from "./SystemLine";
import { TopBar } from "./TopBar";
import type { PendingDecision } from "./types";
import { useFleet } from "./useFleet";

export default function App() {
  const { entries, state, roster, finding, runtime, facts, memoryBackend, live } =
    useFleet();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [capacityDismissed, setCapacityDismissed] = useState(false);
  const [voice, setVoice] = useState(false);
  const [openRequest, setOpenRequest] = useState<PendingDecision | null>(null);
  const [openAgent, setOpenAgent] = useState<string | null>(null);
  const [speaking, setSpeaking] = useState(false);

  const capacityEntry = useMemo(
    () => [...entries].reverse().find((entry) => entry.kind === "capacity"),
    [entries],
  );

  return (
    <>
      <div className="console">
        <TopBar
          state={state}
          runtime={runtime}
          live={live}
          facts={facts}
          memoryBackend={memoryBackend}
          voice={voice}
          speaking={speaking}
          onToggleVoice={() => setVoice((v) => !v)}
          onOpenControlCentre={() => setDrawerOpen(true)}
          onReopenCapacity={
            capacityEntry && capacityDismissed
              ? () => setCapacityDismissed(false)
              : undefined
          }
        />

        <div className="main">
          {/* Who is available comes before who is on shift: an operator
              picks the crew, so the roster reads as a consequence of the
              registry rather than a fixed list. */}
          <RegistryPanel />

          <FleetStrip
            roster={roster}
            entries={entries}
            pending={state?.pending ?? []}
            onOpenRequest={setOpenRequest}
            onOpenAgent={setOpenAgent}
          />

          {/* What the fleet wants sits directly above the plant it is
              talking about, not at the far bottom of the screen. */}
          <Instruments
            pending={state?.pending ?? []}
            selected={openRequest}
            onClear={() => setOpenRequest(null)}
            mode="requests"
          />

          <PermitLines state={state} />

          <div className="region plant">
            <PlantSection state={state} entries={entries} live={live} />
            <SystemLine entries={entries} voice={voice} onSpeaking={setSpeaking} />
          </div>

          <Defences entries={entries} finding={finding} />

          <Instruments
            pending={[]}
            selected={null}
            onClear={() => {}}
            mode="instruments"
            facts={facts}
            memoryBackend={memoryBackend}
          />

          <div className="honesty">
            Representative facility. Real EPA permit structure and limits. Live agents, live
            models, live Google Cloud.
          </div>
        </div>

        <Ledger entries={entries} />
      </div>

      <AgentDetail
        agent={openAgent}
        roster={roster}
        entries={entries}
        facts={facts}
        memoryBackend={memoryBackend}
        onClose={() => setOpenAgent(null)}
      />

      <ControlCentre open={drawerOpen} onClose={() => setDrawerOpen(false)} />

      {capacityEntry && !capacityDismissed && (
        <Capacity
          entry={capacityEntry}
          state={state}
          onDismiss={() => setCapacityDismissed(true)}
          onSend={() => setCapacityDismissed(true)}
        />
      )}

    </>
  );
}
