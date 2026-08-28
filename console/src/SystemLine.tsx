import { useEffect, useState } from "react";
import type { LedgerEntry } from "./types";

/** Every system utterance, burned in as a caption. The first one carries
 *  its provenance — the voice is a product surface, not a voice-over. */

export function SystemLine({ entries }: { entries: LedgerEntry[] }) {
  const [line, setLine] = useState<{ speaker: string; text: string } | null>(null);
  const [captioned, setCaptioned] = useState(false);

  useEffect(() => {
    const latest = [...entries]
      .reverse()
      .find(
        (entry) =>
          (entry.kind === "agent_state" && typeof entry.detail?.say === "string" && entry.detail.say) ||
          entry.kind === "quarantine" ||
          entry.kind === "escalation",
      );
    if (!latest) return;
    const text =
      latest.kind === "quarantine"
        ? "That number never reached you."
        : String(latest.detail?.say ?? latest.action);
    setLine({ speaker: latest.actor, text });
    if (!captioned) setCaptioned(true);
  }, [entries, captioned]);

  if (!line) return null;
  return (
    <div className="sysline">
      <div className="speaker">
        {line.speaker}
        {!captioned ? "" : ""} · Chirp 3 HD · system voice, in product
      </div>
      <div>{line.text}</div>
    </div>
  );
}
