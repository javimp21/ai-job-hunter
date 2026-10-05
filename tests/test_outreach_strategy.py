from ai_job_hunter.outreach.strategy import (
    CompanySizeEvidence,
    ContactType,
    recommend_contact_strategy,
)


def test_technical_role_is_recruiter_first_unless_small_company_is_evidenced():
    strategy = recommend_contact_strategy("Backend Engineer")
    assert strategy.preferred_contact_types == (
        ContactType.RECRUITER,
        ContactType.HIRING_MANAGER,
        ContactType.ENGINEERING_MANAGER,
    )
    # An unsourced size claim is not evidence.
    unsourced = recommend_contact_strategy("Backend Engineer", CompanySizeEvidence(size_bucket="startup"))
    assert unsourced.preferred_contact_types == strategy.preferred_contact_types
    large = recommend_contact_strategy(
        "Backend Engineer", CompanySizeEvidence(employee_count=5000, source="company filing")
    )
    assert large.preferred_contact_types[0] is ContactType.RECRUITER
    leadership = recommend_contact_strategy("Engineering Manager")
    assert leadership.preferred_contact_types[0] is ContactType.HIRING_MANAGER
    assert ContactType.FOUNDER not in leadership.preferred_contact_types


def test_founder_leads_only_with_sourced_small_company_evidence():
    evidence = recommend_contact_strategy(
        "Backend Engineer",
        CompanySizeEvidence(size_bucket="small_startup", source="company filing"),
    )
    assert evidence.preferred_contact_types == (
        ContactType.FOUNDER,
        ContactType.ENGINEERING_MANAGER,
        ContactType.ENGINEER,
        ContactType.RECRUITER,
    )
    assert any("small-company" in reason for reason in evidence.reasons)
    small_count = recommend_contact_strategy(
        "Platform Engineer", CompanySizeEvidence(employee_count=12, source="public profile")
    )
    assert small_count.preferred_contact_types[0] is ContactType.FOUNDER
    lead = recommend_contact_strategy(
        "Engineering Manager", CompanySizeEvidence(size_bucket="small", source="company filing")
    )
    assert lead.preferred_contact_types[0] is ContactType.HIRING_MANAGER
    assert lead.preferred_contact_types[-1] is ContactType.FOUNDER


def test_recruiter_title_prioritizes_talent_and_recruiting_contacts():
    strategy = recommend_contact_strategy("Senior Technical Recruiter")
    assert strategy.preferred_contact_types[:2] == (ContactType.TALENT, ContactType.RECRUITER)
