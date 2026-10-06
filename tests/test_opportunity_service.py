from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
import pytest
from sqlalchemy import func, select

from ai_job_hunter.candidates import CandidateConfig, load_candidate_config
from ai_job_hunter.decision_engine import (
    POLICY_VERSION_V2,
    DecisionCache,
    DecisionEvidence,
    FinalDecision,
    JevAnswers,
    JevSignal,
    build_decision_contexts,
    evaluate_job_decision,
)
from ai_job_hunter.domain.company_intelligence import CompanyEvidenceType
from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    Company,
    CompanyEvidence,
    EvaluationStatus,
    HumanReviewStatus,
    Job,
    JobEvaluation,
    JobReview,
    JobSource,
)
from ai_job_hunter.services import opportunities
from ai_job_hunter.services.monitored_sources import sync_monitored_sources
from ai_job_hunter.services.opportunities import (
    EvaluationOutcome,
    OpportunityServiceError,
    list_opportunities,
    reevaluate_jobs,
    refresh_opportunities,
    set_review_state,
    transition_application,
)


PROJECT_ROOT = Path(__file__).parents[1]
CANDIDATE_CONFIG = PROJECT_ROOT / "config" / "examples" / "candidate.example.json"


def _candidate() -> CandidateConfig:
    return load_candidate_config(CANDIDATE_CONFIG)


def _monitor_company(session) -> Company:
    company = Company(name="Acme", website_url="https://acme.example.test")
    company.evidence_items.append(
        CompanyEvidence(
            provider="observed_job_source",
            source_key="acme:greenhouse",
            source_url="https://boards.greenhouse.io/acme",
            external_identifier="acme",
            evidence_type=CompanyEvidenceType.ATS_OBSERVED.value,
            structured_data={
                "ats_provider": "GREENHOUSE",
                "identifier": "acme",
                "region": None,
                "supporting_job_sources": [
                    {"source_url": "https://boards.greenhouse.io/acme/jobs/1"}
                ],
            },
        )
    )
    session.add(company)
    session.commit()
    # Boards are fetched only once explicitly activated.
    sync_monitored_sources(session, activate_new=True, reason="test fixture")
    return company


def _offer(
    external_id: str,
    *,
    title: str = "Senior Backend Engineer",
    description: str | None = None,
    remote_policy: str = "REMOTE",
    remote_eligibility: str = "WORLDWIDE",
    location: str = "Remote",
    published_at: datetime | None = None,
) -> NormalizedJob:
    return NormalizedJob(
        provider="greenhouse",
        external_id=external_id,
        source_url=f"https://boards.greenhouse.io/acme/jobs/{external_id}",
        canonical_url=f"https://boards.greenhouse.io/acme/jobs/{external_id}",
        apply_url=f"https://boards.greenhouse.io/acme/jobs/{external_id}/apply",
        title=title,
        company_name="Acme",
        company_website="https://acme.example.test",
        description="Minimum 0 years of professional experience required.\n" + (description or ("Build and operate Python backend services. " * 50)),
        location=location,
        remote_policy=remote_policy,
        remote_eligibility=remote_eligibility,
        salary_min="75000",
        salary_max="95000",
        currency="EUR",
        salary_period="YEAR",
        employment_type="FULL_TIME",
        published_at=published_at or datetime(2026, 9, 20, 9, 0, tzinfo=UTC),
    )


def _signal(value: float, *, question_type: str = "noul") -> JevSignal:
    return JevSignal(
        question_type=question_type,
        value=value,
        confidence=0.9 if question_type == "score" else None,
        raw_value=value * 4 if question_type == "score" else value,
    )


def _answers(
    *,
    role: float = 0.92,
    experience: float = 0.82,
    backend: float = 0.88,
    stack: float = 0.84,
    flexibility: float = 0.80,
    career: float = 0.85,
    quality: float = 0.78,
) -> JevAnswers:
    return JevAnswers(
        role_relevance=_signal(role),
        experience_accessibility=_signal(experience),
        backend_relevance=_signal(backend, question_type="score"),
        stack_transferability=_signal(stack),
        requirements_flexibility=_signal(flexibility),
        career_value=_signal(career, question_type="score"),
        observable_role_quality=_signal(quality, question_type="score"),
    )


class FakeEngine:
    cache_identity = "offline-test-engine/model-1"

    def __init__(self, answers_by_id: dict[str, JevAnswers] | None = None) -> None:
        self.answers_by_id = answers_by_id or {}
        self.calls: list[str | None] = []

    def evaluate(self, context) -> DecisionEvidence:
        external_id = context.offer.external_id
        self.calls.append(external_id)
        answers = self.answers_by_id.get(external_id or "", _answers())
        return DecisionEvidence(
            answers=answers,
            model_version="offline-fake-model",
            engine_configuration=self.cache_identity,
            input_tokens=5,
            output_tokens=7,
        )


class RecordingCache(DecisionCache):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.keys: list[str] = []
        self.context_states: list[dict[str, object]] = []

    def key_for(self, context, engine_identity: str, rubric_version: str = "job_decision_v1") -> str:
        key = super().key_for(context, engine_identity, rubric_version)
        self.keys.append(key)
        self.context_states.append(
            {
                "engine": engine_identity,
                "rubric": rubric_version,
                "offer": context.offer.model_dump(mode="json"),
                "candidate": context.candidate.model_dump(mode="json"),
                "facts": context.facts,
                "decision": context.deterministic.decision.value,
                "reasons": context.deterministic.reasons,
            }
        )
        return key


def _install_fetch(monkeypatch, offers: list[NormalizedJob]) -> None:
    def fake_fetch(targets, *, max_jobs_per_company: int, client):
        assert max_jobs_per_company >= 1
        assert client is None
        target = targets[0]
        return [(offer, target) for offer in offers], []

    monkeypatch.setattr(opportunities, "_fetch_targets", fake_fetch)


