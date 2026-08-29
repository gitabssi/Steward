import { useMemo, useState } from "react";
import { Capacity } from "./Capacity";
import { ControlCentre } from "./ControlCentre";
import { Defences } from "./Defences";
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
  const { entries, state, roster, finding, runtime, live } = useFleet();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [capacityDismissed, setCapacityDismissed] = useState(false);
  const [voice, setVoice] = useState(false);
  const [openRequest, setOpenRequest] = useState<PendingDecision | null>(null);
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
        <FleetStrip
          roster={roster}
          entries={entries}
          pending={state?.pending ?? []}
          onOpenRequest={setOpenRequest}
        />
        <div className="region plant">
          <PlantSection state={state} entries={entries} live={live} />
          <SystemLine entries={entries} voice={voice} onSpeaking={setSpeaking} />
        </div>
        <PermitLines state={state} />
        <RegistryPanel />
        <Defences entries={entries} finding={finding} />
        <Instruments
          pending={state?.pending ?? []}
          selected={openRequest}
          onClear={() => setOpenRequest(null)}
        />
        <Ledger entries={entries} />
        <div className="honesty">
          Representative facility. Real EPA permit structure and limits. Live agents, live
          models, live Google Cloud.
        </div>
      </div>

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
