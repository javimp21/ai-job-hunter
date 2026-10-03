from dataclasses import replace
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from ai_job_hunter.candidates import CandidateConfig
from ai_job_hunter.candidates.experience import ExperienceOutcome, assess_experience, extract_experience_requirements
from ai_job_hunter.decision_engine import DecisionCache, FinalDecision
from ai_job_hunter.models import Company, Job, JobSource, JobEvaluation, OpportunityNotification
from ai_job_hunter.services import opportunities
from ai_job_hunter.services.notifications import (
    _notification_fingerprint, format_notification_message, preview_notifications,
    retry_failed_notifications, send_notifications,
)
from ai_job_hunter.cli import _print_opportunity


class NeverProvider:
    def send_message(self, message, **kwargs):
        pytest.fail("This policy-ineligible offer must not send a notification")


def seed(session, monkeypatch, text, *, legacy=False):
    monkeypatch.setattr(opportunities, "_engine_identity", lambda engine: "offline")
    candidate = CandidateConfig.model_validate({"profile": {"years_of_experience": 1, "current_country": "Spain"}})
    company = Company(name="Fictional Product Co")
    job = Job(company=company, title="Backend Engineer", description=text, location="Spain", remote_policy="REMOTE")
    source = JobSource(job=job, provider="greenhouse", external_id="experience-role", source_title=job.title,
                       source_description=text, source_location="Spain", remote_policy="REMOTE",
                       remote_eligibility="SPAIN_ONLY", original_url="https://example.test/role")
    session.add(source)
    session.flush()
    prepared = opportunities._prepare_from_source(job, source, candidate, "offline")
    from datetime import UTC, datetime
    evaluation = JobEvaluation(
        job=job, evaluation_fingerprint="old-fingerprint" if legacy else prepared.fingerprint,
        config_fingerprint="old-config" if legacy else prepared.config_fingerprint,
        status="EVALUATED", decision="APPLY", rubric_version="job_decision_v1",
        policy_version="job_decision_v2", engine_name="offline", deterministic_result={},
        jev_signals={name: {"value": 1} for name in ("role_relevance", "backend_relevance", "experience_accessibility", "stack_transferability", "requirements_flexibility", "career_value")},
        evaluated_at=datetime.now(UTC),
    )
    session.add(evaluation)
    session.commit()
    return candidate, job, evaluation


@pytest.mark.parametrize("legacy", [True, False])
def test_current_experience_filters_old_apply_without_mutation(db_session, monkeypatch, legacy):
    candidate, job, evaluation = seed(db_session, monkeypatch, "3 to 5+ years as a backend engineer at a modern tech company", legacy=legacy)
    assert opportunities.list_opportunities(db_session, candidate) == []
    detail = opportunities.get_opportunity(db_session, job.id, candidate)
    assert detail.decision is FinalDecision.SKIP
    assert detail.experience.outcome is ExperienceOutcome.INCOMPATIBLE
    if legacy:
        assert detail.priority is None
    else:
        assert detail.priority == 100
    assert preview_notifications(db_session, candidate) == []
    assert evaluation.decision == "APPLY"  # preserve history, only project current rules
    assert db_session.scalar(select(func.count()).select_from(OpportunityNotification)) == 0
    assert not db_session.new and not db_session.dirty


def test_cached_stretch_apply_is_review_with_requirement_in_cli_and_alert(db_session, monkeypatch, capsys):
    candidate, job, evaluation = seed(db_session, monkeypatch, "3+ years of professional experience required.")
    item = opportunities.get_opportunity(db_session, job.id, candidate)
    assert item.decision is FinalDecision.REVIEW
    assert not item.evaluation_is_stale
    assert item.experience.outcome is ExperienceOutcome.STRETCH
    _print_opportunity(item)
    local = capsys.readouterr().out
    assert "minimum 3+ years" in local and "Experience shortfall: 2" in local
    previews = preview_notifications(db_session, candidate)
    assert len(previews) == 1 and previews[0].decision == "REVIEW"
    assert "Experiencia: piden 3+ años" in previews[0].message
    assert "stretch" in previews[0].message
    assert "shortfall" not in previews[0].message.lower()
    assert "1 year" not in previews[0].message