def _evaluations(session) -> list[JobEvaluation]:
    return session.scalars(select(JobEvaluation).order_by(JobEvaluation.id)).all()


def test_budget_persists_pending_work_and_resumes_in_stable_order(db_session, monkeypatch, tmp_path) -> None:
    _monitor_company(db_session)
    candidate = _candidate()
    offers = [_offer(f"role-{index:03d}") for index in (3, 1, 2)]
    _install_fetch(monkeypatch, offers)
    engine = FakeEngine()
    cache = DecisionCache(tmp_path / "budget-decisions.local.json")

    first = refresh_opportunities(
        db_session,
        candidate,
        max_jev_jobs=0,
        cache=cache,
        engine=engine,
    )

    assert first.jobs_fetched == 3
    assert first.new_jobs == 3
    assert first.jev_evaluated == 0
    assert first.pending == 3
    assert first.pending_budget == 3
    assert first.pending_no_jev == 0
    assert engine.calls == []
    first_rows = _evaluations(db_session)
    assert len(first_rows) == 3
    assert all(row.status == EvaluationStatus.PENDING.value for row in first_rows)
    assert all(row.decision is None and row.evaluated_at is None for row in first_rows)
    assert all(row.jev_signals is None for row in first_rows)

    # Reverse the fetched order; a one-call budget still picks the same identity.
    _install_fetch(monkeypatch, list(reversed(offers)))
    second = refresh_opportunities(
        db_session,
        candidate,
        max_jev_jobs=1,
        cache=cache,
        engine=engine,
    )

    assert second.jev_evaluated == 1
    assert second.pending == 2
    assert second.pending_budget == 2
    assert engine.calls == ["role-001"]
    after_second = _evaluations(db_session)
    assert len(after_second) == 3
    assert sum(row.status == EvaluationStatus.EVALUATED.value for row in after_second) == 1
    assert sum(row.status == EvaluationStatus.PENDING.value for row in after_second) == 2

    # An identical budget-limited refresh is idempotent: it does not make
    # another set of live calls unless the budget is raised or retry is explicit.
    third = refresh_opportunities(
        db_session,
        candidate,
        max_jev_jobs=1,
        cache=cache,
        engine=engine,
    )
    assert third.jev_evaluated == 0
    assert third.pending == 2
    assert third.pending_budget == 2
    assert engine.calls == ["role-001"]

    fourth = refresh_opportunities(
        db_session,
        candidate,
        max_jev_jobs=1,
        retry_pending=True,
        cache=cache,
        engine=engine,
    )
    assert fourth.jev_evaluated == 1
    assert fourth.pending == 1
    assert engine.calls == ["role-001", "role-002"]
    assert len(_evaluations(db_session)) == 3


def test_hard_prefilter_skip_is_persisted_without_spending_jev_budget(
    db_session, monkeypatch, tmp_path
) -> None:
    _monitor_company(db_session)
    candidate = _candidate()
    rejected = _offer(
        "role-reject",
        remote_policy="ONSITE",
        remote_eligibility="COUNTRY_RESTRICTED",
        location="New York, United States",
    )
    accepted = _offer("role-accept")
    _install_fetch(monkeypatch, [rejected, accepted])
    engine = FakeEngine()

    summary = refresh_opportunities(
        db_session,
        candidate,
        max_jev_jobs=1,
        cache=DecisionCache(tmp_path / "skip-decisions.local.json"),
        engine=engine,
    )

    assert summary.hard_skips == 1
    assert summary.jev_evaluated == 1
    assert summary.pending == 0
    assert len(engine.calls) == 1
    rows = {row.job_id: row for row in _evaluations(db_session)}
    rejected_job_id = db_session.scalar(
        select(JobSource.job_id).where(JobSource.external_id == "role-reject")
    )
    assert rejected_job_id in rows
    hard_skip = rows[rejected_job_id]
    assert hard_skip.status == EvaluationStatus.EVALUATED.value
    assert hard_skip.decision == FinalDecision.SKIP.value
    assert hard_skip.jev_signals is None


def test_repeated_refresh_reuses_persisted_evaluation_and_changed_snapshot_is_stale(
    db_session, monkeypatch, tmp_path
) -> None:
    _monitor_company(db_session)
    candidate = _candidate()
    current_offer = _offer("role-repeat")
    _install_fetch(monkeypatch, [current_offer])
    engine = FakeEngine()
    cache = DecisionCache(tmp_path / "repeat-decisions.local.json")

    first = refresh_opportunities(db_session, candidate, cache=cache, engine=engine)
    first_rows = _evaluations(db_session)
    assert first.jev_evaluated == 1
    assert len(first_rows) == 1
    first_fingerprint = first_rows[0].evaluation_fingerprint

    second = refresh_opportunities(db_session, candidate, cache=cache, engine=engine)
    assert second.jev_evaluated == 0
    assert second.jev_cache_hits == 0
    assert second.known_jobs == 1
    assert len(engine.calls) == 1
    assert len(_evaluations(db_session)) == 1

    changed_offer = current_offer.model_copy(
        update={"description": "Updated scope: " + ("Operate production Python services. " * 55)}
    )
    _install_fetch(monkeypatch, [changed_offer])
    changed = refresh_opportunities(db_session, candidate, cache=cache, engine=engine)

    assert changed.changed_jobs == 1
    assert changed.jev_evaluated == 1
    assert len(engine.calls) == 2
    evaluation_rows = _evaluations(db_session)
    assert len(evaluation_rows) == 2
    assert len({row.evaluation_fingerprint for row in evaluation_rows}) == 2
    current_evaluation = next(
        row for row in evaluation_rows if row.evaluation_fingerprint != first_fingerprint
    )

    changed_candidate = candidate.model_copy(
        update={
            "preferences": candidate.preferences.model_copy(
                update={"preferred_roles": ["Staff Engineer"]}
            )
        }
    )
    review_state = set_review_state(
        db_session,
        current_evaluation.job_id,
        HumanReviewStatus.SAVED,
    )
    assert review_state.state == HumanReviewStatus.SAVED.value
    stale = list_opportunities(
        db_session,
        changed_candidate,
        engine=engine,
        include_applied=True,
    )
    assert len(stale) == 1
    assert stale[0].evaluation_is_stale is True
    assert stale[0].deterministic_result is not None  # current deterministic evidence, not stale Jev
    assert stale[0].experience is not None
    assert stale[0].review_state is HumanReviewStatus.SAVED


