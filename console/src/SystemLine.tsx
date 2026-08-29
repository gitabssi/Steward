import { useEffect, useRef, useState } from "react";
import type { LedgerEntry } from "./types";

/** Every system utterance, burned in as a caption — captions are the
 *  primary channel; the voice (Chirp 3 HD via /api/speak) is the
 *  secondary one, toggled by the operator. The caption carries its
 *  provenance: this is a product surface, not a voice-over. */

export function SystemLine({
  entries,
  voice,
  onSpeaking,
}: {
  entries: LedgerEntry[];
  voice: boolean;
  /** Told when audio starts and stops, so the chrome can show that the
   *  voice is a live product surface and not a track laid over it. */
  onSpeaking?: (speaking: boolean) => void;
}) {
  const [line, setLine] = useState<{ speaker: string; text: string } | null>(null);
  const spoken = useRef(new Set<string>());
  const player = useRef<HTMLAudioElement | null>(null);

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

    if (voice && !spoken.current.has(latest.entry_id)) {
      spoken.current.add(latest.entry_id);
      void (async () => {
        try {
          const response = await fetch("/api/speak", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text }),
          });
          if (!response.headers.get("content-type")?.includes("audio")) return;
          const url = URL.createObjectURL(await response.blob());
          player.current?.pause();
          const audio = new Audio(url);
          player.current = audio;
          audio.onplay = () => onSpeaking?.(true);
          audio.onended = () => onSpeaking?.(false);
          audio.onerror = () => onSpeaking?.(false);
          void audio.play();
        } catch {
          /* captions carry the line */
        }
      })();
    }
  }, [entries, voice]);

  if (!line) return null;
  return (
    <div className="sysline">
      <div className="speaker">{line.speaker} · Chirp 3 HD · system voice, in product</div>
      <div className="said">{line.text}</div>
    </div>
  );
}
