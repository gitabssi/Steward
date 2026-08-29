"""The fences, tested: authority, scope, audit, quarantine, screening.

These tests are the written form of the claims in the README. Each one
exercises a fence a judge can also watch fail-closed in the console.
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.fleet.arbiter import Arbiter, Proposal
from app.fleet.authority import (
    AgentGrant,
    ApprovalVault,
    Authority,
    FleetPolicy,
    ToolPolicy,
)
from app.fleet.events import BUS, EventKind
from app.fleet.guards import screen
from app.fleet.llm import _parse_contract
from app.fleet.supervisor import RELATIVE_TOLERANCE, Claim, Supervisor
from fixtures.replay import World

SEED = pathlib.Path(__file__).resolve().parents[2] / "fixtures/seeds/cedar-ridge.json"


@pytest.fixture()
def policy() -> FleetPolicy:
    p = FleetPolicy()
    p.grant(AgentGrant("observer", "observer@test", "FAC-1", Authority.OBSERVE))
    p.grant(AgentGrant("actor", "actor@test", "FAC-1", Authority.ACT))
    p.register_tool("read_things", ToolPolicy(Authority.OBSERVE))
    p.register_tool("move_things", ToolPolicy(Authority.ACT))
    p.register_tool("burn_bridge", ToolPolicy(Authority.ACT, irreversible=True))
    return p


class TestAuthority:
    def test_observe_cannot_act(self, policy: FleetPolicy) -> None:
        allowed, reason = policy.check("observer", "move_things", {})
        assert not allowed
        assert "observe" in reason

    def test_act_within_scope_allowed(self, policy: FleetPolicy) -> None:
        allowed, _ = policy.check("actor", "move_things", {})
        assert allowed

    def test_irreversible_refused_without_operator_token(self, policy: FleetPolicy) -> None:
        allowed, reason = policy.check("actor", "burn_bridge", {"approval_token": "forged"})
        assert not allowed
        assert "operator approval" in reason

    def test_irreversible_runs_with_minted_token_exactly_once(self, policy: FleetPolicy) -> None:
        token = policy.approvals.mint("burn_bridge:x")
        allowed, _ = policy.check(
            "actor", "burn_bridge", {"approval_token": token, "action_id": "x"}
        )
        assert allowed
        # Replay is refused: the token burned with the action.
        allowed, _ = policy.check(
            "actor", "burn_bridge", {"approval_token": token, "action_id": "x"}
        )
        assert not allowed

    def test_quarantined_agent_loses_everything(self, policy: FleetPolicy) -> None:
        policy.grants["actor"].quarantined = True
        allowed, reason = policy.check("actor", "read_things", {})
        assert not allowed
        assert "quarantined" in reason

    def test_unknown_agent_has_nothing(self, policy: FleetPolicy) -> None:
        allowed, _ = policy.check("stranger", "read_things", {})
        assert not allowed


class TestApprovalVault:
    def test_token_binds_to_action_fingerprint(self) -> None:
        vault = ApprovalVault()
        token = vault.mint("dispatch:tanker-9")
        assert not vault.redeem(token, "dispatch:different-action")

    def test_forged_token_never_redeems(self) -> None:
        assert not ApprovalVault().redeem("forged", "dispatch:x")


class TestSupervisor:
    def sensors(self, citation: str) -> float | None:
        return {"sensor:ammonia": 34.0}.get(citation)

    def test_unsourced_claim_is_quarantined(self) -> None:
        from app.fleet.authority import POLICY

        POLICY.grant(AgentGrant("worker_a", "worker-a@test", "FAC-1", Authority.OBSERVE))
        supervisor = Supervisor(read_source=self.sensors)
        ok = supervisor.audit(Claim("worker_a", "ammonia", 18.0, source=None))
        assert not ok
        assert POLICY.grants["worker_a"].quarantined

    def test_claim_contradicting_its_source_is_quarantined(self) -> None:
        from app.fleet.authority import POLICY

        POLICY.grant(AgentGrant("worker_b", "worker-b@test", "FAC-1", Authority.OBSERVE))
        supervisor = Supervisor(read_source=self.sensors)
        ok = supervisor.audit(Claim("worker_b", "ammonia", 18.0, source="sensor:ammonia"))
        assert not ok  # sensor says 34; the claim never reaches the operator

    def test_sourced_consistent_claim_passes(self) -> None:
        from app.fleet.authority import POLICY

        POLICY.grant(AgentGrant("worker_c", "worker-c@test", "FAC-1", Authority.OBSERVE))
        supervisor = Supervisor(read_source=self.sensors)
        assert supervisor.audit(Claim("worker_c", "ammonia", 33.1, source="sensor:ammonia"))

    def test_unverifiable_citation_passes_but_is_recorded(self) -> None:
        from app.fleet.authority import POLICY

        POLICY.grant(AgentGrant("worker_d", "worker-d@test", "FAC-1", Authority.OBSERVE))
        supervisor = Supervisor(read_source=self.sensors)
        # A forecast figure the supervisor cannot read is not a lie.
        assert supervisor.audit(Claim("worker_d", "rain_mm", 38.0, source="forecast:rain"))
        assert not POLICY.grants["worker_d"].quarantined

    def test_unresponsive_worker_is_stopped_not_left_hanging(self) -> None:
        from app.fleet.authority import POLICY
        from app.fleet.supervisor import TaskEnvelope

        POLICY.grant(AgentGrant("worker_e", "worker-e@test", "FAC-1", Authority.OBSERVE))
        supervisor = Supervisor(read_source=self.sensors)
        reissued: list[tuple[str, str]] = []
        supervisor.reissue_hooks.append(lambda name, task: reissued.append((name, task)))
        supervisor.stop_unresponsive(TaskEnvelope(agent_name="worker_e", task="assess"))
        assert POLICY.grants["worker_e"].quarantined
        assert reissued == [("worker_e", "assess")]

    def test_step_budget_stops_a_looping_worker(self) -> None:
        from app.fleet.authority import POLICY
        from app.fleet.supervisor import STEP_BUDGET, TaskEnvelope

        POLICY.grant(AgentGrant("worker_f", "worker-f@test", "FAC-1", Authority.OBSERVE))
        supervisor = Supervisor(read_source=self.sensors)
        envelope = TaskEnvelope(agent_name="worker_f", task="loop")
        for _ in range(STEP_BUDGET):
            assert supervisor.enforce_budget(envelope)
        assert not supervisor.enforce_budget(envelope)  # the step past the budget
        assert POLICY.grants["worker_f"].quarantined


class TestGuards:
    def test_embedded_instruction_is_stripped_and_numbers_kept(self) -> None:
        poisoned = (SEED.parent / "lab_report_2382_poisoned.txt").read_text()
        result = screen(poisoned, "lab-report")
        assert result.was_poisoned
        assert "ignore previous instructions" not in result.clean_text.lower()
        assert "12.8" in result.clean_text  # the data survived the strip

    def test_clean_report_passes_untouched(self) -> None:
        clean = (SEED.parent / "lab_report_2381.txt").read_text()
        result = screen(clean, "lab-report")
        assert not result.was_poisoned
        assert result.clean_text == clean


class TestArbiter:
    def test_conflicting_proposals_escalate_with_full_option_set(self) -> None:
        arbiter = Arbiter()
        contention = arbiter.open_contention("blowers")
        arbiter.submit(
            contention,
            Proposal("a", "a@t", "raise blowers", "DO low", ["solids carryover in 40m"], 45),
        )
        arbiter.submit(
            contention,
            Proposal("b", "b@t", "hold blowers", "retention compressed", [], 40),
        )
        result = arbiter.resolve(contention)
        assert result["resolution"] == "escalate"
        assert len(result["options"]) == 2

    def test_uncontested_costless_proposal_proceeds(self) -> None:
        arbiter = Arbiter()
        contention = arbiter.open_contention("routine")
        arbiter.submit(contention, Proposal("a", "a@t", "log reading", "routine", [], 60))
        assert arbiter.resolve(contention)["resolution"] == "proceed"


class TestStaleBriefing:
    """The chaos harness must actually produce a catchable contradiction.

    Serving a reader forty-minute-old telemetry is only a useful fault if
    the numbers have moved enough for the supervisor to notice. During
    the infiltration surge they move by multiples — these tests pin that
    down so the beat cannot quietly stop working.
    """

    def _world_at(self, minute: float) -> World:
        world = World(SEED, minutes_per_second=25)
        deadline = time.time() + 20
        while world.minutes < minute and time.time() < deadline:
            world.telemetry()
            time.sleep(0.005)
        return world

    def test_stale_readings_contradict_live_ones_mid_surge(self) -> None:
        world = self._world_at(52)
        live, stale = world.telemetry(), world.telemetry_as_of(40)
        deviations = {
            key: abs(live[key] - stale[key]) / max(abs(live[key]), 1e-9)
            for key in ("aeration_do_mg_l", "effluent_ammonia_mg_l", "influent_flow_mgd")
        }
        # Every one of these is what a specialist would naturally cite.
        for key, dev in deviations.items():
            assert dev > RELATIVE_TOLERANCE, f"{key} only differs by {dev:.0%}"

    def test_the_supervisor_quarantines_a_stale_citation(self) -> None:
        from app.fleet.authority import POLICY

        world = self._world_at(52)
        stale = world.telemetry_as_of(40)
        POLICY.grant(
            AgentGrant("stale_worker", "stale-worker@test", "FAC-1", Authority.RECOMMEND)
        )
        supervisor = Supervisor(read_source=world.read_source)
        # The worker asserts, in good faith, what its briefing told it.
        ok = supervisor.audit(
            Claim(
                "stale_worker",
                "aeration_do_mg_l",
                stale["aeration_do_mg_l"],
                source="sensor:aeration_do_mg_l",
            )
        )
        assert not ok
        assert POLICY.grants["stale_worker"].quarantined

    def test_history_is_bounded(self) -> None:
        world = self._world_at(30)
        assert len(world._history) <= 200


class TestWorld:
    def test_seed_contains_world_facts_not_agent_behaviour(self) -> None:
        text = SEED.read_text().lower()
        for verb in ("mount", "quarantine", "escalate", "deny"):
            assert verb not in text, f"seed scripts agent behaviour: {verb}"

    def test_sources_resolve_for_the_supervisor(self) -> None:
        world = World(SEED, minutes_per_second=1000)
        assert world.read_source("sensor:influent_flow_mgd") is not None
        assert world.read_source("seed:facility.design_flow_mgd") == 2.6
        assert world.read_source("sensor:not_a_thing") is None

    def test_ledger_records_denials_with_attribution(self) -> None:
        denials = [e for e in BUS.tail(400) if e.kind == EventKind.QUARANTINE]
        assert denials, "quarantines above should have produced ledger rows"
        assert all(entry.actor for entry in denials)
        assert all(entry.trace_id for entry in denials)


class TestContract:
    def test_fenced_json_parses(self) -> None:
        parsed = _parse_contract('```json\n{"say": "hi", "claims": []}\n```')
        assert parsed["say"] == "hi"

    def test_prose_wrapped_json_parses(self) -> None:
        parsed = _parse_contract('Sure: {"say": "ok", "claims": [], "proposal": null} done')
        assert parsed["say"] == "ok"

    def test_garbage_raises(self) -> None:
        # A response with no contract in it must fail loudly, so the
        # caller falls back to a deterministic line rather than
        # inventing one.
        with pytest.raises((ValueError, json.JSONDecodeError)):
            _parse_contract("no json here")


class TestMemoryBackend:
    """The memory store must be honest about which backend it has."""

    def _store(self, tmp_path):
        from app.fleet.memory import FleetMemory

        return FleetMemory(store_path=tmp_path / "facts.json")

    def test_defaults_to_local_and_says_so(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("AGENT_ENGINE_MEMORY_BANK", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_AGENT_ENGINE_ID", raising=False)
        store = self._store(tmp_path)
        assert store.backend == "local-json"
        assert not store.pending()  # nothing to flush without a bank

    def test_observe_is_synchronous_and_queues(self, tmp_path) -> None:
        store = self._store(tmp_path)
        fact = store.observe("operator", "chooses haul over bypass", "arbiter@t")
        assert fact.observations == 1
        # Re-observing counts rather than duplicating.
        assert store.observe("operator", "chooses haul over bypass", "arbiter@t").observations == 2
        assert len(store.facts()) == 1

    def test_flush_without_a_bank_clears_and_never_raises(self, tmp_path) -> None:
        import asyncio

        store = self._store(tmp_path)
        store.observe("facility", "blower 2 underperforms below 8C", "aeration@t")
        asyncio.run(store.flush())
        assert not store.pending()

    def test_facts_survive_a_restart_via_the_local_store(self, tmp_path) -> None:
        first = self._store(tmp_path)
        first.observe("facility", "lab turnaround slips on Fridays", "clerk@t")
        second = self._store(tmp_path)
        assert any("Fridays" in f["statement"] for f in second.facts())


class TestMemoryBankResolution:
    """Which engine the bank binds to, and in which region."""

    def test_full_resource_path_yields_id_and_region(self, monkeypatch) -> None:
        from app.fleet import memory_bank

        monkeypatch.setenv(
            "AGENT_ENGINE_MEMORY_BANK",
            "projects/p/locations/europe-west4/reasoningEngines/123",
        )
        target = memory_bank.resolve_engine()
        assert target.engine_id == "123"
        assert target.location == "europe-west4"

    def test_never_inherits_the_global_gemini_region(self, monkeypatch) -> None:
        from app.fleet import memory_bank

        # GOOGLE_CLOUD_LOCATION is 'global' on every deploy path because
        # that is where Gemini 3.x serves. Memory Bank is regional; if it
        # ever picked this up, every call would 404.
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")
        monkeypatch.delenv("STEWARD_MEMORY_BANK_LOCATION", raising=False)
        monkeypatch.delenv("AGENT_ENGINE_MEMORY_BANK", raising=False)
        monkeypatch.setenv("GOOGLE_CLOUD_AGENT_ENGINE_ID", "456")
        assert memory_bank.resolve_engine().location != "global"

    def test_unset_means_no_bank(self, monkeypatch) -> None:
        from app.fleet import memory_bank

        monkeypatch.delenv("AGENT_ENGINE_MEMORY_BANK", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_AGENT_ENGINE_ID", raising=False)
        assert memory_bank.resolve_engine() is None


class TestTracing:
    """Ledger rows must carry a real trace id when a provider exists."""

    def test_spans_share_one_trace_and_degrade_without_a_provider(self) -> None:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider

        from app.fleet.events import _current_trace_id
        from app.fleet.tracing import TRACER

        trace.set_tracer_provider(TracerProvider())
        with TRACER.start_as_current_span("steward.job contention"):
            outer = _current_trace_id()
            with TRACER.start_as_current_span("steward.audit"):
                assert _current_trace_id() == outer  # one reasoning chain
        assert not outer.startswith("untraced")
        assert _current_trace_id().startswith("untraced")  # outside any span