def test_missing_external_id_url_refresh_updates_same_job_and_reevaluates(
    db_session, monkeypatch, tmp_path
) -> None:
    _monitor_company(db_session)
    candidate = _candidate()
    original = _offer("role-without-id").model_copy(
        update={
            "external_id": None,
            "source_url": "https://jobs.example.test/roles/123",
            "canonical_url": "https://jobs.example.test/roles/123",
            "apply_url": "https://jobs.example.test/roles/123/apply",
        }
    )
    _install_fetch(monkeypatch, [original])
    engine = FakeEngine()
    cache = DecisionCache(tmp_path / "no-id-decisions.local.json")

    first = refresh_opportunities(db_session, candidate, cache=cache, engine=engine)
    first_job_id = db_session.scalar(select(Job.id))
    assert first.new_jobs == 1
    assert first.jev_evaluated == 1

    updated = original.model_copy(
        update={"description": "Changed responsibilities. " + ("Build Python systems. " * 50)}
    )
    _install_fetch(monkeypatch, [updated])
    second = refresh_opportunities(db_session, candidate, cache=cache, engine=engine)

    assert second.new_jobs == 0
    assert second.known_jobs == 1
    assert second.changed_jobs == 1
    assert second.jev_evaluated == 1
    assert len(engine.calls) == 2
    assert db_session.scalar(select(func.count()).select_from(Job)) == 1
    assert db_session.scalar(select(func.count()).select_from(JobSource)) == 1
    assert db_session.scalar(select(Job.id)) == first_job_id


def test_cached_jev_answers_are_reused_before_budget_and_not_called_again(db_session, monkeypatch, tmp_path) -> None:
    _monitor_company(db_session)
    candidate = _candidate()
    offer = _offer("role-cached")
    _install_fetch(monkeypatch, [offer])
    engine = FakeEngine()
    cache = RecordingCache(tmp_path / "decisions.local.json")
    context = build_decision_contexts([offer], candidate)[0]
    service_context = opportunities._prepare_offer(
        offer,
        candidate,
        engine_identity=engine.cache_identity,
    )
    assert cache.key_for(context, engine.cache_identity) == cache.key_for(
        service_context.context,
        engine.cache_identity,
    )
    evaluate_job_decision(
        context,
        engine,
        cache=cache,
        policy_version=POLICY_VERSION_V2,
    )
    assert len(engine.calls) == 1
    cached_key = cache.keys[-1]
    assert cache.contains(cached_key)

    summary = refresh_opportunities(
        db_session,
        candidate,
        max_jev_jobs=0,
        cache=cache,
        engine=engine,
    )

    assert summary.jev_calls == 0
    assert summary.jev_evaluated == 0
    direct_state = cache.context_states[0]
    service_state = cache.context_states[-1]
    differences = {}
    for key in direct_state:
        if direct_state[key] == service_state[key]:
            continue
        if key == "offer":
            differences[key] = {
                field: (direct_state[key][field], service_state[key][field])
                for field in direct_state[key]
                if direct_state[key][field] != service_state[key][field]
            }
        else:
            differences[key] = (direct_state[key], service_state[key])
    assert not differences, differences
    assert cache.keys[-1] == cached_key
    assert summary.jev_cache_hits == 1
    assert summary.pending == 0
    assert len(engine.calls) == 1
    row = _evaluations(db_session)[0]
    assert row.status == EvaluationStatus.EVALUATED.value
    assert row.decision == FinalDecision.APPLY.value


def test_evaluation_fingerprint_ignores_database_decimal_scale() -> None:
    candidate = _candidate()
    offer = _offer("salary-scale").model_copy(
        update={"salary_min": Decimal("30000"), "salary_max": Decimal("45000")}
    )
    scaled_offer = offer.model_copy(
        update={"salary_min": Decimal("30000.00"), "salary_max": Decimal("45000.00")}
    )
    first = opportunities._prepare_offer(offer, candidate, engine_identity="test-engine")
    second = opportunities._prepare_offer(
        scaled_offer,
        candidate,
        engine_identity="test-engine",
    )

    assert first.context.deterministic.reasons != second.context.deterministic.reasons
    assert first.fingerprint == second.fingerprint


def test_no_jev_creates_pending_rows_without_making_calls(db_session, monkeypatch, tmp_path) -> None:
    _monitor_company(db_session)
    candidate = _candidate()
    _install_fetch(monkeypatch, [_offer("role-no-jev")])
    engine = FakeEngine()

    summary = refresh_opportunities(
        db_session,
        candidate,
        no_jev=True,
        cache=DecisionCache(tmp_path / "no-jev-decisions.local.json"),
        engine=engine,
    )

    assert summary.pending == 1
    assert summary.pending_no_jev == 1
    assert summary.pending_budget == 0
    assert summary.pending_errors == 0
    assert summary.jev_calls == 0
    assert summary.jev_evaluated == 0
    assert engine.calls == []
    row = _evaluations(db_session)[0]
    assert row.status == EvaluationStatus.PENDING.value
    assert row.decision is None
    assert row.evaluated_at is None
    assert row.jev_reasons == {"pending_reason": "Jev disabled by --no-jev."}


