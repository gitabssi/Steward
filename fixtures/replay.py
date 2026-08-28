"""The world the fleet lives in — a replay over real permit structure.

The honest simulation boundary, stated precisely: monthly reported values
in the public EPA record are real; permit limits are real; exceedances are
real. High-frequency telemetry BETWEEN reported values is interpolated
here — real plants have it (SCADA), the public record does not. This
module is that interpolation: a small, legible physics of a small plant.

The seed (fixtures/seeds/*.json) contains only world facts — telemetry
baselines, weather, arriving documents, equipment states. Nothing in it
describes agent behaviour. Whether the guard strips an instruction,
whether the supervisor quarantines a worker, which specialist gets
mounted: those are the fleet's genuine responses.

The clock is compressible (`minutes_per_second`) so a 92-minute shift can
play in a four-minute take without editing.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

SEEDS = Path(__file__).parent / "seeds"


class World:
    """Current plant state, advanced by the wall clock against the seed."""

    def __init__(self, seed_path: str | Path, minutes_per_second: float = 0.5) -> None:
        self.seed = json.loads(Path(seed_path).read_text())
        self.minutes_per_second = minutes_per_second
        self.started_at = time.time()
        self.baseline: dict[str, float] = {
            k: float(v)
            for k, v in self.seed["telemetry_baseline"].items()
            if isinstance(v, (int, float))
        }
        self.actions: list[dict[str, Any]] = []  # operator/agent actions with effects
        self._delivered_events: set[int] = set()
        self._history: list[tuple[float, dict[str, float]]] = []

    # -- clock --------------------------------------------------------------

    @property
    def minutes(self) -> float:
        """Plant minutes since shift start."""
        return (time.time() - self.started_at) * self.minutes_per_second * 60 / 60

    def due_events(self) -> list[dict[str, Any]]:
        """Timeline events whose moment has arrived, each delivered once."""
        due = []
        for i, event in enumerate(self.seed["timeline"]):
            if i not in self._delivered_events and event["at_minutes"] <= self.minutes:
                self._delivered_events.add(i)
                due.append(event)
        return due

    # -- interpolated telemetry --------------------------------------------

    def telemetry(self) -> dict[str, float]:
        """The plant, now. Baseline + event physics + action effects."""
        t = self.minutes
        v = dict(self.baseline)

        rain = self._event("rain_begins")
        if rain and t >= rain["at_minutes"]:
            ramp = rain["detail"]["infiltration_ramp_minutes"]
            surge = self._event("weather_forecast", "rain_band")
            extra = surge["detail"]["expected_infiltration_mgd"] if surge else 1.9
            progress = min(1.0, (t - rain["at_minutes"]) / ramp)
            v["influent_flow_mgd"] += extra * progress
            # Higher hydraulic load: oxygen demand outruns the blowers,
            # nitrification falters, ammonia climbs.
            v["aeration_do_mg_l"] = max(0.9, v["aeration_do_mg_l"] - 1.6 * progress)
            v["effluent_ammonia_mg_l"] += 2.8 * progress**1.5
            v["effluent_tss_mg_l"] += 4.0 * progress

        dry = self._event("weather_forecast", "dry_spell")
        if dry and t >= dry["at_minutes"]:
            trend = dry["detail"]["creek_flow_trend_cfs"]
            days = min((t - dry["at_minutes"]) / 10.0, len(trend) - 1)
            lo = trend[int(days)]
            hi = trend[min(int(days) + 1, len(trend) - 1)]
            v["creek_flow_cfs"] = lo + (hi - lo) * (days - int(days))

        for action in self.actions:
            v = action_effect(action, v, t)

        # A breath of measurement texture, so nothing renders as a flat wire.
        for key in v:
            v[key] = round(v[key] * (1 + 0.006 * math.sin(t * 2.1 + hash(key) % 7)), 3)

        # Keep a coarse history. A real plant has a historian, and a real
        # integration can serve a reader something forty minutes old
        # without saying so — which is the failure the supervisor exists
        # to catch. Sampling every ~2 plant-minutes is plenty.
        if not self._history or t - self._history[-1][0] >= 2:
            self._history.append((t, dict(v)))
            del self._history[:-200]
        return v

    def telemetry_as_of(self, minutes_ago: float) -> dict[str, float]:
        """The readings a stale cache would still be serving.

        Returns the oldest sample within the window if there is one, so
        a caller asking for "forty minutes ago" during a surge gets
        genuinely pre-surge numbers rather than a rounded copy of now.
        """
        if not self._history:
            return self.telemetry()
        target = max(0.0, self.minutes - minutes_ago)
        best = min(self._history, key=lambda row: abs(row[0] - target))
        return dict(best[1])

    def _event(self, kind: str, subkind: str | None = None) -> dict | None:
        for event in self.seed["timeline"]:
            if event["kind"] != kind:
                continue
            if subkind and event.get("detail", {}).get("event") != subkind:
                continue
            return event
        return None

    # -- sources (the supervisor's ground truth) ----------------------------

    def read_source(self, citation: str) -> float | None:
        """Resolve 'sensor:<key>' or 'seed:<path>' to its current value."""
        scheme, _, key = citation.partition(":")
        if scheme == "sensor":
            return self.telemetry().get(key)
        if scheme == "seed":
            node: Any = self.seed
            for part in key.split("."):
                if not isinstance(node, dict) or part not in node:
                    return None
                node = node[part]
            return float(node) if isinstance(node, (int, float)) else None
        return None

    # -- actions ------------------------------------------------------------

    def apply(self, action: dict[str, Any]) -> None:
        action = {**action, "at_minutes": self.minutes}
        self.actions.append(action)

    # -- documents ----------------------------------------------------------

    def read_document(self, filename: str) -> str:
        return (SEEDS / filename).read_text()

    def dilution_pct_at_intake(self) -> float:
        """Discharge as a share of streamflow at the downstream intake."""
        v = self.telemetry()
        discharge_cfs = v["influent_flow_mgd"] * 1.547  # MGD → cfs
        total = discharge_cfs + max(v["creek_flow_cfs"], 0.1)
        return round(100 * discharge_cfs / total, 1)


def action_effect(action: dict[str, Any], v: dict[str, float], t: float) -> dict[str, float]:
    """How an executed action moves the plant. Small, legible, one place."""
    minutes_since = t - action["at_minutes"]
    if minutes_since < 0:
        return v
    kind = action.get("kind")
    if kind == "set_blowers":
        target = float(action["capacity_pct"])
        v["blower_capacity_pct"] = target
        lift = (target - 58) / 100
        v["aeration_do_mg_l"] += 2.2 * lift * min(1.0, minutes_since / 15)
        # The coupling that makes the plant a plant: more air, more mixing
        # energy, shorter effective retention — solids begin to carry over.
        v["effluent_tss_mg_l"] += 14.0 * lift * min(1.0, minutes_since / 40)
    elif kind == "tanker_dispatch":
        pass  # a logistics fact; its meaning lives in the obligations ledger
    return v
