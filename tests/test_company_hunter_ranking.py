from uuid import uuid4

from company_hunter_support import add_company

from ai_job_hunter.company_hunter.ranking import (
    CompanyInputs,
    CompanyStage,
    FactorStatus,
    PostingEvidence,
    company_stage,
    rank_companies,
    score_company,
)
from ai_job_hunter.domain.company_intelligence import FactStatus
from ai_job_hunter.models import (
    Application,
    ApplicationStatus,
    CompanyEvidence,
    CompanyLead,
    Job,
    JobReview,
    MonitoredSource,
    MonitoredSourceState,
    Outreach,
    OutreachChannel,
    OutreachPurpose,
    OutreachStatus,
)


def _posting(title="Java Engineer", description="Java and Spring Boot", location="Madrid", eligibility=None):
    return PostingEvidence(title, description, location, None, eligibility, "https://x.example.test/1")


def _factor(fit, name):
    return next(factor for factor in fit.factors if factor.name == name)


def test_full_evidence_scores_each_factor_with_provenance():
    fit = score_company(
        CompanyInputs(
            company_id=uuid4(),
            name="Acme",
            description="A fintech and AI company.",
            company_type="product",
            employee_count=120,
            size_provenance="manual",
            postings=(_posting(), _posting("Kotlin Dev", "Kotlin backend")),
        )
    )

    assert _factor(fit, "sector").points == 25
    assert _factor(fit, "product company").status is FactorStatus.YES
    assert _factor(fit, "Spain presence").points == 20
    assert _factor(fit, "stack").points == 30  # two primary-stack postings
    assert _factor(fit, "size/stage").points == 10
    assert fit.score == 95
    assert fit.stage is CompanyStage.MID_SIZE
    assert fit.unknowns == ()
    assert _factor(fit, "stack").provenance == ("https://x.example.test/1",)


def test_unknown_stays_unknown_and_scores_zero():
    fit = score_company(CompanyInputs(company_id=uuid4(), name="Mystery"))

    assert fit.score == 0
    assert set(fit.unknowns) == {"sector", "product company", "Spain presence", "stack", "size/stage"}
    assert all(factor.status is FactorStatus.UNKNOWN for factor in fit.factors)
    assert fit.stage is CompanyStage.UNKNOWN


def test_hints_earn_partial_credit_and_are_labelled():
    fit = score_company(
        CompanyInputs(
            company_id=uuid4(),
            name="Hinty",
            lead_notes=("Cool banking SaaS product company",),
            lead_location_hints=("Madrid",),
        )
    )

    sector = _factor(fit, "sector")
    assert (sector.status, sector.points) == (FactorStatus.PARTIAL, 12)
    assert "hint" in sector.reason
    assert _factor(fit, "product company").points == 5
    geography = _factor(fit, "Spain presence")
    assert (geography.status, geography.points) == (FactorStatus.PARTIAL, 8)
    assert "hint" in geography.reason


def test_services_companies_get_no_product_points_and_stack_tiers_differ():
    consultancy = score_company(CompanyInputs(company_id=uuid4(), name="C", company_type="consultancy"))
    assert _factor(consultancy, "product company").status is FactorStatus.NO

    python_only = score_company(
        CompanyInputs(company_id=uuid4(), name="P", postings=(_posting("Python Dev", "Python and Django"),))
    )
    java = score_company(CompanyInputs(company_id=uuid4(), name="J", postings=(_posting(),)))
    none = score_company(
        CompanyInputs(company_id=uuid4(), name="N", postings=(_posting("PHP Dev", "Laravel"),))
    )
    assert _factor(python_only, "stack").points == 12
    assert _factor(java, "stack").points == 25
    assert (_factor(none, "stack").status, _factor(none, "stack").points) == (FactorStatus.NO, 0)


def test_geography_levels_and_remote_evidence():
    spain = score_company(CompanyInputs(company_id=uuid4(), name="S", postings=(_posting(location="Barcelona, Spain"),)))
    eu = score_company(
        CompanyInputs(company_id=uuid4(), name="E", postings=(_posting(location="Remote", eligibility="EU_REMOTE"),))
    )
    evidence = score_company(
        CompanyInputs(
            company_id=uuid4(), name="R", remote_from_spain=FactStatus.YES, remote_from_spain_provenance=("manual",)
        )
    )
    assert _factor(spain, "Spain presence").points == 15
    assert _factor(eu, "Spain presence").points == 10
    assert _factor(evidence, "Spain presence").points == 20
    assert _factor(evidence, "Spain presence").provenance == ("manual",)