def test_jev_errors_remain_pending_and_are_counted_without_a_decision(db_session, monkeypatch, tmp_path) -> None:
    from ai_job_hunter.decision_engine import JobDecisionError

    class FailingEngine(FakeEngine):
        def evaluate(self, context) -> DecisionEvidence:
            self.calls.append(context.offer.external_id)
            raise JobDecisionError("offline fake failure")

    _monitor_company(db_session)
    candidate = _candidate()
    _install_fetch(monkeypatch, [_offer("role-error")])
    engine = FailingEngine()

    summary = refresh_opportunities(
        db_session,
        candidate,
        max_jev_jobs=1,
        cache=DecisionCache(tmp_path / "error-decisions.local.json"),
        engine=engine,
    )

    assert summary.pending == 1
    assert summary.pending_errors == 1
    assert summary.pending_budget == 0
    assert summary.jev_evaluated == 0
    assert engine.calls == ["role-error"]
    row = _evaluations(db_session)[0]
    assert row.status == EvaluationStatus.PENDING.value
    assert row.decision is None
    assert row.evaluated_at is None


def test_review_application_lifecycle_is_idempotent_and_validates_transitions(db_session) -> None:
    job = Job(title="Backend Engineer")
    db_session.add(job)
    db_session.commit()

    first = transition_application(
        db_session,
        job.id,
        ApplicationStatus.APPLIED,
        note="  Submitted from the careers page.  ",
        source="  careers page  ",
        application_url="  https://acme.example.test/apply  ",
        cv_version="  backend-2026  ",
    )
    app_id = first.id
    assert first.applied_at is not None
    assert first.notes == "Submitted from the careers page."
    assert first.source == "careers page"
    assert first.application_url == "https://acme.example.test/apply"
    assert first.cv_version == "backend-2026"
    assert db_session.scalar(select(func.count()).select_from(ApplicationEvent)) == 1

    repeated = transition_application(db_session, job.id, ApplicationStatus.APPLIED)
    assert repeated.id == app_id
    assert db_session.scalar(select(func.count()).select_from(ApplicationEvent)) == 1

    interview = transition_application(
        db_session,
        job.id,
        ApplicationStatus.INTERVIEW,
        note="Technical interview scheduled.",
    )
    assert interview.status == ApplicationStatus.INTERVIEW.value
    events = db_session.scalars(
        select(ApplicationEvent).order_by(ApplicationEvent.occurred_at, ApplicationEvent.id)
    ).all()
    assert [(event.from_status, event.to_status) for event in events] == [
        (None, ApplicationStatus.APPLIED.value),
        (ApplicationStatus.APPLIED.value, ApplicationStatus.INTERVIEW.value),
    ]
    assert events[-1].note == "Technical interview scheduled."

    with pytest.raises(OpportunityServiceError, match="Invalid application transition"):
        transition_application(db_session, job.id, ApplicationStatus.DRAFT)
    assert db_session.scalars(select(Application)).one().status == ApplicationStatus.INTERVIEW.value
    assert db_session.scalar(select(func.count()).select_from(ApplicationEvent)) == 2

    saved = set_review_state(db_session, job.id, HumanReviewStatus.SAVED)
    assert saved.state == HumanReviewStatus.SAVED.value
    assert set_review_state(db_session, job.id, HumanReviewStatus.DISMISSED).id == saved.id
    assert db_session.scalars(select(Application)).one().status == ApplicationStatus.INTERVIEW.value


def test_first_application_status_cannot_skip_submission(db_session) -> None:
    job = Job(title="Backend Engineer")
    db_session.add(job)
    db_session.commit()

    with pytest.raises(OpportunityServiceError, match="first application status must be DRAFT or APPLIED"):
        transition_application(db_session, job.id, ApplicationStatus.INTERVIEW)
    assert db_session.scalar(select(func.count()).select_from(Application)) == 0
    assert db_session.scalar(select(func.count()).select_from(ApplicationEvent)) == 0


def _with_source_and_evaluation(
    session,
    candidate: CandidateConfig,
    engine: FakeEngine,
    external_id: str,
    title: str,
    answers: JevAnswers,
) -> Job:
    offer = _offer(external_id, title=title)
    from ai_job_hunter.services.ingestion import ingest_job
    from ai_job_hunter.services.opportunities import _prepare_from_source

    ingested = ingest_job(session, offer)
    job = session.get(Job, ingested.job_id)
    assert job is not None
    source = session.scalars(select(JobSource).where(JobSource.external_id == external_id)).one()
    source.source_title = offer.title
    source.source_description = offer.description
    source.source_location = offer.location
    source.remote_policy = offer.remote_policy.value
    source.remote_eligibility = offer.remote_eligibility.value
    source.salary_min = offer.salary_min
    source.salary_max = offer.salary_max
    source.salary_currency = offer.currency
    source.salary_period = offer.salary_period.value
    source.employment_type = offer.employment_type.value
    prepared = _prepare_from_source(job, source, candidate, engine.cache_identity)
    assert prepared is not None
    result = evaluate_job_decision(
        prepared.context,
        FakeEngine({external_id: answers}),
        policy_version=POLICY_VERSION_V2,
    )
    session.add(
        JobEvaluation(
            job_id=job.id,
            evaluation_fingerprint=prepared.fingerprint,
            status=EvaluationStatus.EVALUATED.value,
            decision=result.final_decision.value,
            rubric_version=result.rubric_version,
            policy_version=result.policy_version,
            engine_name="fake",
            engine_configuration=engine.cache_identity,
            model_version=result.model_version,
            config_fingerprint=prepared.config_fingerprint,
            deterministic_result={"decision": prepared.context.deterministic.decision.value},
            jev_signals=result.jev_answers.model_dump(mode="json") if result.jev_answers else None,
            evaluated_at=result.evaluated_at,
        )
    )
    session.commit()
    return job


