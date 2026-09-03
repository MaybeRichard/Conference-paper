"""Contract validation, not scientific verification of cited evidence."""
from datetime import date
import hashlib

import pytest
from pydantic import ValidationError


def test_fact_requires_source():
    from research_agent.schemas.research import Claim
    with pytest.raises(ValidationError):
        Claim(statement="测试陈述", epistemic_status="FACT", evidence_ids=())


def test_claim_roundtrip_preserves_unicode_and_evidence():
    from research_agent.schemas.research import Claim
    claim = Claim(statement="作者报告了实验", epistemic_status="FACT", evidence_ids=("ev_1",))
    assert Claim.model_validate_json(claim.model_dump_json()) == claim
    assert claim.evidence_ids == ("ev_1",)


@pytest.mark.parametrize("status", ["SYNTHESIS", "HYPOTHESIS", "TRANSFER", "RISK"])
def test_non_fact_does_not_require_fabricated_citation(status):
    from research_agent.schemas.research import Claim
    assert Claim(statement="待核验", epistemic_status=status).evidence_ids == ()


@pytest.mark.parametrize("changes", [
    {"statement": "   "}, {"statement": 42}, {"epistemic_status": "PROVEN"},
    {"invented_field": True}, {"evidence_ids": ("",)},
    {"evidence_ids": ("ev_1", "ev_1")},
])
def test_invalid_claim_is_rejected(changes):
    from research_agent.schemas.research import Claim
    value = {"statement": "测试", "epistemic_status": "FACT", "evidence_ids": ("ev_1",)}
    with pytest.raises(ValidationError):
        Claim(**(value | changes))


def ref_payload():
    return {"artifact_id": "brief", "version": 1, "sha256": "a" * 64}


@pytest.mark.parametrize("changes", [
    {"version": 0}, {"version": True}, {"version": "1"},
    {"sha256": "a" * 63}, {"sha256": "A" * 64},
    {"artifact_id": "../x"}, {"extra": 1},
])
def test_invalid_artifact_ref_is_rejected(changes):
    from research_agent.schemas.base import ArtifactRef
    with pytest.raises(ValidationError):
        ArtifactRef(**(ref_payload() | changes))


def test_artifact_ref_is_frozen_and_roundtrips():
    from research_agent.schemas.base import ArtifactRef
    ref = ArtifactRef(**ref_payload())
    assert ArtifactRef.model_validate_json(ref.model_dump_json()) == ref
    with pytest.raises(ValidationError):
        ref.version = 2


def decision_payload():
    return {"request_id": "approval_1", "gate_id": "gate_1", "artifact": ref_payload(),
            "actor": "user", "action": "approve"}


@pytest.mark.parametrize("changes", [{"actor": "agent"}, {"action": "auto_approve"},
                                      {"request_id": ""}, {"extra": "x"}])
def test_decision_requires_explicit_user_contract(changes):
    from research_agent.schemas.workflow import DecisionInput
    with pytest.raises(ValidationError):
        DecisionInput(**(decision_payload() | changes))


def test_decision_roundtrip():
    from research_agent.schemas.workflow import DecisionInput
    decision = DecisionInput(**decision_payload())
    assert DecisionInput.model_validate_json(decision.model_dump_json()) == decision


def test_gate_and_workspace_roundtrip():
    from research_agent.schemas.workflow import GateRecord, WorkspaceState
    gate = GateRecord(gate_id="gate_1", kind="G1", artifact=ref_payload(), status="pending")
    state = WorkspaceState(workspace_id="ws_1", snapshot_id="snapshot_1", stage="G1",
                           status="waiting_for_user", pending_gate=gate)
    assert WorkspaceState.model_validate_json(state.model_dump_json()) == state


@pytest.mark.parametrize("stage,status,gate_kind", [
    ("G2", "waiting_for_user", "G1"), ("G1", "running", "G1"),
])
def test_pending_gate_cannot_disagree_with_state(stage, status, gate_kind):
    from research_agent.schemas.workflow import GateRecord, WorkspaceState
    gate = GateRecord(gate_id="gate_1", kind=gate_kind, artifact=ref_payload(), status="pending")
    with pytest.raises(ValidationError):
        WorkspaceState(workspace_id="ws_1", snapshot_id="snapshot_1", stage=stage,
                       status=status, pending_gate=gate)


