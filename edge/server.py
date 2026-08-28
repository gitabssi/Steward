"""The edge — Gemma inside the plant's OT boundary.

This service represents the plant-side edge appliance that would sit
inside the OT (operational technology) segment in production; the
boundary it enforces is real. Raw SCADA telemetry and the operator's
dictated round notes are among the most identifying data the plant
produces, and neither may lawfully leave a segmented critical-
infrastructure network.

So Gemma runs HERE, self-hosted (Ollama, gemma4:e4b), never as a Vertex
API — an API call would mean the raw data already crossed the boundary
and would defeat the property this service exists to demonstrate. What
crosses the wire to the fleet is only what this service emits: structured,
de-identified summaries.

Endpoints:
    POST /summarize    raw high-frequency telemetry in → structured,
                       de-identified condition summary out
    POST /transcribe   the operator's dictated round note in → text out,
                       names redacted, on the edge (Gemma 4 E4B native
                       audio when the local runtime exposes it; text
                       passthrough with redaction otherwise — recorded in
                       the response, never silent)
    GET  /healthz      liveness, model identity
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL = os.environ.get("EDGE_MODEL", "gemma4:e4b")

app = FastAPI(
    title="steward-edge",
    description="Self-hosted Gemma inside the OT boundary. Nothing raw crosses.",
)

# The de-identification pass: whatever the model does, these never leave.
# Order matters — the specific patterns run before the general one, or
# "341 Cedar Road" loses its street to the person-name rule.
_IDENTIFYING = [
    (re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"), "[phone]"),
    (
        re.compile(
            r"\b\d{1,5} [A-Z][a-z]+ (?:Road|Rd|Street|St|Avenue|Ave|Lane|Ln|Route|Hwy|Drive|Dr)\b"
        ),
        "[address]",
    ),
    (re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b"), "[name]"),  # person names, last
]


def deidentify(text: str) -> str:
    for pattern, replacement in _IDENTIFYING:
        text = pattern.sub(replacement, text)
    return text


# The appliance this service stands in for would carry an accelerator.
# On Cloud Run's CPU the first token costs minutes, so the model is kept
# resident between calls and the output is capped: a condition summary
# is three short fields, not an essay.
GENERATE_TIMEOUT_S = int(os.environ.get("EDGE_TIMEOUT_S", "480"))


def ollama_generate(prompt: str, num_predict: int = 160) -> str:
    body = json.dumps(
        {
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "30m",
            "options": {
                "temperature": 0.1,
                "num_predict": num_predict,
                "num_ctx": 2048,
            },
        }
    ).encode()
    request = urllib.request.Request(
        f"{OLLAMA}/api/generate", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=GENERATE_TIMEOUT_S) as response:
        return json.load(response)["response"]


@app.post("/warm")
def warm() -> dict:
    """Load the weights and hold them resident — called once before a
    demo so the first real request isn't paying for a cold model."""
    try:
        ollama_generate("Reply with the single word: ready", num_predict=8)
        return {"model": MODEL, "state": "resident"}
    except Exception as exc:
        return {"model": MODEL, "state": "cold", "error": str(exc)[:200]}


class Telemetry(BaseModel):
    readings: dict[str, Any]
    station: str = "plant"


@app.post("/summarize")
def summarize(telemetry: Telemetry) -> dict:
    """Raw readings in; a structured, de-identified condition out."""
    try:
        raw = ollama_generate(
            "You are an edge summarizer inside a water reclamation plant's OT "
            "network. Given raw SCADA readings, emit STRICT JSON only: "
            '{"condition": "normal|watch|stress", "summary": "<one sentence, '
            'no names, no locations>", "notable": ["<key>: <why>"]}. '
            f"Readings for {telemetry.station}: {json.dumps(telemetry.readings)}"
        )
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        parsed = json.loads(match.group(0)) if match else {"condition": "watch", "summary": raw[:200]}
        parsed["summary"] = deidentify(str(parsed.get("summary", "")))
        return {"model": MODEL, "boundary": "enforced", **parsed}
    except Exception as exc:
        # The fleet is told the edge is degraded; raw data still does not cross.
        return {
            "model": MODEL,
            "boundary": "enforced",
            "condition": "unknown",
            "summary": "edge summarizer unavailable; raw telemetry withheld at the boundary",
            "error": str(exc)[:200],
        }


class RoundNote(BaseModel):
    text: str | None = None
    audio_b64: str | None = None


@app.post("/transcribe")
def transcribe(note: RoundNote) -> dict:
    """The operator's dictated round note, transcribed on the edge.

    Gemma 4 E4B has native audio input; where the local runtime exposes
    it, audio is transcribed here. Where it does not, the caller sends
    text and this endpoint still performs the part that matters for the
    boundary: de-identification before anything leaves the segment. The
    `path` field says which happened — never silent.
    """
    if note.audio_b64:
        try:
            body = json.dumps(
                {
                    "model": MODEL,
                    "prompt": "Transcribe this dictated plant round note verbatim.",
                    "audio": [note.audio_b64],
                    "stream": False,
                }
            ).encode()
            request = urllib.request.Request(
                f"{OLLAMA}/api/generate",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=GENERATE_TIMEOUT_S) as response:
                text = json.load(response)["response"]
            return {"model": MODEL, "path": "edge-audio", "text": deidentify(text)}
        except Exception as exc:
            return {
                "model": MODEL,
                "path": "edge-audio-unavailable",
                "text": "",
                "error": str(exc)[:200],
            }
    return {"model": MODEL, "path": "edge-text", "text": deidentify(note.text or "")}


@app.get("/health")
@app.get("/healthz")
def health() -> dict:
    # Both paths: some fronting infrastructure reserves /healthz.
    return {"service": "steward-edge", "model": MODEL, "boundary": "OT — nothing raw crosses"}