def test_list_filters_order_and_priority_are_deterministic(db_session) -> None:
    _monitor_company(db_session)
    candidate = _candidate()
    engine = FakeEngine()
    scenarios = [
        ("job-alpha", "Backend Engineer Alpha", _answers()),
        (
            "job-beta",
            "Backend Engineer Beta",
            _answers(role=0.80, experience=0.75, backend=0.80, stack=0.70, flexibility=0.60, career=0.70, quality=0.60),
        ),
        (
            "job-review",
            "Backend Engineer Review",
            _answers(role=0.70, experience=0.80, backend=0.80, stack=0.70, flexibility=0.65, career=0.70, quality=0.60),
        ),
        (
            "job-skip",
            "Backend Engineer Skip",
            _answers(role=0.10, experience=0.80, backend=0.80, stack=0.80, flexibility=0.80, career=0.80, quality=0.70),
        ),
    ]
    jobs = {
        external_id: _with_source_and_evaluation(
            db_session,
            candidate,
            engine,
            external_id,
            title,
            answers,
        )
        for external_id, title, answers in scenarios
    }
    set_review_state(db_session, jobs["job-alpha"].id, HumanReviewStatus.SAVED)
    transition_application(db_session, jobs["job-beta"].id, ApplicationStatus.APPLIED)

    listed = list_opportunities(
        db_session,
        candidate,
        engine=engine,
        include_applied=True,
        include_skip=True,
    )
    observed = [(item.title, item.decision, item.priority) for item in listed]
    assert [item[0] for item in observed] == [
        "Backend Engineer Alpha",
        "Backend Engineer Beta",
        "Backend Engineer Review",
        "Backend Engineer Skip",
    ], observed
    assert [item[1] for item in observed] == [
        FinalDecision.APPLY,
        FinalDecision.APPLY,
        FinalDecision.REVIEW,
        FinalDecision.SKIP,
    ]
    assert [item[2] for item in observed] == sorted(
        (item[2] for item in observed), reverse=True
    )
    assert list_opportunities(
        db_session,
        candidate,
        engine=engine,
        include_applied=True,
        include_skip=True,
    ) == listed

    apply_filter = list_opportunities(
        db_session,
        candidate,
        engine=engine,
        decision=FinalDecision.APPLY,
        company="  aCmE  ",
        technology="PYTH",
        remote_only=True,
        include_applied=True,
    )
    assert [item.title for item in apply_filter] == [
        "Backend Engineer Alpha",
        "Backend Engineer Beta",
    ]
    skip_filter = list_opportunities(
        db_session,
        candidate,
        engine=engine,
        decision=FinalDecision.SKIP,
        include_applied=True,
    )
    assert [item.title for item in skip_filter] == ["Backend Engineer Skip"]

    # Tracked applications are hidden by default and act as SEEN in the feed.
    default_list = list_opportunities(db_session, candidate, engine=engine)
    assert all(item.application_status is None for item in default_list)
    seen = list_opportunities(
        db_session,
        candidate,
        engine=engine,
        include_applied=True,
        status=HumanReviewStatus.SEEN,
    )
    assert [item.title for item in seen] == ["Backend Engineer Beta"]
    assert seen[0].application_status is ApplicationStatus.APPLIED


def _job_id(session, external_id: str):
    return session.scalar(select(JobSource.job_id).where(JobSource.external_id == external_id))


def _forbid_fetch(monkeypatch) -> None:
    def no_fetch(*args, **kwargs):
        raise AssertionError("reevaluate must not fetch ATS boards")

    monkeypatch.setattr(opportunities, "_fetch_targets", no_fetch)


def _changed_candidate(candidate: CandidateConfig) -> CandidateConfig:
    """Any candidate change alters the config fingerprint and makes rows stale."""

    return candidate.model_copy(
        update={"profile": candidate.profile.model_copy(update={"current_role": "Changed Backend Engineer"})}
    )


def _seed_evaluated(db_session, monkeypatch, tmp_path, offers: list[NormalizedJob]) -> CandidateConfig:
    _monitor_company(db_session)
    candidate = _candidate()
    _install_fetch(monkeypatch, offers)
    refresh_opportunities(
        db_session,
        candidate,
        max_jev_jobs=len(offers),
        cache=DecisionCache(tmp_path / "seed-decisions.local.json"),
        engine=FakeEngine(),
    )
    _forbid_fetch(monkeypatch)
    return candidate


def _row_state(session) -> list[tuple]:
    return [
        (row.job_id, row.evaluation_fingerprint, row.status, row.decision, row.evaluated_at)
        for row in _evaluations(session)
    ]


def test_reevaluate_evaluates_only_selected_stale_jobs_without_fetching(db_session, monkeypatch, tmp_path) -> None:
    candidate = _seed_evaluated(
        db_session, monkeypatch, tmp_path, [_offer("role-a"), _offer("role-b"), _offer("role-c")]
    )
    stale_candidate = _changed_candidate(candidate)
    rows_before = _row_state(db_session)
    engine = FakeEngine()

    summary = reevaluate_jobs(
        db_session,
        stale_candidate,
        [_job_id(db_session, "role-a"), _job_id(db_session, "role-c")],
        max_jev_jobs=5,
        cache=DecisionCache(tmp_path / "reevaluate-decisions.local.json"),
        engine=engine,
    )

    assert sorted(engine.calls) == ["role-a", "role-c"]
    assert summary.jev_calls == 2
    assert summary.jev_evaluated == 2
    assert {item.outcome for item in summary.items} == {EvaluationOutcome.JEV_CALL}
    rows_after = _row_state(db_session)
    # History is preserved; only one new row per selected job is added.
    assert set(rows_before) <= set(rows_after)
    assert len(rows_after) == len(rows_before) + 2
    new_job_ids = {row[0] for row in set(rows_after) - set(rows_before)}
    assert new_job_ids == {_job_id(db_session, "role-a"), _job_id(db_session, "role-c")}
    by_job = {
        item.job_id: item.evaluation_is_stale
        for item in list_opportunities(db_session, stale_candidate, engine=engine, include_skip=True, limit=10)
    }
    assert by_job[_job_id(db_session, "role-a")] is False
    assert by_job[_job_id(db_session, "role-b")] is True
    assert by_job[_job_id(db_session, "role-c")] is False