def test_stage_from_size_evidence():
    assert company_stage(12, None) is CompanyStage.EARLY_STAGE
    assert company_stage(30, None) is CompanyStage.MID_SIZE
    assert company_stage(None, "seed") is CompanyStage.EARLY_STAGE
    assert company_stage(None, "scale-up") is CompanyStage.MID_SIZE
    assert company_stage(None, None) is CompanyStage.UNKNOWN


def test_rank_uses_leads_and_monitored_sources_and_reads_company_evidence(db_session):
    lead_company = add_company(db_session, "Lead Co", lead=True)
    source_company = add_company(
        db_session, "Source Co", lead=False, postings=(("Python Dev", "Python services", "Remote", "WORLDWIDE"),)
    )
    db_session.add(
        MonitoredSource(
            company_id=source_company.id, provider="GREENHOUSE", identifier="sourceco", identifier_key="sourceco",
            origin="career_url", state=MonitoredSourceState.ACTIVE.value,
        )
    )
    unrelated = add_company(db_session, "Unrelated Co", lead=False)
    db_session.add(
        CompanyEvidence(
            company_id=lead_company.id, provider="manual", source_key="size", evidence_type="other",
            source_url="https://acme.example.test/about", structured_data={"employee_count": 40},
        )
    )
    db_session.add(CompanyLead(
        company_name="Not Linked", normalized_name="not linked", domain_key="x", source_type="manual", source_label="l",
    ))
    db_session.commit()

    result = rank_companies(db_session)

    assert [fit.name for fit in result.ranked] == ["Lead Co", "Source Co"]
    assert unrelated.name not in [fit.name for fit in result.ranked]
    assert result.unresolved_leads == 1
    assert _factor(result.ranked[0], "size/stage").status is FactorStatus.YES
    assert result.ranked[0].stage is CompanyStage.MID_SIZE
    assert rank_companies(db_session, limit=1).ranked[0].name == "Lead Co"


def test_rejected_monitored_source_alone_does_not_qualify(db_session):
    company = add_company(db_session, "Rejected Co", lead=False)
    db_session.add(
        MonitoredSource(
            company_id=company.id, provider="GREENHOUSE", identifier="r", identifier_key="r",
            origin="career_url", state=MonitoredSourceState.REJECTED.value,
        )
    )
    db_session.commit()

    assert rank_companies(db_session).ranked == ()


def _job_of(session, company) -> Job:
    return session.query(Job).filter(Job.company_id == company.id).first()


def test_applied_dismissed_and_declined_companies_are_excluded(db_session):
    applied = add_company(db_session, "Applied Co")
    db_session.add(Application(job_id=_job_of(db_session, applied).id, status=ApplicationStatus.APPLIED.value))
    draft_only = add_company(db_session, "Draft Co")
    db_session.add(Application(job_id=_job_of(db_session, draft_only).id, status=ApplicationStatus.DRAFT.value))
    company_reason = add_company(db_session, "Dismissed Company Reason")
    db_session.add(JobReview(job_id=_job_of(db_session, company_reason).id, state="DISMISSED", reason="company"))
    salary_only = add_company(
        db_session, "Dismissed Salary", postings=(("Java A", "Java", "Madrid", None), ("Java B", "Java", "Madrid", None))
    )
    first_job = db_session.query(Job).filter(Job.company_id == salary_only.id).first()
    db_session.add(JobReview(job_id=first_job.id, state="DISMISSED", reason="salary"))
    all_dismissed = add_company(db_session, "All Dismissed")
    db_session.add(JobReview(job_id=_job_of(db_session, all_dismissed).id, state="DISMISSED", reason="salary"))
    declined = add_company(db_session, "Declined Co")
    db_session.add(
        Outreach(
            company_id=declined.id, purpose=OutreachPurpose.COLD_OUTREACH.value,
            channel=OutreachChannel.EMAIL.value, status=OutreachStatus.DECLINED.value,
        )
    )
    db_session.commit()

    result = rank_companies(db_session)

    assert {fit.name for fit in result.ranked} == {"Draft Co", "Dismissed Salary"}
    reasons = {item.name: item.reason for item in result.excluded}
    assert reasons["Applied Co"] == "already applied"
    assert reasons["Dismissed Company Reason"] == "dismissed (company-level reason)"
    assert reasons["All Dismissed"] == "every known job dismissed"
    assert reasons["Declined Co"] == "outreach declined"