@pytest.mark.parametrize("legacy", [True, False])
def test_pending_and_retry_cannot_bypass_current_experience(db_session, monkeypatch, legacy):
    candidate, job, evaluation = seed(db_session, monkeypatch, "3-5 years of experience required", legacy=legacy)
    row = OpportunityNotification(job=job, evaluation_fingerprint=_notification_fingerprint(evaluation),
                                  channel="TELEGRAM", decision="APPLY", status="PENDING", message="old alert")
    db_session.add(row)
    db_session.commit()
    result = send_notifications(db_session, candidate, NeverProvider())
    assert result.sent == 0
    db_session.refresh(row)
    assert row.status == "SUPPRESSED"
    row.status = "FAILED"
    row.retryable = True
    db_session.commit()
    assert retry_failed_notifications(db_session, candidate, NeverProvider()).sent == 0
    assert row.status == "FAILED"


def test_real_candidate_or_posting_change_never_reuses_semantic_evidence(db_session, monkeypatch):
    candidate, job, evaluation = seed(db_session, monkeypatch, "0 years of professional experience required")
    changed = candidate.model_copy(update={"profile": candidate.profile.model_copy(update={"years_of_experience": Decimal("2")})})
    item = opportunities.get_opportunity(db_session, job.id, changed)
    assert item.evaluation_is_stale
    assert item.priority is None and item.jev_signals is None
    assert item.evaluation_fingerprint is None
    assert preview_notifications(db_session, changed) == []
    job.sources[0].source_description = "Changed role. 0 years of professional experience required"
    db_session.commit()
    assert opportunities.get_opportunity(db_session, job.id, candidate).evaluation_is_stale


def test_unknown_experience_ceilings_current_cached_apply(db_session, monkeypatch):
    candidate, job, evaluation = seed(db_session, monkeypatch, "Build modern backend systems.")
    item = opportunities.get_opportunity(db_session, job.id, candidate)
    assert item.decision is FinalDecision.REVIEW
    assert item.experience.outcome is ExperienceOutcome.UNKNOWN
    assert "Experiencia: no especificada" in format_notification_message(item)


def test_refresh_hard_rejects_before_existing_evaluated_shortcut(db_session, monkeypatch, tmp_path):
    candidate, job, evaluation = seed(db_session, monkeypatch, "4+ years of experience required")
    prepared = opportunities._prepare_from_source(job, job.sources[0], candidate, "offline")
    monkeypatch.setattr(opportunities, "build_company_monitor_targets", lambda *a, **k: [type("Target", (), {"company_id": job.company_id})()])
    monkeypatch.setattr(opportunities, "_fetch_targets", lambda *a, **k: ([(prepared.offer, None)], []))
    class NeverEngine:
        cache_identity = "offline"
        def evaluate(self, context):
            pytest.fail("Existing APPLY cannot bypass current deterministic REJECT")
    db_session.rollback()
    summary = opportunities.refresh_opportunities(db_session, candidate, engine=NeverEngine(), cache=DecisionCache(tmp_path / "offline.json"), no_jev=True)
    assert summary.hard_skips == 1 and summary.skip == 1 and summary.jev_calls == 0


def test_outgoing_experience_never_discloses_fractional_candidate_gap(db_session, monkeypatch):
    candidate, job, _ = seed(db_session, monkeypatch, "3 years of experience")
    item = opportunities.get_opportunity(db_session, job.id, candidate)
    personal = assess_experience(extract_experience_requirements("3 years of experience"), Decimal("1.25"))
    message = format_notification_message(replace(item, experience=personal))
    assert "Experiencia: piden 3 años" in message
    assert "1.25" not in message and "1.75" not in message
