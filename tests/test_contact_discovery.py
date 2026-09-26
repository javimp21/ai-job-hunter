from __future__ import annotations

from ai_job_hunter.contact_discovery import (
    ContactCandidate,
    ContactLookupStrategy,
    ContactMatchDecision,
    FakeContactProvider,
    ManualContactProvider,
    canonical_linkedin_profile_url,
    match_contacts,
    normalize_contact_email,
)


def test_manual_provider_searches_company_and_job_without_filling_empty_fields() -> None:
    sparse = ContactCandidate(company="Example Systems", job_title="Recruiting Manager")
    unrelated = ContactCandidate(company="Other Corp", job_title="Recruiting Manager")
    provider = ManualContactProvider([sparse, unrelated])

    company_result = provider.search_company("EXAMPLE SYSTEMS, INC.")
    job_result = provider.search_job("Example Systems", "Recruiting Manager")

    assert company_result == (sparse,)
    assert job_result == (sparse,)
    assert sparse.full_name is None
    assert sparse.email is None
    assert sparse.linkedin_url is None


def test_fake_provider_is_provider_injected_and_tracks_exact_queries() -> None:
    contact = ContactCandidate(provider="fixture", full_name="Test Person", company="Example")
    provider = FakeContactProvider(
        company_results={"Example": [contact]},
        job_results={("Example", "Engineering Manager"): [contact]},
    )
    strategy = ContactLookupStrategy([provider])

    by_company = strategy.search_company("Example, Inc.")
    by_job = strategy.search_job("Example", "Engineering Manager")

    assert by_company.contacts == (contact,)
    assert by_job.contacts == (contact,)
    assert provider.company_queries == ["Example, Inc."]
    assert provider.job_queries == [("Example", "Engineering Manager")]


def test_provider_and_external_id_is_a_strong_identity_signal() -> None:
    first = ContactCandidate(provider="Apollo", external_id="P-17")
    second = ContactCandidate(provider="apollo", external_id="P-17")

    match = match_contacts(first, second)

    assert match.decision is ContactMatchDecision.MATCH
    assert match.signals.strong_matches == ("provider_external_id",)


def test_normalized_email_is_a_strong_identity_signal() -> None:
    first = ContactCandidate(email="  PERSON@Example.COM ")
    second = ContactCandidate(email="person@example.com")

    assert normalize_contact_email(first.email) == "person@example.com"
    assert match_contacts(first, second).decision is ContactMatchDecision.MATCH


def test_linkedin_profile_url_is_canonicalized_without_network_access() -> None:
    first = ContactCandidate(linkedin_url="https://www.linkedin.com/in/Test-Person/?trk=abc#top")
    second = ContactCandidate(linkedin_url="http://es.linkedin.com/in/test-person")

    assert canonical_linkedin_profile_url(first.linkedin_url) == "https://linkedin.com/in/test-person"
    assert match_contacts(first, second).decision is ContactMatchDecision.MATCH
    assert canonical_linkedin_profile_url("https://www.linkedin.com/company/example") is None


def test_conflicting_strong_identifiers_prevent_automatic_match() -> None:
    first = ContactCandidate(
        provider="crm",
        external_id="123",
        email="person@example.com",
        linkedin_url="https://linkedin.com/in/person-a",
    )
    second = ContactCandidate(
        provider="crm",
        external_id="123",
        email="person@example.com",
        linkedin_url="https://linkedin.com/in/person-b",
    )

    match = match_contacts(first, second)

    assert match.decision is ContactMatchDecision.POSSIBLE_MATCH
    assert match.signals.strong_conflicts == ("linkedin_url",)


def test_name_and_company_are_only_a_possible_match() -> None:
    first = ContactCandidate(full_name="José García", company="Example Systems, Inc.")
    second = ContactCandidate(full_name="Jose Garcia", company="Example Systems")

    match = match_contacts(first, second)

    assert match.decision is ContactMatchDecision.POSSIBLE_MATCH
    assert match.signals.name_company_match


def test_weak_matches_are_reported_but_never_merged_automatically() -> None:
    first = ContactCandidate(full_name="Test Person", company="Example")
    second = ContactCandidate(full_name="Test Person", company="Example")
    provider = FakeContactProvider(company_results={"Example": [first, second]})

    result = ContactLookupStrategy([provider]).search_company("Example")

    assert result.contacts == (first, second)
    assert result.strong_duplicates == ()
    assert len(result.possible_matches) == 1
    assert result.possible_matches[0].match.decision is ContactMatchDecision.POSSIBLE_MATCH


def test_ambiguous_strong_match_is_not_merged_when_it_also_matches_another_row() -> None:
    first = ContactCandidate(provider="crm", external_id="1", full_name="Test Person", company="Example")
    second = ContactCandidate(provider="other", external_id="2", full_name="Test Person", company="Example")
    third = ContactCandidate(provider="crm", external_id="1", full_name="Test Person", company="Example")
    provider = FakeContactProvider(company_results={"Example": [first, second, third]})

    result = ContactLookupStrategy([provider]).search_company("Example")

    assert len(result.contacts) == 3
    assert result.strong_duplicates == ()
    assert len(result.possible_matches) == 3
    assert all(
        possible.match.decision is ContactMatchDecision.POSSIBLE_MATCH
        for possible in result.possible_matches
    )


def test_empty_fields_do_not_create_identity_or_weak_match() -> None:
    empty = ContactCandidate(provider="", external_id="", full_name="", company="", email="", linkedin_url="")

    match = match_contacts(empty, ContactCandidate())

    assert match.decision is ContactMatchDecision.NO_MATCH
    assert match.signals.strong_matches == ()
    assert match.signals.strong_conflicts == ()
    assert not match.signals.name_company_match


def test_linkedin_and_email_normalizers_reject_empty_or_invalid_values() -> None:
    assert normalize_contact_email(None) is None
    assert normalize_contact_email("   ") is None
    assert normalize_contact_email("invalid") is None
    assert canonical_linkedin_profile_url(None) is None
    assert canonical_linkedin_profile_url("https://example.com/in/person") is None