def test_reevaluate_budget_counts_attempts_including_provider_failures(db_session, monkeypatch, tmp_path) -> None:
    from ai_job_hunter.decision_engine import JobDecisionError

    class FailingEngine(FakeEngine):
        def evaluate(self, context) -> DecisionEvidence:
            self.calls.append(context.offer.external_id)
            raise JobDecisionError("offline fake failure")

    candidate = _seed_evaluated(
        db_session, monkeypatch, tmp_path, [_offer("role-a"), _offer("role-b"), _offer("role-c")]
    )
    engine = FailingEngine()

    summary = reevaluate_jobs(
        db_session,
        _changed_candidate(candidate),
        [_job_id(db_session, external_id) for external_id in ("role-a", "role-b", "role-c")],
        max_jev_jobs=2,
        cache=DecisionCache(tmp_path / "budget-decisions.local.json"),
        engine=engine,
    )

    assert len(engine.calls) == 2
    assert summary.jev_calls == 2
    assert summary.pending_errors == 2
    assert summary.pending_budget == 1
    outcomes = sorted(item.outcome for item in summary.items)
    assert outcomes == sorted(
        [EvaluationOutcome.PENDING_ERROR, EvaluationOutcome.PENDING_ERROR, EvaluationOutcome.PENDING_BUDGET]
    )


def test_reevaluate_dry_run_plans_without_writes_or_calls(db_session, monkeypatch, tmp_path) -> None:
    candidate = _seed_evaluated(
        db_session, monkeypatch, tmp_path, [_offer("role-a"), _offer("role-b")]
    )
    rows_before = _row_state(db_session)
    engine = FakeEngine()
    cache_path = tmp_path / "dry-run-decisions.local.json"

    summary = reevaluate_jobs(
        db_session,
        _changed_candidate(candidate),
        [_job_id(db_session, "role-a"), _job_id(db_session, "role-b")],
        max_jev_jobs=1,
        dry_run=True,
        cache=DecisionCache(cache_path),
        engine=engine,
    )

    assert engine.calls == []
    assert summary.jev_calls == 0
    assert summary.dry_run is True
    assert sorted(item.outcome for item in summary.items) == sorted(
        [EvaluationOutcome.JEV_CALL, EvaluationOutcome.PENDING_BUDGET]
    )
    assert _row_state(db_session) == rows_before
    assert not cache_path.exists()


def test_reevaluate_reuses_current_evaluations_on_second_run(db_session, monkeypatch, tmp_path) -> None:
    candidate = _seed_evaluated(db_session, monkeypatch, tmp_path, [_offer("role-a")])
    stale_candidate = _changed_candidate(candidate)
    job_id = _job_id(db_session, "role-a")
    engine = FakeEngine()
    # A fresh cache path per run proves reuse comes from the current DB row.
    first = reevaluate_jobs(
        db_session, stale_candidate, [job_id], max_jev_jobs=1,
        cache=DecisionCache(tmp_path / "first.local.json"), engine=engine,
    )
    rows_after_first = _row_state(db_session)

    second = reevaluate_jobs(
        db_session, stale_candidate, [job_id, job_id], max_jev_jobs=1,
        cache=DecisionCache(tmp_path / "second.local.json"), engine=engine,
    )

    assert first.jev_calls == 1
    assert second.jev_calls == 0
    assert second.jobs_selected == 1
    assert [item.outcome for item in second.items] == [EvaluationOutcome.CURRENT]
    assert engine.calls == ["role-a"]
    assert _row_state(db_session) == rows_after_first


def test_reevaluate_deterministic_skip_never_calls_jev(db_session, monkeypatch, tmp_path) -> None:
    rejected = _offer(
        "role-reject",
        remote_policy="ONSITE",
        remote_eligibility="COUNTRY_RESTRICTED",
        location="New York, United States",
    )
    candidate = _seed_evaluated(db_session, monkeypatch, tmp_path, [rejected])
    engine = FakeEngine()

    summary = reevaluate_jobs(
        db_session,
        _changed_candidate(candidate),
        [_job_id(db_session, "role-reject")],
        max_jev_jobs=1,
        cache=DecisionCache(tmp_path / "skip.local.json"),
        engine=engine,
    )

    assert engine.calls == []
    assert summary.jev_calls == 0
    assert [(item.outcome, item.decision) for item in summary.items] == [
        (EvaluationOutcome.DETERMINISTIC_SKIP, FinalDecision.SKIP.value)
    ]


def test_reevaluate_rejects_unknown_job_ids_before_any_work(db_session, monkeypatch, tmp_path) -> None:
    from uuid import uuid4

    candidate = _seed_evaluated(db_session, monkeypatch, tmp_path, [_offer("role-a")])
    rows_before = _row_state(db_session)
    engine = FakeEngine()
    unknown = uuid4()

    with pytest.raises(OpportunityServiceError, match=str(unknown)):
        reevaluate_jobs(
            db_session,
            _changed_candidate(candidate),
            [_job_id(db_session, "role-a"), unknown],
            max_jev_jobs=1,
            cache=DecisionCache(tmp_path / "unknown.local.json"),
            engine=engine,
        )

    assert engine.calls == []
    assert _row_state(db_session) == rows_before
    with pytest.raises(OpportunityServiceError):
        reevaluate_jobs(db_session, candidate, [], max_jev_jobs=1, engine=engine)
    with pytest.raises(OpportunityServiceError):
        reevaluate_jobs(db_session, candidate, [unknown], max_jev_jobs=-1, engine=engine)