def test_waiting_state_requires_gate():
    from research_agent.schemas.workflow import WorkspaceState
    with pytest.raises(ValidationError):
        WorkspaceState(workspace_id="ws_1", snapshot_id="snapshot_1", stage="G1",
                       status="waiting_for_user")


@pytest.mark.parametrize("changes", [
    {"status": "failed", "outputs": (ref_payload(),), "reason": "error"},
    {"status": "blocked", "cache_hit": True, "reason": "missing handler"},
    {"status": "failed"}, {"status": "completed", "reason": "failed anyway"},
])
def test_task_result_cannot_fake_completion(changes):
    from research_agent.schemas.workflow import TaskResult
    with pytest.raises(ValidationError):
        TaskResult(**changes)


def test_task_result_roundtrip():
    from research_agent.schemas.workflow import TaskResult
    result = TaskResult(status="completed", outputs=(ref_payload(),), cache_hit=True)
    assert TaskResult.model_validate_json(result.model_dump_json()) == result


def brief_payload():
    return {"topic": "二维医学图像扩散生成", "domain": "medical_diffusion_2d",
            "target_venue": "MICCAI", "scope": {"dimensionality": "2d"},
            "start_date": "2021-09-03", "end_date": "2026-09-03",
            "snapshot_id": "snapshot_1", "creation_basis": "profile_and_user_input"}


def test_brief_roundtrip_and_absolute_dates():
    from research_agent.schemas.research import ResearchBrief
    brief = ResearchBrief(**brief_payload())
    assert brief.start_date == date(2021, 9, 3)
    assert ResearchBrief.model_validate_json(brief.model_dump_json()) == brief


@pytest.mark.parametrize("changes", [{"start_date": "2027-01-01"},
    {"end_date": "2026-02-30"}, {"scope": {"weight": float("nan")}}, {"topic": ""}])
def test_brief_rejects_invalid_dates_or_scope(changes):
    from research_agent.schemas.research import ResearchBrief
    with pytest.raises(ValidationError):
        ResearchBrief(**(brief_payload() | changes))


def test_hash_is_order_independent_and_utf8():
    from research_agent.core.serialization import canonical_bytes, digest
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})
    data = canonical_bytes({"字": ["甲", 1]})
    assert data == '{"字":["甲",1]}'.encode("utf-8")
    assert digest({"字": ["甲", 1]}) == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("number", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_json_is_rejected(number):
    from research_agent.core.serialization import canonical_bytes
    with pytest.raises(ValueError):
        canonical_bytes({"value": number})


def test_non_json_types_are_not_silently_stringified():
    from research_agent.core.serialization import canonical_bytes
    with pytest.raises(TypeError):
        canonical_bytes({"value": object()})


def test_error_codes_and_safe_messages():
    from research_agent.core.errors import (ResearchAgentError, PathViolation, IntegrityError,
        ConflictError, GateError, BusyError, UnsupportedStage)
    for cls in (PathViolation, IntegrityError, ConflictError, GateError, BusyError, UnsupportedStage):
        error = cls("Safe message")
        assert isinstance(error, ResearchAgentError)
        assert error.code
        assert str(error) == "Safe message"
    assert ResearchAgentError("test_code", "message").code == "test_code"


@pytest.mark.parametrize("payload", [{1: "x"}, {"nested": [{False: "x"}]}])
def test_canonical_json_does_not_coerce_mapping_keys(payload):
    from research_agent.core.serialization import canonical_bytes
    with pytest.raises(TypeError):
        canonical_bytes(payload)


@pytest.mark.parametrize("changes", [{"start_date": 0}, {"start_date": 86400.0}])
def test_brief_dates_are_not_implicitly_unix_timestamps(changes):
    from research_agent.schemas.research import ResearchBrief
    with pytest.raises(ValidationError):
        ResearchBrief(**(brief_payload() | changes))
