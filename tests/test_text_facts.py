from ai_job_hunter.services.text_facts import salary_from_text, work_mode_from_text


def test_work_mode_is_read_only_from_explicit_wording():
    assert work_mode_from_text("Madrid (modelo híbrido; se requiere residencia en Madrid)") == "HYBRID"
    assert work_mode_from_text("This is a fully remote role") == "REMOTE"
    assert work_mode_from_text("Teletrabajo 100%. Horario flexible") == "REMOTE"
    assert work_mode_from_text("Presencial en Madrid") == "ONSITE"
    assert work_mode_from_text("3 days per week in the office") == "HYBRID"
    assert work_mode_from_text("We build tools for remote teams") is None  # a loose use of the word
    assert work_mode_from_text("Horario flexible aunque no on-site") is None
    assert work_mode_from_text("Fully remote, but some on-site days in Berlin") is None  # two modes: ambiguous
    assert work_mode_from_text(None, "", None) is None


def test_salary_needs_a_currency_a_range_and_a_plausible_yearly_amount():
    assert salary_from_text("Salario 25.000 - 35.000€/b año. Jornada de 35 horas") == "25.000–35.000 €"
    assert salary_from_text("Salary: €40,000 - €50,000 per year") == "40.000–50.000 €"
    assert salary_from_text("Rango: 55.000 a 65.000 euros brutos al año") == "55.000–65.000 €"
    assert salary_from_text("40k-50k EUR") == "40.000–50.000 €"
    assert salary_from_text("CHF 80'000 - 95'000") == "80.000–95.000 CHF"
    assert salary_from_text("We raised $10,000,000 - 20,000,000 in funding") is None
    assert salary_from_text("3.000 - 4.000 € al mes") is None  # monthly figures are not shown
    assert salary_from_text("Call 600-700 now") is None
    assert salary_from_text("Jornada de 35 - 40 horas") is None
