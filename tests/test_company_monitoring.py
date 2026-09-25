from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import func, select

from ai_job_hunter.candidates import JobFacts, PreFilterDecision, evaluate_job, load_candidate_config
from ai_job_hunter.connectors import FakeJobConnector, build_job_connectors
from ai_job_hunter.domain.company_intelligence import (
    ATSProvider,
    CompanyEvidenceType,
)
from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.job_sources import JobSourceSpec, JobSourcesConfig
from ai_job_hunter.models import Company, CompanyEvidence, Job, JobSource
from ai_job_hunter.services.company_intelligence import (
    CompanyMonitorFilters,
    build_company_monitor_targets,
    get_company_facts,
    sync_ats_evidence_from_job_sources,
)
from ai_job_hunter.services.pipeline import run_ingestion_pipeline
from ai_job_hunter.snapshots import load_job_snapshot, save_job_snapshot

PROJECT_ROOT = Path(__file__).parents[1]
ASHBY_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "ashby_jobs.json"


def _offer(**changes) -> NormalizedJob:
    values = {
        "provider": "ashby",
        "external_id": "ashby-role-1",
        "source_url": "https://jobs.ashbyhq.com/example-product/ashby-role-1",
        "canonical_url": "https://jobs.ashbyhq.com/example-product/ashby-role-1",
        "apply_url": "https://jobs.ashbyhq.com/example-product/ashby-role-1/application",
        "title": "Backend Engineer",
        "company_name": "Example Product Co",
        "description": "Build and operate backend APIs with Python and PostgreSQL. " * 60,
        "location": "Spain",
        "discovered_at": datetime(2026, 9, 24, tzinfo=UTC),
    }
    values.update(changes)
    return NormalizedJob.model_validate(values)


def test_persisted_job_sources_create_idempotent_preferred_ats_evidence(db_session):
    company = Company(name="Observed Systems")
    company.evidence_items.append(
        CompanyEvidence(
            provider="company_catalog",
            source_key="observed-careers",
            evidence_type=CompanyEvidenceType.CAREER_PAGE.value,
            structured_data={"career_page_url": "https://jobs.ashbyhq.com/inferred-board"},
        )
    )
    job = Job(company=company, title="Platform Engineer")
    job.sources.append(
        JobSource(
            provider="greenhouse",
            external_id="greenhouse-role-7",
            original_url="https://boards.greenhouse.io/observed-board/jobs/7",
            canonical_url="https://boards.greenhouse.io/observed-board/jobs/7",
        )
    )
    db_session.add(job)
    db_session.flush()

    first = sync_ats_evidence_from_job_sources(db_session)
    db_session.commit()
    facts = get_company_facts(db_session, "Observed Systems")
    assert facts is not None
    assert facts.ats_discoveries[0].provider is ATSProvider.GREENHOUSE
    assert facts.ats_discoveries[0].identifier == "observed-board"
    assert facts.ats_discoveries[0].source_url.endswith("/jobs/7")
    assert facts.ats_discoveries[0].confidence.value == "OBSERVED_JOB_SOURCE"

    second = sync_ats_evidence_from_job_sources(db_session)

    assert first.sources_examined == 1
    assert first.evidence_created == 1
    assert second.evidence_created == 0
    assert second.evidence_updated == 1
    assert db_session.scalar(select(func.count(CompanyEvidence.id)).where(
        CompanyEvidence.evidence_type == CompanyEvidenceType.ATS_OBSERVED.value
    )) == 1
    targets = build_company_monitor_targets(
        db_session,
        CompanyMonitorFilters(supported_ats=True),
        company_name="Observed Systems",
    )
    assert len(targets) == 1
    assert targets[0].provider is ATSProvider.GREENHOUSE
    assert targets[0].identifier == "observed-board"
    assert targets[0].evidence_source == "observed_job_source"


def test_normalized_snapshot_ats_evidence_groups_job_sources_without_duplicates(db_session):
    offers = [
        _offer(external_id="ashby-role-1"),
        _offer(
            external_id="ashby-role-2",
            source_url="https://jobs.ashbyhq.com/example-product/ashby-role-2",
            canonical_url="https://jobs.ashbyhq.com/example-product/ashby-role-2",
            title="Senior Backend Engineer",
        ),
    ]

    first = sync_ats_evidence_from_job_sources(
        db_session,
        normalized_jobs=offers,
        source_label="saved_normalized_job_snapshot",
    )
    second = sync_ats_evidence_from_job_sources(
        db_session,
        normalized_jobs=offers,
        source_label="saved_normalized_job_snapshot",
    )

    evidence = db_session.scalars(
        select(CompanyEvidence).where(CompanyEvidence.evidence_type == CompanyEvidenceType.ATS_OBSERVED.value)
    ).one()
    assert first.sources_examined == 2
    assert first.evidence_created == 1
    assert second.evidence_updated == 1
    assert len(evidence.structured_data["supporting_job_sources"]) == 2
    assert evidence.structured_data["observation_basis"] == "saved_normalized_job_snapshot"


def test_end_to_end_jobsource_to_target_ashby_snapshot_and_prefilter(db_session, tmp_path):
    seed_offer = _offer()
    ingested = run_ingestion_pipeline(FakeJobConnector([seed_offer]), db_session)
    assert ingested.created == 1

    observed = sync_ats_evidence_from_job_sources(db_session)
    db_session.commit()
    assert observed.evidence_created == 1
    targets = build_company_monitor_targets(
        db_session,
        CompanyMonitorFilters(supported_ats=True),
        provider=ATSProvider.ASHBY,
        limit_companies=1,
    )
    assert len(targets) == 1
    target = targets[0]
    config = JobSourcesConfig(
        sources=[
            JobSourceSpec(
                provider=target.provider.value.casefold(),
                identifier=target.identifier,
                company_name=target.company_name,
                max_jobs=10,
            )
        ]
    )
    ashby_payload = json.loads(ASHBY_FIXTURE.read_text(encoding="utf-8"))
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=ashby_payload)))
    connectors = build_job_connectors(config, client=client)
    try:
        offers = connectors[0].fetch_jobs()
    finally:
        client.close()

    snapshot_path = tmp_path / "monitor.local.json"
    save_job_snapshot(snapshot_path, offers)
    replayed = load_job_snapshot(snapshot_path)
    candidate_path = PROJECT_ROOT / "config" / "examples" / "candidate.example.json"
    candidate = load_candidate_config(candidate_path)
    prefilter_results = [evaluate_job(JobFacts.from_normalized_job(job), candidate) for job in replayed]
    eligible = [result for result in prefilter_results if result.decision is not PreFilterDecision.REJECT]
    db_session.commit()
    dedup_summary = run_ingestion_pipeline(FakeJobConnector(replayed), db_session)

    assert len(replayed) == 2
    assert eligible
    assert dedup_summary.fetched == 2
    assert dedup_summary.already_known == 1
    assert get_company_facts(db_session, "Example Product Co").ats_discoveries[0].provider is ATSProvider.ASHBY
