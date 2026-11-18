import pytest

from ai_job_hunter.candidates.profile import CandidatePreferences
from ai_job_hunter.candidates.stack_gate import stack_gate_reason

STRICT = CandidatePreferences(core_technologies=["Java", "Spring Boot"])


@pytest.mark.parametrize(
    ("title", "description"),
    [
        ("Backend Engineer", "We build services in Java 21 and Spring Boot."),
        ("Java Developer", None),
        ("Software Engineer", "Our stack: Kotlin or Java, PostgreSQL, Kafka."),
        ("Backend Engineer (Python)", "Python and Django. No prior experience with Python required."),
        ("Software Engineer", "You can come from any programming language, we use Go."),
        ("Desarrollador Python", "Buscamos perfiles junior. No se requiere experiencia previa en Python."),
    ],
)
def test_offers_with_the_core_stack_or_that_need_no_experience_pass(title, description) -> None:
    assert stack_gate_reason(title, description, STRICT) is None


@pytest.mark.parametrize(
    ("title", "description", "named"),
    [
        ("Backend Engineer", "Python, FastAPI and PostgreSQL in production.", "python"),
        ("Full Stack Developer", "React, TypeScript and Node.js.", "typescript"),
        ("Android Engineer", "Kotlin and Jetpack Compose.", "kotlin"),
        ("Frontend Developer", "Strong JavaScript skills.", "javascript"),
        ("Software Engineer", "Join our friendly team and build great products.", None),
    ],
)
def test_offers_without_the_core_stack_are_rejected(title, description, named) -> None:
    reason = stack_gate_reason(title, description, STRICT)

    assert reason is not None
    if named:
        assert named in reason
    else:
        assert "names no technology" in reason


def test_javascript_does_not_count_as_java() -> None:
    assert stack_gate_reason("Frontend Engineer", "JavaScript and Vue.", STRICT) is not None


def test_the_gate_is_off_without_core_technologies() -> None:
    assert stack_gate_reason("Frontend Developer", "React only.", CandidatePreferences()) is None


def test_an_offer_outside_the_strict_stack_is_rejected_before_jev() -> None:
    from test_opportunity_service import _candidate, _offer

    from ai_job_hunter.candidates.prefilter import PreFilterDecision
    from ai_job_hunter.services.opportunities import _prepare_offer

    base = _candidate()
    strict = base.model_copy(
        update={"preferences": base.preferences.model_copy(update={"core_technologies": ["Java", "Spring Boot"]})}
    )
    python_offer = _offer("py-1", title="Backend Engineer")  # the helper's text is about Python services
    java_offer = _offer("java-1", title="Backend Engineer", description="Java and Spring Boot services. " * 40)

    assert _prepare_offer(python_offer, strict, engine_identity="x").context.deterministic.decision is PreFilterDecision.REJECT
    assert _prepare_offer(java_offer, strict, engine_identity="x").context.deterministic.decision is not PreFilterDecision.REJECT
    # Without the preference nothing changes, and the evaluation fingerprint stays the same.
    plain = _prepare_offer(python_offer, base, engine_identity="x")
    assert plain.context.deterministic.decision is not PreFilterDecision.REJECT or "core stack" not in " ".join(
        plain.context.deterministic.reasons
    )
    assert plain.config_fingerprint == _prepare_offer(
        python_offer, base.model_copy(update={"preferences": base.preferences.model_copy(update={"core_technologies": []})}),
        engine_identity="x",
    ).config_fingerprint
