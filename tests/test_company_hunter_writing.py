
import pytest
from company_hunter_support import BASE_CV, add_company, add_contact, drafts_json, scripted_client, write_private

from ai_job_hunter.company_hunter.ranking import CompanyStage
from ai_job_hunter.company_hunter.service import best_contact, company_context, draft_for_company
from ai_job_hunter.company_hunter.writing import (
    LINKEDIN_NOTE_LIMIT,
    CompanyFacts,
    HunterWritingError,
    PersonFacts,
    build_request,
    check_text,
    enforce_note_limit,
    generate_company_drafts,
    generate_connection_note,
    generate_follow_up,
    load_base_cv,
    resolve_language,
    unsupported_claims,
)
from ai_job_hunter.models import Outreach, OutreachStatus

FACTS = CompanyFacts(
    name="Acme Pay", website="https://acme.example.test", stage=CompanyStage.EARLY_STAGE,
    description="Acme Pay is a fintech building payments APIs.", stack_terms=("java", "spring boot"),
    posting_titles=("Senior Java Engineer",), fit_reasons=("stack: Java in 1 of 1 postings",), unknowns=("size/stage",),
)
PERSON = PersonFacts("Jane Doe", "Engineering Manager", quote="Jane Doe — Engineering Manager", topic="Kafka at Acme")


def _kwargs(tmp_path):
    _cv, style = write_private(tmp_path)
    return {"base_cv": BASE_CV, "style_guide": style.read_text(encoding="utf-8")}


