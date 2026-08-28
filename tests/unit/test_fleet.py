"""The fences, tested: authority, scope, audit, quarantine, screening.

These tests are the written form of the claims in the README. Each one
exercises a fence a judge can also watch fail-closed in the console.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.fleet.arbiter import Arbiter, Proposal
from app.fleet.authority import AgentGrant, ApprovalVault, Authority, FleetPolicy, ToolPolicy
from app.fleet.events import BUS, EventKind
from app.fleet.guards import screen
from app.fleet.llm import _parse_contract
from app.fleet.supervisor import Claim, Supervisor
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
        with pytest.raises(Exception):
            _parse_contract("no json here")
