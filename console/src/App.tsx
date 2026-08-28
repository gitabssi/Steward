import { useMemo, useState } from "react";
import { Capacity } from "./Capacity";
import { ControlCentre } from "./ControlCentre";
import { Defences } from "./Defences";
import { FleetStrip } from "./FleetStrip";
import { Ledger } from "./Ledger";
import { PermitLines } from "./PermitLines";
import { PlantSection } from "./PlantSection";
import { Queue } from "./Queue";
import { SystemLine } from "./SystemLine";
import { TopBar } from "./TopBar";
import { useFleet } from "./useFleet";

export default function App() {
  const { entries, state, roster, finding, live } = useFleet();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [capacityDismissed, setCapacityDismissed] = useState(false);
  const [voice, setVoice] = useState(false);
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
        <FleetStrip roster={roster} entries={entries} />
        <div className="region plant">
          <PlantSection state={state} entries={entries} live={live} />
          <SystemLine entries={entries} voice={voice} onSpeaking={setSpeaking} />
        </div>
        <PermitLines state={state} />
        <Defences entries={entries} finding={finding} />
        <Queue pending={state?.pending ?? []} />
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