def test_vanished_cache_entry_never_calls_jev_outside_budget(db_session, monkeypatch, tmp_path) -> None:
    class VanishingCache(DecisionCache):
        def contains(self, key: str) -> bool:
            return True

        def get(self, key: str):
            return None

    candidate = _seed_evaluated(db_session, monkeypatch, tmp_path, [_offer("role-a")])
    engine = FakeEngine()

    summary = reevaluate_jobs(
        db_session,
        _changed_candidate(candidate),
        [_job_id(db_session, "role-a")],
        max_jev_jobs=0,
        cache=VanishingCache(tmp_path / "vanishing.local.json"),
        engine=engine,
    )

    assert engine.calls == []
    assert summary.jev_calls == 0
    assert [item.outcome for item in summary.items] == [EvaluationOutcome.PENDING_ERROR]


def test_reevaluate_reports_selected_jobs_without_source_snapshots(db_session, tmp_path) -> None:
    job = Job(title="Backend Engineer")
    db_session.add(job)
    db_session.commit()
    engine = FakeEngine()

    summary = reevaluate_jobs(
        db_session,
        _candidate(),
        [job.id],
        max_jev_jobs=1,
        cache=DecisionCache(tmp_path / "empty.local.json"),
        engine=engine,
    )

    assert summary.items == []
    assert summary.jobs_without_snapshot == [job.id]
    assert engine.calls == []


@pytest.mark.parametrize(
    ("location", "remote_policy", "penalized"),
    [
        ("Málaga, Spain", "HYBRID", True),
        ("Málaga, Spain", "ONSITE", True),
        ("Madrid, Spain", "HYBRID", False),
        ("Remote Spain", "REMOTE", False),
        ("Remote", None, False),
        ("Bilbao, Spain", None, True),
    ],
)
def test_roles_outside_preferred_locations_lose_review_priority(location, remote_policy, penalized) -> None:
    candidate = _candidate()
    candidate = candidate.model_copy(
        update={
            "preferences": candidate.preferences.model_copy(
                update={"preferred_locations": ["Madrid"], "acceptable_locations": ["Madrid", "Málaga", "Bilbao"]}
            )
        }
    )
    offer = _offer("role-x", location=location, remote_policy=remote_policy or "REMOTE")
    if remote_policy is None:
        offer = offer.model_copy(update={"remote_policy": None})
    prepared = opportunities._prepare_offer(offer, candidate, engine_identity="offline")

    adjustments = opportunities._relocation_adjustment(prepared.context)

    assert bool(adjustments) is penalized
    if penalized:
        assert adjustments[0][0] == -opportunities.RELOCATION_PENALTY
        assert "fuera de Madrid" in adjustments[0][1]


@pytest.mark.parametrize(
    ("salary_min", "salary_max", "currency", "period", "points"),
    [
        ("35000", "40000", "EUR", "YEAR", 5),
        ("70000", "90000", "EUR", "YEAR", 10),
        ("2000", "2600", "EUR", "MONTH", 5),
        ("20000", "25000", "EUR", "YEAR", 0),
        ("90000", "120000", "USD", "YEAR", 0),
        (None, None, None, None, 0),
    ],
)
def test_published_salary_at_or_above_target_moves_job_up(salary_min, salary_max, currency, period, points) -> None:
    candidate = _candidate()
    candidate = candidate.model_copy(
        update={"preferences": candidate.preferences.model_copy(update={"target_salary": Decimal("30000"), "salary_currency": "EUR"})}
    )
    offer = NormalizedJob.model_validate(
        _offer("role-salary").model_dump()
        | {"salary_min": salary_min, "salary_max": salary_max, "currency": currency, "salary_period": period}
    )
    prepared = opportunities._prepare_offer(offer, candidate, engine_identity="offline")

    adjustments = opportunities._salary_adjustment(prepared.context)

    assert sum(value for value, _label in adjustments) == points


def _source_closed(session, external_id):
    return session.scalar(select(JobSource.closed_at).where(JobSource.external_id == external_id))


def test_postings_missing_from_a_complete_board_fetch_are_closed_and_reopened(db_session, monkeypatch, tmp_path):
    _monitor_company(db_session)
    candidate = _candidate()
    cache = DecisionCache(tmp_path / "closed.json")
    kwargs = dict(no_jev=True, cache=cache, engine=FakeEngine())
    _install_fetch(monkeypatch, [_offer("role-a"), _offer("role-b", title="Platform Engineer")])
    refresh_opportunities(db_session, candidate, **kwargs)

    _install_fetch(monkeypatch, [_offer("role-a")])
    summary = refresh_opportunities(db_session, candidate, **kwargs)

    assert summary.closed_postings == 1
    assert _source_closed(db_session, "role-b") is not None and _source_closed(db_session, "role-a") is None
    titles = [item.title for item in list_opportunities(db_session, candidate, engine=FakeEngine(), include_skip=True)]
    assert "Platform Engineer" not in titles

    _install_fetch(monkeypatch, [_offer("role-a"), _offer("role-b", title="Platform Engineer")])
    refresh_opportunities(db_session, candidate, **kwargs)
    assert _source_closed(db_session, "role-b") is None


