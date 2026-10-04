"""Shared fakes and builders for the Company Hunter tests (offline; no network, no real model)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from ai_job_hunter.models import Company, CompanyLead, Contact, Job, JobSource

BASE_CV = """# Alex Example

**Backend Engineer**

Java, Spring Boot and Kafka services at Fictional Bank. Built payment APIs in Java and Spring Boot.

## Experience

- Backend Engineer at Fictional Bank (2023-2026): Java 21, Spring Boot, Kafka, PostgreSQL.
"""


class ScriptedMessages:
    """Replays model responses in order; the last one repeats. Records every request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        item = self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=item)], stop_reason="end_turn", model="fake", usage=None
        )


def scripted_client(*responses):
    messages = ScriptedMessages(responses)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def drafts_json(**overrides) -> str:
    data = {
        "overlap": "Their payment APIs match my Java and Spring Boot payment work.",
        "email_subject": "Java payment APIs",
        "email_body": "Hola,\n\nVi que Acme Pay trabaja con Java.\n- Construí APIs de pagos en Java y Spring Boot.\n\nAlex",
        "linkedin_dm": "Hola! Vi lo que hacéis en Acme Pay con Java, me gustaría charlar un rato.",
    }
    data.update(overrides)
    return json.dumps(data)


def write_private(tmp_path: Path) -> tuple[Path, Path]:
    cv_dir = tmp_path / "cv"
    cv_dir.mkdir(exist_ok=True)
    (cv_dir / "CV_base_EN.md").write_text(BASE_CV, encoding="utf-8")
    (cv_dir / "CV_base_ES.md").write_text(BASE_CV, encoding="utf-8")
    style = tmp_path / "WRITING.md"
    style.write_text("# Style\n- Plain, honest, no filler.\n", encoding="utf-8")
    return cv_dir, style


def add_company(
    session,
    name="Acme Pay",
    *,
    website="https://acme.example.test",
    description="Acme Pay is a fintech building payments infrastructure.",
    postings=(("Senior Java Engineer", "Build Java and Spring Boot services.", "Madrid, Spain", "SPAIN_ONLY"),),
    lead=True,
) -> Company:
    company = Company(name=name, website_url=website, description=description)
    session.add(company)
    session.flush()
    for index, (title, text, location, eligibility) in enumerate(postings):
        job = Job(company=company, title=title, description=text, location=location)
        session.add(job)
        session.flush()
        session.add(
            JobSource(
                job=job,
                provider="greenhouse",
                external_id=f"{name}-{index}",
                original_url=f"https://boards.example.test/{name.replace(' ', '-')}/{index}",
                source_title=title,
                source_description=text,
                source_location=location,
                remote_eligibility=eligibility,
            )
        )
    if lead:
        session.add(
            CompanyLead(
                company_name=name,
                normalized_name=name.casefold(),
                domain_key=name.casefold().replace(" ", ""),
                source_type="manual",
                source_label="test list",
                company_id=company.id,
            )
        )
    session.flush()
    return company


def add_contact(
    session,
    company,
    name="Jane Doe",
    title="Engineering Manager",
    contact_type="ENGINEERING_MANAGER",
    *,
    linkedin_url=None,
    language="en",
    source_url="https://acme.example.test/team",
) -> Contact:
    contact = Contact(
        company_id=company.id,
        name=name,
        title=title,
        contact_type=contact_type,
        linkedin_url=linkedin_url,
        source_provider="company_site",
        external_id=f"{source_url}#{name.casefold()}",
        source_url=source_url,
        evidence={"evidence_type": "team_page", "quote": f"{name} — {title}", "language": language},
    )
    session.add(contact)
    session.flush()
    return contact
