import { useMemo, useState } from "react";
import { Capacity } from "./Capacity";
import { ControlCentre } from "./ControlCentre";
import { Ledger } from "./Ledger";
import { PermitLines } from "./PermitLines";
import { PlantSection } from "./PlantSection";
import { Queue } from "./Queue";
import { SystemLine } from "./SystemLine";
import { TopBar } from "./TopBar";
import { useFleet } from "./useFleet";

export default function App() {
  const { entries, state, live } = useFleet();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [capacityDismissed, setCapacityDismissed] = useState(false);
  const [voice, setVoice] = useState(false);

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
          onToggleVoice={() => setVoice((v) => !v)}
          onOpenControlCentre={() => setDrawerOpen(true)}
        />
        <div className="region plant">
          <PlantSection state={state} entries={entries} live={live} />
          <SystemLine entries={entries} voice={voice} />
        </div>
        <PermitLines state={state} />
        <Queue pending={state?.pending ?? []} />
        <Ledger entries={entries} />
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

      <div className="honesty">
        Representative facility. Real EPA permit structure and limits. Live agents, live
        models, live Google Cloud.
      </div>
    </>
  );
}