def test_truncated_or_failed_board_fetches_never_close_postings(db_session, monkeypatch, tmp_path):
    _monitor_company(db_session)
    candidate = _candidate()
    kwargs = dict(no_jev=True, cache=DecisionCache(tmp_path / "trunc.json"), engine=FakeEngine())
    _install_fetch(monkeypatch, [_offer("role-a"), _offer("role-b", title="Platform Engineer")])
    refresh_opportunities(db_session, candidate, **kwargs)

    _install_fetch(monkeypatch, [_offer("role-a")])
    truncated = refresh_opportunities(db_session, candidate, max_jobs_per_company=1, **kwargs)
    assert truncated.closed_postings == 0

    def failing_fetch(targets, *, max_jobs_per_company, client):
        return [], [opportunities.SourceFailure("Acme", "GREENHOUSE", "GreenhouseConnectorError")]

    monkeypatch.setattr(opportunities, "_fetch_targets", failing_fetch)
    failed = refresh_opportunities(db_session, candidate, **kwargs)
    assert failed.closed_postings == 0
    assert _source_closed(db_session, "role-b") is None


def test_review_reason_is_validated_and_stored(db_session) -> None:
    job = Job(title="Backend Engineer")
    db_session.add(job)
    db_session.commit()

    review = set_review_state(db_session, job.id, HumanReviewStatus.DISMISSED, reason="salary")
    assert (review.state, review.reason) == ("DISMISSED", "salary") and review.reason_at is not None
    with pytest.raises(OpportunityServiceError):
        set_review_state(db_session, job.id, HumanReviewStatus.SAVED, reason="location")
    review = set_review_state(db_session, job.id, HumanReviewStatus.SEEN)
    assert review.reason is None


@pytest.mark.parametrize(
    ("description", "points"),
    [
        ("We build services in Java and Spring Boot with React on the front.", 5),
        ("Backend in Python and Go, with a React dashboard.", 0),
        ("Work with React, TypeScript and Node.js on our web app.", -15),
        ("Required: 3+ years of experience with React and TypeScript. Node.js is a plus.", -25),
        ("We value curiosity and ownership.", 0),
    ],
)
def test_stack_adjustment_prefers_java_and_demotes_javascript_roles(description, points) -> None:
    offer = NormalizedJob.model_validate(_offer("role-stack").model_dump() | {"description": description * 3})
    prepared = opportunities._prepare_offer(offer, _candidate(), engine_identity="offline")

    adjustments = opportunities._stack_adjustment(prepared.context)

    assert sum(value for value, _label in adjustments) == points


def test_priority_weights_stack_and_experience_most() -> None:
    signals = {name: {"value": 0.5} for name in opportunities.PRIORITY_WEIGHTS}
    assert opportunities._priority(signals) == 50
    assert abs(sum(opportunities.PRIORITY_WEIGHTS.values()) - 1.0) < 1e-9
    strong_stack = dict(signals, stack_transferability={"value": 1.0})
    strong_career = dict(signals, career_value={"value": 1.0})
    assert opportunities._priority(strong_stack) > opportunities._priority(strong_career)


@pytest.mark.parametrize(("location", "points"), [("Luxembourg", -5), ("Vigo", -15), ("Madrid", 0)])
def test_relocation_to_a_preferred_destination_costs_less(location, points) -> None:
    candidate = _candidate()
    preferences = candidate.preferences.model_copy(
        update={
            "preferred_locations": ["Madrid"],
            "acceptable_locations": ["Madrid", "Vigo", "Luxembourg"],
            "relocation_preferred_locations": ["Luxembourg"],
        }
    )
    candidate = candidate.model_copy(update={"preferences": preferences})
    offer = NormalizedJob.model_validate(
        _offer("role-relocation").model_dump() | {"location": location, "remote_policy": "ONSITE"}
    )
    prepared = opportunities._prepare_offer(offer, candidate, engine_identity="offline")

    assert sum(value for value, _label in opportunities._relocation_adjustment(prepared.context)) == points


def test_fetch_targets_records_the_connector_error_message_as_failure_detail() -> None:
    import httpx
    from uuid import uuid4

    from ai_job_hunter.domain.company_intelligence import ATSDiscoveryConfidence, ATSProvider, CompanyMonitorTarget

    target = CompanyMonitorTarget(
        company_id=uuid4(),
        company_name="Acme",
        provider=ATSProvider.WORKDAY,
        identifier="acme/Careers",
        region="wd1",
        careers_url="https://acme.wd1.myworkdayjobs.com/Careers",
        evidence_source="test",
        confidence=ATSDiscoveryConfidence.OBSERVED_JOB_SOURCE,
    )
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(429)))

    jobs, failures = opportunities._fetch_targets([target], max_jobs_per_company=5, client=client)

    assert jobs == []
    assert [(f.company, f.provider, f.error_type) for f in failures] == [("Acme", "WORKDAY", "WorkdayConnectorError")]
    assert failures[0].detail == "Workday career site API returned HTTP 429."


GERMAN_AD = (
    "Wir suchen einen Entwickler für unser Team in Berlin. Sie arbeiten mit Java und Spring und entwickeln mit uns "
    "die Plattform. Das Team ist international und wir bieten Ihnen eine flexible Arbeitszeit mit der Möglichkeit "
    "von zu Hause zu arbeiten. Sie bringen Erfahrung mit und haben Spaß an der Arbeit im Team und der Entwicklung "
    "von Software."
)


@pytest.mark.parametrize(
    ("description", "points", "label"),
    [
        ("Build Java services. Fluent German is required.", -opportunities.LANGUAGE_REQUIRED_PENALTY, "pide alemán"),
        ("Build Java services. German is a plus.", 0, None),
        (GERMAN_AD, -opportunities.LANGUAGE_WRITTEN_PENALTY, "anuncio en alemán"),
        ("Build Java services with a friendly team in Madrid.", 0, None),
    ],
)
def test_postings_that_need_another_spoken_language_lose_review_priority(description, points, label) -> None:
    offer = _offer("role-language").model_copy(update={"description": description})
    prepared = opportunities._prepare_offer(offer, _candidate(), engine_identity="offline")

    adjustments = opportunities._language_adjustment(prepared.context)

    assert sum(value for value, _label in adjustments) == points
    assert (label is None) or label in adjustments[0][1]
