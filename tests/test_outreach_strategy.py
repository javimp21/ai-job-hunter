from ai_job_hunter.outreach.strategy import (
    CompanySizeEvidence,
    ContactType,
    recommend_contact_strategy,
)


def test_backend_strategy_uses_role_evidence_without_one_global_order():
    strategy = recommend_contact_strategy("Backend Engineer")
    assert strategy.preferred_contact_types == (
        ContactType.ENGINEERING_MANAGER,
        ContactType.ENGINEER,
        ContactType.RECRUITER,
    )
    leadership = recommend_contact_strategy("Engineering Manager")
    assert leadership.preferred_contact_types[0] is ContactType.HIRING_MANAGER


def test_founder_suggested_only_with_sourced_small_startup_evidence():
    no_evidence = recommend_contact_strategy(
        "Backend Engineer", CompanySizeEvidence(size_bucket="startup")
    )
    assert ContactType.FOUNDER not in no_evidence.preferred_contact_types

    evidence = recommend_contact_strategy(
        "Backend Engineer",
        CompanySizeEvidence(size_bucket="small_startup", source="company filing"),
    )
    assert ContactType.FOUNDER in evidence.preferred_contact_types
    assert any("Sourced small-startup" in reason for reason in evidence.reasons)


def test_recruiter_title_prioritizes_talent_and_recruiting_contacts():
    strategy = recommend_contact_strategy("Senior Technical Recruiter")
    assert strategy.preferred_contact_types[:2] == (ContactType.TALENT, ContactType.RECRUITER)