def test_request_matches_cover_letter_style_and_carries_rules_cv_and_facts(tmp_path):
    client, messages = scripted_client(drafts_json())

    generate_company_drafts(client, FACTS, PERSON, language="es", **_kwargs(tmp_path))

    request = messages.requests[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["fallbacks"] == "default" and request["betas"] == ["server-side-fallback-2026-07-01"]
    system = request["system"][0]
    assert system["cache_control"] == {"type": "ephemeral"}
    for rule in ("early-stage", "mid-size", "ONE-LINE", "Never claim anything about the candidate", "Plain, honest"):
        assert rule.casefold() in system["text"].casefold()
    user = request["messages"][0]["content"][0]["text"]
    assert "Java 21, Spring Boot, Kafka" in user  # base CV
    assert "Acme Pay is a fintech" in user and "unknown facts" in user and "Jane Doe" in user
    assert "Spanish" in system["text"]


def test_checks_reject_placeholders_inventions_and_overlong_text():
    allowed = BASE_CV + "Acme Pay fintech Java"

    assert check_text("Hi [Name], I know Java", allowed_text=allowed)
    assert any("python" in p for p in check_text("I wrote Python and Java", allowed_text=allowed))
    assert any("7" in p for p in check_text("I have 7 years of Java", allowed_text=allowed))
    assert check_text("x" * 301, allowed_text=allowed, max_chars=300)
    assert check_text("line one\nline two", allowed_text=allowed, single_line=True)
    assert check_text("Java and Spring Boot work at Fictional Bank", allowed_text=allowed) == []
    assert unsupported_claims("Kafka", "Kafka") == []


def test_invented_technology_is_rejected_then_retried_with_feedback(tmp_path):
    bad = drafts_json(linkedin_dm="Hola, soy experto en Kotlin y Python, hablamos?")
    client, messages = scripted_client(bad, drafts_json())

    drafts = generate_company_drafts(client, FACTS, PERSON, language="es", **_kwargs(tmp_path))

    assert len(messages.requests) == 2
    retry = messages.requests[1]["messages"][0]["content"][0]["text"]
    assert "previous attempt was rejected" in retry and "kotlin" in retry.casefold()
    assert "Kotlin" not in drafts.linkedin_dm


def test_drafts_that_keep_failing_raise_and_nothing_is_returned(tmp_path):
    client, messages = scripted_client(drafts_json(linkedin_dm="Hola " * 70))

    with pytest.raises(HunterWritingError, match="failed the checks"):
        generate_company_drafts(client, FACTS, PERSON, language="en", **_kwargs(tmp_path))
    assert len(messages.requests) == 3


def test_email_word_limit_depends_on_stage(tmp_path):
    long_body = "word " * 130
    client, _ = scripted_client(drafts_json(email_body=long_body))
    with pytest.raises(HunterWritingError):
        generate_company_drafts(client, FACTS, PERSON, language="en", **_kwargs(tmp_path))  # early: 110 max

    mid = CompanyFacts(
        name="Acme Pay", website=None, stage=CompanyStage.MID_SIZE, description=FACTS.description,
        stack_terms=(), posting_titles=(), fit_reasons=(), unknowns=(),
    )
    client, _ = scripted_client(drafts_json(email_body=long_body))
    assert generate_company_drafts(client, mid, PERSON, language="en", **_kwargs(tmp_path)).stage is CompanyStage.MID_SIZE


def test_malformed_model_output_is_retried_and_json_fences_are_accepted(tmp_path):
    client, messages = scripted_client("not json", "```json\n" + drafts_json() + "\n```")

    drafts = generate_company_drafts(client, FACTS, None, language="en", **_kwargs(tmp_path))

    assert drafts.email_subject == "Java payment APIs" and len(messages.requests) == 2


def test_provider_errors_and_refusals_are_safe(tmp_path):
    secret_error = RuntimeError("sk-ant-secret request failed")
    client, _ = scripted_client(secret_error)
    with pytest.raises(HunterWritingError) as error:
        generate_company_drafts(client, FACTS, None, language="en", **_kwargs(tmp_path))
    assert "sk-ant-secret" not in str(error.value) and "RuntimeError" in str(error.value)


def test_connection_note_is_enforced_to_300_chars_with_retry(tmp_path):
    too_long = "Hola Jane, " + "me gusta mucho Java en Acme Pay " * 12
    ok = "Hola Jane, leí tu artículo Kafka at Acme: trabajo con Java y Kafka en banca y me gustaría conectar."
    client, messages = scripted_client(too_long, ok)

    note = generate_connection_note(client, FACTS, PERSON, language="es", **_kwargs(tmp_path))

    assert note == ok and len(note) <= LINKEDIN_NOTE_LIMIT and len(messages.requests) == 2
    assert "300 characters" in messages.requests[0]["system"][0]["text"]
    assert f"is {len(too_long.strip())} characters" in messages.requests[1]["messages"][0]["content"][0]["text"]

    client, _ = scripted_client(too_long)
    with pytest.raises(HunterWritingError):
        generate_connection_note(client, FACTS, PERSON, language="es", **_kwargs(tmp_path))
    with pytest.raises(HunterWritingError):
        enforce_note_limit("y" * 301)
    assert enforce_note_limit("  a   b ") == "a b"


def test_post_grounded_note_includes_the_pasted_post_and_rules(tmp_path):
    client, messages = scripted_client("Hola Jane, tu post sobre Kafka me hizo pensar; yo uso Kafka en banca.")

    generate_connection_note(
        client, FACTS, PERSON, language="es", post="Hoy migramos a Kafka con Java.", **_kwargs(tmp_path)
    )

    request = messages.requests[0]
    assert "grounded in a LinkedIn post" in request["system"][0]["text"]
    assert "Hoy migramos a Kafka con Java." in request["messages"][0]["content"][0]["text"]
    with pytest.raises(HunterWritingError):
        generate_connection_note(client, FACTS, PERSON, language="es", post="   ", **_kwargs(tmp_path))


def test_follow_up_is_a_single_casual_line(tmp_path):
    client, messages = scripted_client("Gracias por aceptar, Jane! Me gustó lo de Kafka en Acme Pay.")

    text = generate_follow_up(client, FACTS, PERSON, language="es", previous_note="Hola Jane", **_kwargs(tmp_path))

    assert "\n" not in text and len(text) <= 300
    assert "very casual" in messages.requests[0]["system"][0]["text"]


def test_base_cv_loading_falls_back_and_errors_when_missing(tmp_path):
    cv_dir, _ = write_private(tmp_path)
    (cv_dir / "CV_base_ES.md").unlink()
    assert load_base_cv("es", cv_dir) == BASE_CV  # falls back to the English CV (same facts)
    with pytest.raises(HunterWritingError, match="Base CV not found"):
        load_base_cv("en", tmp_path / "missing")
    assert resolve_language("auto", "Hola, nuestro equipo trabaja con el cliente", default="en") == "es"
    assert resolve_language("en", "Hola") == "en"
    assert resolve_language("auto", None, default="en") == "en"
    assert build_request("rules", "style", "hi")["messages"][0]["content"][0]["text"] == "hi"


# ---- service: saved drafts --------------------------------------------------------------


def test_company_drafts_are_saved_as_email_and_linkedin_outreach_and_are_idempotent(db_session, tmp_path):
    company = add_company(db_session)
    contact = add_contact(db_session, company, "Jane Doe", "Engineering Manager")
    db_session.commit()
    cv_dir, style = write_private(tmp_path)
    client, messages = scripted_client(drafts_json())

    first = draft_for_company(db_session, company.id, client=client, language="es", cv_dir=cv_dir, style_guide_path=style)
    db_session.commit()
    second = draft_for_company(db_session, company.id, client=client, language="es", cv_dir=cv_dir, style_guide_path=style)

    assert first.created and not second.created and len(messages.requests) == 1  # no second paid call
    assert first.contact.id == contact.id
    assert (first.email.channel, first.linkedin.channel) == ("EMAIL", "LINKEDIN")
    assert first.email.status == "DRAFT" and first.email.purpose == "COLD_OUTREACH"
    assert first.email.subject == "Java payment APIs" and "\n" not in first.linkedin.body
    assert "Overlap used" in first.email.rationale and "Fit " in first.email.rationale
    assert second.email.id == first.email.id and second.linkedin.id == first.linkedin.id
    assert db_session.query(Outreach).count() == 2


def test_force_replaces_drafts_but_never_a_sent_one(db_session, tmp_path):
    company = add_company(db_session)
    db_session.commit()
    cv_dir, style = write_private(tmp_path)
    client, _ = scripted_client(drafts_json())
    kwargs = {"client": client, "language": "es", "cv_dir": cv_dir, "style_guide_path": style}

    first = draft_for_company(db_session, company.id, **kwargs)
    forced = draft_for_company(db_session, company.id, force=True, **kwargs)

    assert forced.email.id != first.email.id
    assert db_session.get(Outreach, first.email.id).status == OutreachStatus.CANCELLED.value

    from ai_job_hunter.services.outreach_persistence import transition_outreach

    transition_outreach(db_session, forced.email.id, OutreachStatus.APPROVED)
    transition_outreach(db_session, forced.email.id, OutreachStatus.SENT, manual=True)
    with pytest.raises(HunterWritingError, match="already sent"):
        draft_for_company(db_session, company.id, force=True, **kwargs)


def test_missing_base_cv_fails_before_any_model_call(db_session, tmp_path):
    company = add_company(db_session)
    db_session.commit()
    client, messages = scripted_client(drafts_json())

    with pytest.raises(HunterWritingError, match="Base CV"):
        draft_for_company(db_session, company.id, client=client, cv_dir=tmp_path / "none", style_guide_path=tmp_path / "x")

    assert messages.requests == [] and db_session.query(Outreach).count() == 0


def test_context_has_stack_from_postings_and_hints_are_labelled(db_session):
    company = add_company(db_session, description=None)
    from ai_job_hunter.models import CompanyLead

    lead = db_session.query(CompanyLead).first()
    lead.notes = "Banking SaaS product company"
    db_session.commit()

    context = company_context(db_session, company.id)

    assert "java" in context.facts.stack_terms and "spring boot" in context.facts.stack_terms
    assert "unverified hint" in context.facts.description
    assert context.facts.posting_titles == ("Senior Java Engineer",)
    assert "stack" in " ".join(context.facts.fit_reasons)


def test_best_contact_prefers_the_most_relevant_person_and_never_a_large_companys_ceo(db_session):
    company = add_company(db_session)
    ceo = add_contact(db_session, company, "Fay Founder", "Chief Executive Officer", "FOUNDER")
    cto = add_contact(db_session, company, "Cto Person", "CTO", "ENGINEERING_MANAGER")
    manager = add_contact(db_session, company, "Eve Manager", "Engineering Manager", "ENGINEERING_MANAGER")
    engineer = add_contact(db_session, company, "Eng Ineer", "Backend Engineer", "ENGINEER")

    assert best_contact((engineer, manager, cto, ceo)).id == manager.id  # a CTO is top only at small companies
    assert best_contact((engineer, manager, cto, ceo), small_known=True).id == cto.id
    assert best_contact((ceo,)) is None and best_contact((ceo,), small_known=True).id == ceo.id
    assert best_contact(()) is None
